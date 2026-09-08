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
    """D：蓝图自动自查——文件内前置存在、无自指/环 + R18 内容不变式（真实库）全绿。"""
    from app.content.loader import load_library

    lib = load_library()
    edges: dict[str, dict[str, list]] = {}
    meta: dict[str, dict[str, dict]] = {}
    for nid, loaded in lib.by_id.items():
        doc = loaded.doc
        lv = doc.level or nid.split(".")[0]
        edges.setdefault(lv, {})[nid] = list(doc.prereqs or ())
        meta.setdefault(lv, {})[nid] = {"kind": getattr(doc, "kind", "") or "", "topic": doc.topic or ""}
    for level in ("primary", "middle", "high", "college", "ai"):
        rep = audit(
            level,
            known_node_ids=set(lib.by_id),
            content_edges=edges.get(level),
            content_meta=meta.get(level),
        )
        assert rep["ok"], rep
        assert rep["cycles"] == []
        assert rep["anchors_missing"] == []
        assert rep["content_prereq_violations"] == [], rep["content_prereq_violations"]
        assert rep["boss_unmatched"] == [], rep["boss_unmatched"]


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


# ---------------------------------------------------------------------------
# R14 后续 #1：跨学段 prereq（audit 语义 + loader 格式 + pipeline 解析）
# ---------------------------------------------------------------------------

def _mk_entry(eid, prereqs=None, anchors=None, topic="t"):
    from app.content.roadmap import RoadmapEntry

    level = eid.split(".", 1)[0]
    return RoadmapEntry(
        id=eid, title=eid, level=level, topic=topic,
        prereqs=list(prereqs or []), anchors=list(anchors or []),
    )


def test_audit_cross_level_ref_ok_with_gap():
    """合法跨学段引用（前序学段）：ok=True、进 cross_refs；目标未落地 → cross_gaps 提示（不影响 ok）。"""
    from app.content.roadmap import Roadmap

    fake_ai = Roadmap(level="ai", entries=[_mk_entry("ai.t1", prereqs=["college.c01"])])
    fake_reg = {"college.c01": ("college", _mk_entry("college.c01"))}
    rep = audit("ai", roadmap=fake_ai, registry=fake_reg, known_node_ids=set())
    assert rep["ok"] is True, rep
    assert rep["cross_refs"] == ["ai.t1->college.c01"]
    assert len(rep["cross_gaps"]) == 1
    assert rep["cross_reverse"] == []


def test_audit_cross_level_ref_landed_no_gap():
    """跨学段目标条目已落地（锚点节点在内容库）→ 无 gap。"""
    from app.content.roadmap import Roadmap

    fake_ai = Roadmap(level="ai", entries=[_mk_entry("ai.t1", prereqs=["high.x1"])])
    fake_reg = {"high.x1": ("high", _mk_entry("high.x1", anchors=["high.0201"]))}
    rep = audit("ai", roadmap=fake_ai, registry=fake_reg, known_node_ids={"high.0201"})
    assert rep["ok"] is True
    assert rep["cross_refs"] == ["ai.t1->high.x1"]
    assert rep["cross_gaps"] == []


def test_audit_cross_level_ref_missing_entry():
    """跨学段引用指向不存在的条目 → prereq_missing、ok=False。"""
    from app.content.roadmap import Roadmap

    fake_ai = Roadmap(level="ai", entries=[_mk_entry("ai.t1", prereqs=["college.zzz"])])
    fake_reg = {"college.c01": ("college", _mk_entry("college.c01"))}
    rep = audit("ai", roadmap=fake_ai, registry=fake_reg, known_node_ids=set())
    assert rep["ok"] is False, rep
    assert any("college.zzz" in e for e in rep["prereq_missing"])


def test_audit_cross_level_ref_reverse_rejected():
    """反向引用（引用后序学段条目）→ cross_reverse、ok=False。"""
    from app.content.roadmap import Roadmap

    fake_primary = Roadmap(level="primary", entries=[_mk_entry("primary.t1", prereqs=["ai.a01"])])
    fake_reg = {"ai.a01": ("ai", _mk_entry("ai.a01"))}
    rep = audit("primary", roadmap=fake_primary, registry=fake_reg, known_node_ids=set())
    assert rep["ok"] is False, rep
    assert any("反向" in e for e in rep["cross_reverse"])


def test_audit_same_file_cycle_still_detected():
    """同文件环仍由 DFS 检出（跨学段方向单向无环，但文件内环能力保留）。"""
    from app.content.roadmap import Roadmap

    fake = Roadmap(
        level="primary",
        entries=[
            _mk_entry("primary.x1", prereqs=["primary.x2"]),
            _mk_entry("primary.x2", prereqs=["primary.x1"]),
        ],
    )
    rep = audit("primary", roadmap=fake, registry={}, known_node_ids=set())
    assert rep["ok"] is False
    assert rep["cycles"], "同文件环应被检出"


def test_loader_rejects_bad_cross_ref_format(tmp_path):
    """loader 格式层：prereq `foo.bar`（非法学段前缀）→ RoadmapError 信息清晰。"""
    import pytest
    import yaml

    from app.content.roadmap import RoadmapError, load_roadmap

    raw = {
        "level": "primary",
        "entries": [
            {"id": "primary.t1", "title": "t", "topic": "t", "prereqs": ["foo.bar"]},
        ],
    }
    p = tmp_path / "primary.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(RoadmapError) as ei:
        load_roadmap("primary", path=p)
    assert "格式非法" in str(ei.value) and "foo.bar" in str(ei.value)


def test_cross_level_gaps_real_blueprints():
    """真实蓝图（改写跨学段引用后）：ai 的跨学段前置未落地 → gaps 列出；audit 仍 ok。"""
    from app.content.loader import load_library
    from app.content.pipeline import cross_level_gaps

    lib = load_library()
    # 内容库现仅 primary/middle/high 人工锚点节点；ai 引用的 college 条目未落地 → 有 gap（提示语义）
    gaps = cross_level_gaps("ai")
    assert gaps, "改写后 ai.yaml 应有跨学段引用且目标未落地 → 缺口提示"
    assert all("未落地" in g for g in gaps)
    rep = audit("ai", known_node_ids=set(lib.by_id))
    assert rep["ok"] is True and rep["cross_refs"], rep


# ---------------------------------------------------------------------------
# R18 阶段 3：audit 内容不变式（造错必报）
# ---------------------------------------------------------------------------

def test_audit_content_prereq_backward_reported():
    """内容节点手写 prereq 指向蓝图序更后条目（超出前置闭包）→ 报错。"""
    from app.content.roadmap import Roadmap

    fake = Roadmap(
        level="primary",
        entries=[
            _mk_entry("primary.a1", prereqs=[]),
            _mk_entry("primary.a2", prereqs=["primary.a1"]),
        ],
    )
    reg = {"primary.a1": ("primary", fake.by_id()["primary.a1"]), "primary.a2": ("primary", fake.by_id()["primary.a2"])}
    # a1 内容手写 prereq 指向后项 a2 → 超出 a1 前置闭包 → 违规
    rep = audit(
        "primary",
        roadmap=fake,
        registry=reg,
        known_node_ids={"primary.a1", "primary.a2"},
        content_edges={"primary.a1": ["primary.a2"]},
        content_meta={"primary.a1": {"kind": "", "topic": "t"}},
    )
    assert rep["ok"] is False
    assert any("primary.a2" in m for m in rep["content_prereq_violations"])


def test_audit_content_prereq_forward_ok():
    """内容手写 prereq 落在蓝图前置闭包内 → 不报（同构正常）。"""
    from app.content.roadmap import Roadmap

    fake = Roadmap(
        level="primary",
        entries=[
            _mk_entry("primary.a1", prereqs=[]),
            _mk_entry("primary.a2", prereqs=["primary.a1"]),
        ],
    )
    reg = {"primary.a1": ("primary", fake.by_id()["primary.a1"]), "primary.a2": ("primary", fake.by_id()["primary.a2"])}
    rep = audit(
        "primary",
        roadmap=fake,
        registry=reg,
        known_node_ids={"primary.a1", "primary.a2"},
        content_edges={"primary.a2": ["primary.a1"]},
        content_meta={"primary.a2": {"kind": "", "topic": "t"}},
    )
    assert rep["ok"] is True
    assert rep["content_prereq_violations"] == []


def test_audit_boss_unmatched_reported():
    """首领内容 topic 无匹配蓝图主题组 → 无主/错主报错。"""
    from app.content.roadmap import Roadmap

    fake = Roadmap(level="primary", entries=[_mk_entry("primary.a1", prereqs=[], topic="数与运算")])
    reg = {"primary.a1": ("primary", fake.by_id()["primary.a1"])}
    rep = audit(
        "primary",
        roadmap=fake,
        registry=reg,
        known_node_ids={"primary.boss"},
        content_edges={"primary.boss": ["primary.a1"]},
        content_meta={"primary.boss": {"kind": "boss", "topic": "神秘首领组"}},
    )
    assert rep["ok"] is False
    assert any("神秘首领组" in m for m in rep["boss_unmatched"])
