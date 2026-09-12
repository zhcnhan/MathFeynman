"""app.outline.concepts：概念层与进度映射（docs/14 §2.2 · Phase A A2）。

机制（"换大纲不丢进度"的核心）：
1. **概念注册表**（concepts 表）：大纲单元的 concept_tags → 归一化 concept_id（去空白/ASCII 小写/
   全半角统一）；同义合并 MVP = 精确归一匹配（docs/14 §7 #3 更细策略列为治理项）。
2. **掌握证据挂 (subject, concept)**（user_concepts 表）：由"已掌握内容节点 → 归属单元 →
   单元概念标签集"幂等派生（recompute_subject_concepts），非人工录入；证据带来源节点列表。
   内容节点标签 = 其归属单元（unit.id==node.id 或 unit.anchors 含 node.id）的 concept_tags；
   无归属单元的节点（孤儿/首领）以节点自身 core_concepts 兜底（数学既有 13 锚点节点均带
   core_concepts，保证历史掌握可确定性归一）。
3. **大纲重生成 → 新单元等效已掌握**：unit 概念标签集非空且 ⊆ 已掌握概念集 → equivalent
   （地图标绿/可跳过/快速过；未命中照学）。单元级达成 = 覆盖内容节点 mastered；
   equivalent 是"概念级等效达成"（无内容节点也行）。
4. **显式重置学科进度**（reset_subject_progress）：清概念证据 + 该学科内容节点 mastered/learning
   降回 available（含复习队列行），随后全图重算（总序门禁照常，其它学科不受影响）。
5. **数学历史掌握迁移**：recompute 即迁移入口——现库 user_nodes.mastered（锚点/auto 内容节点）
   → 节点 core_concepts 或归属单元标签 → user_concepts(subject=math)；后续 math 大纲重生成时
   新单元标签命中已掌握概念即等效（进度不丢）。

纯 DB+大纲计算模块：不依赖 LLM/UI；内容库节点元信息由调用方注入（lib_docs: id → NodeDoc-like），
测试可注入假文档。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..domain.graph import AVAILABLE, LEARNING, MASTERED
from . import store as outline_store
from .schemas import OutlineDoc, OutlineUnit
from .store import PRESET_MATH

_WS = re.compile(r"\s+")


def normalize_tag(tag: str) -> str:
    """概念标签 → 规范 concept_id（去空白 + ASCII 小写 + 全角→半角统一）。"""
    t = _WS.sub("", str(tag)).strip()
    out = []
    for ch in t:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
            continue
        if 0xFF01 <= code <= 0xFF5E:  # 全角 → 半角
            out.append(chr(code - 0xFEE0))
            continue
        out.append(ch)
    return "".join(out).lower()


def unit_tags(outline: OutlineDoc, unit_id: str) -> set[str]:
    u = outline.by_id().get(unit_id)
    if u is None:
        return set()
    return {normalize_tag(t) for t in u.concept_tags if normalize_tag(t)}


def outline_tags(outline: OutlineDoc) -> dict[str, set[str]]:
    """{unit_id: 归一化概念集}（空标签单元 → 空集）。"""
    return {u.id: {normalize_tag(t) for t in u.concept_tags if normalize_tag(t)} for u in outline.units}


def content_to_unit(outline: OutlineDoc, lib_ids: set[str]) -> dict[str, str]:
    """内容节点 id → 归属单元 id（unit.id 在库 或 unit.anchors 在库）。

    一个内容节点同时被多个单元锚定时取列表序首个（roadmap 惯例 anchors[0] 为主覆盖）。
    """
    mapping: dict[str, str] = {}
    for u in outline.units:
        if u.id in lib_ids and u.id not in mapping:
            mapping[u.id] = u.id
        for a in u.anchors:
            if a in lib_ids and a not in mapping:
                mapping[a] = u.id
    return mapping


def node_concept_tags(outline: OutlineDoc, node_id: str, lib_docs: dict[str, Any]) -> set[str]:
    """内容节点的概念标签：归属单元 concept_tags（非空时优先）→ 节点自身 core_concepts 兜底。

    兜底保证：单元标签尚未精修（A2 渐进治理）的 auto/孤儿节点，其历史掌握也能以既有
    core_concepts 归一为概念证据（数学迁移不依赖逐单元人工补标）。
    """
    unit_id: str | None = None
    if node_id in outline.by_id():
        unit_id = node_id
    else:
        for u in outline.units:
            if node_id in u.anchors:
                unit_id = u.id
                break
    tags = unit_tags(outline, unit_id) if unit_id is not None else set()
    if tags:
        return tags
    doc = lib_docs.get(node_id)
    concepts = (doc.core_concepts or []) if doc is not None else []
    return {normalize_tag(c) for c in concepts if normalize_tag(c)}


def sync_concept_registry(db: Session, subject_id: str, tags: list[str]) -> int:
    """把大纲出现的标签注册进 concepts 表（幂等 upsert；label 保留首个书写）。"""
    added = 0
    seen: set[str] = set()
    for raw in tags:
        tag = str(raw).strip()
        cid = normalize_tag(tag)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        row = db.get(models.Concept, (subject_id, cid))
        if row is None:
            db.add(models.Concept(subject_id=subject_id, concept_id=cid, label=tag))
            added += 1
        elif not row.label:
            row.label = tag
    db.flush()
    return added


def sync_outline_registry(db: Session, subject_id: str, outline: OutlineDoc) -> int:
    """大纲全单元标签注册（add/derive outline 后调用；返回新注册概念数）。"""
    tags = [t for u in outline.units for t in u.concept_tags]
    return sync_concept_registry(db, subject_id, tags)


def _mastered_node_ids(db: Session, user_id: str, candidates: set[str]) -> set[str]:
    if not candidates:
        return set()
    rows = (
        db.query(models.UserNode.node_id)
        .filter(
            models.UserNode.user_id == user_id,
            models.UserNode.node_id.in_(candidates),
            models.UserNode.state == MASTERED,
        )
        .all()
    )
    return {r[0] for r in rows}


def _subject_universe(
    db: Session,
    subject_id: str,
    outline: OutlineDoc,
    lib_docs: dict[str, Any],
) -> set[str]:
    """该学科的内容节点全集（进度/概念证据只对该集生效，杜绝跨学科污染）。

    - preset(math)：内容库中 level ∈ LEVELS 的全部节点（学段语义=数学关卡组；含首领 0199、
      孤儿锚点 high.0201 与 auto 节点——它们不属于任何大纲单元，但属数学内容）；
    - custom：大纲单元内容节点（unit.id 在库 / anchors 在库）——通用学科内容全部由大纲派生。
    """
    lib_ids = set(lib_docs)
    mapped = set(content_to_unit(outline, lib_ids))
    if subject_id == PRESET_MATH:
        from ..domain.graph import LEVELS

        level_ids = {
            nid for nid, doc in lib_docs.items() if (getattr(doc, "level", "") or "") in LEVELS
        }
        return mapped | level_ids
    return mapped


def recompute_subject_concepts(
    db: Session,
    user_id: str,
    subject_id: str,
    *,
    lib_ids: set[str] | None = None,
    lib_docs: dict[str, Any] | None = None,
    outline: OutlineDoc | None = None,
    universe: set[str] | None = None,
    now: datetime | None = None,
) -> dict:
    """幂等重算用户 (subject) 概念掌握证据（= 数学历史掌握迁移入口）。

    规则：该学科内容节点 mastered → 其概念标签（归属单元 concept_tags 非空优先，否则节点
    core_concepts 兜底）→ user_concepts 全量替换（旧证据行删除后按新证据重建）。
    outline/lib/universe 可注入（测试用）；缺省读 outline 文件 + 内容库。
    返回 {concepts: n, evidence_nodes: n, units_covered: n, note}
    """
    outline = outline or outline_store.get_outline(subject_id)
    now = now or datetime.now(timezone.utc)
    if outline is None:
        return {
            "concepts": 0,
            "evidence_nodes": 0,
            "units_covered": 0,
            "note": f"学科 {subject_id} 尚无大纲，概念证据未派生（数学历史迁移待 math 大纲建立后执行）",
        }
    if lib_docs is None:
        # R63：请求路径上走进程内缓存（get_library），不要每次重扫重解析全库；
        # 缓存由 refresh_library()/sync_content() 刷新（内容生成、导入、测试清场都会走）。
        from ..service.library import get_library

        lib = get_library()
        lib_docs = {n.id: n.doc for n in lib.nodes}
    elif lib_ids is None:
        lib_ids = set(lib_docs)
    universe = universe if universe is not None else _subject_universe(db, subject_id, outline, lib_docs)
    c2u = content_to_unit(outline, universe)
    unit_tags_map = outline_tags(outline)
    # 候选 = 学科节点集中"有概念可挂"者（归属单元标签非空，或无归属单元时节点自带 core_concepts）
    candidates = {
        nid
        for nid in universe
        if nid in lib_docs and _has_concepts(nid, lib_docs, outline, unit_tags_map, c2u)
    }
    mastered = _mastered_node_ids(db, user_id, candidates)
    # 概念 → 证据节点
    concept_evidence: dict[str, set[str]] = {}
    for node_id in mastered:
        tags = node_concept_tags(outline, node_id, lib_docs)
        for cid in tags:
            concept_evidence.setdefault(cid, set()).add(node_id)
    # 全量替换（派生证据以当前 mastered 集为准）
    db.query(models.UserConcept).filter(
        models.UserConcept.user_id == user_id,
        models.UserConcept.subject_id == subject_id,
    ).delete()
    for cid, nodes in concept_evidence.items():
        db.add(
            models.UserConcept(
                user_id=user_id,
                subject_id=subject_id,
                concept_id=cid,
                evidence_json=sorted(nodes),
                mastered_at=now,
            )
        )
    db.flush()
    covered_units = {
        u_id for nid in mastered for u_id in [c2u.get(nid)] if u_id
    }
    return {
        "concepts": len(concept_evidence),
        "evidence_nodes": len(mastered),
        "units_covered": len(covered_units),
        "note": "",
    }


def _has_concepts(node_id: str, lib_docs: dict[str, Any], outline: OutlineDoc,
                  unit_tags_map: dict[str, set[str]], c2u: dict[str, str]) -> bool:
    unit_id = c2u.get(node_id)
    if unit_id is not None:
        return bool(unit_tags_map.get(unit_id)) or bool(_node_core(node_id, lib_docs))
    return bool(_node_core(node_id, lib_docs))


def _node_core(node_id: str, lib_docs: dict[str, Any]) -> list[str]:
    doc = lib_docs.get(node_id)
    return list((doc.core_concepts or []) if doc is not None else [])


def mastered_concepts(db: Session, user_id: str, subject_id: str) -> set[str]:
    rows = (
        db.query(models.UserConcept.concept_id)
        .filter(
            models.UserConcept.user_id == user_id,
            models.UserConcept.subject_id == subject_id,
        )
        .all()
    )
    return {r[0] for r in rows}


def unit_states(
    db: Session,
    user_id: str,
    subject_id: str,
    *,
    lib_ids: set[str] | None = None,
    lib_docs: dict[str, Any] | None = None,
    outline: OutlineDoc | None = None,
    now: datetime | None = None,
) -> dict:
    """学科单元进度视图（地图/审阅用）：node/等效达成、是否开放（前置全达成）。

    返回 {subject, outline_revision, concepts_mastered, units: [...],
          content: {node_id: 节点状态}}。
    单元状态优先级：mastered（覆盖节点 mastered）> learning > equivalent（概念命中）> todo。
    open = 未达成 且 全部前置单元达成（前置达成 = mastered 或 equivalent）。
    """
    outline = outline or outline_store.get_outline(subject_id)
    if outline is None:
        return {"subject": subject_id, "outline_revision": None, "concepts_mastered": 0,
                "units": [], "content": {}, "note": "尚无大纲"}
    if lib_docs is None:
        # R63：`/subjects/{id}/progress` 是主页/学科页每屏都会打的请求，走进程内缓存
        from ..service.library import get_library

        lib = get_library()
        lib_docs = {n.id: n.doc for n in lib.nodes}
        lib_ids = set(lib_docs)
    elif lib_ids is None:
        lib_ids = set(lib_docs)
    c2u = content_to_unit(outline, lib_ids)
    unit_tags_map = outline_tags(outline)
    # 节点级状态
    node_rows = {
        r.node_id: r.state
        for r in db.query(models.UserNode)
        .filter(models.UserNode.user_id == user_id, models.UserNode.node_id.in_(c2u))
    }
    concept_mastered = mastered_concepts(db, user_id, subject_id)
    # 每单元：内容节点状态聚合 + 等效
    unit_node_state: dict[str, list[str]] = {}
    for node_id, unit_id in c2u.items():
        unit_node_state.setdefault(unit_id, []).append(node_rows.get(node_id, "locked"))
    satisfied: dict[str, str] = {}  # unit_id -> mastered|equivalent
    for u in outline.units:
        node_states = unit_node_state.get(u.id, [])
        if MASTERED in node_states:
            satisfied[u.id] = "mastered"
        elif LEARNING in node_states:
            satisfied[u.id] = "learning"
        elif unit_tags_map[u.id] and unit_tags_map[u.id] <= concept_mastered:
            satisfied[u.id] = "equivalent"
        else:
            satisfied[u.id] = "todo"
    # open（前置全达成；环已由大纲校验排除）
    index = {u.id: u for u in outline.units}
    open_flags: dict[str, bool] = {}
    for u in outline.units:
        if satisfied[u.id] in ("mastered", "equivalent"):
            open_flags[u.id] = False
            continue
        pre_ok = all(
            satisfied.get(p, "todo") in ("mastered", "equivalent") if p in index else True
            for p in u.prereqs
        )
        open_flags[u.id] = pre_ok
    units = []
    for u in outline.units:
        units.append(
            {
                "id": u.id,
                "title": u.title,
                "group": u.group,
                "concept_tags": u.concept_tags,
                "status": satisfied[u.id],
                "open": open_flags[u.id],
                "content_ids": sorted(nid for nid, uid in c2u.items() if uid == u.id),
                "prereqs": list(u.prereqs),
            }
        )
    return {
        "subject": subject_id,
        "outline_revision": outline.revision,
        "concepts_mastered": len(concept_mastered),
        "units": units,
        "content": dict(node_rows),
        "note": "",
    }


def subject_content_ids(db: Session, user_id: str, subject_id: str) -> set[str]:
    """学科全部内容节点 id（重置/删除进度用）。

    preset(math)：内容库中 level ∈ LEVELS 的全部节点（学段语义 = 数学关卡组，含首领/孤儿锚点
    primary.0199、high.0201 等）；custom：大纲单元内容节点（unit id / anchors 落库者）。
    """
    from ..domain.graph import LEVELS

    outline = outline_store.get_outline(subject_id)
    # R63：`/progress/reset` 也是请求路径；读内容库走进程内缓存（写库语义不变）
    from ..service.library import get_library

    lib = get_library()
    if outline is None and subject_id == PRESET_MATH:
        return {n.id for n in lib.nodes if n.doc.level in LEVELS}
    if outline is None:
        return set()
    lib_ids = {n.id for n in lib.nodes}
    mapped = set(content_to_unit(outline, lib_ids))
    if subject_id == PRESET_MATH:
        mapped |= {n.id for n in lib.nodes if n.doc.level in LEVELS}
    return mapped


def reset_subject_progress(
    db: Session,
    user_id: str,
    subject_id: str,
    *,
    now: datetime | None = None,
) -> dict:
    """显式重置学科进度（docs/14 §2.2/§0.4）：清概念证据 + 学科内容节点 mastered/learning
    降回 available + 清该学科复习行；随后全图重算（其它学科/学段不受影响）。

    仅影响 user_nodes 中属于该学科大纲单元内容（含锚点）的节点与 (subject) 概念证据。
    """
    now = now or datetime.now(timezone.utc)
    ids = subject_content_ids(db, user_id, subject_id)
    cleared_nodes = 0
    if ids:
        rows = (
            db.query(models.UserNode)
            .filter(
                models.UserNode.user_id == user_id,
                models.UserNode.node_id.in_(ids),
                models.UserNode.state.in_([MASTERED, LEARNING]),
            )
            .all()
        )
        for row in rows:
            row.state = AVAILABLE
            row.mastered_at = None
            row.consecutive_correct = 0
            cleared_nodes += 1
        db.query(models.Review).filter(
            models.Review.user_id == user_id,
            models.Review.node_id.in_(ids),
        ).delete(synchronize_session=False)
    db.query(models.UserConcept).filter(
        models.UserConcept.user_id == user_id,
        models.UserConcept.subject_id == subject_id,
    ).delete(synchronize_session=False)
    db.flush()
    from ..service.library import get_graph

    from ..service.progress import recompute_states

    recompute_states(db, user_id, get_graph())
    db.flush()
    return {"subject": subject_id, "nodes_reset": cleared_nodes, "concepts_reset": True}


__all__ = [
    "normalize_tag",
    "unit_tags",
    "outline_tags",
    "content_to_unit",
    "node_concept_tags",
    "sync_concept_registry",
    "sync_outline_registry",
    "recompute_subject_concepts",
    "mastered_concepts",
    "unit_states",
    "subject_content_ids",
    "reset_subject_progress",
]
