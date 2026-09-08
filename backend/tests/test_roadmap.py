"""docs/10 §2.2 课程蓝图 loader 单测：primary.yaml 结构完整性（阶段 3 子步 6）。"""
from __future__ import annotations

import pytest

from app.content.roadmap import RoadmapError, all_levels_exist, audit, load_roadmap


def test_primary_roadmap_loads_and_is_ordered():
    roadmap = load_roadmap("primary")
    assert roadmap.level == "primary"
    assert len(roadmap.entries) >= 15, "小学蓝图应有 ≥15 条（全序列草案）"
    ids = list(roadmap.by_id())
    assert len(set(ids)) == len(ids)  # id 唯一


def test_entries_wellformed():
    roadmap = load_roadmap("primary")
    for e in roadmap.entries:
        assert e.id and e.title and e.topic
        assert 1 <= e.difficulty <= 3
        assert e.level == "primary"
        if e.objectives:
            assert len(e.objectives) <= 3  # 轻条目：目标 ≤3 句
        # prereq 指向文件内条目或锚点节点（loader 已强校验，此处再抽查几处）
        for pr in e.prereqs:
            assert pr in roadmap.by_id() or "." in pr


def test_roadmap_missing_file_raises():
    with pytest.raises(RoadmapError):
        load_roadmap("no_such_level")  # 该文件名永不存在（college 建成后仍成立）


def test_all_levels_exist_helpers():
    assert "primary" in all_levels_exist()


def test_roadmap_audit_no_cycle_no_missing():
    """D：蓝图自动自查——文件内前置存在、无自指/环（供人工精核基线）。"""
    from app.content.loader import load_library

    lib = load_library()
    for level in ("primary", "middle", "high", "college", "ai"):
        rep = audit(level, known_node_ids=set(lib.by_id))
        assert rep["ok"], rep
        assert rep["cycles"] == []
        assert rep["anchors_missing"] == []


def test_roadmap_audit_covered_and_pending_detail():
    """C：covered/待生成明细与锚点判定口径一致。"""
    from app.content.loader import load_library

    lib = load_library()
    rep = audit("primary", known_node_ids=set(lib.by_id))
    covered = {e["id"] for e in rep["covered_entries"]}
    assert covered == {"primary.s05", "primary.s06", "primary.s07", "primary.s08"}
    pending = {e["id"] for e in rep["pending_entries"]}
    assert {"primary.s22", "primary.s23", "primary.s24", "primary.s25", "primary.s26"} <= pending
    # 交集为空：每一条非此即彼
    assert not (covered & pending)


def test_roadmap_audit_reports_missing_anchor():
    """C：人为造错锚点（不在内容库）→ audit 报错。"""
    from app.content.roadmap import Roadmap, RoadmapEntry

    fake = Roadmap(
        level="primary",
        entries=[
            RoadmapEntry(id="primary.x01", title="x", level="primary", topic="t", anchors=["primary.9999"], prereqs=[]),
            RoadmapEntry(id="primary.x02", title="y", level="primary", topic="t", prereqs=["primary.x01"]),
        ],
    )
    rep = audit("primary", roadmap=fake, known_node_ids=set())
    assert rep["ok"] is False
    assert any("primary.9999" in e for e in rep["anchors_missing"])
    # 无锚点条目在 pending 明细
    pending_ids = {e["id"] for e in rep["pending_entries"]}
    assert "primary.x02" in pending_ids
