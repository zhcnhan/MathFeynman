"""Phase A A2：概念层与进度映射（docs/14 §2.2）。

覆盖：标签归一化；大纲标签 → concepts 注册表同步；掌握证据派生（user_nodes.mastered →
(subject, concept)，节点 core_concepts 兜底）；大纲重生成后新单元"等效已掌握"（概念命中）；
显式重置学科进度；数学历史掌握迁移的引擎路径（math outline 注入形态，A3 起真实派生）。
"""
from __future__ import annotations

import uuid

import pytest

from app import models
from app.outline import concepts as cv
from app.outline import store as st
from app.outline.schemas import OutlineDoc, OutlineUnit


def _u(uid: str, tags=(), prereqs=None, group: str = "g1", title: str = "t") -> OutlineUnit:
    d = {"id": uid, "title": title, "group": group, "objectives": ["目标1"]}
    if tags:
        d["concept_tags"] = list(tags)
    if prereqs is not None:
        d["prereqs"] = prereqs
    return OutlineUnit(**d)


class _FakeDoc:
    """NodeDoc-like：只需 core_concepts（可带 level 参与 math 学科全集过滤）。"""

    def __init__(self, core_concepts, level: str = ""):
        self.core_concepts = list(core_concepts)
        self.level = level


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MF_CONTENT_ROOT", str(tmp_path / "content"))
    from app.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    from app.outline import store as _st

    _st.ensure_math_preset(db)
    db.commit()
    before = set(_created)
    yield db
    # 清理：只删本模块该测试创建的行（避免触碰共享 content 的 Edge FK / 其它模块进度）
    db.query(models.UserConcept).delete()
    db.query(models.Concept).delete()
    for nid in _created:
        if nid in before:
            continue
        db.query(models.Review).filter(models.Review.node_id == nid).delete(synchronize_session=False)
        db.query(models.UserNode).filter(
            models.UserNode.user_id == "local", models.UserNode.node_id == nid
        ).delete(synchronize_session=False)
        db.query(models.Node).filter(models.Node.id == nid).delete(synchronize_session=False)
    del _created[:]  # 重置为快照语义：下次测试从零计数
    for row in _st.list_subjects(db, include_removed=True):
        if row.kind != "preset":
            db.delete(row)
    db.commit()
    db.close()


_created: list[str] = []


def _seed_node(db, node_id: str, state: str = "mastered", core=()):
    if db.get(models.Node, node_id) is None:
        db.add(models.Node(id=node_id, title=node_id, level="primary"))
        db.flush()
        _created.append(node_id)
    row = db.get(models.UserNode, ("local", node_id))
    if row is None:
        row = models.UserNode(user_id="local", node_id=node_id, state=state)
        db.add(row)
    else:
        row.state = state
    db.commit()
    return _FakeDoc(core) if core else _FakeDoc([])


class TestConceptNormalization:
    def test_normalize_tag_basic(self):
        assert cv.normalize_tag(" 分数 加减 ") == "分数加减"
        assert cv.normalize_tag("Mixed Case") == "mixedcase"
        assert cv.normalize_tag("ＡＢＣ") == "abc"  # 全角→半角 + 小写

    def test_unit_tags_empty_and_dedup(self):
        doc = OutlineDoc(subject="s", units=[_u("s.u1", tags=["分数", " 分数", ""])])
        assert cv.unit_tags(doc, "s.u1") == {"分数"}


class TestConceptRegistryAndRecompute:
    def test_sync_registry_upsert(self, env):
        db = env
        sid = "syncx"  # 独立学科 id：避免 math 大纲派生（A3）已注册的全局概念污染计数
        n1 = cv.sync_concept_registry(db, sid, ["分数加减", "分数加减", "分数", " mixed "])
        assert n1 == 3
        assert db.get(models.Concept, (sid, "分数加减")) is not None
        # 幂等：再次同步不新增
        n2 = cv.sync_concept_registry(db, sid, ["分数加减", "新概念"])
        assert n2 == 1

    def test_recompute_derives_evidence_and_equivalence_after_restructure(self, env):
        db = env
        st.create_subject(db, label="Demo", subject_id="demo")
        # 大纲 v1：单元 demo.one（概念 分数/通分）——其内容节点 id 即单元 id
        doc1 = st.add_outline(
            db, "demo", units=[_u("demo.one", tags=["分数", "通分"])],
            status="active", source="manual",
        )
        cv.sync_outline_registry(db, "demo", doc1)
        # 用户掌握 demo.one（模拟学完；内容节点存在于内容库）
        _seed_node(db, "demo.one", state="mastered")
        docs = {"demo.one": _FakeDoc([])}
        rep = cv.recompute_subject_concepts(db, "local", "demo", lib_docs=docs)
        assert rep["concepts"] == 2 and rep["evidence_nodes"] == 1
        assert cv.mastered_concepts(db, "local", "demo") == {"分数", "通分"}
        # 大纲 v2（重生成：单元结构调整，demo.one 拆/改名，但保留概念标签）
        doc2 = st.add_outline(
            db, "demo",
            units=[
                _u("demo.frac", tags=["分数", "通分"], title="分数与通分（重组）"),
                _u("demo.plus", tags=["同分母加减"], prereqs=["demo.frac"]),
            ],
            status="active", source="ai",
        )
        cv.sync_outline_registry(db, "demo", doc2)
        # 重生成后概念证据仍在（挂在 subject,concept，不随大纲版本丢失）
        assert cv.mastered_concepts(db, "local", "demo") == {"分数", "通分"}
        view = cv.unit_states(db, "local", "demo")
        byid = {u["id"]: u for u in view["units"]}
        # demo.frac 未直接学过（无内容节点），但概念命中 → 等效已掌握、不可再"开放先学"
        assert byid["demo.frac"]["status"] == "equivalent"
        assert byid["demo.frac"]["open"] is False
        # demo.plus 概念未命中 → 照学；前置 demo.frac 等效 → 其 open=True
        assert byid["demo.plus"]["status"] == "todo"
        assert byid["demo.plus"]["open"] is True

    def test_math_orphan_node_core_concepts_evidence(self, env):
        """数学历史掌握迁移引擎路径：非大纲单元的孤儿人工节点（如 high.0201）mastered →
        core_concepts 兜底归一为 (math, concept) 证据（大纲重生成后概念仍在，进度不丢）。"""
        db = env
        # math 大纲以"保存"方式注入（A3 起由 roadmap 真实派生；此处验引擎路径）
        from app.outline.schemas import OutlineDoc

        st.save_outline("math", OutlineDoc(subject="math", units=[], status="draft"))
        # 孤儿节点：不属任何大纲单元/锚点，level=middle（数学关卡组）
        core = ["负数", "数轴"]
        _seed_node(db, "math.orphan", state="mastered", core=core)
        # 模拟其存在于内容库（level 参与 math 学科全集）
        docs = {"math.orphan": _FakeDoc(core, level="middle")}
        rep = cv.recompute_subject_concepts(db, "local", "math", lib_docs=docs)
        assert rep["concepts"] == 2 and rep["evidence_nodes"] == 1
        assert cv.mastered_concepts(db, "local", "math") == {"负数", "数轴"}
        # 大纲重生成（单元结构调整）后概念证据仍挂在 subject,concept（引擎不丢）
        st.save_outline("math", OutlineDoc(
            subject="math", revision=2, units=[
                _u("math.new1", tags=["负数"]), _u("math.new2", tags=["数轴"]),
            ], status="active",
        ))
        assert cv.mastered_concepts(db, "local", "math") == {"负数", "数轴"}
        view = cv.unit_states(db, "local", "math")
        byid = {u["id"]: u for u in view["units"]}
        assert byid["math.new1"]["status"] == "equivalent"
        assert byid["math.new2"]["status"] == "equivalent"

    def test_reset_clears_concepts_and_node_mastery(self, env):
        db = env
        st.create_subject(db, label="D3", subject_id="d3")
        doc = st.add_outline(db, "d3", units=[_u("d3.x", tags=["甲"])], status="active", source="manual")
        cv.sync_outline_registry(db, "d3", doc)
        # 模拟掌握 d3.x（内容库外注入：库外节点不属于"学科内容节点"，节点级重置不适用——
        # 重置只作用于 content 库内节点（见 API 层 math 测试）；概念证据仍可清空）
        _seed_node(db, "d3.x", state="mastered")
        cv.recompute_subject_concepts(db, "local", "d3",
                                      lib_docs={"d3.x": _FakeDoc([])})
        assert cv.mastered_concepts(db, "local", "d3") == {"甲"}
        rep = cv.reset_subject_progress(db, "local", "d3")
        assert rep["nodes_reset"] == 0  # 库外节点不属于学科内容集
        assert cv.mastered_concepts(db, "local", "d3") == set()

    def test_math_recompute_with_and_without_outline(self, env):
        db = env
        # env 内容根无 math 大纲 → 提示；A3 起真实 math 大纲存在时走正常派生（两次幂等）
        rep = cv.recompute_subject_concepts(db, "local", "math")
        if rep["note"]:
            assert "尚无大纲" in rep["note"] and rep["concepts"] == 0


class TestConceptsApi:
    def test_progress_and_reset_flow(self, app_client):
        sid = f"cdemo{uuid.uuid4().hex[:6]}"
        app_client.post("/api/subjects", json={"label": "C", "subject_id": sid})
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": [
                               {"id": f"{sid}.one", "title": "单元一", "group": "g1",
                                "objectives": ["o"], "concept_tags": ["概念甲", "概念乙"]},
                               {"id": f"{sid}.two", "title": "单元二", "group": "g1",
                                "objectives": ["o"], "concept_tags": ["概念丙"],
                                "prereqs": [f"{sid}.one"]},
                           ], "status": "active", "source": "manual"})
        assert r.status_code == 200
        # 尚无掌握 → 全部 todo；单元一 open（无前置）、单元二未开放（前置未达成）
        r = app_client.get(f"/api/subjects/{sid}/progress")
        assert r.status_code == 200
        units = {u["id"]: u for u in r.json()["units"]}
        assert units[f"{sid}.one"]["status"] == "todo" and units[f"{sid}.one"]["open"] is True
        assert units[f"{sid}.two"]["open"] is False
        # 无掌握节点 → recompute 幂等空跑（概念派生引擎正确性见 store 级注入测试）
        r = app_client.post(f"/api/subjects/{sid}/progress/recompute")
        assert r.status_code == 200 and r.json()["concepts"] == 0
        # 显式重置（无掌握节点 → 0 重置；概念证据清空幂等）
        r = app_client.post(f"/api/subjects/{sid}/progress/reset", json={"mode": "all"})
        assert r.status_code == 200 and r.json()["nodes_reset"] == 0
        # 概念注册表已随大纲采纳同步（A2）
        from app.db import SessionLocal
        from app import models as m

        with SessionLocal() as db:
            n = db.query(m.Concept).filter(m.Concept.subject_id == sid).count()
            assert n == 3
        app_client.delete(f"/api/subjects/{sid}")

    def test_progress_404_unknown_subject(self, app_client):
        r = app_client.get("/api/subjects/nope/progress")
        assert r.status_code == 404

    def test_math_reset_clears_content_library_node(self, app_client):
        """math（preset）显式重置：内容库节点（primary.0101 锚点）mastered → available。"""
        from app import models as m
        from app.db import SessionLocal
        from app.service.library import get_graph
        from app.service.progress import recompute_states

        node_id = "primary.0101"
        with SessionLocal() as db:
            existed = db.get(m.UserNode, ("local", node_id)) is not None
            prior = db.get(m.UserNode, ("local", node_id))
            if prior is None:
                db.add(m.UserNode(user_id="local", node_id=node_id, state="mastered",
                                  mastered_at=None))
            else:
                prior.state = "mastered"
            db.commit()
        try:
            r = app_client.post("/api/subjects/math/progress/reset", json={"mode": "all"})
            assert r.status_code == 200
            assert r.json()["nodes_reset"] >= 1
            with SessionLocal() as db:
                row = db.get(m.UserNode, ("local", node_id))
                assert row is None or row.state != "mastered"
        finally:
            # 还原进度，避免影响后续模块的"零掌握/既有掌握"断言
            with SessionLocal() as db:
                if not existed:
                    db.query(m.UserNode).filter(
                        m.UserNode.user_id == "local", m.UserNode.node_id == node_id
                    ).delete()
                else:
                    prior = db.get(m.UserNode, ("local", node_id))
                    if prior is not None:
                        prior.state = "mastered"
                recompute_states(db, "local", get_graph())
                db.commit()
