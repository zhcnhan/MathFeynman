"""service.review：复习队列与提交（docs/03 §3、06 §1 review 端点）。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..domain import fsrs as fsrs_domain
from ..domain.fsrs import FsrsScheduler, ReviewState, RATING_GOOD, should_relearn
from .progress import demote_to_learning

STACK_DAYS = 3  # 逾期超 3 天未复习 → 堆积警示（docs/03 §3）


def _scheduler() -> FsrsScheduler:
    return FsrsScheduler()


def _naive(d: dt.datetime | None) -> dt.datetime | None:
    """DB DateTime 列存 naive UTC；比较前归一。"""
    return d.replace(tzinfo=None) if d and d.tzinfo else d


def schedule_first(db: Session, user_id: str, node_id: str, *, now: dt.datetime | None = None) -> ReviewState:
    """节点达标后的首次排程（docs/05 §5：rating 默认 good）。"""
    sched = _scheduler()
    state = sched.schedule(node_id, RATING_GOOD, current=None, now=now)
    row = db.get(models.Review, (user_id, node_id))
    if row is None:
        row = models.Review(user_id=user_id, node_id=node_id)
        db.add(row)
    row.state_json = state.to_dict()
    row.due_at = _naive(state.due_at)
    row.last_rating = state.last_rating
    row.lapse_count = state.lapse_count
    db.flush()
    return state


def due_queue(
    db: Session,
    user_id: str,
    *,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """到期复习列表（含堆积警示）。"""
    now = _naive(now or dt.datetime.now(dt.timezone.utc))
    rows = (
        db.query(models.Review)
        .filter(
            models.Review.user_id == user_id,
            models.Review.due_at.is_not(None),
            models.Review.due_at <= now,
        )
        .order_by(models.Review.due_at.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        node = db.get(models.Node, r.node_id)
        due_at = _naive(r.due_at)
        stacked = bool(due_at and due_at + dt.timedelta(days=STACK_DAYS) < now)
        out.append(
            {
                "node_id": r.node_id,
                "title": node.title if node else r.node_id,
                "level": node.level if node else "",
                "due_at": due_at.isoformat() if due_at else None,
                "stacked": stacked,
                "lapse_count": r.lapse_count,
                "interval_days": round(max(0.0, (due_at - now).total_seconds() / 86400.0), 1)
                if due_at
                else 0.0,
            }
        )
    return out


def submit_review(
    db: Session,
    user_id: str,
    node_id: str,
    rating: int,
    answers: list[dict] | None = None,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """复习提交：FSRS 更新 + 降级规则（docs/03 §3）。

    answers 仅作审计传参、**不做判题依据**：判题只发生在 /exercises/check
    （sympy 服务端裁决并留痕 attempts），此处 rating 由 FSRS 状态机裁决。
    """
    del answers  # 判题结果只来自 sympy（红线）；attempts 已在 check 端点落库
    now_aware = now or dt.datetime.now(dt.timezone.utc)
    row = db.get(models.Review, (user_id, node_id))
    if row is None:
        raise KeyError(f"该节点不在复习队列: {node_id}")

    current = ReviewState.from_dict(row.state_json or {})
    sched = _scheduler()
    new_state = sched.schedule(node_id, rating, current=current, now=now_aware)

    # 降级规则：again/hard 累计 ≥2 → mastered 降级 learning 回炉
    if should_relearn(new_state.lapse_count):
        demote_to_learning(db, user_id, node_id, _graph_of(db), reason="复习 again/hard 累计2次")
        db.query(models.Review).filter(
            models.Review.user_id == user_id, models.Review.node_id == node_id
        ).delete()
        db.flush()
        return {
            "action": "relearn",
            "node_id": node_id,
            "reason": "复习 rating again/hard 累计 2 次，节点降级回炉重学",
            "next_due_at": None,
        }

    row.state_json = new_state.to_dict()
    row.due_at = _naive(new_state.due_at)
    row.last_rating = rating
    row.lapse_count = new_state.lapse_count
    db.flush()
    return {
        "action": "scheduled",
        "node_id": node_id,
        "rating": rating,
        "next_due_at": new_state.due_at.isoformat() if new_state.due_at else None,
        "interval_days": round(
            max(0.0, (new_state.due_at - now_aware).total_seconds() / 86400.0), 1
        )
        if new_state.due_at
        else 0.0,
        "lapse_count": new_state.lapse_count,
    }


def _graph_of(db: Session):
    from ..service.library import get_graph

    return get_graph()


__all__ = ["schedule_first", "due_queue", "submit_review", "STACK_DAYS"]
