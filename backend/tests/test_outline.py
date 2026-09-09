"""Phase A A1：学科注册 + 大纲 schema/持久化/校验（docs/14 §1、§2.1）。

覆盖：schema 载入与结构校验（id 唯一/自指/环/引用存在性/目标上限）；
store 版本递增/原子落盘；API 注册/采纳/重生成/局部改/删除；preset 治理红线。
"""
from __future__ import annotations

import uuid

import pytest
import yaml

from app.outline.schemas import (
    OutlineDoc,
    OutlineUnit,
    load_outline_yaml,
    outline_to_yaml,
    validate_outline_doc,
)


def _u(uid: str, title: str = "t", prereqs=None, group: str = "g1", **kw) -> dict:
    d = {"id": uid, "title": title, "group": group, "objectives": ["目标1"]}
    if prereqs is not None:
        d["prereqs"] = prereqs
    d.update(kw)
    return d


# ---------- schema / 校验（无 DB） ----------
class TestOutlineSchema:
    def test_roundtrip_yaml_preserves_units(self):
        doc = OutlineDoc(
            subject="demo", label="Demo",
            units=[OutlineUnit(**_u("demo.u01")), OutlineUnit(**_u("demo.u02", prereqs=["demo.u01"]))],
        )
        text = outline_to_yaml(doc)
        back = load_outline_yaml(text)
        assert back.subject == "demo"
        assert [u.id for u in back.units] == ["demo.u01", "demo.u02"]
        assert back.units[1].prereqs == ["demo.u01"]

    def test_duplicate_ids_detected(self):
        doc = OutlineDoc(subject="d", units=[OutlineUnit(**_u("d.a")), OutlineUnit(**_u("d.a"))])
        problems = validate_outline_doc(doc)
        assert any("重复" in p for p in problems)

    def test_self_ref_detected(self):
        doc = OutlineDoc(subject="d", units=[OutlineUnit(**_u("d.a", prereqs=["d.a"]))])
        problems = validate_outline_doc(doc)
        assert any("自指" in p for p in problems)

    def test_cycle_detected(self):
        doc = OutlineDoc(
            subject="d",
            units=[
                OutlineUnit(**_u("d.a", prereqs=["d.b"])),
                OutlineUnit(**_u("d.b", prereqs=["d.a"])),
            ],
        )
        problems = validate_outline_doc(doc)
        assert any("环" in p for p in problems)

    def test_missing_prereq_detected(self):
        doc = OutlineDoc(
            subject="d",
            units=[
                OutlineUnit(**_u("d.a")),
                OutlineUnit(**_u("d.b", prereqs=["d.zzz"])),
            ],
        )
        # '.' 引用按"内容节点引用"语义：无 known 集不判；提供 known 集后未知引用被报
        assert validate_outline_doc(doc) == []
        problems = validate_outline_doc(doc, known_content_ids={"primary.0101"})
        assert any("d.zzz" in p and "内容节点" in p for p in problems)

    def test_content_node_ref_checked_only_with_known_set(self):
        doc = OutlineDoc(subject="d", units=[OutlineUnit(**_u("d.a", prereqs=["primary.0101"]))])
        assert validate_outline_doc(doc) == []  # 未提供 known 集 → 不判内容存在性
        problems = validate_outline_doc(doc, known_content_ids={"middle.0201"})
        assert any("primary.0101" in p for p in problems)
        assert validate_outline_doc(doc, known_content_ids={"primary.0101"}) == []

    def test_objectives_cap_four(self):
        with pytest.raises(Exception):
            OutlineUnit(**_u("d.a", objectives=["1", "2", "3", "4", "5"]))
        unit = OutlineUnit(**_u("d.a", objectives=["1", "2", "3", "4"]))  # 数学既有 ≤4 兼容
        assert len(unit.objectives) == 4

    def test_difficulty_range(self):
        OutlineUnit(**_u("d.a", difficulty=1))
        OutlineUnit(**_u("d.a", difficulty=3))
        with pytest.raises(Exception):
            OutlineUnit(**_u("d.a", difficulty=0))
        with pytest.raises(Exception):
            OutlineUnit(**_u("d.a", difficulty=4))

    def test_schema_version_guard(self):
        with pytest.raises(Exception):
            OutlineDoc(subject="d", schema_version=2, units=[])

    def test_empty_outline_invalid(self):
        assert any("至少" in p for p in validate_outline_doc(OutlineDoc(subject="d", units=[])))


# ---------- store 持久化（temp 内容根；DB 用会话级共享库 + 自清理） ----------
@pytest.fixture
def outline_env(tmp_path, monkeypatch):
    """outline store 的文件读写全部落在 tmp 内容根；DB 行测试后自清理（preset 保留）。"""
    monkeypatch.setenv("MF_CONTENT_ROOT", str(tmp_path / "content"))
    from app.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    from app.outline import store as st

    st.ensure_math_preset(db)
    db.commit()
    try:
        yield db
    finally:
        # 清理本测试创建的自定义学科行（大纲文件落在 tmp 内容根，随 tmp_path 回收）
        for row in st.list_subjects(db):
            if row.kind != "preset":
                db.delete(row)
        db.commit()
        db.close()


class TestOutlineStore:
    def test_math_preset_registered_and_protected(self, outline_env):
        from app.outline import store as st

        db = outline_env
        row = st.ensure_math_preset(db)
        assert row.id == "math" and row.kind == "preset"
        st.ensure_math_preset(db)  # 幂等：不产生重复行
        ids = [s.id for s in st.list_subjects(db)]
        assert ids.count("math") == 1
        # preset 不可删除 / 不可直接 PUT 大纲
        with pytest.raises(Exception, match="预置学科不可删除"):
            st.delete_subject(db, "math")
        with pytest.raises(Exception, match="roadmap 派生治理"):
            st.add_outline(db, "math", units=[OutlineUnit(**_u("math.x"))])

    def test_create_custom_and_outline_revision_bump(self, outline_env):
        from app.outline import store as st

        db = outline_env
        subj = st.create_subject(db, label="Python 入门", subject_id="pydemo")
        assert subj.kind == "custom"
        assert st.get_outline("pydemo") is None
        units = [OutlineUnit(**_u("pydemo.u01")),
                 OutlineUnit(**_u("pydemo.u02", prereqs=["pydemo.u01"]))]
        doc1 = st.add_outline(db, "pydemo", units=units, status="draft", source="manual")
        assert doc1.revision == 1
        assert doc1.status == "draft"
        # 整份重生成 → revision+1、原子替换
        units2 = [OutlineUnit(**_u("pydemo.u01")),
                  OutlineUnit(**_u("pydemo.u02", prereqs=["pydemo.u01"])),
                  OutlineUnit(**_u("pydemo.u03", prereqs=["pydemo.u02"]))]
        doc2 = st.add_outline(db, "pydemo", units=units2, status="active", source="ai")
        assert doc2.revision == 2 and doc2.status == "active"
        got = st.get_outline("pydemo")
        assert got.revision == 2 and len(got.units) == 3
        assert (st.subject_dir("pydemo") / "outline.yaml").exists()
        # 再次载入（文本层）内容一致
        text = (st.subject_dir("pydemo") / "outline.yaml").read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
        assert raw["revision"] == 2 and raw["schema_version"] == 1

    def test_cycle_rejected_on_add(self, outline_env):
        from app.outline import store as st

        db = outline_env
        st.create_subject(db, label="D", subject_id="cyc")
        units = [OutlineUnit(**_u("cyc.a", prereqs=["cyc.b"])),
                 OutlineUnit(**_u("cyc.b", prereqs=["cyc.a"]))]
        with pytest.raises(Exception, match="环"):
            st.add_outline(db, "cyc", units=units)

    def test_patch_unit_custom_and_preset_restriction(self, outline_env):
        from app.outline import store as st

        db = outline_env
        st.create_subject(db, label="P", subject_id="patchme")
        st.add_outline(db, "patchme", units=[OutlineUnit(**_u("patchme.u01"))])
        doc = st.patch_outline_unit(db, "patchme", "patchme.u01",
                                    fields={"objectives": ["改后目标"], "concept_tags": ["c1"]})
        assert doc.by_id()["patchme.u01"].objectives == ["改后目标"]
        assert doc.by_id()["patchme.u01"].concept_tags == ["c1"]
        # 不允许改 id / 改分组（结构性）与未知字段
        with pytest.raises(Exception, match="不允许修改字段"):
            st.patch_outline_unit(db, "patchme", "patchme.u01", fields={"id": "patchme.xx"})
        with pytest.raises(Exception, match="不允许修改字段"):
            st.patch_outline_unit(db, "patchme", "patchme.u01", fields={"group": "g9"})
        # preset 大纲不存在时同样拒绝
        with pytest.raises(Exception, match="尚无大纲"):
            st.patch_outline_unit(db, "math", "math.x", fields={})

    def test_delete_custom_subject(self, outline_env):
        from app.outline import store as st

        db = outline_env
        st.create_subject(db, label="Gone", subject_id="gone")
        st.add_outline(db, "gone", units=[OutlineUnit(**_u("gone.u01"))])
        st.delete_subject(db, "gone")
        assert st.get_subject(db, "gone") is None
        assert not (st.subject_dir("gone") / "outline.yaml").exists()

    def test_invalid_subject_id_rejected(self, outline_env):
        from app.outline import OutlineError, store as st

        db = outline_env
        with pytest.raises(OutlineError):
            st.create_subject(db, label="Bad", subject_id="UPPER-BAD")


# ---------- API 集成（共享 app_client：math preset 由 lifespan 注册） ----------
def _mk_units(prefix: str):
    return [_u(f"{prefix}.u01"), _u(f"{prefix}.u02", prereqs=[f"{prefix}.u01"])]


class TestSubjectsApi:
    def test_list_contains_math_preset(self, app_client):
        r = app_client.get("/api/subjects")
        assert r.status_code == 200
        sids = {s["id"] for s in r.json()["subjects"]}
        assert "math" in sids
        math = next(s for s in r.json()["subjects"] if s["id"] == "math")
        assert math["kind"] == "preset" and math["outline"] is None

    def test_preset_outline_put_forbidden(self, app_client):
        r = app_client.put("/api/subjects/math/outline", json={"units": _mk_units("math")})
        assert r.status_code == 422
        assert "roadmap 派生治理" in r.json()["detail"]["error"]["message"]

    def test_crud_flow(self, app_client):
        sid = f"apidemo{uuid.uuid4().hex[:6]}"
        # 创建（显式 id）
        r = app_client.post("/api/subjects", json={"label": "API Demo", "subject_id": sid})
        assert r.status_code == 201
        assert r.json()["id"] == sid and r.json()["kind"] == "custom"
        # 采纳大纲（revision 1）
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": _mk_units(sid), "status": "active", "source": "manual"})
        assert r.status_code == 200
        assert r.json()["revision"] == 1 and r.json()["status"] == "active"
        # 整份重生成（revision 2）
        units2 = _mk_units(sid) + [_u(f"{sid}.u03", prereqs=[f"{sid}.u02"])]
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": units2, "status": "active", "source": "ai"})
        assert r.json()["revision"] == 2 and len(r.json()["units"]) == 3
        # 单元局部改
        r = app_client.patch(f"/api/subjects/{sid}/outline/units/{sid}.u01",
                             json={"fields": {"objectives": ["改写目标"]}})
        assert r.status_code == 200
        unit = next(u for u in r.json()["units"] if u["id"] == f"{sid}.u01")
        assert unit["objectives"] == ["改写目标"]
        # 环候选被拒（校验端点 + PUT）
        cyc = [_u(f"{sid}.a", prereqs=[f"{sid}.b"]), _u(f"{sid}.b", prereqs=[f"{sid}.a"])]
        r = app_client.post(f"/api/subjects/{sid}/outline/validate", json={"units": cyc})
        assert r.status_code == 200 and r.json()["ok"] is False
        assert any("环" in p for p in r.json()["problems"])
        r = app_client.put(f"/api/subjects/{sid}/outline", json={"units": cyc})
        assert r.status_code == 422
        # 单元 id 不带学科前缀 → 命名空间约定被拒
        r = app_client.put(f"/api/subjects/{sid}/outline", json={"units": _mk_units("other")})
        assert r.status_code == 422
        assert "学科前缀" in r.json()["detail"]["error"]["message"]
        # 非法 id 创建
        r = app_client.post("/api/subjects", json={"label": "X", "subject_id": "UPPER"})
        assert r.status_code == 422
        # 删除
        r = app_client.delete(f"/api/subjects/{sid}")
        assert r.status_code == 204
        r = app_client.get(f"/api/subjects/{sid}")
        assert r.status_code == 404
        # preset 删除被拒
        r = app_client.delete("/api/subjects/math")
        assert r.status_code == 409

    def test_regenerate_placeholder_501(self, app_client):
        sid = f"regen{uuid.uuid4().hex[:6]}"
        app_client.post("/api/subjects", json={"label": "R", "subject_id": sid})
        r = app_client.post(f"/api/subjects/{sid}/outline/regenerate")
        assert r.status_code == 501
        app_client.delete(f"/api/subjects/{sid}")
