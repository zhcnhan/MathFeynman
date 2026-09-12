"""service.ai_trace：**提示词监听 / AI 对话审计**（docs/09 R39 §3）。

- **每次调用一条**记录（``ai_logs`` 扩字段）：时间 · 调用点 · 档位 · 模型名 · 渲染后 system/user ·
  原始返回 · 解析/校验结果 · 重试次数 · token · 耗时 · 最终结局（采纳/降级/丢弃/失败）；
- **防库爆**：全文（system/user/response）落文件 ``.runtime/ai_trace/<时间>-<调用点>-<id>.txt``，
  DB 只存 **路径 + 预览 + 字符数**；界面默认收起长文，**展开即完整**（读文件）；
- **默认记录**：不靠开关决定"要不要留证据"（调试开关只决定界面入口是否出现）；
- **红线**：① 全文里**不得**出现 API Key（本模块只收 prompt/response，不碰密钥；
  另有一道兜底：写文件前把疑似密钥替换为 ``[已隐去]``）；② 记录**不得阻塞**主流程
  （一切异常吞掉，但写文件失败会**记账**"审计写入失败"——不静默）；
- 文件按保留期清理时，**账本记"已清理哪几条"**（``cleanup_old``）。
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import REPO_ROOT
from . import ledger

OUTCOME_ADOPTED = "adopted"     # 采纳
OUTCOME_DEGRADED = "degraded"   # 降级（改走离线/兜底路径）
OUTCOME_DROPPED = "dropped"     # 丢弃（模型给了但被服务端校验丢掉）
OUTCOME_FAILED = "failed"       # 失败（重试耗尽/网络错误）

OUTCOME_LABELS_ZH = {
    OUTCOME_ADOPTED: "采纳",
    OUTCOME_DEGRADED: "降级",
    OUTCOME_DROPPED: "丢弃",
    OUTCOME_FAILED: "失败",
}

# 疑似密钥的兜底遮蔽（审计全文里绝不出现 API Key）
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,})")
# **R56**：用户**在设置页填的** Key（可能不带 sk- 前缀）也要遮蔽——由 model_config 每次解析时登记
_EXTRA_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """登记一个"必须遮蔽的密钥"（幂等；只在内存里，不落盘）。"""
    v = (value or "").strip()
    if len(v) >= 8:
        _EXTRA_SECRETS.add(v)

DEFAULT_DIR = ".runtime/ai_trace"
DEFAULT_KEEP_DAYS = 30
PREVIEW_CHARS = 600


def trace_dir() -> Path:
    import os

    raw = (os.getenv("MF_AI_TRACE_DIR") or DEFAULT_DIR).strip() or DEFAULT_DIR
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


def keep_days() -> int:
    import os

    try:
        return int(os.getenv("MF_AI_TRACE_KEEP_DAYS", str(DEFAULT_KEEP_DAYS)) or DEFAULT_KEEP_DAYS)
    except Exception:
        return DEFAULT_KEEP_DAYS


def redact(text: str) -> str:
    """遮蔽疑似密钥（红线：审计里不得出现 API Key）。

    **R56**：除正则外，还逐字遮蔽"设置页里填过的 Key"（`register_secret` 登记）——
    自定义服务商的 Key 未必长成 `sk-…`，只靠正则兜不住。
    """
    out = _SECRET.sub("[已隐去]", text or "")
    for secret in _EXTRA_SECRETS:
        if secret and secret in out:
            out = out.replace(secret, "[已隐去]")
    return out


def _preview(text: str, *, chars: int = PREVIEW_CHARS) -> str:
    t = text or ""
    if len(t) <= chars:
        return t
    return t[:chars] + f"\n…（预览截断，共 {len(t)} 字，完整内容见审计文件）"


# ---------------------------------------------------------------------------
# R44 A：审计全文文件名**防碰撞**（同秒同调用点不得覆盖）
# ---------------------------------------------------------------------------
# 缺陷（R43 架构侧独立复现）：旧实现用 `abs(hash((call_name, at)))` 当唯一后缀——
# 同一秒内同一调用点 hash 完全相同 → 同名 → `write_text` **静默覆盖**，
# 前几次调用的全文永久丢失（违反 R39 §1「一切显性」/§3「展开即完整」）。
#
# 修法（三层，全部不依赖 hash() 做唯一性）：
#   ① **进程内同秒序号**：`(stamp, call_name)` → 序号（`-02`、`-03`…），首次落盘不加后缀；
#   ② **落盘冲突兜底**：文件名已被占用（另一进程写的、或人为预置）→ **换名**（附中文说明）；
#   ③ **原子独占写入**：`open("x")` —— 即使 ①② 都没预见，也**绝不会覆盖**已有文件。
# 三者任一触发 → `ledger.note(...)` 记一条中文账目（**绝不再出现静默覆盖**）。
# 文件名仍保持 `<时间>-<调用点>[-序号].txt` 的可读形状（用户靠它肉眼找）。
_SEQ_LOCK = threading.Lock()
_SEQ_BY_KEY: dict[tuple[str, str], int] = {}
# **R48 A**：本秒该调用点的"换名报因"记忆——一旦确认"目标名被占用"，**该秒内每次**换名都用同一原因
# （否则第 2–4 次只剩通用文案"同秒多次"，把更重要的"被占用"丢掉）。
_COLLISION_BY_KEY: dict[tuple[str, str], str] = {}
_MAX_NAME_TRIES = 200


def _reset_naming_state() -> None:
    """清空"同秒序号 + 换名报因"进程内记忆（**仅供测试**复位，避免用例之间互相污染）。"""
    with _SEQ_LOCK:
        _SEQ_BY_KEY.clear()
        _COLLISION_BY_KEY.clear()


def _next_name(entry_dir: Path, stamp: str, call_name: str) -> tuple[Path, str, str]:
    """返回 ``(path, base_name, 冲突说明)``；冲突说明非空＝发生过换名（需记账）。

    - 首次（该秒该调用点第 1 次）→ ``<stamp>-<call_name>.txt``（最可读）；
    - 同秒第 n 次 → ``<stamp>-<call_name>-02.txt``、``-03``…（序号单调，不覆盖）；
    - 目标名已被占用（跨进程/预置文件）→ 序号继续自增**换名**，并在冲突说明里写明原因；
      **R48 A**：该原因**记在该秒该调用点上**，本秒后续每次换名都沿用（不再退化成"同秒多次"）。
    - **R50 A（上界）**：进来先**只保留"当前秒"的键**——键是 `(秒, 调用点)`，跨秒即丢，
      记忆量恒定为"当前秒的调用点数"（不再 `86400 × 调用点数/天` 无界增长）；
      **同一秒内的序号与换名报因原样保留**（正确性所在，R48 的"报因不退化"不受影响）。
    """
    with _SEQ_LOCK:
        # R50 A：一行上界——两个字典都只留 stamp 等于本次的项（同秒项一律不动）
        for _d in (_SEQ_BY_KEY, _COLLISION_BY_KEY):
            for _k in [k for k in _d if k[0] != stamp]:
                _d.pop(_k, None)
        key = (stamp, call_name)
        seq = _SEQ_BY_KEY.get(key, 0)
        base = f"{stamp}-{call_name}"
        first = f"{base}.txt"
        if seq == 0 and not (entry_dir / first).exists():
            _SEQ_BY_KEY[key] = 1
            return entry_dir / first, base, ""
        why = _COLLISION_BY_KEY.get(key, "")   # R48 A：本秒已确认的占用原因（有则沿用）
        if seq == 0:
            why = f"目标文件名已被占用（{first}，可能是另一进程写的或人为预置），已换名以免覆盖"
            _SEQ_BY_KEY[key] = 1               # R48 A：先置位（并记住报因）——本秒后续写入不再当作"首次"
            _COLLISION_BY_KEY[key] = why
        n = max(1, seq)
        while n <= _MAX_NAME_TRIES:
            name = f"{base}-{n + 1:02d}.txt"
            if not (entry_dir / name).exists():
                _SEQ_BY_KEY[key] = n + 1
                return entry_dir / name, base, (why or "")
            n += 1
        # 极端兜底：序号用尽（200 次同秒同名）→ 仍换名并说明
        _SEQ_BY_KEY[key] = n + 1
        name = f"{base}-{n + 1:04d}.txt"
        return entry_dir / name, base, (why or f"同秒同名次数过多（>{_MAX_NAME_TRIES}），已换名")


NAMING_HEAD = "==== 文件命名说明 ===="
_COLLISION_FALLBACK = "同一秒内对同一调用点多次记录："


def _rename_reason(*, base_name: str, final_name: str, collision: str) -> str:
    """换名的中文原因——**总账账目与文件正文共用同一句文案**（不写两份）。"""
    return ((collision + "；" if collision else _COLLISION_FALLBACK)
            + f"已改名为 `{final_name}`（原拟 `{base_name}.txt`），"
            "以确保每次调用的完整 prompt/response **各自独立留存、不被覆盖**")


def _naming_block(*, final_name: str, base_name: str, rename_reason: str) -> str:
    """**R46 A**：把"本文件为什么叫这个名字"写进文件正文（第二道可见性）。

    换名记账走独立连接——调用方持有写事务时可能只落到 stderr（R45 §3-1 保留该口径）。
    **不把审计改成持写事务**（那会把记审计变成主流程死锁源，违反 R39 §3）；改用文件自证：
    文件本身说明"原拟名 / 实际名 / 为什么换名"，**不依赖数据库**。
    """
    if final_name == f"{base_name}.txt":
        why = "本文件是该秒该调用点的**第 1 个**（目标名未被占用），**无需换名**。"
    else:
        why = rename_reason
    return (f"{NAMING_HEAD}\n"
            f"本文件实际文件名：{final_name}\n"
            f"原拟文件名：{base_name}.txt\n"
            f"命名说明：{why}\n")


def _write_file(*, call_name: str, subject_id: str, unit_id: str, at: str,
                model: str, tier: str, retries: int, outcome: str,
                latency_ms: int, prompt_tokens: int, completion_tokens: int,
                system: str, user: str, raw: str, parse_result: str,
                parse_ok: bool, prompt_versions: str) -> tuple[str, int]:
    d = trace_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = at.replace(":", "").replace("-", "").replace("+0000", "Z")
    meta = (
        "==== 本次调用的完整记录 ====\n"
        f"时间：{at}\n用途：{call_name}\n学科：{subject_id or '（无）'}\n单元：{unit_id or '（无）'}\n"
        f"模型档位：{tier}\n模型：{model}\n重试次数：{retries}\n"
        f"用时：{latency_ms} ms\n用量：输入 {prompt_tokens} + 输出 {completion_tokens}\n"
        f"结果：{OUTCOME_LABELS_ZH.get(outcome, outcome)}\n"
        f"提示词版本：{prompt_versions}\n"
        f"检查结果：{'通过' if parse_ok else '未通过'}｜{parse_result}\n"
        f"system 字数：{len(system)}\nuser 字数：{len(user)}\nAI 原始回答字数：{len(raw)}\n"
    )

    def render(final_name: str, base_name: str, rename_reason: str) -> str:
        """正文＝元信息 + **命名说明** + 三段完整内容（分段标记与解析器一致）。"""
        return (
            meta
            # 命名情况放在 system 段**之前**：`_split_trace`/`_meta_block` 按 `==== … ====`
            # 找自己的段，system/user/response 三段不受影响（`meta` 里可看到命名说明）
            + "\n" + _naming_block(final_name=final_name, base_name=base_name,
                                   rename_reason=rename_reason) + "\n"
            "==== 发给 AI 的完整内容 · system ====\n" + redact(system) + "\n"
            "\n==== 发给 AI 的完整内容 · user ====\n" + redact(user) + "\n"
            "\n==== AI 返回的完整内容（原始，未解析） ====\n" + redact(raw) + "\n"
            "\n==== 解析/校验结果 ====\n" + redact(parse_result) + "\n"
        )

    # ① 取候选名（同秒序号）+ ② 冲突换名；③ 再以 `x` 原子独占创建，彻底杜绝覆盖
    path, base_name, collision = _next_name(d, stamp, call_name)
    for _ in range(_MAX_NAME_TRIES):
        renamed = path.name != f"{base_name}.txt"
        reason = (_rename_reason(base_name=base_name, final_name=path.name, collision=collision)
                  if renamed else "")
        body = render(path.name, base_name, reason)
        try:
            with open(path, "x", encoding="utf-8", newline="") as fh:
                fh.write(body)
            if renamed:
                # 换了名（同秒多次 / 目标被占用）→ **必须显式记账**（不许静默）；
                # 同一句原因也写在文件正文里（R46 A：锁冲突下仍有第二道可见性）
                ledger.note(
                    ledger.CAT_OTHER, f"AI 对话审计文件（{call_name}）", reason,
                    impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
                    subject_id=subject_id, unit_id=unit_id,
                    detail={"kind": "trace_name_renamed", "base_name": f"{base_name}.txt",
                            "final_name": path.name, "collision": collision or "",
                            "reason_in_body": True},
                )
            return str(path), len(body)
        except FileExistsError:
            # 竞态：候选名刚好被占用（另一进程/线程）→ 换下一个序号再试
            collision = collision or (
                f"目标文件名已被占用（{path.name}，可能是另一进程写的或人为预置），已换名以免覆盖")
            path, base_name, _ = _next_name(d, stamp, call_name)
    raise OSError(f"审计文件名连续 {_MAX_NAME_TRIES} 次全部被占用，放弃写盘（已记账）")


def write_trace(*, call_name: str, system: str, user: str, raw: str = "",
                parsed: dict | None = None, parse_error: str = "", retries: int = 0,
                ok: bool = True, model: str = "", tier: str = "", latency_ms: int = 0,
                prompt_tokens: int = 0, completion_tokens: int = 0,
                outcome: str = OUTCOME_ADOPTED, subject_id: str = "", unit_id: str = "",
                prompt_versions: str = "", sink=None) -> dict:
    """记录一次调用：**先写全文文件，再把元数据交给 sink**（落 ``ai_logs``）。

    返回 ``{trace_path, trace_chars, wrote_file, entry}``。任何异常都不上抛（不阻塞主流程）。
    """
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parse_ok = bool(parsed) and not parse_error
    parse_result = "解析成功" if parse_ok else (parse_error or "未解析")
    if parsed:
        keys = "、".join(sorted(str(k) for k in parsed.keys()))
        parse_result = f"解析成功（字段：{keys}）"
    trace_path = ""
    trace_chars = 0
    wrote_file = False
    try:
        trace_path, trace_chars = _write_file(
            call_name=call_name, subject_id=subject_id, unit_id=unit_id, at=at, model=model,
            tier=tier, retries=retries, outcome=outcome, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            system=system, user=user, raw=raw, parse_result=parse_result, parse_ok=parse_ok,
            prompt_versions=prompt_versions,
        )
        wrote_file = True
    except Exception as e:  # 铁则：写文件失败要**记账**（不许静默）
        ledger.note(
            ledger.CAT_OTHER, f"AI 对话审计（{call_name}）",
            f"审计全文写入失败，本次调用的完整 prompt/response 未能留存：{e}",
            impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
            subject_id=subject_id, unit_id=unit_id,
            detail={"call_name": call_name, "error": str(e)[:200]},
        )
    entry = {
        "call_name": call_name, "model": model, "tier": tier,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "ok": bool(ok), "error": (parse_error or None), "latency_ms": latency_ms,
        "subject_id": subject_id, "unit_id": unit_id, "retries": int(retries or 0),
        "outcome": outcome, "prompt_versions": prompt_versions,
        "trace_path": trace_path, "trace_chars": trace_chars,
        "system_preview": _preview(system), "user_preview": _preview(user),
        "response_preview": _preview(raw), "parse_result": parse_result,
    }
    # "一切显性"在此的落法：**默认记录**——任何调用点（含自建 provider 的 outline 路径）
    # 都必须留下元数据；不给 sink 时落到默认 sink（ai_logs）。
    if sink is None:
        try:
            from .ai_sink import make_ai_log_sink

            sink = make_ai_log_sink()
        except Exception:
            sink = None
    if sink is not None:
        try:
            sink(entry)
        except Exception:  # 元数据写入失败同样不得阻塞（审计文件已在）
            pass
    return {"trace_path": trace_path, "trace_chars": trace_chars,
            "wrote_file": wrote_file, "entry": entry}


# ---------------------------------------------------------------------------
# 查询（调试模式界面）
# ---------------------------------------------------------------------------
def _to_iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _row_dict(r) -> dict:
    return {
        "id": int(r.id),
        "at": _to_iso(r.created_at),
        "call_name": r.call_name or "",
        "call_label": _call_label(r.call_name or ""),
        "subject_id": r.subject_id or "",
        "unit_id": r.unit_id or "",
        "tier": r.tier or "",
        "model": r.model or "",
        "ok": bool(r.ok),
        "outcome": r.outcome or OUTCOME_ADOPTED,
        "outcome_label": OUTCOME_LABELS_ZH.get(r.outcome or OUTCOME_ADOPTED, r.outcome or ""),
        "retries": int(r.retries or 0),
        "prompt_tokens": int(r.prompt_tokens or 0),
        "completion_tokens": int(r.completion_tokens or 0),
        "latency_ms": int(r.latency_ms or 0),
        "error": r.error or "",
        "trace_path": r.trace_path or "",
        "trace_chars": int(r.trace_chars or 0),
        "system_preview": r.system_preview or "",
        "user_preview": r.user_preview or "",
        "response_preview": r.response_preview or "",
        "parse_result": r.parse_result or "",
        "prompt_versions": r.prompt_versions or "",
        "is_failure": (not bool(r.ok)) or (r.outcome in (OUTCOME_FAILED, OUTCOME_DROPPED)),
    }


def _call_label(call_name: str) -> str:
    try:
        from ..ai import prompt_templates as reg

        spec = reg.PROMPTS.get(call_name)
        return spec.label if spec else call_name
    except Exception:
        return call_name


def query(db, *, subject_id: str = "", call_name: str = "", outcome: str = "",
          only_failed: bool = False, limit: int = 50, offset: int = 0) -> dict:
    """审计列表：时间倒序 + **失败/丢弃置顶**（前端另有红色标记）。"""
    from sqlalchemy import case, func, select

    from .. import models

    stmt = select(models.AiLog)
    cnt = select(func.count()).select_from(models.AiLog)
    conds = []
    if subject_id:
        conds.append(models.AiLog.subject_id == subject_id)
    if call_name:
        conds.append(models.AiLog.call_name == call_name)
    if outcome:
        conds.append(models.AiLog.outcome == outcome)
    if only_failed:
        conds.append((models.AiLog.ok.is_(False))
                     | (models.AiLog.outcome.in_((OUTCOME_FAILED, OUTCOME_DROPPED))))
    for c in conds:
        stmt = stmt.where(c)
        cnt = cnt.where(c)
    # 失败/丢弃置顶，其次按时间倒序
    bad = case((((models.AiLog.ok.is_(False))
                 | (models.AiLog.outcome.in_((OUTCOME_FAILED, OUTCOME_DROPPED)))), 0),
               else_=1)
    stmt = stmt.order_by(bad, models.AiLog.id.desc()).offset(max(0, offset)).limit(
        max(1, min(int(limit or 50), 200)))
    rows = list(db.execute(stmt).scalars())
    total = int(db.execute(cnt).scalar() or 0)
    return {
        "items": [_row_dict(r) for r in rows],
        "count": len(rows),
        "total": total,
        "call_sites": [{"name": n, "label": _call_label(n)} for n in _known_call_names(db)],
        "outcomes": [{"key": k, "label": v} for k, v in OUTCOME_LABELS_ZH.items()],
        "filter": {"subject_id": subject_id, "call_name": call_name, "outcome": outcome,
                   "only_failed": bool(only_failed)},
    }


def _known_call_names(db) -> list[str]:
    from sqlalchemy import select

    from .. import models

    names = [n for (n,) in db.execute(
        select(models.AiLog.call_name).group_by(models.AiLog.call_name)).all() if n]
    return sorted(names)


def get_detail(db, log_id: int) -> dict:
    """一条审计详情：**上=发给 AI 的完整内容，下=AI 返回的完整内容**（读全文文件）。

    文件不存在（被保留期清理/落盘失败）→ 如实说明 + 库里预览兜底（不静默失败）。
    """
    from .. import models

    r = db.get(models.AiLog, int(log_id))
    if r is None:
        raise ValueError(f"审计记录不存在: {log_id}")
    out = _row_dict(r)
    full = {"system": "", "user": "", "response": "", "parse_result": r.parse_result or "",
            "meta": ""}
    note = ""
    path = r.trace_path or ""
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = REPO_ROOT / path
        try:
            text = p.read_text(encoding="utf-8")
            full = _split_trace(text) | {"parse_result": r.parse_result or "", "meta": _meta_block(text)}
        except Exception as e:
            note = (f"审计全文文件读取失败（{e}）：文件可能已被保留期清理或落盘失败——"
                    "下面显示的是库内预览（不完整）。")
    else:
        note = "该次调用没有审计全文文件（落盘失败或为本功能上线前的历史记录）——仅显示库内预览。"
    out["full"] = full
    out["note"] = note
    out["file_exists"] = bool(path) and (REPO_ROOT / path if not Path(path).is_absolute() else Path(path)).exists()
    return out


def _split_trace(text: str) -> dict:
    def seg(start: str, end: str | None) -> str:
        i = text.find(start)
        if i < 0:
            return ""
        i += len(start)
        if end is None:
            return text[i:].strip("\n")
        j = text.find(end, i)
        return text[i:j if j > 0 else len(text)].strip("\n")

    return {
        "system": seg("==== 发给 AI 的完整内容 · system ====",
                      "==== 发给 AI 的完整内容 · user ===="),
        "user": seg("==== 发给 AI 的完整内容 · user ====",
                    "==== AI 返回的完整内容（原始，未解析） ===="),
        "response": seg("==== AI 返回的完整内容（原始，未解析） ====",
                        "==== 解析/校验结果 ===="),
    }


def _meta_block(text: str) -> str:
    i = text.find("==== 发给 AI 的完整内容 · system ====")
    return (text[:i] if i > 0 else text).strip()


# ---------------------------------------------------------------------------
# 保留期清理（清理也要记账——"不静默消失"）
# ---------------------------------------------------------------------------
def cleanup_old(db, *, keep_days_override: int | None = None,
                trigger: str = "手动") -> dict:
    """按保留期清理审计与账本文件：**先记账（要清理哪几条），再删除**。

    ``trigger``（**R48 B**）：本次清理的**触发者**（``启动`` / ``定时`` / ``手动``），写进账目
    ``detail.trigger``——事后能分辨"这次是谁清的"；账目文案本身不变。
    """
    import time

    days = keep_days_override if keep_days_override is not None else keep_days()
    d = trace_dir()
    if not d.exists():
        return {"removed": [], "count": 0, "keep_days": days}
    cutoff = time.time() - max(0, days) * 86400
    doomed = [p for p in sorted(d.glob("*.txt")) if p.stat().st_mtime < cutoff]
    if doomed:
        ledger.note(
            ledger.CAT_OTHER, f"AI 对话审计文件（{len(doomed)} 个）",
            f"按保留期（{days} 天）清理审计全文文件：" + "、".join(p.name for p in doomed[:20])
            + ("…" if len(doomed) > 20 else "")
            + "（账本留痕，不静默消失；过程数据本身按要求过期清理）",
            impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_NO,
            detail={"files": [p.name for p in doomed], "keep_days": days,
                    "trigger": str(trigger or "手动")},
        )
    removed = []
    for p in doomed:
        try:
            p.unlink()
            removed.append(p.name)
        except Exception:
            pass
    return {"removed": removed, "count": len(removed), "keep_days": days, "trigger": trigger}


# ---------------------------------------------------------------------------
# R46 B：保留期清理**定时化**（启动清一次 + 之后每 N 小时清一次）
# ---------------------------------------------------------------------------
# 为什么 6 小时：保留期是**天**级（默认 30 天），清理成本只是一次目录 glob；
# 6 小时（≈每天 4 次）能把"过期后最长滞留"压到 6 小时以内（相对 30 天可忽略），
# 又不至于频繁唤醒。可用 `MF_AI_TRACE_CLEAN_INTERVAL_HOURS` 覆盖；非法/<=0 → 回默认
# （**不许**用配置把清理静默关掉；真要不清理请调大保留期）。
DEFAULT_CLEAN_INTERVAL_HOURS = 6.0

logger = logging.getLogger("yanhui.ai_trace")


def clean_interval_hours() -> float:
    import os

    raw = (os.getenv("MF_AI_TRACE_CLEAN_INTERVAL_HOURS") or "").strip()
    try:
        v = float(raw) if raw else DEFAULT_CLEAN_INTERVAL_HOURS
    except Exception:
        return DEFAULT_CLEAN_INTERVAL_HOURS
    return v if v > 0 else DEFAULT_CLEAN_INTERVAL_HOURS


def cleanup_once(reason: str = "定时", *, keep_days_override: int | None = None) -> dict:
    """跑一次保留期清理：启动 / 定时 / 手动三处**共用同一实现**（不新建第二套清理）。

    ``reason``（**R48 B**）作为 ``trigger`` 落进账目 ``detail``（``启动`` / ``定时`` / ``手动``）。
    异常一律**只 warning**（不清就下次再清），**绝不抛**——审计清理不得影响主流程。
    """
    try:
        out = cleanup_old(None, keep_days_override=keep_days_override, trigger=reason)
        if out.get("count"):
            logger.info("审计保留期清理（%s）: 删除 %s 个文件（保留期 %s 天，已记入总账）",
                        reason, out["count"], out.get("keep_days"))
        return out
    except Exception as e:
        logger.warning("审计保留期清理失败（%s，不影响主流程，下次再清）: %s", reason, e)
        return {"removed": [], "count": 0, "keep_days": keep_days(),
                "trigger": reason, "error": str(e)}


class PeriodicCleanup:
    """**R46 B**：把保留期清理挂到一个**守护线程**上（每 ``interval_seconds`` 跑一次）。

    - **不阻塞主流程**：清理在后台线程里跑，异常只 warning；
    - **关闭时干净退出**：``stop()`` 置停止事件 + ``join(timeout)``，可重复调用（幂等）；
    - **进程兜底**：线程是 ``daemon``——即使调用方忘了 ``stop()``，也**不会**挂住进程退出。
    """

    def __init__(self, interval_seconds: float):
        self.interval = max(0.01, float(interval_seconds))
        self.runs = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "PeriodicCleanup":
        if self._thread is not None and self._thread.is_alive():
            return self  # 幂等：已在跑就不起第二个
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="yanhui-ai-trace-cleanup", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        # `Event.wait` 可被 stop() 立刻唤醒 → 关闭时不用等满一个周期
        while not self._stop.wait(self.interval):
            cleanup_once("定时")
            self.runs += 1

    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def stop(self, *, timeout: float = 2.0) -> bool:
        """停止并等待退出；返回**本次是否真的停了**（已在停/未启动 → False，幂等）。"""
        th = self._thread
        if th is None:
            return False
        self._stop.set()
        if th.is_alive():
            th.join(timeout=max(0.0, float(timeout)))
        stopped = not th.is_alive()
        if stopped:
            self._thread = None
        return stopped


def start_periodic_cleanup(*, interval_seconds: float | None = None) -> PeriodicCleanup:
    """启动定时清理（默认间隔＝``clean_interval_hours()``）并返回句柄（调用方负责 ``stop()``）。"""
    secs = (float(interval_seconds) if interval_seconds is not None
            else clean_interval_hours() * 3600.0)
    return PeriodicCleanup(secs).start()


__all__ = [
    "OUTCOME_ADOPTED", "OUTCOME_DEGRADED", "OUTCOME_DROPPED", "OUTCOME_FAILED",
    "OUTCOME_LABELS_ZH", "trace_dir", "keep_days", "redact", "write_trace",
    "query", "get_detail", "cleanup_old", "cleanup_once", "PeriodicCleanup",
    "start_periodic_cleanup", "clean_interval_hours", "DEFAULT_CLEAN_INTERVAL_HOURS",
]
