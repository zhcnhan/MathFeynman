"""Phase B · B3：内容来源策略 + 材料层（docs/14 §8 · 离线可测）。

覆盖：source_policy 默认 ai 可切换；本地上传/列表/摘要；search 无网提示；select 勾选入库；
生成端点注入引用摘要（存在性校验）；math（preset）同样支持策略与材料；停用学科材料/策略被拒。
"""
from __future__ import annotations

import uuid

from app.outline import materials as mat


def _sid(prefix="mat") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label="材料学", prefix="mat"):
    sid = _sid(prefix)
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


class TestMaterials:
    def test_policy_default_and_switch(self, app_client):
        sid = _mk_subject(app_client)
        try:
            r = app_client.get(f"/api/subjects/{sid}/policy")
            assert r.json()["source_policy"] == "ai"
            for p in ("import", "web", "mixed", "ai"):
                r = app_client.put(f"/api/subjects/{sid}/policy",
                                   json={"source_policy": p})
                assert r.status_code == 200 and r.json()["source_policy"] == p
            r = app_client.put(f"/api/subjects/{sid}/policy", json={"source_policy": "magic"})
            assert r.status_code == 422
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_upload_list_summaries_and_injection_signal(self, app_client):
        sid = _mk_subject(app_client, label="行星科学")
        try:
            # 采纳大纲（store 层落盘；API PUT outline 在 outline 模块全量覆盖）
            from app.db import SessionLocal
            from app.outline import store as st
            from app.outline.schemas import OutlineUnit

            with SessionLocal() as db:
                st.add_outline(db, sid, units=[OutlineUnit(
                    id=f"{sid}.u1", title="行星定义", group="g", objectives=["o"],
                    concept_tags=["行星"])], status="active", source="manual")
            # 本地导入
            r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                                json={"title": "行星科学教材第一章",
                                      "text": "行星是围绕恒星运行且自身不能发光的较大天体。……"})
            assert r.status_code == 201, r.text
            mid = r.json()["id"]
            r = app_client.get(f"/api/subjects/{sid}/materials")
            assert any(m["id"] == mid for m in r.json()["materials"])
            # search（离线 → 明确提示，无网不崩）
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "行星"})
            assert r.status_code == 200 and r.json()["items"] == []
            assert "联网检索" in r.json()["note"]
            # select（候选勾选 → 本地化引用入库）
            r = app_client.post(f"/api/subjects/{sid}/materials/select",
                                json={"items": [
                                    {"title": "行星条目", "url": "https://example.org/planet",
                                     "source": "示例网", "summary": "行星绕恒星运行；八大行星分两类。"},
                                ]})
            assert r.status_code == 201 and len(r.json()["saved"]) == 1
            # 摘要可被生成端点注入（不崩；AI 时用于起草上下文）
            r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u1/content")
            assert r.status_code == 200, r.text
            assert r.json()["status"] in ("created", "exists")
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_math_preset_policy_and_materials_supported(self, app_client):
        """math（preset）同样支持策略与材料（docs/14 §8：不独特）。"""
        r = app_client.put("/api/subjects/math/policy", json={"source_policy": "mixed"})
        assert r.status_code == 200
        r = app_client.post("/api/subjects/math/materials/upload",
                            json={"title": "数学史补充", "text": "分数起源于度量与分配。……"})
        assert r.status_code == 201, r.text
        r = app_client.get("/api/subjects/math/materials")
        assert len(r.json()["materials"]) >= 1
        # 复原默认（避免影响其它用例语义判定——策略默认 ai 不改变功能）
        app_client.put("/api/subjects/math/policy", json={"source_policy": "ai"})
        from app.db import SessionLocal

        with SessionLocal() as db:
            for m in mat.list_materials(db, "math"):
                mat.delete_material(db, "math", m["id"])
            db.commit()

    def test_disabled_subject_policy_materials_409(self, app_client):
        sid = _mk_subject(app_client)
        app_client.delete(f"/api/subjects/{sid}")  # soft 停用
        try:
            assert app_client.get(f"/api/subjects/{sid}/policy").status_code == 409
            r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                                json={"title": "x", "text": "y"})
            assert r.status_code == 409
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")
