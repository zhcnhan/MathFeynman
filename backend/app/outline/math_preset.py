"""app.outline.math_preset：数学预置学科的大纲派生（docs/14 §5 · Phase A A3）。

数学 = subject=math preset：现有五学段 roadmap（docs/12）为**持久治理载体**；本模块把
roadmap 派生为**数学总 Outline**（schema v1，content/subjects/math/outline.yaml）：
- 关卡组 = 学段（primary/middle/high/college/ai），组内 = 既有总序链（roadmap 列表序）；
- 单元 = roadmap 条目：title/objectives/prereqs/difficulty/thinking/anchors/topic 原样映射；
  概念标签（concept_tags）：
  · 优先沿用上一大纲版本同 id 单元的人工/回填标签（重生成不丢标签编辑）；
  · 否则由该单元已落地内容节点（anchors[0] 在库 → 锚点节点；否则单元 id 自身在库=auto 节点）
    的 core_concepts 归一回填（"既有锚点节点归一到概念标签"，免人工补标）；
- 单元转正状态（roadmap draft 如实标注，docs/14 §5 ①）：primary=reviewed（已精核转正）；
  middle/high/college/ai=draft（roadmap 精核转正为持续治理项，docs/12 §4 滚动推进）。

派生语义与约束：
- 派生结果与 roadmap 结构一致：单元 id 全局唯一、prereq 闭环（同大纲单元或真实内容节点）、无环；
- preset(math) 大纲禁止结构编辑（store 治理红线）；roadmap 精核批后重跑派生即"版本递增再生"，
  概念标签按 unit id 保留（重组单元若仍锚定同一内容节点，标签自动由 core_concepts 回填）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from . import store as outline_store
from .concepts import normalize_tag, sync_outline_registry
from .schemas import (
    OUTLINE_SCHEMA_VERSION,
    OutlineDoc,
    OutlineError,
    OutlineUnit,
    validate_outline_doc,
)

# 数学关卡组（= 学段学习顺序，docs/12 LEVELS）
MATH_GROUPS = ("primary", "middle", "high", "college", "ai")
# 已精核转正的关卡组（docs/14 §5 ①：primary 转正；其余 draft 随用户到段滚动精核）
MATH_REVIEWED_GROUPS = ("primary",)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unit_tags_from_content(
    entry,
    lib_docs: dict[str, Any],
    *,
    known: set[str] | None = None,
) -> list[str]:
    """由已落地内容节点 core_concepts 归一回填概念标签（anchors[0] 在库优先；否则 auto 节点）。"""
    known = known or set(lib_docs)
    cands = list(entry.anchors or []) + [entry.id]
    for nid in cands:
        if nid not in known:
            continue
        doc = lib_docs.get(nid)
        if doc is None:
            continue
        return [c for c in (doc.core_concepts or []) if c and normalize_tag(c)]
    return []


def build_math_outline(
    *,
    roadmaps: dict[str, Any] | None = None,
    lib_docs: dict[str, Any] | None = None,
    lib_ids: set[str] | None = None,
    prev_tags: dict[str, list[str]] | None = None,
    revision: int | None = None,
    status: str = "active",
    note: str = "",
) -> OutlineDoc:
    """纯函数：从 roadmap 构建数学总 OutlineDoc（不碰 DB/文件；测试与派生共用）。

    roadmaps: {level: Roadmap}（缺省读内容库 roadmap 文件）；
    lib_docs/lib_ids: 内容库节点元信息（缺省读 stages；用于标签回填与引用存在性校验）；
    prev_tags: {unit_id: [tags]}（上一大纲版本同 id 单元标签，重生成保留）；
    revision: 显式指定版本号（缺省 1）。
    """
    from ..content import roadmap as rm

    roadmaps = roadmaps or {lv: rm.load_roadmap(lv) for lv in MATH_GROUPS}
    if lib_docs is None:
        from ..content.loader import load_library

        lib = load_library()
        lib_docs = {n.id: n.doc for n in lib.nodes}
    lib_ids = lib_ids or set(lib_docs)
    prev_tags = prev_tags or {}
    units: list[OutlineUnit] = []
    for lv in MATH_GROUPS:
        rd = roadmaps.get(lv)
        if rd is None:
            continue
        for e in rd.entries:
            tags = prev_tags.get(e.id)
            if not tags:  # 无历史标签 → 由已落地内容节点 core_concepts 回填
                tags = _unit_tags_from_content(e, lib_docs, known=lib_ids)
            units.append(
                OutlineUnit(
                    id=e.id,
                    title=e.title,
                    objectives=list(e.objectives),
                    concept_tags=[t for t in (tags or []) if t and normalize_tag(t)],
                    group=lv,
                    prereqs=list(e.prereqs),
                    difficulty=e.difficulty,
                    requires_thinking=e.requires_thinking,
                    anchors=list(e.anchors),
                    topic=e.topic or "",
                    status="reviewed" if lv in MATH_REVIEWED_GROUPS else "draft",
                )
            )
    doc = OutlineDoc(
        subject=outline_store.PRESET_MATH,
        label="数学",
        schema_version=OUTLINE_SCHEMA_VERSION,
        revision=revision or 1,
        status=status,
        source="roadmap",
        unit_id_scope="entry",
        generated_at=_now_iso(),
        updated_at=_now_iso(),
        note=note
        or (
            "数学总 Outline：由五学段 roadmap（docs/12）派生（学段=关卡组、段内=既有总序链）。"
            "primary 组已精核转正(reviewed)；middle/high/college/ai 为 draft，随用户到段滚动精核转正"
            "（docs/12 §4）。概念标签 = 锚点/auto 内容节点 core_concepts 归一回填，重生成按单元 id "
            "保留既有标签。学习门禁仍由 roadmap 权威总序引擎（R18）驱动。"
        ),
        units=units,
    )
    problems = validate_outline_doc(doc, known_content_ids=lib_ids)
    if problems:
        raise OutlineError("数学大纲派生校验未通过：" + "；".join(problems))
    return doc


def derive_math_outline(
    db: Session,
    *,
    roadmaps: dict[str, Any] | None = None,
    lib_docs: dict[str, Any] | None = None,
    lib_ids: set[str] | None = None,
    status: str = "active",
    note: str = "",
) -> OutlineDoc:
    """派生并持久化数学总 Outline（幂等；再次调用 = roadmap 变更后的重生成，revision+1）。

    派生 → 结构校验（已知内容库引用）→ 原子替换 content/subjects/math/outline.yaml →
    概念注册表同步 → DB 提交。返回新大纲文档。
    """
    if db.get(models.Subject, outline_store.PRESET_MATH) is None:
        outline_store.ensure_math_preset(db)
    # 旧大纲读取容错：文件损坏/结构非法（如 title 空）时降级为“无旧版”，
    # 直接由 roadmap 干净重派生并覆盖（标签保留尽力而为，不阻塞修复）。
    prev = None
    try:
        prev = outline_store.get_outline(outline_store.PRESET_MATH)
    except Exception as e:  # OutlineError / OSError 等
        print(f"[math_preset] 读取旧大纲失败，降级全量重派生: {e}")
        prev = None
    prev_tags = {u.id: list(u.concept_tags) for u in prev.units} if prev else {}
    if lib_docs is None and lib_ids is None:
        from ..content.loader import load_library

        lib = load_library()
        lib_docs = {n.id: n.doc for n in lib.nodes}
    revision = (prev.revision + 1) if prev else 1
    doc = build_math_outline(
        roadmaps=roadmaps,
        lib_docs=lib_docs,
        lib_ids=lib_ids,
        prev_tags=prev_tags,
        revision=revision,
        status=status,
        note=note,
    )
    outline_store.save_outline(outline_store.PRESET_MATH, doc)
    sync_outline_registry(db, outline_store.PRESET_MATH, doc)
    db.commit()
    return doc


__all__ = [
    "MATH_GROUPS",
    "MATH_REVIEWED_GROUPS",
    "build_math_outline",
    "derive_math_outline",
]
