"""app.api.dashboard：仪表盘聚合（docs/06 §1；07 §2.1）。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..domain.graph import AVAILABLE, LOCKED, LEVELS, LEARNING, MASTERED
from ..service import progress, review as review_svc
from ..service.library import ensure_user, get_graph
from .deps import get_db

router = APIRouter(tags=["dashboard"])
USER = "local"


def _total_order_recommend(states: dict[str, str], graph, visible: list[str]) -> str | None:
    """R18：推荐 = 总序允许集（state==available）内 学段 → 图谱层序 → 编号 最小者。

    C3：仅在**启用学科**的可见节点内推荐（停用学科内容在仪表盘隐藏）。
    """
    level_index = {lv: i for i, lv in enumerate(LEVELS)}
    visible_set = set(visible)
    avail = [n for n, s in states.items() if s == AVAILABLE and n in visible_set]
    if not avail:
        return None
    return min(
        avail,
        key=lambda nid: (
            level_index.get(graph.get(nid).level, len(LEVELS)),
            graph.depth_of(nid),
            nid,
        ),
    )


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    import os

    from ..service import outline_gate as og

    ensure_user(db, USER)
    # 内容自续自动触发（docs/10 §2.3）：显式开启 MF_AUTO_EXTEND=1 时才在后台检查
    if os.getenv("MF_AUTO_EXTEND") == "1":
        from ..service import selfextend as se

        se.run_auto(db, USER)
    graph = get_graph()
    states = progress.state_map(db, USER, graph)
    visible = og.visible_node_ids(db, graph.node_ids)  # C3：停用学科节点视觉隐藏
    visible_set = set(visible)
    mastered = {n for n, s in states.items() if s in (MASTERED, "reviewing") and n in visible_set}
    learning = {n for n, s in states.items() if s == LEARNING and n in visible_set}

    due = review_svc.due_queue(db, USER)
    # C3：复习/统计同样剔除停用学科（推荐只在可见节点内取）
    due = [d for d in due if d["node_id"] in visible_set]
    recommended = _total_order_recommend(states, graph, visible)
    rec_node = graph.get(recommended) if recommended else None
    today = dt.date.today().isoformat()
    today_done = (
        db.query(func.count(models.Attempt.id))
        .join(models.Session, models.Attempt.session_id == models.Session.id)
        .filter(
            models.Session.user_id == USER,
            func.date(models.Attempt.created_at) == today,
            # R35 S3 红线：挑战题**完全不上算**（只进复盘）→ 不得计入"今日完成"这类进度统计。
            # 用 models.PROGRESS_KINDS 白名单（默认拒绝新 kind），而不是"排除 challenge"黑名单。
            models.Attempt.kind.in_(models.PROGRESS_KINDS),
        )
        .scalar()
        or 0
    )
    stat_keys = {MASTERED, LEARNING, AVAILABLE, LOCKED}
    # 计数按可见节点集收敛（全图 state_map 含停用学科锁定节点，须剔除）
    stats = {k: sum(1 for n in visible if states.get(n) == k) for k in stat_keys}
    stats["reviewing"] = sum(1 for n in visible if states.get(n) == "reviewing")
    # 断点清单（捡拾=诊断，MVP 不做全流程，docs/08 §1）→ 空
    # L1（R36 §3）：预置学科生命周期状态**由本响应直接给出**——前端不再为看一个布尔值去拉
    # 全量学科列表（`/subjects` 默认隐藏已移除者，会导致"停用"被误判为"启用"，横幅永不显示）。
    preset = (
        db.query(models.Subject)
        .filter(models.Subject.kind == "preset")
        .order_by(models.Subject.id)
        .first()
    )
    return {
        "preset_subject": (
            None
            if preset is None
            else {
                "id": preset.id,
                "label": preset.label or preset.id,
                "enabled": bool(preset.enabled),
            }
        ),
        "recommended_node": (
            {
                "id": rec_node.id,
                "title": rec_node.title,
                "level": rec_node.level,
                "topic": rec_node.topic,
                "prereqs_met": sum(1 for p in rec_node.prereqs if p in mastered),
                "prereqs_total": len(rec_node.prereqs),
            }
            if rec_node
            else None
        ),
        "due_reviews": due,
        "breakpoints": [],
        "stats": {
            "mastered": stats.get(MASTERED, 0) + stats.get("reviewing", 0),
            "learning": stats.get(LEARNING, 0),
            "available": stats.get(AVAILABLE, 0),
            "locked": stats.get(LOCKED, 0),
            "consecutive_days": progress.consecutive_days(db, USER),
            "today_done": today_done,
        },
    }
