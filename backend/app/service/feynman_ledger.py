"""service.feynman_ledger：费曼缺口账本与 evidence 纪律（docs/09 R27 · v3 混合制）。

设计要点（R27）：
- **账本**：``{dims: {key: {key, best, latest, weight, evidence_quote, comment, updated_round}},
  gaps: [...], rounds: [各轮分维卡], updated_at}``。维度分 = 历轮**最高分**（max 合成），
  由此"答对认账、看得见涨分"，且新回答不会再被旧文锚定（不再拼合并稿整体重评）。
- **缺口**：未达标维度 → ``{key, description（学生视角"要补什么"）, evidence_quote, comment,
  score}``，按权重倒序 = 弱到强；追问定向第一项（一次一个）。
- **evidence 纪律（硬校验）**：评分卡 ``evidence_quote`` 必须逐字出自**本轮**提交文本。
  校验用"归一化子串包含"（去空白 + 统一标点/引号，容忍 LLM 的排版差异）**+ 最短长度门槛**
  （归一化后 < 6 字视为无效，R30 F5：极短引文能平凡通过校验），
  失败 → 该维度 score 降级（默认 ×0.5）并标记 ``evidence_valid=False / evidence_reason``，
  防"没读新内容还打分"。原始引文保留以便用户复盘时肉眼核对。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from ..content.citations import MIN_QUOTE_CHARS
from ..content.citations import invalid_reason as _citation_reason
from ..content.citations import is_valid as _citation_valid
from ..content.citations import normalize as normalize_quote

# 每个维度"要补什么"的学生视角模板（comment 缺失时兜底；也用于保证追问可执行）
_GAP_TEMPLATES = {
    "correctness": "把「{key}」讲对：说出关键结论并与事实一致（可用课本原话之外的说法）",
    "own_words": "用自己的话把「{key}」讲一遍，不要背书式罗列",
    "evidence": "说出任意一种依据/方法（观测、实验、推导或例子都算），说明你凭什么这样讲",
    "self_correction": "根据追问修正原先讲错/讲漏的地方，并说明改了什么",
}

# evidence 校验失败时的降级系数（不归零：允许"分低但认账"，且学生可见原因）
EVIDENCE_PENALTY = 0.5

# evidence **最短门槛**（R30 F5）：归一化（去空白/标点/省略号）后 < 6 字视为无效引文——
# 极短引文（单字/词）能平凡通过"子串包含"校验，等于没有依据（R28 F5 加固建议）。
# R36：实现已收敛到 `app.content.citations`（同一把尺子，供大纲材料溯源 / R35 basis 复用）；
# 此处仅保留历史名字以兼容既有测试与调用方。
MIN_EVIDENCE_CHARS = MIN_QUOTE_CHARS

# --------------------------------------------------------------------------
# R35 S4：学生原话里"有没有可引用的实质内容"
#
# 用途**只有一处**：追问纪律——学生没提供可引用的实质内容（如只写"我不知道"）时，
# **禁止硬造发散题**，返回 `reteach`（退回讲解补讲）。
#
# 分层说明（不是两套机制，而是一道确定性前置 + 一道模型判定）：
# 1. 本函数：**确定性前置**——让"我不想答"既不烧一次评分额度、也不换来一条无法回答的追问；
# 2. 追问调用点：`student_quote` 必须逐字出自学生原话（同一把引文尺子）——真模型路径的**通用**兜底。
#
# 边界（如实分界）：这是一条**语言层启发式**（去敷衍用语后是否还剩实质内容），
# 与学科无关（任何学科同一套），但**不可能百分百准确**；故它只用于"退回讲解"这一安全方向
# （宁可多退一次讲解，也不发一条学生答不出的追问）。
DISMISSIVE_MARKERS = (
    "不知道", "不会", "不懂", "不明白", "不清楚", "没学过", "没听过", "不记得", "忘了",
    "想不起来", "随便", "无所谓", "没兴趣", "不感兴趣", "放弃", "跳过", "空着",
)
# 纯语气/指代/礼貌填充词：去掉它们后仍不足以构成"可引用的实质内容"
FILLER_MARKERS = (
    "我", "你", "的", "了", "吧", "呢", "啊", "嗯", "哦", "嘛", "呀", "真的", "确实", "就是",
    "还是", "这个", "那个", "一道", "这道", "题目", "老师", "其实", "应该", "好像",
)


def has_quotable_content(text: str, *, min_chars: int = MIN_QUOTE_CHARS) -> bool:
    """学生的话里是否有**可逐字引用的实质内容**（R35 S4）。

    判定：归一化后先过最短门槛；再剔掉敷衍用语与纯填充词——**仍不足门槛**即视为
    "没有可引用的实质内容"（→ `reteach`）。空串/None → False。
    """
    norm = normalize_quote(text)
    if len(norm) < min_chars:
        return False
    stripped = norm
    for marker in DISMISSIVE_MARKERS + FILLER_MARKERS:
        stripped = stripped.replace(marker, "")
    return len(stripped) >= min_chars


def student_quote(text: str, *, min_chars: int = MIN_QUOTE_CHARS) -> str:
    """从学生原话里取一段**可逐字引用**的片段（R35 S4：追问必须先逐字引用学生刚说的话）。

    优先取第一个整句；首句太短则逐字取前缀（取到刚好达门槛为止）。
    原文归一化后不足门槛（无从引用）→ 返回空串（调用方据此走 `reteach`）。
    """
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    for sent in re.split(r"[。！？；!?;\n]+", flat):
        s = sent.strip()
        if len(normalize_quote(s)) >= min_chars:
            return s
    for n in range(1, len(flat) + 1):
        cand = flat[:n]
        if len(normalize_quote(cand)) >= min_chars:
            return cand
    return ""


def quote_valid(quote: str, transcript: str) -> bool:
    """evidence_quote 是否逐字出自本轮文本（归一化子串包含 + 最短长度门槛 R30 F5）。"""
    return _citation_valid(quote, transcript)


def quote_invalid_reason(quote: str, transcript: str, *, where: str = "本轮提交文本") -> str:
    """引文无效的中文原因（区分"过短"与"不在本轮文本中"；面向学生展示）。"""
    return _citation_reason(quote, transcript, where=where)


# --------------------------------------------------------------------------
# 账本
# --------------------------------------------------------------------------
def empty_ledger() -> dict[str, Any]:
    return {"dims": {}, "gaps": [], "rounds": [], "updated_at": None}


def normalize_ledger(f: dict[str, Any], dims: Iterable[Any]) -> dict[str, Any]:
    """确保 flow.feynman.ledger 结构完整（旧会话自愈 + 补齐 rubric 新增维度）。"""
    ledger = f.get("ledger")
    if not isinstance(ledger, dict):
        ledger = empty_ledger()
    if not isinstance(ledger.get("dims"), dict):
        ledger["dims"] = {}
    if not isinstance(ledger.get("gaps"), list):
        ledger["gaps"] = []
    if not isinstance(ledger.get("rounds"), list):
        ledger["rounds"] = []
    ledger.setdefault("updated_at", None)
    for d in dims:
        key = d.get("key") if isinstance(d, dict) else getattr(d, "key", None)
        if not key:
            continue
        weight = d.get("weight") if isinstance(d, dict) else getattr(d, "weight", 0.0)
        entry = ledger["dims"].get(key)
        if not isinstance(entry, dict):
            entry = {}
            ledger["dims"][key] = entry
        entry.setdefault("key", key)
        entry.setdefault("best", 0.0)
        entry.setdefault("latest", 0.0)
        entry["weight"] = float(weight or 0.0)
        entry.setdefault("evidence_quote", "")
        entry.setdefault("comment", "")
        entry.setdefault("updated_round", 0)
    f["ledger"] = ledger
    return ledger


def candidate_acknowledged(ledger: dict[str, Any]) -> list[dict]:
    """R27：``previously_acknowledged`` —— 账本里已有认可内容的摘要（喂给整体评分）。

    学生没把已认可点重抄一遍**不扣分**（LLM 上下文依据）；空账本返回 []。
    """
    out: list[dict] = []
    for key, entry in (ledger.get("dims") or {}).items():
        best = float(entry.get("best") or 0.0)
        if best <= 0.0:
            continue
        out.append(
            {
                "key": key,
                "best_score": round(best, 3),
                "evidence_quote": (entry.get("evidence_quote") or "")[:80],
                "note": entry.get("comment") or "",
            }
        )
    return out


def clean_card(
    card: list[dict], *, transcript: str, apply_penalty: bool = True
) -> tuple[list[dict], bool]:
    """净化评分卡：evidence 包含校验 + 降级，**不并入账本**（R30 F6 复评取卡复用）。

    返回 ``(净化后的 card, any_penalty)``；每行附加 ``evidence_valid``（校验结论），
    无效时再附 ``evidence_reason``。与 :func:`merge_card` 同源，保证"边缘带复评"两轮卡
    的口径（分数是否降级）完全一致。
    """
    clean: list[dict] = []
    penalty = False
    for item in card or []:
        key = str(item.get("key", ""))
        if not key:
            continue
        quote = str(item.get("evidence_quote") or "")
        valid = quote_valid(quote, transcript)
        score = float(item.get("score") or 0.0)
        if apply_penalty and not valid:
            score = round(score * EVIDENCE_PENALTY, 3)
            penalty = True
        row = {
            "key": key,
            "score": round(score, 3),
            "weight": float(item.get("weight") or 0.0),
            "evidence_quote": quote,
            "comment": str(item.get("comment") or ""),
            "evidence_valid": valid,
        }
        if not valid:
            row["evidence_reason"] = quote_invalid_reason(quote, transcript)
        clean.append(row)
    return clean, penalty


def card_combined(card: list[dict]) -> float:
    """单轮评分卡的加权综合分 = Σ(w·score)/Σw（R30 F6：两次评分卡比较取高用）。"""
    total_w = sum(float(item.get("weight") or 0.0) for item in (card or []))
    if total_w <= 0:
        return 0.0
    weighted = sum(
        float(item.get("weight") or 0.0) * float(item.get("score") or 0.0) for item in (card or [])
    )
    return weighted / total_w


def merge_clean_card(ledger: dict[str, Any], clean: list[dict], *, round_no: int) -> None:
    """把**已净化**的评分卡并入账本（维度取 max）；净化见 :func:`clean_card`。

    R30 F6：边缘带复评需先比较两次卡、再只并入"采用那一次"，故并入动作与净化拆开
    （避免对同一张卡二次降级）。
    """
    for row in clean or []:
        entry = ledger["dims"].setdefault(
            row["key"],
            {"key": row["key"], "best": 0.0, "latest": 0.0, "weight": row["weight"],
             "evidence_quote": "", "comment": "", "updated_round": 0},
        )
        entry["weight"] = row["weight"]
        entry["latest"] = row["score"]
        if row["score"] >= float(entry.get("best") or 0.0):
            entry["best"] = row["score"]
            entry["evidence_quote"] = row["evidence_quote"]
            entry["comment"] = row["comment"]
            entry["updated_round"] = round_no
            entry["evidence_valid"] = row["evidence_valid"]
    if clean:
        ledger["rounds"].append({"round": round_no, "dims": clean})
        ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()


def merge_card(
    ledger: dict[str, Any], card: list[dict], *, round_no: int, transcript: str, apply_penalty: bool = True
) -> tuple[list[dict], bool]:
    """把一轮评分卡并入账本（维度取 max），并做 evidence 包含校验。

    返回 (净化后的 card, any_penalty)。card 内每条附加 ``evidence_valid``（校验结论）。
    """
    clean, penalty = clean_card(card, transcript=transcript, apply_penalty=apply_penalty)
    merge_clean_card(ledger, clean, round_no=round_no)
    return clean, penalty


def update_dimension(
    ledger: dict[str, Any],
    *,
    key: str,
    score: float,
    evidence_quote: str,
    comment: str,
    transcript: str,
    round_no: int,
    apply_penalty: bool = True,
) -> tuple[dict, bool]:
    """补答轮：只更新缺口所属维度（R27 §2），返回 (该维度行, 是否降级)。"""
    valid = quote_valid(evidence_quote, transcript)
    s = float(score or 0.0)
    if apply_penalty and not valid:
        s = round(s * EVIDENCE_PENALTY, 3)
    entry = ledger["dims"].setdefault(
        key,
        {"key": key, "best": 0.0, "latest": 0.0, "weight": 0.0,
         "evidence_quote": "", "comment": "", "updated_round": 0},
    )
    entry["latest"] = round(s, 3)
    if s >= float(entry.get("best") or 0.0):
        entry["best"] = round(s, 3)
        entry["evidence_quote"] = str(evidence_quote or "")
        entry["comment"] = str(comment or "")
        entry["updated_round"] = round_no
        entry["evidence_valid"] = valid
    ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    row = {
        "key": key,
        "score": round(s, 3),
        "weight": float(entry.get("weight") or 0.0),
        "evidence_quote": str(evidence_quote or ""),
        "comment": str(comment or ""),
        "evidence_valid": valid,
    }
    if not valid:
        row["evidence_reason"] = quote_invalid_reason(evidence_quote, transcript, where="本轮补答文本")
    return row, (not valid)


def combined(ledger: dict[str, Any]) -> float:
    """实时综合分 = Σ(w·账本维度最高分) / Σw（R27 §2 分数合成）。"""
    dims = ledger.get("dims") or {}
    total_w = sum(float(e.get("weight") or 0.0) for e in dims.values())
    if total_w <= 0:
        return 0.0
    weighted = sum(float(e.get("weight") or 0.0) * float(e.get("best") or 0.0) for e in dims.values())
    return weighted / total_w


def weakest(ledger: dict[str, Any], threshold: float) -> dict | None:
    """最弱缺口（未达标维度按 权重×缺失幅度 降序取第一）。"""
    gaps = [g for g in (ledger.get("gaps") or []) if not g.get("filled")]
    if not gaps:
        return None
    return max(gaps, key=lambda g: float(g.get("weight") or 0.0) * (1.0 - float(g.get("score") or 0.0)))


def extract_gaps(
    ledger: dict[str, Any], card: list[dict], threshold: float, *, round_no: int, keep_unmet: bool = True
) -> list[dict]:
    """从本轮评分卡提取缺口清单（未达标维度 → 学生视角"要补什么"）。

    - 本轮未达标维度 → 新缺口（保留历史 attempts，便于"同一缺口可再追一次"）；
    - 本轮已达标的维度 → 不再是缺口（答对即认账）；
    - ``keep_unmet``：整体重评时，历史缺口在本轮**未出现**（学生没讲到该维度）也保留在账本
      （R27：缺口保留、可再追；只有补答填上或不再出现在 rubric 才算消失）。
      UI/追问只取未填（``filled`` 为假）者。
    """
    prev_by_key: dict[str, dict] = {}
    for g in ledger.get("gaps") or []:
        key = str(g.get("key") or "")
        if key and key not in prev_by_key:
            prev_by_key[key] = g
    scored = {str(item.get("key", "")): item for item in (card or [])}
    new_gaps: list[dict] = []
    for key, item in scored.items():
        if not key:
            continue
        score = float(item.get("score") or 0.0)
        weight = float(item.get("weight") or 0.0)
        if score >= threshold:
            continue  # 已达标 → 缺口消失
        prev = prev_by_key.get(key)
        description = _gap_description(key, str(item.get("comment") or ""))
        if prev and prev.get("description"):
            description = str(prev["description"])  # 缺口描述稳定，便于"同一缺口再追一次"
        new_gaps.append(
            {
                "key": key,
                "description": description,
                "weight": weight,
                "score": score,
                "evidence_quote": str(item.get("evidence_quote") or ""),
                "comment": str(item.get("comment") or ""),
                "round": round_no,
                "attempts": int((prev or {}).get("attempts") or 0),
                "filled": False,
            }
        )
    if keep_unmet:
        seen = {g["key"] for g in new_gaps}
        for key, prev in prev_by_key.items():
            if key in seen or key in scored:
                continue  # 本轮未评到该维度 → 保留历史缺口原样
            row = dict(prev)
            row["filled"] = False
            new_gaps.append(row)
    ledger["gaps"] = new_gaps
    return new_gaps


def mark_gap_attempt(ledger: dict[str, Any], key: str, *, filled: bool) -> None:
    """记录对该缺口的一次补答尝试（attempts+1；filled=True 则该缺口关闭）。"""
    keep: list[dict] = []
    for g in ledger.get("gaps") or []:
        if str(g.get("key")) == key:
            if filled:
                continue  # 补上 → 缺口关闭
            g = dict(g)
            g["attempts"] = int(g.get("attempts") or 0) + 1
            g["filled"] = False
        keep.append(g)
    ledger["gaps"] = keep



def _gap_description(key: str, comment: str) -> str:
    """缺口描述 = 评语要点（若有实质内容）否则维度模板。"""
    text = (comment or "").strip()
    # comment 里常见的"未涉及/缺/没有"类评语直接可用；排除纯表扬/离线前缀
    if text and not text.startswith("提到核心概念") and any(k in text for k in ("缺", "未", "没有", "需", "应", "不足")):
        return text[:80]
    return _GAP_TEMPLATES.get(key, f"补讲「{key}」这个维度的内容")


def gap_view(ledger: dict[str, Any], threshold: float) -> dict[str, Any]:
    """UI 用的进度视图：各维度账本分 + 缺口提示 + 综合分/门槛。

    ``score`` 与 ``best`` 同值（账本分 = 历轮最高分）；``score`` 供 UI 直接渲染进度条。
    """
    dims = [
        {
            "key": key,
            "label": key,
            "score": round(float(e.get("best") or 0.0), 3),
            "best": round(float(e.get("best") or 0.0), 3),
            "latest": round(float(e.get("latest") or 0.0), 3),
            "weight": float(e.get("weight") or 0.0),
            "evidence_quote": e.get("evidence_quote") or "",
            "comment": e.get("comment") or "",
            "updated_round": int(e.get("updated_round") or 0),
        }
        for key, e in (ledger.get("dims") or {}).items()
    ]
    return {
        "dimensions": dims,
        "combined": round(combined(ledger), 3),
        "threshold": threshold,
        "gaps": [
            {"key": g.get("key"), "description": g.get("description"), "score": g.get("score")}
            for g in (ledger.get("gaps") or [])
        ],
    }


__all__ = [
    "EVIDENCE_PENALTY",
    "MIN_EVIDENCE_CHARS",
    "DISMISSIVE_MARKERS",
    "normalize_quote",
    "has_quotable_content",
    "student_quote",
    "quote_valid",
    "quote_invalid_reason",
    "empty_ledger",
    "normalize_ledger",
    "candidate_acknowledged",
    "clean_card",
    "card_combined",
    "merge_clean_card",
    "merge_card",
    "update_dimension",
    "combined",
    "weakest",
    "extract_gaps",
    "mark_gap_attempt",
    "gap_view",
]
