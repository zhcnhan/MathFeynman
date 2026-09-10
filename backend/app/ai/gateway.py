"""app.ai.gateway：AI 门面（service 唯一依赖面）。

- AiGateway（Protocol）：各调用点方法。两种实现：
  1. OpenAICompatibleGateway —— 真模型（默认 DeepSeek；ollama/Qwen 兼容），经
     ai.provider.chat_json（JSON 提取 + pydantic 校验 + 重试）产出，AiCallError 上抛；
  2. OfflineGateway —— 无 key/降级时的内容库兜底（docs/05 §6）与离线启发式（仅演示）。
- service 捕获 AiCallError 后按 docs/05 §6 降级，绝不脏状态。
"""
from __future__ import annotations

import json
import re
from typing import Protocol

from ..content import citations
from .prompts import context_parts
from .calls import (
    AiCallError,
    AnswerQuestionIn,
    AnswerQuestionOut,
    CALL_ANSWER_QUESTION,
    CALL_CHALLENGE_CHECK,
    CALL_CHALLENGE_EXERCISE,
    CALL_CLASSIFY_ERROR,
    CALL_EXPLAIN_NODE,
    CALL_FEYNMAN_EVALUATE,
    CALL_FEYNMAN_FOLLOWUP,
    CALL_FEYNMAN_GAP_CHECK,
    CALL_GENERATE_VARIANT,
    CALL_HINT_ON_ERROR,
    ChallengeCheckIn,
    ChallengeCheckOut,
    ChallengeIn,
    ChallengeOut,
    CiteBasis,
    ClassifyErrorIn,
    ClassifyErrorOut,
    ExplainIn,
    ExplainOut,
    FeynmanDimScore,
    FeynmanEvaluateIn,
    FeynmanEvaluateOut,
    FeynmanFollowupIn,
    FeynmanFollowupOut,
    GapCheckIn,
    GapCheckOut,
    HintOnErrorIn,
    HintOnErrorOut,
    VariantIn,
    VariantOut,
)
from .provider import LogSink, OpenAICompatibleProvider
from .prompts import context_block, context_parts, task_json

MIN_FEYNMAN_CHARS = 20  # docs/05 §5：口述 <20 字直接判敷衍，不进评分


def _js(value: object) -> str:
    """审计/prompt 里注入的结构化取值（JSON 文本；None → "null"）。"""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _subject_of_node(node_id: str) -> str:
    """内容节点 → 所属学科 id（R39 §3：审计要能按学科筛）；查不到 → 空串（不阻塞）。"""
    if not node_id:
        return ""
    try:
        from ..db import SessionLocal
        from ..service import outline_gate

        with SessionLocal() as db:
            return str(outline_gate.subject_of_node(db, node_id) or "")
    except Exception:
        return ""

# ---- R27：离线启发式评分常量（仅无 key/降级兜底；真模型可用时不得抢占，docs/09 R4/R27） ----
BASE_SCORES = {"correctness": 0.30, "own_words": 0.25, "evidence": 0.10, "self_correction": 0.15}
# 提到 n 个核心概念 → 基础分（"讲了什么"）；具体讲全程度见 offline_feynman_scores 的明确分档
_BY_CONCEPTS = ((0, 0.0), (1, 0.55), (2, 0.75), (3, 0.88))
_EVIDENCE_KEYWORDS = (
    "因为", "所以", "依据", "证据", "观测", "观察", "实验", "探测", "推导", "证明", "例如", "比如",
)
_SELF_CORRECTION_KEYWORDS = (
    "我原先", "我之前", "原来以为", "纠正", "改正", "修正", "不对", "错在", "其实应该是",
)

_MODE_HINT = {
    "numeric_value": "先检查计算过程：代入、进位/借位、正负号，再核对题目要求。",
    "equation_solution": "检查三步：移项是否变号？同类项是否合并正确？系数除法是否算对？",
    "symbolic_equivalence": "检查代数变形：去括号每一项都乘到？合并同类项有没有漏项、错符号？",
    "boolean_judgment": "回到定义逐条核对：等式？含未知数？一元？一次？哪一条不满足？",
}


def _step_score(table: tuple[tuple[int, float], ...], value: int) -> float:
    """阶梯分档：返回所有满足 ``value >= 阈值`` 的档位中最高分（与表序无关）。"""
    best = 0.0
    for threshold, score in table:
        if value >= threshold and score > best:
            best = score
    return best


def _concept_hits(text: str, concepts: list[str]) -> list[str]:
    return [c for c in concepts if c and c in text]


def offline_feynman_scores(
    transcript: str, core_concepts: list[str], rubric_dimensions: list[dict]
) -> tuple[list[dict], bool]:
    """离线启发式分维评分（R27 重构：分维不同权重 + evidence/自纠真实分档）。

    返回 (card, evidence_plausible)。card 元素 {key, score, evidence_quote, comment}
    且 ``evidence_quote`` 必为 transcript 子串（服务端包含校验与离线一致性；见 R27 §2）。
    """
    text = (transcript or "").strip()
    hits = _concept_hits(text, core_concepts)
    n = len(hits)
    target = max(1, len(core_concepts))
    length = len(text)
    has_evidence = any(k in text for k in _EVIDENCE_KEYWORDS)
    has_self_correction = any(k in text for k in _SELF_CORRECTION_KEYWORDS)
    plausible = n >= 1
    # 讲全程度（own_words 与"讲得对"代理分）：概念覆盖 × 篇幅（+依据）→ 明确档位。
    # "中档"（覆盖 ≥3 目标 + 篇幅 ≥25 + 有依据）对应"看过追问提示后自己把该讲的补齐"。
    if n >= target or (n >= 4 and length >= 40):
        cover_score = 0.95
    elif n >= 3 and length >= 40:
        cover_score = 0.85
    elif (n >= 3 and length >= 25) or (n >= 2 and length >= 30):
        cover_score = 0.75
    elif n >= 1:
        cover_score = 0.45 if has_evidence else 0.3
    else:
        cover_score = 0.05
    base = _step_score(_BY_CONCEPTS, n)
    if n >= 3 and length >= 40:
        detail = 0.75 + (0.10 if has_evidence else 0.0)
    elif (n >= 3 and length >= 25) or (n >= 2 and length >= 25):
        detail = 0.7
    else:
        detail = 0.0
    base = max(base, detail)

    quote = text[:40] + ("…" if len(text) > 40 else "")
    scores: dict[str, tuple[float, str]] = {}
    for dim in rubric_dimensions:
        key = str(dim.get("key", ""))
        base_score = BASE_SCORES.get(key, 0.3)
        if key == "own_words":
            score, why = max(base_score, cover_score), "是否用自己的话讲全（离线按核心概念覆盖分档）"
        elif key == "evidence":
            score = min(1.0, base + (0.12 if has_evidence else 0.0))
            why = "给出了依据（因为/观测/推导等）" if has_evidence else "未给出依据（缺观测/实验/推导类表述）"
        elif key == "self_correction":
            # 离线无法真的"追问"，给保底分体现"愿意接受修正"；明确的自纠表述再上调
            score = 0.7 if has_self_correction else 0.5
            why = "体现了自我修正" if has_self_correction else "已给出可被追问修正的说法"
        else:
            # correctness / example_and_edge / evidence_and_reasoning 及未知维度：
            # 一律以"核心概念覆盖"为基础分（concept 覆盖是这类维度的可判据代理）
            score, why = base, f"提到核心概念 {n}/{target}（{('、'.join(hits[:3]) or '无')}）"
        scores[key] = (round(score, 3), why)
    card = [
        {
            "key": str(dim.get("key", "")),
            "score": scores[str(dim.get("key", ""))][0],
            "evidence_quote": quote,
            "comment": scores[str(dim.get("key", ""))][1] + "（离线启发式，仅供参考）",
        }
        for dim in rubric_dimensions
    ]
    return card, plausible


def offline_gap_check(ctx: GapCheckIn) -> GapCheckOut:
    """离线缺口补答启发式：只判目标缺口维度是否补上（只更新该维度）。"""
    text = (ctx.student_answer or "").strip()
    gap = ctx.target_gap or {}
    key = str(gap.get("key", ""))
    if len(text) < 10:
        return GapCheckOut(
            gap_filled=False,
            dimension_updates=[],
            comment="补答太短，还没有具体回答追问的内容——请把你的依据/方法说清楚（≥10 字）。",
        )
    hits = _concept_hits(text, list(ctx.core_concepts or []))
    has_evidence = any(k in text for k in _EVIDENCE_KEYWORDS)
    has_self_correction = any(k in text for k in _SELF_CORRECTION_KEYWORDS)
    if key == "evidence":
        filled = has_evidence
        score = 0.9 if (has_evidence and len(hits) >= 2) else 0.82 if has_evidence else 0.0
        why = "补上了'依据/方法'缺口（给出观测、实验或推导依据）" if filled else "仍未给出可核对的依据/方法"
    elif key == "self_correction":
        filled = has_self_correction
        score = 0.85 if filled else 0.0
        why = "体现了自我修正" if filled else "仍未体现自我修正（说出原先哪里理解错了即可）"
    elif key == "own_words":
        filled = len(hits) >= 1 or len(text) >= 30
        score = 0.85 if filled else 0.0
        why = "用自己的话补充说明了" if filled else "补答没有实质内容"
    else:  # correctness 及未知维度
        filled = len(hits) >= 1
        score = 0.9 if len(hits) >= 2 else 0.85 if filled else 0.0
        why = f"补上了缺口（提到 {('、'.join(hits) or '—')}）" if filled else "补答未涉及该缺口的核心概念"
    quote = text[:40] + ("…" if len(text) > 40 else "")
    updates = (
        [{"key": key, "score": round(score, 3), "evidence_quote": quote,
          "comment": why + "（离线启发式，仅供参考）"}]
        if filled and key
        else []
    )
    return GapCheckOut(
        gap_filled=bool(filled),
        dimension_updates=updates,
        comment=why,
    )


# ---------------------------------------------------------------------------
# R35 S6：🤔 小思考的引文纪律（"零基础学生只读讲解就能答"才允许下发）
# ---------------------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")


def sentence_with(body: str, needle: str, *, min_chars: int = citations.MIN_QUOTE_CHARS) -> str:
    """从讲解正文里取**包含该关键词**的整句（供引文用）；取不到返回空串。"""
    if not body or not needle:
        return ""
    for sent in _SENTENCE_SPLIT.split(body):
        s = sent.strip()
        if len(citations.normalize(s)) < min_chars:
            continue
        if citations.normalize(needle) and citations.normalize(needle) in citations.normalize(s):
            return s
    return ""


def student_quote(transcript: str, *, min_chars: int = citations.MIN_QUOTE_CHARS) -> str:
    """R35 S4：从学生原话里取一段**可逐字引用**的片段（离线兜底与真模型同一把尺子）。

    取不到（归一化后不足门槛）→ 返回空串 → 调用方走 `reteach`（禁止硬造发散题）。
    实现委托 `service.feynman_ledger.student_quote`（**单一实现**，不在网关里重写一份）。
    """
    from ..service.feynman_ledger import student_quote as _sq

    return _sq(transcript, min_chars=min_chars)


def filter_asks(out: ExplainOut, *, sources: list[str], fact_ids: set[str] | None = None) -> ExplainOut:
    """只保留**有据**的 asked_to_confirm（S6）：引文须逐字出自讲解（≥6 字，citations 同一把尺子）；
    若声明了 `taught_facts`，引用的 fact_ids 必须落在其中。无据的那条**直接丢弃**（模板套话不再兜底）。
    """
    kept: list[str] = []
    kept_basis: list[CiteBasis] = []
    declared = fact_ids or set()
    for i, ask in enumerate(out.asked_to_confirm or []):
        basis = out.asks_basis[i] if i < len(out.asks_basis) else None
        quote = str(getattr(basis, "quote", "") or "")
        if quote and not any(citations.is_valid(quote, s) for s in sources if s):
            continue  # 引文不在讲解里 → 不可答
        if not quote:
            continue  # 无引文 → 不可答
        ids = [str(x) for x in (getattr(basis, "fact_ids", None) or [])]
        if declared and any(x not in declared for x in ids):
            continue  # 引用了未声明的事实 id
        kept.append(ask)
        kept_basis.append(basis)
    return ExplainOut(lecture_md=out.lecture_md, asked_to_confirm=kept, asks_basis=kept_basis)


class AiGateway(Protocol):
    """service 只依赖此协议。所有方法要么返回校验过的输出，要么抛 AiCallError。

    strategy（R12）：fast|think|None —— 服务层经 ai/tier 决策后传入；None=按调用点默认档。
    """

    name: str

    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut: ...
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut: ...
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut: ...
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut: ...
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut: ...
    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut: ...
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut: ...
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut: ...
    # R35 S3：挑战题池（单独生成 / 单独判分；**完全不上算**）
    def challenge_exercise(self, ctx: ChallengeIn, *, strategy: str | None = None) -> ChallengeOut: ...
    def challenge_check(self, ctx: ChallengeCheckIn, *, strategy: str | None = None) -> ChallengeCheckOut: ...


class OfflineGateway:
    """确定性离线兜底实现（无 key 默认；真模型失败时 service 回落至此路径）。"""

    name = "offline"
    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        del strategy  # 离线实现忽略档位（决策层在 service 记账）
        header = "（离线模式：以下为官方讲解稿原文）\n\n"
        lecture = ctx.explanation_body.strip() or "（本节点暂无讲解稿）"
        asks: list[str] = []
        asks_basis: list[CiteBasis] = []
        if ctx.core_concepts:
            concept = str(ctx.core_concepts[0])
            quote = sentence_with(ctx.explanation_body, concept)
            if quote:  # R35 S6：没有讲解依据就不出这条（离线模式也不得凭空发问）
                asks.append(f"请确认：你能用自己的话说出「{concept}」是什么吗？")
                asks_basis.append(CiteBasis(fact_ids=[], quote=quote))
        return ExplainOut(lecture_md=header + lecture, asked_to_confirm=asks, asks_basis=asks_basis)

    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        del strategy
        return AnswerQuestionOut(
            reply_md=(
                "（离线模式）我暂时无法针对你的具体问题自由作答。"
                "建议先重读本课讲解稿原文，再完成练习；如果仍卡住，请把卡住的那句话原样发给我，"
                "我会记录下来，联网后由老师为你详细解答。"
            ),
            needs_more_info=False,
            out_of_scope=False,
        )

    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        del strategy
        return HintOnErrorOut(hint_md=_MODE_HINT.get(ctx.mode, "再读一遍题目，检查每一步推导是否都有依据。"))

    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")

    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        del strategy
        text = ctx.transcript.strip()
        if len(text) < MIN_FEYNMAN_CHARS:
            raise AiCallError("feynman_evaluate", f"口述过短（{len(text)}<{MIN_FEYNMAN_CHARS}字），按敷衍处理")
        card, plausible = offline_feynman_scores(text, list(ctx.core_concepts), list(ctx.rubric_dimensions))
        dims = [FeynmanDimScore(**c) for c in card]
        return FeynmanEvaluateOut(
            dimension_scores=dims,
            overall_note="离线启发式评分（未接 LLM），仅供参考；evidence_quote 均为本轮文本子串。",
            misconceptions_found=[],
            recommend_action="pass" if plausible else "followup",
            confidence=0.3,  # 离线自评置信度（低=启发式；不参与通过判定）
        )

    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        del strategy
        # R35 S4：追问必须**逐字引用学生刚说的话**；引用不出来 → reteach（禁止硬造发散题）。
        quote = student_quote(ctx.student_transcript)
        if not quote:
            return FeynmanFollowupOut(reteach=True)
        # R27：优先按"最弱缺口"定向追问（一次一个），不再自由发问
        gap = (ctx.unmet_gaps or [None])[0]
        if gap:
            key, desc = str(gap.get("key", "")), str(gap.get("description", "")).strip()
            if desc:
                return FeynmanFollowupOut(
                    question_md=(f"你刚才说：「{quote}」——这句话里缺的是：**{desc}**（维度：{key}）。"
                                 "请就这一点补讲，用你自己的话讲清依据即可。"),
                    student_quote=quote,
                    missing=desc,
                )
        # 无缺口描述：**不套用 socratic 模板兜底**（S4），只针对学生原话要求讲透
        return FeynmanFollowupOut(
            question_md=(f"你刚才说：「{quote}」——这句话还不足以让我确认你讲懂了这个概念。"
                         "请把它展开讲透：关键一步的依据是什么？"),
            student_quote=quote,
            missing="讲解还停在结论层面，没有给出关键一步的依据",
        )

    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut:
        del strategy
        return offline_gap_check(ctx)

    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        return ClassifyErrorOut(error_type="unknown")

    # ---- R35 S3：挑战题池（离线确定性示例；**完全不上算**） ----
    def challenge_exercise(self, ctx: ChallengeIn, *, strategy: str | None = None) -> ChallengeOut:
        del strategy
        concept = str((ctx.core_concepts or ["本单元内容"])[0])
        return ChallengeOut(
            prompt_md=(
                f"（离线模式 · 示例挑战题）本单元只讲了「{concept}」在讲解稿里出现的那些情形。"
                f"请**不看讲解**想一想：把「{concept}」用到讲解里**没有出现过的**情形"
                "（换一类对象、数量级变大/变小、或出现极端值）会怎样？说说你的判断与理由。"
            ),
            answer_hint_md="用几句话说明判断与理由即可（挑战题没有标准答案）。",
            why_hard_md="它要求讲解之外的迁移/推广知识——所以答不出**完全不影响任何进度**。",
            difficulty=3,
        )

    def challenge_check(self, ctx: ChallengeCheckIn, *, strategy: str | None = None) -> ChallengeCheckOut:
        del strategy
        text = (ctx.student_answer or "").strip()
        if len(text) < 6:
            return ChallengeCheckOut(
                correct=False, score=0.0,
                feedback_md="挑战题没有标准答案；但你这次几乎没写内容——说一句你的判断和理由就好。",
                better_md="（离线模式不提供参考思路。）",
            )
        return ChallengeCheckOut(
            correct=True, score=0.6,
            feedback_md="已记录（离线启发式：只看你有没有给出实质判断与理由，不判对错）。"
                        "挑战题**不计入任何进度**，只进复盘。",
            better_md="（离线模式不提供参考思路；接入真模型后会给出更具体的点评。）",
        )


# --------------------------------------------------------------------------
# OpenAI 兼容网关（真模型）
# --------------------------------------------------------------------------
class OpenAICompatibleGateway:
    """经 provider.chat_json 调真模型；每个调用点 = schema 化（docs/05 §3/§6）。"""

    name = "openai-compatible"

    def __init__(self, provider: OpenAICompatibleProvider):
        self._p = provider

    # ---- prompt 装配（R39 §2：模板可在程序内修改；改动后**下一次调用即生效**） ----
    def _texts(self, call_name: str, *, subject_id: str = "", unit_id: str = "") -> tuple[str, str, str]:
        """取生效模板 ``(system_template, user_template, 版本标签)``（唯一入口见 prompt_runtime）。"""
        from . import prompt_runtime

        rt = prompt_runtime.PromptRuntime(call_name, subject_id=subject_id, unit_id=unit_id)
        return rt.system_template, rt.user_template, rt.version

    def _render(self, call_name: str, *, context_vars: dict | None = None,
                task_vars: dict | None = None, subject_id: str = "",
                unit_id: str = "", material_discipline: bool = False) -> tuple[str, str, str]:
        """渲染 ``(system, user, 版本标签)``；渲染失败 → 记账 + 回退默认模板。"""
        from . import prompt_templates as reg

        spec = reg.PROMPTS[call_name]
        sys_t, usr_t, tag = self._texts(call_name, subject_id=subject_id, unit_id=unit_id)
        cv = dict(context_vars or {})
        # 教材纪律占位符：只有"这次真的有教材"时才注入（无教材时置空，逐字等于旧行为）
        cv.setdefault("material_discipline", reg._MATERIAL_DISCIPLINE if material_discipline else "")
        tv = dict(task_vars or {})
        try:
            sys_final = reg.render(sys_t, **cv) if sys_t else ""
            usr_final = reg.render(usr_t, **tv) if usr_t else ""
            if reg.is_material_disciplined(sys_t) and not material_discipline:
                pass  # 无教材：占位符已置空
            return sys_final, usr_final, tag
        except reg.PromptError as e:
            from ..service import ledger

            ledger.note(
                ledger.CAT_OTHER, f"提示词（{call_name}）",
                f"提示词渲染失败，本次已回退默认模板：{e}",
                impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
                subject_id=subject_id, unit_id=unit_id,
                detail={"call_name": call_name, "error": str(e)[:200]},
            )
            dv = reg.default_vars(spec)
            dv.update({k: str(v) for k, v in cv.items()})
            dv.update({k: str(v) for k, v in tv.items()})
            return (reg.render(spec.system, **dv) if spec.system else "",
                    reg.render(spec.user, **dv) if spec.user else "",
                    f"fallback-default:{call_name}")

    def _call_json(self, call, sys_text: str, usr_text: str, *, strategy: str | None,
                   prompt_versions: str, subject_id: str = "", unit_id: str = ""):
        """统一出口：把渲染后的 prompt 交给 provider，并带上审计元数据（R39 §3）。"""
        subj = subject_id or _subject_of_node(unit_id)
        return self._p.chat_json(
            call,
            [{"role": "system", "content": sys_text}, {"role": "user", "content": usr_text}],
            strategy=strategy,
            audit={"subject_id": subj, "unit_id": unit_id,
                   "prompt_versions": prompt_versions},
        )

    # ---- 调用点 1：讲解 ----
    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        facts = list(getattr(ctx, "taught_facts", []) or [])
        fact_hint = ""
        if facts:
            fact_hint = ("本单元已声明事实（可引用其 id）："
                         + "；".join(f"{f.get('id')}={str(f.get('text'))[:40]}" for f in facts[:8]))
        system, user, tag = self._render(
            "explain_node",
            context_vars=context_parts(
                level=getattr(ctx, "level", ""),
                explanation_body=getattr(ctx, "explanation_body", ""),
                worked_examples=getattr(ctx, "worked_examples", []) or [],
                whitelist=list(getattr(ctx, "whitelist", []) or []),
                core_concepts=list(getattr(ctx, "core_concepts", []) or []),
                style=getattr(ctx, "profile_style_block", ""),
            ),
            task_vars={"fact_hint": " " + fact_hint if fact_hint else "",
                       "node_title": ctx.node_title or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_EXPLAIN_NODE, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return filter_asks(ExplainOut(**out.parsed),
                           sources=[out.parsed.get("lecture_md") or "", ctx.explanation_body or ""],
                           fact_ids={str(f.get("id")) for f in facts})

    # ---- 调用点 2：答疑 ----
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        system, user, tag = self._render(
            "answer_question",
            context_vars=context_parts(
                level=getattr(ctx, "level", ""),
                explanation_body=getattr(ctx, "explanation_body", ""),
                worked_examples=[],
                whitelist=list(getattr(ctx, "whitelist", []) or []),
                core_concepts=list(getattr(ctx, "core_concepts", []) or []),
                style=getattr(ctx, "profile_style_block", ""),
            ),
            task_vars={"question": ctx.student_question or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_ANSWER_QUESTION, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return AnswerQuestionOut(**out.parsed)

    # ---- 调用点 4：错题提示（禁令：禁止输出完整解答） ----
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        system, user, tag = self._render(
            "hint_on_error",
            context_vars=context_parts(
                level="", explanation_body="", worked_examples=[], whitelist=[],
                core_concepts=[],
                extra_bans=[
                    "这是提示生成：**绝对禁止给出完整解答或最终答案表达式**，"
                    "只给方向性提示（哪一步可疑、检查什么）。",
                ],
            ),
            task_vars={"prompt": ctx.prompt or "", "mode": ctx.mode or "",
                       "student_answer": ctx.user_answer or "",
                       "judge_detail": ctx.judge_detail or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_HINT_ON_ERROR, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return HintOnErrorOut(**out.parsed)

    # ---- 调用点 6：费曼评分（逐字 evidence） ----
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        system, user, tag = self._render(
            "feynman_evaluate",
            context_vars=context_parts(
                level="", explanation_body="", worked_examples=[],
                whitelist=list(getattr(ctx, "core_concepts", []) or []),
                core_concepts=list(getattr(ctx, "core_concepts", []) or []),
                extra_bans=[
                    "评分必须可审计：每个维度必须给出 **evidence_quote —— 逐字引用学生原话片段**，"
                    "禁止无据评分；misconceptions_found 也须附 evidence。",
                ],
            ),
            task_vars={"task_prompt": ctx.task_prompt or "",
                       "rubric_dimensions": _js(ctx.rubric_dimensions),
                       "transcript": ctx.transcript or "",
                       "previous_round": _js(ctx.previous_round),
                       "previously_acknowledged": _js(ctx.previously_acknowledged)},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_FEYNMAN_EVALUATE, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return FeynmanEvaluateOut(**out.parsed)

    # ---- 调用点 7：Socratic 追问（R27 定向缺口 + R35 S4 引文纪律） ----
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        system, user, tag = self._render(
            "feynman_followup",
            context_vars=context_parts(
                level="", explanation_body="", worked_examples=[], whitelist=[], core_concepts=[],
                extra_bans=[
                    "追问必须**定向到 unmet_gaps 里最弱的那一个缺口**（一次只问一个问题、只问这一点），"
                    "不要泛泛自由发问，也不要给出答案。",
                    "**R35 S4 追问纪律（硬要求）**："
                    "① `student_quote` 必须**逐字**取自 student_transcript（照抄一段 ≥6 字的原话，"
                    "不得改写、不得拼接；服务端做逐字包含校验，不通过则整条追问作废）；"
                    "② `missing` 必须说清**这句话缺了什么**（学生视角，具体到这一点）；"
                    "③ `question_md` 只针对该缺口，并且要**引用学生原话**再提问。"
                    "④ 若学生的话里**没有可引用的实质内容**（例如只写「我不知道」「不会」），"
                    "**禁止硬造发散题**：把 `reteach` 置 true（`student_quote`/`missing`/`question_md` 留空）。",
                    "禁止任何指代不明的模板套话作为兜底（如「这个概念还适用于什么情况」"
                    "「它与你学过的内容有什么联系」）——无从判断的问题一律不出。",
                ],
            ),
            task_vars={"unmet_gaps": _js(ctx.unmet_gaps),
                       "socratic_topics": _js(ctx.socratic_followups),
                       "previous_scores": _js(ctx.previous_scores),
                       "student_transcript": ctx.student_transcript or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_FEYNMAN_FOLLOWUP, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return FeynmanFollowupOut(**out.parsed)

    # ---- 调用点 13（R27）：缺口补答评估（轻量，只更新缺口维度） ----
    def feynman_gap_check(self, ctx: GapCheckIn, *, strategy: str | None = None) -> GapCheckOut:
        system, user, tag = self._render(
            "feynman_gap_check",
            context_vars=context_parts(
                level="", explanation_body="", worked_examples=[],
                whitelist=list(getattr(ctx, "core_concepts", []) or []),
                core_concepts=list(getattr(ctx, "core_concepts", []) or []),
                extra_bans=[
                    "这是**缺口补答评估**（不是整体重评）：只判断 target_gap.key 这一个维度是否补上，"
                    "dimension_updates **只允许包含该维度一条**；"
                    "evidence_quote 必须**逐字引用 student_answer**（服务端做包含校验，杜撰即降级）；"
                    "若补答没有真正回答该缺口，gap_filled=false 且 dimension_updates 为空数组。",
                ],
            ),
            task_vars={"task_prompt": ctx.task_prompt or "",
                       "rubric_dimensions": _js(ctx.rubric_dimensions),
                       "followup_question": ctx.followup_question or "",
                       "target_gap": _js(ctx.target_gap),
                       "student_answer": ctx.student_answer or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_FEYNMAN_GAP_CHECK, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return GapCheckOut(**out.parsed)

    # ---- 调用点 14（R35 S3）：挑战题单独生成（**允许超出讲解**——与核心题池刻意相反） ----
    def challenge_exercise(self, ctx: ChallengeIn, *, strategy: str | None = None) -> ChallengeOut:
        system, user, tag = self._render(
            "challenge_exercise",
            context_vars=context_parts(
                level=ctx.level, explanation_body=ctx.explanation_body,
                worked_examples=list(ctx.worked_examples or []),
                whitelist=list(ctx.whitelist or []),
                core_concepts=list(ctx.core_concepts or []),
                style=ctx.profile_style_block,
                extra_bans=[
                    "⚠️ 本调用点是**挑战题池**（R35 S3）：上面那条『禁止引入白名单之外的新名词/公式/方法』"
                    "**对本题不适用**——挑战题**就是要**超出讲解（更广的背景、迁移推广、极端情形、"
                    "与其它知识的联系）。这不是越界，是本池的定义。",
                    "但必须：只出**一道**题；可被一个没读过本讲解的人凭常识或外部知识**尝试**作答"
                    "（不许出无解、需要未公开数据、或依赖本节点私有编号的题）；"
                    "不得照抄讲解稿里的原题；用 why_hard_md 说明它为什么超出讲解。",
                ],
            ),
            task_vars={"node_title": ctx.node_title or "",
                       "core_concepts": "、".join(ctx.core_concepts or []),
                       "asked_before": str(ctx.asked or 0)},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_CHALLENGE_EXERCISE, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return ChallengeOut(**out.parsed)

    # ---- 调用点 15（R35 S3）：挑战题判分（只记复盘，不写任何账本） ----
    def challenge_check(self, ctx: ChallengeCheckIn, *, strategy: str | None = None) -> ChallengeCheckOut:
        system, user, tag = self._render(
            "challenge_check",
            context_vars=context_parts(
                level="", explanation_body="", worked_examples=[], whitelist=[], core_concepts=[],
                extra_bans=[
                    "这是**挑战题判分**：挑战题允许超出讲解，学生用课外知识作答是**正确行为**，"
                    "不得因此扣分。只判「有没有给出实质判断 + 理由是否站得住」；"
                    "没有标准答案时，讲清楚即可给分。",
                    "feedback_md 必须对学习者说人话（鼓励 + 指出差在哪）；better_md 给参考思路"
                    "（挑战题不上算，教比考重要）。",
                ],
            ),
            task_vars={"prompt_md": ctx.prompt_md or "",
                       "student_answer": ctx.student_answer or "",
                       "node_title": ctx.node_title or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_CHALLENGE_CHECK, system, user, strategy=strategy,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return ChallengeCheckOut(**out.parsed)

    # ---- 调用点 8：错误分类 ----
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        system, user, tag = self._render(
            "classify_error",
            task_vars={"prompt": ctx.prompt or "", "correct_solution": ctx.correct_solution or "",
                       "student_answer": ctx.user_answer or ""},
            unit_id=ctx.node_id)
        out = self._call_json(CALL_CLASSIFY_ERROR, system, user, strategy=None,
                             prompt_versions=tag, unit_id=ctx.node_id)
        return ClassifyErrorOut(**out.parsed)

    # ---- 调用点 3：变体（MVP 不启用，docs/08 §1） ----
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")

    # ---- 调用点 5：解题步骤（轻量；保留接口） ----
    def explain_solution_step(self, step_text: str, *, strategy: str | None = None) -> SolutionStepOut:
        system, user, tag = self._render(
            "explain_solution_step",
            context_vars=context_parts(level="", explanation_body="", worked_examples=[],
                                       whitelist=[], core_concepts=[]),
            task_vars={"step_text": step_text or ""})
        out = self._call_json(CALL_EXPLAIN_SOLUTION_STEP, system, user, strategy=strategy,
                             prompt_versions=tag)
        return SolutionStepOut(**out.parsed)


# --------------------------------------------------------------------------
# 工厂
# --------------------------------------------------------------------------
def gateway_factory(
    *,
    api_key: str = "",
    base_url: str = "",
    heavy_model: str = "",
    light_model: str = "",
    log_sink: LogSink | None = None,
    transport=None,
) -> AiGateway:
    """有 key → OpenAI 兼容真网关；无 key → OfflineGateway（离线兜底）。"""
    if api_key:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            model_heavy=heavy_model,
            model_light=light_model,
            log_sink=log_sink,
            transport=transport,
        )
        return OpenAICompatibleGateway(provider)
    return OfflineGateway()


__all__ = [
    "AiGateway",
    "OfflineGateway",
    "OpenAICompatibleGateway",
    "gateway_factory",
    "MIN_FEYNMAN_CHARS",
    "offline_feynman_scores",
    "offline_gap_check",
    "filter_asks",
    "sentence_with",
    "student_quote",
]
