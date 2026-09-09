"""service.progress：用户进度读取/重算（docs/03 §1 节点状态机 + docs/09 R18 总序）。

设计约定：
- user_nodes.state 持久化列只存 locked/available/learning/mastered 之一；
  reviewing 为 mastered 之上由复习到期推导的显示态（docs/03 §1/§3），读时叠加。
- 重算规则（R18）：mastered/learning 由既有记录决定；其余节点按**蓝图总序门禁**
  （service.path.PathEngine）推 available/locked——内容手写 prereq 不再单独决定可学性；
  复习（已掌握内容）不受总序限制。
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..domain.graph import AVAILABLE, LEARNING, LOCKED, MASTERED, KnowledgeGraph
from .path import PathEngine, make_engine

REVIEWING = "reviewing"


def _sets(db: Session, user_id: str) -> tuple[set[str], set[str]]:
    rows = (
        db.query(models.UserNode.node_id, models.UserNode.state)
        .filter(models.UserNode.user_id == user_id)
        .all()
    )
    mastered = {nid for nid, st in rows if st == MASTERED}
    learning = {nid for nid, st in rows if st == LEARNING}
    return mastered, learning


def _engine_and_infos(db: Session, user_id: str, graph: KnowledgeGraph, mastered: set[str]):
    """构建总序引擎 + 节点元信息（kind/level/topic/prereqs 供门禁）。"""
    from .library import get_library

    lib = get_library()
    eng = make_engine(mastered, lib=lib)
    infos: dict[str, dict] = {}
    for nid in graph.node_ids:
        doc = None
        loaded = lib.by_id.get(nid)
        if loaded is not None:
            doc = loaded.doc
        nd = graph.get(nid)
        infos[nid] = {
            "kind": getattr(doc, "kind", "") if doc is not None else "",
            "level": getattr(nd, "level", "") or (getattr(doc, "level", "") if doc else ""),
            "topic": getattr(nd, "topic", "") or (getattr(doc, "topic", "") if doc else ""),
            "prereqs": list(getattr(nd, "prereqs", ()) or ()),
        }
    return eng, infos


def _node_allowed(db: Session, user_id: str, node_id: str, infos: dict, eng) -> bool:
    """统一可学门禁：通用学科（custom 大纲权威）→ outline_gate；其余（math roadmap 总序）→ PathEngine。"""
    from . import outline_gate

    res = outline_gate.resolve_subject_unit(db, node_id)
    if res is not None:
        ok, _ = outline_gate.unit_allowed(db, user_id, res[0], res[1])
        return ok
    ok, _ = eng.node_allowed(node_id, **infos[node_id])
    return ok


def recompute_states(db: Session, user_id: str, graph: KnowledgeGraph) -> None:
    """按当前 mastered/learning 记录 + 学科门禁（math=roadmap 总序 / custom=大纲）重算全部节点状态。"""
    mastered, learning = _sets(db, user_id)
    eng, infos = _engine_and_infos(db, user_id, graph, mastered)
    for node_id in graph.node_ids:
        if node_id in mastered:
            state = MASTERED
        elif node_id in learning:
            state = LEARNING
        else:
            state = AVAILABLE if _node_allowed(db, user_id, node_id, infos, eng) else LOCKED
        row = db.get(models.UserNode, (user_id, node_id))
        if row is None:
            row = models.UserNode(user_id=user_id, node_id=node_id)
            db.add(row)
        row.state = state


def state_map(db: Session, user_id: str, graph: KnowledgeGraph, *, now: dt.datetime | None = None) -> dict[str, str]:
    """{node_id: 显示状态}：叠加 reviewing（mastered 且复习到期）。可用性按蓝图总序（R18）。"""
    # DB DateTime 列为 naive UTC；比较前归一
    now = (now or dt.datetime.now(dt.timezone.utc)).replace(tzinfo=None)
    states: dict[str, str] = {}
    mastered, learning = _sets(db, user_id)
    due_nodes = {
        r.node_id
        for r in db.query(models.Review).filter(
            models.Review.user_id == user_id,
            models.Review.due_at.is_not(None),
            models.Review.due_at <= now,
        )
    }
    eng, infos = _engine_and_infos(db, user_id, graph, mastered)
    for node_id in graph.node_ids:
        if node_id in mastered:
            states[node_id] = REVIEWING if node_id in due_nodes else MASTERED
        elif node_id in learning:
            states[node_id] = LEARNING
        else:
            states[node_id] = AVAILABLE if _node_allowed(db, user_id, node_id, infos, eng) else LOCKED
    return states


def counts(db: Session, user_id: str, graph: KnowledgeGraph, *, now: dt.datetime | None = None) -> dict[str, int]:
    sm = state_map(db, user_id, graph, now=now)
    return {k: sum(1 for v in sm.values() if v == k) for k in (LOCKED, AVAILABLE, LEARNING, MASTERED, REVIEWING)}


def activity_days(db: Session, user_id: str) -> set[str]:
    """有学习/复习活动的日期集合（YYYY-MM-DD，本地时区日期）。

    信号源：sessions.created_at（学习会话）+ reviews.created_at（复习）。
    """
    days: set[str] = set()
    for (ts,) in db.query(models.Session.created_at).filter(models.Session.user_id == user_id).all():
        if ts:
            days.add(ts.astimezone().date().isoformat())
    for (ts,) in db.query(models.Review.created_at).filter(models.Review.user_id == user_id).all():
        if ts:
            days.add(ts.astimezone().date().isoformat())
    return days


def consecutive_days(db: Session, user_id: str, *, today: dt.date | None = None) -> int:
    """连续学习天数：从今天或昨天起向过去数连续有活动的天数。"""
    today = today or dt.date.today()
    days = activity_days(db, user_id)
    if not days:
        return 0
    start = today if today.isoformat() in days else today - dt.timedelta(days=1)
    n = 0
    cursor = start
    while cursor.isoformat() in days:
        n += 1
        cursor -= dt.timedelta(days=1)
    return n


def mark_learning(db: Session, user_id: str, node_id: str, graph: KnowledgeGraph) -> None:
    """节点开始学习：available → learning（首次）。"""
    row = db.get(models.UserNode, (user_id, node_id))
    if row is None:
        row = models.UserNode(user_id=user_id, node_id=node_id)
        db.add(row)
    if row.state in (LOCKED, AVAILABLE):
        row.state = LEARNING


def mark_mastered(db: Session, user_id: str, node_id: str, graph: KnowledgeGraph) -> None:
    """learning → mastered（达标）；随后重算相邻 available 扩散。"""
    row = db.get(models.UserNode, (user_id, node_id))
    if row is None:
        row = models.UserNode(user_id=user_id, node_id=node_id)
        db.add(row)
    row.state = MASTERED
    row.consecutive_correct = 3
    row.mastered_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    recompute_states(db, user_id, graph)
    from . import outline_gate

    outline_gate.refresh_concept_evidence(db, user_id, node_id)  # 通用学科：概念证据实时更新


def demote_to_learning(db: Session, user_id: str, node_id: str, graph: KnowledgeGraph, reason: str) -> None:
    """mastered → learning（复习降级回炉，docs/03 §3）；留痕 relearn_logs。"""
    row = db.get(models.UserNode, (user_id, node_id))
    if row is not None and row.state == MASTERED:
        row.state = LEARNING
        row.consecutive_correct = 0
        row.mastered_at = None
        db.add(
            models.RelearnLog(user_id=user_id, node_id=node_id, reason=reason)
        )
        db.flush()
        recompute_states(db, user_id, graph)


__all__ = [
    "state_map",
    "counts",
    "recompute_states",
    "consecutive_days",
    "mark_learning",
    "mark_mastered",
    "demote_to_learning",
    "REVIEWING",
]
