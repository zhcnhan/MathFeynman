"""service.outline_gate：通用学科的大纲门禁（docs/14 §2.2/§6 · Phase A A4）。

数学 = subject=math 的学习顺序由 roadmap 权威总序引擎（service/path，R18）驱动；
**通用学科（custom）**的内容节点学习顺序由各自 **Outline 大纲**权威驱动（概念层映射）：

- 节点 → 所属 (subject, unit)：内容节点 id == 大纲单元 id（通用学科内容按单元生成，
  单元 id 强制 `<subject>.` 前缀）；math 内容节点（level ∈ LEVELS）不经过本门禁；
- 单元满足（satisfied）= 覆盖内容节点 mastered 或 **概念等效已掌握**
  （concept_tags ⊆ (subject) 已掌握概念，A2）；学习中另有 learning 行；
- 单元开放（open）= 未满足 且 全部大纲前置单元已满足（等效即达成——"跳过/快速过"
  不卡后链）；
- 节点可学（allowed）= 其单元 satisfied（复习/快速过）或 open；否则 locked/409。

纯 DB+大纲文件计算：无 LLM/UI 依赖；大纲读取每次实时（文件小、无缓存一致性负担）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..domain.graph import LEVELS
from ..outline import concepts as concept_svc
from ..outline import store as outline_store
from ..outline.schemas import OutlineDoc, OutlineError

# 课程内容节点的 subject 前缀 = 学段名的（math）不路由本门禁
_MATH_PREFIXES = set(LEVELS)


def _subject_ids(db: Session) -> set[str]:
    return {r.id for r in db.query(models.Subject.id).all()}


def resolve_subject_unit(db: Session, node_id: str) -> tuple[str, str] | None:
    """内容节点 → (subject_id, unit_id)。math / 未知节点 → None（走 roadmap/内容前置兜底）。"""
    head, sep, _ = node_id.partition(".")
    if not sep or not head or head in _MATH_PREFIXES:
        return None
    subjects = _subject_ids(db)
    if head not in subjects:
        return None
    outline = outline_store.get_outline(head)
    if outline is None or node_id not in outline.by_id():
        return None
    return head, node_id


def _outline_of(subject_id: str) -> OutlineDoc | None:
    try:
        return outline_store.get_outline(subject_id)
    except OutlineError:
        return None


def _node_states(db: Session, user_id: str, node_ids: set[str]) -> dict[str, str]:
    rows = (
        db.query(models.UserNode.node_id, models.UserNode.state)
        .filter(models.UserNode.user_id == user_id, models.UserNode.node_id.in_(node_ids))
    )
    return {nid: st for nid, st in rows}


def _satisfaction(
    db: Session,
    user_id: str,
    subject_id: str,
    outline: OutlineDoc,
    node_states: dict[str, str],
) -> tuple[dict[str, str], set[str]]:
    """{unit_id: satisfied|learning|todo} + 已掌握概念集。

    satisfied：单元覆盖节点 mastered；否则 concept_tags（非空）⊆ 已掌握概念 → equivalent 达成。
    """
    mastered_concepts = concept_svc.mastered_concepts(db, user_id, subject_id)
    sat: dict[str, str] = {}
    for u in outline.units:
        ns = node_states.get(u.id)
        if ns == "mastered":
            sat[u.id] = "satisfied"
        elif ns == "learning":
            sat[u.id] = "learning"
        else:
            tags = {concept_svc.normalize_tag(t) for t in u.concept_tags if concept_svc.normalize_tag(t)}
            if tags and tags <= mastered_concepts:
                sat[u.id] = "satisfied"  # 概念等效已掌握
            else:
                sat[u.id] = "todo"
    return sat, mastered_concepts


def unit_allowed(
    db: Session,
    user_id: str,
    subject_id: str,
    unit_id: str,
    outline: OutlineDoc | None = None,
) -> tuple[bool, list[str]]:
    """大纲单元是否可学：(已满足 或 前置全满足)。返回 (ok, 未满足前置标题列表)。"""
    outline = outline or _outline_of(subject_id)
    if outline is None:
        return False, [f"学科 {subject_id} 尚无大纲"]
    byid = outline.by_id()
    unit = byid.get(unit_id)
    if unit is None:
        return False, [f"单元不在大纲中: {unit_id}"]
    node_states = _node_states(db, user_id, {u.id for u in outline.units})
    sat, _ = _satisfaction(db, user_id, subject_id, outline, node_states)
    if sat.get(unit_id) == "satisfied":
        return True, []
    if sat.get(unit_id) == "learning":
        return True, []
    missing: list[str] = []
    for p in unit.prereqs:
        if p in byid:
            if sat.get(p) != "satisfied":
                missing.append(byid[p].title)
    if missing:
        return False, [f"请先完成：{'、'.join(missing[:5])}"]
    return True, []


def node_allowed(db: Session, user_id: str, node_id: str) -> tuple[bool, list[str]]:
    """内容节点门禁（通用学科）。math/未注册 → (False,[]) 由调用方走 roadmap 引擎。"""
    res = resolve_subject_unit(db, node_id)
    if res is None:
        return False, []
    subject_id, unit_id = res
    outline = _outline_of(subject_id)
    ok, missing = unit_allowed(db, user_id, subject_id, unit_id, outline)
    if ok:
        return True, []
    if not missing:
        missing = [f"当前节点尚未解锁（须按学科大纲顺序先学前置：{unit_id}）"]
    return False, missing


def refresh_concept_evidence(db: Session, user_id: str, node_id: str) -> dict | None:
    """节点掌握状态变化后同步刷新其学科概念证据（使大纲等效判定实时成立）。

    仅对通用学科（custom，大纲解析可命中）生效；math 走 roadmap 门禁，等效判定不依赖
    实时概念证据（数学迁移/查看经显式 recompute）。返回 recompute 报告或 None。
    """
    res = resolve_subject_unit(db, node_id)
    if res is None:
        return None
    from ..outline.concepts import recompute_subject_concepts

    return recompute_subject_concepts(db, user_id, res[0])


def subject_node_allowed(db: Session, user_id: str, node_id: str) -> bool:
    """快速判定节点归属通用学科大纲（供调用方分流）。"""
    return resolve_subject_unit(db, node_id) is not None


__all__ = [
    "resolve_subject_unit",
    "unit_allowed",
    "node_allowed",
    "subject_node_allowed",
    "refresh_concept_evidence",
]
