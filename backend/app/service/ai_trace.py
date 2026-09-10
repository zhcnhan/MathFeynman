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
    """遮蔽疑似密钥（红线：审计里不得出现 API Key）。"""
    return _SECRET.sub("[已隐去]", text or "")


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
_MAX_NAME_TRIES = 200


def _next_name(entry_dir: Path, stamp: str, call_name: str) -> tuple[Path, str, str]:
    """返回 ``(path, base_name, 冲突说明)``；冲突说明非空＝发生过换名（需记账）。

    - 首次（该秒该调用点第 1 次）→ ``<stamp>-<call_name>.txt``（最可读）；
    - 同秒第 n 次 → ``<stamp>-<call_name>-02.txt``、``-03``…（序号单调，不覆盖）；
    - 目标名已被占用（跨进程/预置文件）→ 序号继续自增**换名**，并在冲突说明里写明原因。
    """
    with _SEQ_LOCK:
        key = (stamp, call_name)
        seq = _SEQ_BY_KEY.get(key, 0)
        base = f"{stamp}-{call_name}"
        first = f"{base}.txt"
        if seq == 0 and not (entry_dir / first).exists():
            _SEQ_BY_KEY[key] = 1
            return entry_dir / first, base, ""
        why = ""
        if seq == 0:
            why = f"目标文件名已被占用（{first}，可能是另一进程写的或人为预置），已换名以免覆盖"
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


def _write_file(*, call_name: str, subject_id: str, unit_id: str, at: str,
                model: str, tier: str, retries: int, outcome: str,
                latency_ms: int, prompt_tokens: int, completion_tokens: int,
                system: str, user: str, raw: str, parse_result: str,
                parse_ok: bool, prompt_versions: str) -> tuple[str, int]:
    d = trace_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = at.replace(":", "").replace("-", "").replace("+0000", "Z")
    name_hint = f"{stamp}-{call_name}"
    body = (
        "==== 提示词监听 / AI 对话审计（R39 §3）====\n"
        f"时间：{at}\n调用点：{call_name}\n学科：{subject_id or '（无）'}\n单元：{unit_id or '（无）'}\n"
        f"档位：{tier}\n模型：{model}\n重试次数：{retries}\n"
        f"耗时：{latency_ms} ms\ntoken：prompt={prompt_tokens} completion={completion_tokens}\n"
        f"结局：{OUTCOME_LABELS_ZH.get(outcome, outcome)}\n提示词版本：{prompt_versions}\n"
        f"解析/校验结果：{'通过' if parse_ok else '未通过'}｜{parse_result}\n"
        f"system 字符数：{len(system)}\nuser 字符数：{len(user)}\n原始返回字符数：{len(raw)}\n"
        "\n==== 发给 AI 的完整内容 · system ====\n" + redact(system) + "\n"
        "\n==== 发给 AI 的完整内容 · user ====\n" + redact(user) + "\n"
        "\n==== AI 返回的完整内容（原始，未解析） ====\n" + redact(raw) + "\n"
        "\n==== 解析/校验结果 ====\n" + redact(parse_result) + "\n"
    )
    # ① 取候选名（同秒序号）+ ② 冲突换名；③ 再以 `x` 原子独占创建，彻底杜绝覆盖
    path, base_name, collision = _next_name(d, stamp, call_name)
    for _ in range(_MAX_NAME_TRIES):
        try:
            with open(path, "x", encoding="utf-8", newline="") as fh:
                fh.write(body)
            if path.name != f"{base_name}.txt":
                # 换了名（同秒多次 / 目标被占用）→ **必须显式记账**（不许静默）
                ledger.note(
                    ledger.CAT_OTHER, f"AI 对话审计文件（{call_name}）",
                    (collision + "；" if collision else
                     "同一秒内对同一调用点多次记录：") +
                    f"已改名为 `{path.name}`（原拟 `{base_name}.txt`），"
                    "以确保每次调用的完整 prompt/response **各自独立留存、不被覆盖**",
                    impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
                    subject_id=subject_id, unit_id=unit_id,
                    detail={"kind": "trace_name_renamed", "base_name": f"{base_name}.txt",
                            "final_name": path.name, "collision": collision or ""},
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
def cleanup_old(db, *, keep_days_override: int | None = None) -> dict:
    """按保留期清理审计与账本文件：**先记账（要清理哪几条），再删除**。"""
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
            detail={"files": [p.name for p in doomed], "keep_days": days},
        )
    removed = []
    for p in doomed:
        try:
            p.unlink()
            removed.append(p.name)
        except Exception:
            pass
    return {"removed": removed, "count": len(removed), "keep_days": days}


__all__ = [
    "OUTCOME_ADOPTED", "OUTCOME_DEGRADED", "OUTCOME_DROPPED", "OUTCOME_FAILED",
    "OUTCOME_LABELS_ZH", "trace_dir", "keep_days", "redact", "write_trace",
    "query", "get_detail", "cleanup_old",
]
