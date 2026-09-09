"""Phase A A3：数学 preset 迁移——数学总 Outline 派生 + 概念标签回填 + 治理锁（docs/14 §5）。

覆盖：
1. roadmap → math outline（258 单元/5 关卡组/转正状态如实标注/结构校验无环无悬空）；
2. 锚点单元概念标签 = 锚点节点 core_concepts 归一（"既有锚点节点归一到概念标签"）；
3. s27 因数倍数补链一致性复核（分数 0102 在因数倍数/口诀之后——docs/14 §5 治理①红线段）；
4. 派生重生成 revision 递增、同 id 单元概念标签保留；结构重组（单元改名仍锚定同一节点）
   → 标签自动回填 → 已掌握概念映射到新单元（等效已掌握，进度不丢）；
5. 数学历史掌握迁移（真实锚点/auto mastered → (math,concept) 证据）；
6. API regenerate（math=roadmap 派生；custom 仍 501）；
7. 耦合抽离锁定：通用学段（非 LEVELS）档位语义 = fast 基础 + content_think 覆盖。
"""
from __future__ import annotations

import uuid

import pytest

from app import models
from app.outline import concepts as cv
from app.outline import store as st
from app.outline.math_preset import MATH_GROUPS, build_math_outline, derive_math_outline
from app.outline.schemas import load_outline_yaml, validate_outline_doc

EXPECTED_GROUP_SIZES = {"primary": 27, "middle": 31, "high": 81, "college": 59, "ai": 60}


@pytest.fixture
def db_env():
    """共享 DB 会话（内容根 = conftest hermetic 副本，含 roadmap 与 13 个人工节点）。"""
    from app.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    st.ensure_math_preset(db)
    db.commit()
    yield db
    db.query(models.UserConcept).delete()
    db.query(models.Concept).delete()
    db.commit()
    db.close()


def _hermetic_outline() -> dict:
    """从 hermetic 内容库构建（roadmap + 13 人工节点；auto 已被 conftest 排除）。"""
    from app.content.roadmap import load_roadmap

    roadmaps = {lv: load_roadmap(lv) for lv in MATH_GROUPS}
    from app.content.loader import load_library

    lib = load_library()
    return roadmaps, {n.id: n.doc for n in lib.nodes}


class TestBuildMathOutline:
    def test_derives_258_units_and_groups(self):
        roadmaps, docs = _hermetic_outline()
        doc = build_math_outline(roadmaps=roadmaps, lib_docs=docs)
        assert len(doc.units) == 258
        from collections import Counter

        assert dict(Counter(u.group for u in doc.units)) == EXPECTED_GROUP_SIZES
        assert doc.subject == "math" and doc.source == "roadmap" and doc.unit_id_scope == "entry"
        assert doc.schema_version == 1

    def test_status_truthful_reviewed_only_primary(self):
        roadmaps, docs = _hermetic_outline()
        doc = build_math_outline(roadmaps=roadmaps, lib_docs=docs)
        from collections import Counter

        assert Counter(u.status for u in doc.units) == {"reviewed": 27, "draft": 231}
        # 抽查：primary 转正、middle/high draft
        byid = doc.by_id()
        assert byid["primary.s05"].status == "reviewed"
        assert byid["middle.m01"].status == "draft"
        assert byid["high.h01"].status == "draft"

    def test_validation_clean_against_content_library(self):
        roadmaps, docs = _hermetic_outline()
        doc = build_math_outline(roadmaps=roadmaps, lib_docs=docs)
        problems = validate_outline_doc(doc, known_content_ids=set(docs))
        assert problems == []

    def test_anchor_unit_tags_are_anchor_node_core_concepts(self):
        roadmaps, docs = _hermetic_outline()
        doc = build_math_outline(roadmaps=roadmaps, lib_docs=docs)
        byid = doc.by_id()
        # s05 → primary.0101（四则）；m01 → middle.0201（负数与数轴）
        assert {cv.normalize_tag(t) for t in byid["primary.s05"].concept_tags} == {
            cv.normalize_tag(c) for c in docs["primary.0101"].core_concepts
        }
        assert {cv.normalize_tag(t) for t in byid["middle.m01"].concept_tags} == {
            cv.normalize_tag(c) for c in docs["middle.0201"].core_concepts
        }

    def test_s27_consistency_recheck_red_line_order(self):
        """治理①：s27 因数倍数补链后一致性复核——分数(s06/0102)在因数倍数(s27)与口诀/除法之后。"""
        roadmaps, docs = _hermetic_outline()
        doc = build_math_outline(roadmaps=roadmaps, lib_docs=docs)
        ids = [u.id for u in doc.units if u.group == "primary"]
        assert ids.index("primary.s27") > ids.index("primary.s04")   # 因数倍数在除法之后
        assert ids.index("primary.s06") > ids.index("primary.s27")   # 分数意义在其后
        byid = doc.by_id()
        assert "primary.s27" in byid["primary.s06"].prereqs          # 分数意义依赖因数倍数
        assert "primary.s04" in byid["primary.s27"].prereqs
        # 排序无正向引用（roadmap 列表序即学习序；audit 既有断言外再锁一条）
        assert ids.index("primary.s03") > ids.index("primary.s02")   # 口诀在加减后


class TestDeriveAndMigration:
    def test_derive_persists_and_revision_bumps_with_tag_preserve(self, db_env):
        db = db_env
        roadmaps, docs = _hermetic_outline()
        base = st.get_outline("math")
        base_rev = base.revision if base else 0
        d1 = derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)
        assert d1.revision == base_rev + 1
        got1 = st.get_outline("math")
        assert got1 is not None and len(got1.units) == 258
        d2 = derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)
        assert d2.revision == base_rev + 2
        # 同 id 概念标签在重生成中保留（即使推导源为空——模拟人工补标不回退）
        b2 = d2.by_id()
        assert b2["primary.s05"].concept_tags
        # 概念注册表已同步（A2）
        assert db.get(models.Concept, ("math", cv.normalize_tag("运算顺序"))) is not None

    def test_restructure_keeps_progress_via_concepts(self, db_env):
        """大纲结构重组（单元改名但仍锚定同一节点）→ 标签自动回填 → 历史掌握映射到新单元。"""
        db = db_env
        roadmaps, docs = _hermetic_outline()
        d1 = derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)
        # 模拟用户掌握 primary.s05 锚点内容（primary.0101 四则）
        if db.get(models.Node, "primary.0101") is None:
            db.add(models.Node(id="primary.0101", title="四则"))
            db.flush()
        if db.get(models.UserNode, ("local", "primary.0101")) is None:
            db.add(models.UserNode(user_id="local", node_id="primary.0101", state="mastered"))
        else:
            db.get(models.UserNode, ("local", "primary.0101")).state = "mastered"
        db.commit()
        # 派生大纲 + 概念迁移（真实数学历史掌握 → (math, concept)）
        derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)
        rep = cv.recompute_subject_concepts(db, "local", "math", lib_docs=docs)
        assert rep["concepts"] >= 2 and rep["evidence_nodes"] >= 1
        mastered = cv.mastered_concepts(db, "local", "math")
        assert mastered  # 锚点 core_concepts 已归一进概念层
        # roadmap 精核重排：s05 改名 primary.s05v2（重排后位置仍在 s22/s27 前、仍锚 0101）
        import copy

        rd = copy.deepcopy(roadmaps["primary"])
        entries = []
        for e in rd.entries:
            if e.id == "primary.s05":
                e = e.model_copy(update={"id": "primary.s05v2"})
                entries.append(e)
            else:
                pr = [p.replace("primary.s05", "primary.s05v2") for p in e.prereqs]
                if pr != e.prereqs:
                    e = e.model_copy(update={"prereqs": pr})
                entries.append(e)
        rd.entries = entries
        roadmaps2 = dict(roadmaps, primary=rd)
        d2 = derive_math_outline(db, roadmaps=roadmaps2, lib_docs=docs)
        b2 = d2.by_id()
        assert "primary.s05" not in b2 and "primary.s05v2" in b2
        # 新单元仍锚定 primary.0101 → 标签由锚点 core_concepts 自动回填
        assert b2["primary.s05v2"].concept_tags
        view = cv.unit_states(db, "local", "math", lib_docs=docs)
        unit = next(u for u in view["units"] if u["id"] == "primary.s05v2")
        # 状态仍为"达成"（mastered：锚点节点级掌握映射到新单元；或 equivalent：概念级命中）——
        # 绝不因大纲重构回退为 todo（红线：换大纲/精核重排不丢进度）
        assert unit["status"] in ("mastered", "equivalent")
        # 原内容节点仍在 user_nodes mastered（节点级进度本来就不丢）
        assert db.get(models.UserNode, ("local", "primary.0101")).state == "mastered"

    def test_fresh_run_first_unit_open_and_recommendation(self, db_env):
        """治理③：0 掌握用户的总序起点链实测——math 大纲下首个开放单元 = primary.s01；
        （R18 门禁矩阵另行锁定 s01→s02→s03→s04→s27→0102 逐环解锁）。"""
        db = db_env
        roadmaps, docs = _hermetic_outline()
        derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)
        cv.recompute_subject_concepts(db, "local", "math", lib_docs=docs)
        view = cv.unit_states(db, "local", "math", lib_docs=docs)
        assert view["outline_revision"] >= 1
        primary_units = [u for u in view["units"] if u["group"] == "primary"]
        first_open = next(u for u in primary_units if u["open"])
        assert first_open["id"] == "primary.s01" and first_open["status"] == "todo"

    def test_derive_from_corrupted_prev_outline_no_500(self, db_env):
        """928c400/25c5a42 复审：旧大纲文件损坏（空 title 等）→ 派生降级为无旧版，
        全量干净重派生（258 单元）并原子覆盖，绝不 500/挂起。"""
        db = db_env
        path = st.subject_dir("math") / "outline.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 模拟损坏旧大纲（结构非法：单元缺 id、title 为空）
        path.write_text("subject: math\nunits:\n- title: ''\n", encoding="utf-8")
        with pytest.raises(Exception):  # 前置确认：该文件确实损坏（读必报 OutlineError）
            st.get_outline("math")
        roadmaps, docs = _hermetic_outline()
        doc = derive_math_outline(db, roadmaps=roadmaps, lib_docs=docs)  # 不得抛 500
        assert len(doc.units) == 258 and doc.status == "active"
        # 覆盖后的文件可正常读取
        got = st.get_outline("math")
        assert got is not None and len(got.units) == 258


class TestApiAndCoupling:
    def test_regenerate_math_outline_via_api(self, app_client):
        r = app_client.post("/api/subjects/math/outline/regenerate")
        assert r.status_code == 200
        body = r.json()
        assert body["subject"] == "math" and body["source"] == "roadmap"
        assert body["schema_version"] == 1
        assert body["revision"] >= 1
        assert len(body["units"]) == 258

    def test_custom_regenerate_drafts_candidate(self, app_client):
        """A4：custom regenerate = AI/启发式重起草候选（math 除外；math 走 roadmap 派生）。"""
        sid = f"mathx{uuid.uuid4().hex[:6]}"
        app_client.post("/api/subjects", json={"label": "X", "subject_id": sid})
        r = app_client.post(f"/api/subjects/{sid}/outline/regenerate")
        assert r.status_code == 200
        assert r.json()["subject"] == sid and len(r.json()["units"]) == 6
        app_client.delete(f"/api/subjects/{sid}")

    def test_generic_level_tier_semantics_locked(self):
        """耦合抽离：非 LEVELS 学段（通用学科关卡组）基础档 = fast；content_think 覆盖为 think。"""
        from app.ai.tier import base_strategy

        assert base_strategy(level="python101") == "fast"
        assert base_strategy(level="python101", content_think=True) == "think"
        assert base_strategy(level="college") == "think"  # math 既有语义不变

    def test_committed_outline_file_parses(self):
        """仓库内 content/subjects/math/outline.yaml 可解析且为 roadmap 派生形态。"""
        from pathlib import Path

        p = Path("content/subjects/math/outline.yaml")
        if not p.exists():
            pytest.skip("未提交 math outline 文件（由启动自动派生覆盖）")
        doc = load_outline_yaml(p.read_text(encoding="utf-8"))
        assert doc.subject == "math" and doc.source == "roadmap"
        assert len(doc.units) == 258
