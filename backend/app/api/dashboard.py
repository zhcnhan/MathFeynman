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


def _total_order_recommend(states: dict[str, str], graph) -> str | None:
    """R18：推荐 = 总序允许集（state==available）内 学段 → 图谱层序 → 编号 最小者。"""
    level_index = {lv: i for i, lv in enumerate(LEVELS)}
    avail = [n for n, s in states.items() if s == AVAILABLE]
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

    ensure_user(db, USER)
    # 内容自续自动触发（docs/10 §2.3）：显式开启 MF_AUTO_EXTEND=1 时才在后台检查
    if os.getenv("MF_AUTO_EXTEND") == "1":
        from ..service import selfextend as se

        se.run_auto(db, USER)
    graph = get_graph()
    states = progress.state_map(db, USER, graph)
    mastered = {n for n, s in states.items() if s in (MASTERED, "reviewing")}
    learning = {n for n, s in states.items() if s == LEARNING}

    cnt = progress.counts(db, USER, graph)
    due = review_svc.due_queue(db, USER)
    recommended = _total_order_recommend(states, graph)  # R18：总序允许集内推荐
    rec_node = graph.get(recommended) if recommended else None
    today = dt.date.today().isoformat()
    today_done = (
        db.query(func.count(models.Attempt.id))
        .join(models.Session, models.Attempt.session_id == models.Session.id)
        .filter(models.Session.user_id == USER, func.date(models.Attempt.created_at) == today)
        .scalar()
        or 0
    )
    # 断点清单（捡拾=诊断，MVP 不做全流程，docs/08 §1）→ 空
    return {
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
            "mastered": cnt.get(MASTERED, 0) + cnt.get("reviewing", 0),
            "learning": cnt.get(LEARNING, 0),
            "available": cnt.get(AVAILABLE, 0),
            "locked": cnt.get(LOCKED, 0),
            "consecutive_days": progress.consecutive_days(db, USER),
            "today_done": today_done,
        },
    }
