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
    """统一可学门禁：停用学科 → False；通用学科（custom 大纲权威）→ outline_gate；
    其余（math roadmap 总序）→ PathEngine。"""
    from . import outline_gate

    subj_id = outline_gate.subject_of_node(db, node_id)
    if subj_id is not None and outline_gate.is_subject_disabled(db, subj_id):
        return False  # B4：学科停用 → 其内容一律不可学（locked）
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
    """mastered → learning（复习降级回炉，docs/03 §3）；留痕 relearn_logs。

    **R44 B（R41 §3-③ 漏做项）**：回炉还要在 **R39 总账**留一条**引用条目**——
    只做索引（`detail.ref="relearn_logs"` + `relearn_id`），**不复制** `relearn_logs` 的明细
    （保持单一权威源）；同一次回炉**幂等**（只记一条）。
    """
    row = db.get(models.UserNode, (user_id, node_id))
    if row is not None and row.state == MASTERED:
        row.state = LEARNING
        row.consecutive_correct = 0
        row.mastered_at = None
        log = models.RelearnLog(user_id=user_id, node_id=node_id, reason=reason)
        db.add(log)
        db.flush()
        # R44 B：总账引用条目（幂等；失败不阻塞回炉本身）
        note_relearn_in_ledger(db, user_id=user_id, node_id=node_id, reason=reason,
                               relearn_id=int(getattr(log, "id", 0) or 0))
        recompute_states(db, user_id, graph)


def note_relearn_in_ledger(db: Session, *, user_id: str, node_id: str, reason: str,
                           relearn_id: int = 0, extra_key: str = "") -> bool:
    """**R44 B**：在总账里给"回炉"记一条**引用条目**（中文原因 + 指向 `relearn_logs`）。

    幂等判据＝ ``detail.ref == "relearn_logs"`` 且 ``detail.relearn_id`` / ``extra_key`` 相同
    （同一次回炉被多条路径调用时**只留一条**）。返回是否新记了一条。

    - 类别：``CAT_OTHER``（总账页可筛"其它"）；
    - **只做索引**：不把 `relearn_logs` 的明细内容抄进来（单一权威源不变）；
    - **落库走调用方事务**（`ledger.write_via(db, …)`，R44 实测修正）：回炉发生在
      `demote_to_learning` 已 flush 的写事务里，用独立连接的 `ledger.write` 会与自身事务
      争 SQLite 写锁（`database is locked`）→ 账目丢失；改走同一事务后与回炉**同生共死**。
      若有活跃收集器（会话路径），同时补一条**就地提示**条目（不重复落库）。
    """
    from . import ledger

    ref_key = str(relearn_id or extra_key or f"{node_id}:{reason}")
    try:
        existing = (
            db.query(models.ContentLedger)
            .filter(models.ContentLedger.category == ledger.CAT_OTHER,
                    models.ContentLedger.unit_id == node_id)
            .all()
        )
        for row in existing:
            detail = dict(row.detail_json or {})
            if detail.get("ref") != "relearn_logs":
                continue
            if str(detail.get("relearn_id") or detail.get("ref_key") or "") == ref_key:
                return False  # 同一次回炉已记账 → 幂等跳过
    except Exception:  # 查重失败也不能阻塞回炉（宁可多一条也不静默）
        pass
    reason_zh = (f"节点回炉重学：{reason or '复习/练习未通过'}——"
                 "明细见**复习记录**（`relearn_logs`，本条目只做索引，不重复存内容）")
    entry = ledger.Entry(
        category=ledger.CAT_OTHER, object=f"节点 {node_id} · 回炉", reason=reason_zh,
        impact=ledger.SCOPE_UNIT, remedy=ledger.REMEDY_YES, unit_id=node_id,
        detail={"ref": "relearn_logs", "relearn_id": int(relearn_id or 0),
                "ref_key": ref_key, "user_id": user_id, "kind": "relearn_index"},
        created_at=ledger._now_iso(),
    )
    acc = ledger.current()
    if acc is not None:  # 有活跃收集器 → 同步补进"就地提示"（persist=False，避免二次落库）
        try:
            acc.record(ledger.CAT_OTHER, entry.object, entry.reason, impact=entry.impact,
                       remedy=entry.remedy, unit_id=node_id, detail=entry.detail, persist=False)
        except Exception:
            pass
    return ledger.write_via(db, entry) is not None


__all__ = [
    "state_map",
    "counts",
    "recompute_states",
    "consecutive_days",
    "mark_learning",
    "mark_mastered",
    "demote_to_learning",
    "note_relearn_in_ledger",
    "REVIEWING",
]
