"""Phase C · C3：学科停用过滤（视觉层 subject.enabled · docs/14 §9 / R23 B4#2/#3）。

覆盖（引擎 409 之外的 API/数据层隐藏，前端消费这些数据实现 UI 一致）：
- 停用 custom 学科：其内容节点从 /graph 消失、不进 /dashboard 推荐/统计；
- 停用 math（预置）：图谱/关卡地图/仪表盘不再展示学段内容、越级 start 409；
- math 停用后**清进度**（锚点节点 user_nodes 行被清，docs/14 §9"移除=清进度"对 preset 成立）；
- 复习到期队列对停用学科节点隐藏（一致性兜底）；
- 重新启用后恢复可见/可学（UI 入口在学科列表"已移除"分组）。
"""
from __future__ import annotations

import uuid

import pytest

from app import models
from app.db import SessionLocal
from app.service.library import get_graph
from app.service.progress import mark_mastered

_MATH_PREFIXES = ("primary", "middle", "high", "college", "ai")


def _sid(prefix="vis") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_custom(app_client, prefix="vis") -> str:
    sid = _sid(prefix)
    r = app_client.post("/api/subjects", json={"label": "可见性", "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _adopt_unit(app_client, sid: str) -> None:
    uid = f"{sid}.u1"
    r = app_client.put(f"/api/subjects/{sid}/outline",
                       json={"units": [
                           {"id": uid, "title": "U1", "group": "g1",
                            "objectives": ["目标"], "concept_tags": ["甲"]},
                       ], "status": "active", "source": "manual"})
    assert r.status_code == 200, r.text


def _gen(app_client, sid: str) -> None:
    r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u1/content")
    assert r.status_code == 200 and r.json()["status"] == "created", r.text


def _master(node_id: str) -> None:
    with SessionLocal() as db:
        mark_mastered(db, "local", node_id, get_graph())
        db.commit()


def _graph_node_ids(app_client) -> set[str]:
    return {n["id"] for n in app_client.get("/api/graph").json()["nodes"]}


class TestDisabledCustomSubjectHidden:
    def test_soft_remove_custom_hides_from_graph_and_dashboard(self, app_client):
        sid = _mk_custom(app_client)
        try:
            _adopt_unit(app_client, sid)
            _gen(app_client, sid)
            _master(f"{sid}.u1")
            # 基线：内容在图中可见
            assert f"{sid}.u1" in _graph_node_ids(app_client)
            # soft 停用 → 图谱隐藏、仪表盘推荐不含它
            assert app_client.delete(f"/api/subjects/{sid}").status_code == 204
            assert f"{sid}.u1" not in _graph_node_ids(app_client)
            dash = app_client.get("/api/dashboard").json()
            rec = dash["recommended_node"]
            assert rec is None or rec["id"] != f"{sid}.u1"
            # 重新启用 → 恢复可见
            assert app_client.post(f"/api/subjects/{sid}/enable").status_code == 200
            assert f"{sid}.u1" in _graph_node_ids(app_client)
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")


class TestDisabledMathHidden:
    def _math_visible(self, app_client) -> bool:
        return any(n.startswith(p + ".") for p in _MATH_PREFIXES for n in _graph_node_ids(app_client))

    def test_math_soft_remove_hides_map_graph_and_blocks_start(self, app_client):
        assert self._math_visible(app_client)  # 前置：math 内容可见
        # 预置一个已掌握节点（验证"停用=清进度"对 preset 同样成立）
        _master("primary.0101")
        with SessionLocal() as db:
            assert db.get(models.UserNode, ("local", "primary.0101")) is not None

        r = app_client.delete("/api/subjects/math")
        assert r.status_code == 204
        try:
            assert app_client.get("/api/subjects/math").status_code == 404
            # 图谱/关卡地图/仪表盘全部不再展示 math（含锚点/auto）
            assert not self._math_visible(app_client)
            nodes_visible = sum(len(lv["groups"]) for lv in
                                app_client.get("/api/campaign").json()["levels"])
            assert nodes_visible == 0
            # 学习越级 → 引擎 409（内容文件仍在，门禁分流）
            r = app_client.post("/api/session/start", json={"node_id": "primary.0101"})
            assert r.status_code == 409, r.text
            # 停用=清进度：math 内容节点的掌握行被清（docs/14 §9 对 preset 成立）
            with SessionLocal() as db:
                assert db.get(models.UserNode, ("local", "primary.0101")) is None
            # 到期复习队列不展示停用学科节点（math 停用时不应出现 primary.* 到期项）
            queue = app_client.get("/api/review/queue").json()["due"]
            assert all(not d["node_id"].startswith("primary.") for d in queue)
        finally:
            # 重新启用恢复：math 内容回到图谱/地图
            assert app_client.post("/api/subjects/math/enable").status_code == 200
            assert app_client.get("/api/subjects/math").status_code == 200
            assert self._math_visible(app_client)

    def test_math_due_review_row_hidden_when_disabled(self, app_client):
        """停用期间即使残留到期行，复习队列按 subject.enabled 隐藏（视觉层兜底）。"""
        assert app_client.delete("/api/subjects/math").status_code == 204
        try:
            import datetime as dt

            from app.service.review import _naive

            with SessionLocal() as db:
                row = db.get(models.Review, ("local", "primary.0102"))
                if row is None:
                    row = models.Review(user_id="local", node_id="primary.0102")
                    db.add(row)
                row.due_at = _naive(dt.datetime.now(dt.timezone.utc))
                db.commit()
            queue = app_client.get("/api/review/queue").json()["due"]
            assert all(d["node_id"] != "primary.0102" for d in queue)
        finally:
            with SessionLocal() as db:
                db.query(models.Review).filter(
                    models.Review.user_id == "local", models.Review.node_id == "primary.0102"
                ).delete()
                db.commit()
            app_client.post("/api/subjects/math/enable")
