"""service.selfextend：内容自续触发（docs/10 §2.3、docs/11 子步 8）。

- 触发：当前阶段蓝图目标掌握 ≥90%（自动）或用户"继续下一关"（POST /selfextend/run，手动）。
- 非阻塞：后台线程执行生成（写盘 + DB 同步 + 进程内库刷新），不占学习请求；module 级运行态。
- 每日 token 限额：LLM_MAX_TOKENS_PER_DAY（0=不限）——AI 出稿时按 ai_logs 当日已用 + 每条估算
  切批；离线 stub（无 key）不耗真实 token，不受限。
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..content import pipeline as pl
from ..content.loader import load_library
from ..content.roadmap import Roadmap, all_levels_exist, load_roadmap
from ..domain.graph import LEVELS
from . import progress as progress_svc
from .library import get_graph, refresh_library, sync_content

AUTO_RATIO = 0.90
EST_TOKENS_PER_ITEM = 6000
MASTER_SET = {"mastered", "reviewing"}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "last_status": "idle",  # idle|running|done|error|budget
    "last_summary": "",
    "last_at": None,
}


def status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


# --------------------------------------------------------------------------
# 蓝图目标口径
# --------------------------------------------------------------------------
def _anchor_map(roadmap: Roadmap) -> dict[str, str]:
    return {e.id: e.anchors[0] for e in roadmap.entries if e.anchors}


def _effective_ids(roadmap: Roadmap) -> dict[str, str]:
    """蓝图条目 → 内容落地 id（anchors → 真实节点 id；否则条目自身将生成 id）。"""
    am = _anchor_map(roadmap)
    return {e.id: am.get(e.id, e.id) for e in roadmap.entries}


def _lib_ids() -> set[str]:
    return set(load_library().by_id)


def roadmap_levels() -> list[str]:
    return [lv for lv in LEVELS if lv in all_levels_exist()]


def next_pending_topics(level: str) -> list[str]:
    """按蓝图顺序，尚无落地内容的主题组（内容缺失=待自续）。"""
    roadmap = load_roadmap(level)
    eff = _effective_ids(roadmap)
    lib = _lib_ids()
    pending: list[str] = []
    for e in roadmap.entries:
        if eff[e.id] not in lib and e.topic not in pending:
            pending.append(e.topic)
    return pending


def mastered_ratio(db: Session, user_id: str, level: str) -> float:
    """已落地蓝图目标节点中 mastered 占比。"""
    roadmap = load_roadmap(level)
    eff = _effective_ids(roadmap)
    lib = _lib_ids()
    landed = {v for v in eff.values() if v in lib}
    if not landed:
        return 0.0
    states = progress_svc.state_map(db, user_id, get_graph())
    hits = sum(1 for v in landed if states.get(v, "locked") in MASTER_SET)
    return hits / len(landed)


def _today_used_tokens() -> int:
    from ..db import SessionLocal

    today = dt.date.today().isoformat()
    with SessionLocal() as db:
        total = (
            db.query(func.coalesce(func.sum(models.AiLog.prompt_tokens + models.AiLog.completion_tokens), 0))
            .filter(func.date(models.AiLog.created_at) == today)
            .scalar()
        )
        return int(total or 0)


# --------------------------------------------------------------------------
# 同步生成核心（wait=1 / 后台线程共用）
# --------------------------------------------------------------------------
def extend(
    db: Session,
    user_id: str,
    level: str | None = None,
    *,
    wait: bool = True,
) -> dict[str, Any]:
    """生成下一主题组。wait=False → 后台线程执行并立即返回 started。"""
    settings = get_settings()
    use_ai = bool(settings.llm_api_key)
    if use_ai:
        from ..ai.drafting import DraftingError, make_ai_drafter  # R13：在线 AI 出稿接入

        drafter = make_ai_drafter(settings)
        if drafter is None:
            raise DraftingError("AI 出稿器不可用（已配置 key 但工厂构建失败）")
    else:
        drafter = pl.stub_drafter  # 无 key：离线确定性桩（机制/演示，入库策略仍生效）
    if wait:
        result = _extend_sync(db, level, drafter=drafter, use_ai=use_ai, settings=settings)
        _set(
            running=False,
            last_status=result.get("status", "done"),
            last_summary=str(result.get("summary", "")),
            last_at=dt.datetime.now().isoformat(),
        )
        return result
    if status()["running"]:
        return {"started": False, "reason": "已有生成任务运行中"}
    _set(running=True, last_status="running", last_summary="", last_at=None)

    def _worker():
        from ..db import SessionLocal

        try:
            with SessionLocal() as wdb:
                result = _extend_sync(wdb, level, drafter=drafter, use_ai=use_ai, settings=settings)
                wdb.commit()
                _set(
                    running=False,
                    last_status=result.get("status", "done"),
                    last_summary=str(result.get("summary", "")),
                    last_at=dt.datetime.now().isoformat(),
                )
        except Exception as e:  # 后台失败不炸主流程
            _set(running=False, last_status="error", last_summary=str(e), last_at=dt.datetime.now().isoformat())

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True}


def _first_pending_level() -> tuple[str, list[str]] | None:
    """按学段顺序第一个有待生成主题的学段。"""
    for lv in roadmap_levels():
        pending = next_pending_topics(lv)
        if pending:
            return lv, pending
    return None


def _full_complete(db: Session, user_id: str, level: str) -> bool:
    """该学段蓝图全部内容落地且全部 mastered。"""
    if next_pending_topics(level):
        return False
    return mastered_ratio(db, user_id, level) >= 1.0


def _extend_sync(db: Session, level: str | None, *, drafter, use_ai: bool, settings) -> dict[str, Any]:
    levels = roadmap_levels()
    if not levels:
        return {"status": "idle", "summary": "尚无课程蓝图"}

    # 目标学段：显式指定且有待生成 → 用之；否则按学段顺序找下一个待生成的学段
    effective = None
    if level is not None and next_pending_topics(level):
        effective = level
    if effective is None:
        found = _first_pending_level()
        if found is None:
            return {"status": "done", "summary": "全部蓝图内容已齐（等待人工精核扩充蓝图）"}
        effective = found[0]
    pending = next_pending_topics(effective)
    if not pending:
        return {"status": "done", "summary": f"{effective} 蓝图内容已齐（可扩充下一学段蓝图）"}

    max_items: int | None = None
    if use_ai and settings.llm_max_tokens_per_day:
        used = _today_used_tokens()
        remaining = max(0, settings.llm_max_tokens_per_day - used)
        max_items = max(0, remaining // EST_TOKENS_PER_ITEM)
        if max_items == 0:
            return {"status": "budget", "summary": f"当日 token 预算已用尽（used={used}）"}

    topic = pending[0]
    # docs/12 P4：高+ 自动入库的纠错召回熔断——该主题问题率超阈值 → 本轮转 _drafts 待检
    from . import guardrails as gr

    stats = gr.topic_problem_stats(db, effective, topic)
    meltdown = stats["tripped"]
    results = pl.generate_topic(
        effective, topic, drafter=drafter, limit=max_items,
        force_drafts=True if meltdown else None,
    )
    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status == "failed"]
    if not ok:
        errs = [e for r in failed for e in r.errors]
        return {"status": "error" if failed else "done", "summary": f"{effective}:{topic} 无成功生成", "errors": errs[:5]}

    # 写盘完成 → 刷新进程内库 + 同步 DB（节点+边+状态重算）→ UI 关卡地图可见
    refresh_library()
    sync_content(db)
    db.flush()
    covered = len([r for r in results if r.status == "covered"])
    fail_note = ""
    if failed:
        sample = "; ".join(f"{r.entry_id}: {('; '.join(r.errors))[:100]}" for r in failed[:2])
        fail_note = f"；失败 {len(failed)}（例：{sample}）"  # R13/A2：失败原因透传 UI/状态
    melt_note = ""
    if meltdown:
        melt_note = (
            f"；⚠️ 纠错召回熔断：该主题问题率 {stats['problems']}/{stats['landed']} "
            f"> 阈值 {gr.TRIP_RATIO:.0%} → 本轮内容转 _drafts 待检（pending 清零后自动恢复）"
        )
    gap_note = ""
    cross_gaps = pl.cross_level_gaps(effective)  # R14 后续#1：跨学段前置未落地 → 提示（不阻塞）
    if cross_gaps:
        gap_note = "；跨学段前置缺口提示（不阻塞，学段顺序兜底）：" + "；".join(cross_gaps[:3])
    return {
        "status": "done",
        "summary": f"已生成 {effective}:{topic}：auto {len(ok)} 条 + 锚点覆盖 {covered} 条" + fail_note + melt_note + gap_note,
        "generated": [r.entry_id for r in ok],
        "failed": [r.entry_id for r in failed],
        "errors": [r.errors for r in failed],  # 失败明细（状态/日志可审计）
        "level": effective,
        "topic": topic,
        "guardrail": {"meltdown_topic": topic, "tripped": meltdown, "problems": stats["problems"], "landed": stats["landed"]},
    }


def auto_check(db: Session, user_id: str) -> dict[str, Any]:
    """自动触发：本学段掌握 ≥90% 触发下一主题；前一学段全通关 → 放行下一学段首批（跨学段自续）。"""
    if status()["running"]:
        return {"auto": False, "reason": "running"}
    levels = roadmap_levels()
    prev_full = False  # 只有"有更早学段且其已全通关"才放行下阶段自动首批
    for i, lv in enumerate(levels):
        pending = next_pending_topics(lv)
        ratio = mastered_ratio(db, user_id, lv)
        if pending and (ratio >= AUTO_RATIO or (i > 0 and prev_full)):
            return {"auto": True, "level": lv, "topic": pending[0]}
        # 本学段是否全通关（无待生成且全部已掌握）→ 决定是否放行下一学段
        prev_full = not pending and ratio >= 1.0
    return {"auto": False, "reason": "no-close-to-done"}


def run_auto(db: Session, user_id: str) -> dict[str, Any]:
    """命中自动条件 → 后台执行。"""
    check = auto_check(db, user_id)
    if not check["auto"]:
        return {"started": False, "reason": check.get("reason", "not-auto")}
    return extend(db, user_id, level=check["level"], wait=False)


__all__ = [
    "status",
    "extend",
    "auto_check",
    "run_auto",
    "next_pending_topics",
    "roadmap_levels",
    "mastered_ratio",
]
