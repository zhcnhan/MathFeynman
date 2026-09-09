"""Phase A A4：通用学科路径闭环 E2E（docs/14 §6 验收 · 临时示例学科，不预置正式内容）。

链路：创建自定义学科（Python 入门示例）→ AI/启发式起草大纲 → 校验/采纳 → 地图（进度视图：
首单元开放、后链锁定）→ 懒生成单元内容（source:auto）→ 大纲门禁 409（越级 start 被拒）→
依序达成（内容节点 mastered → 概念证据实时更新）→ 后链解锁 → 大纲重生成（结构重组）→
概念/节点双轨进度不丢（等效/保持达成）。

（交互式"练习→费曼评估"为真人浏览器验收项（docs/11 惯例）；本 E2E 以服务层"达成 + 概念证据
派生"确定性闭环覆盖引擎侧，机制与 math 侧 R18 测试同口径。）
"""
from __future__ import annotations

import uuid

import pytest

from app import models
from app.db import SessionLocal
from app.service.library import get_graph
from app.service.progress import mark_mastered


@pytest.fixture(scope="module")
def cleanup_sids():
    sids: list[str] = []
    yield sids
    # 清理 DB 行（内容 *_auto 文件由 conftest 模块级钩子统一清除）
    with SessionLocal() as db:
        for sid in sids:
            node_ids = {
                nid
                for (nid,) in db.query(models.Node.id)
                .filter(models.Node.id.like(f"{sid}.%"))
                .all()
            }
            if node_ids:
                db.query(models.UserConcept).filter(
                    models.UserConcept.subject_id == sid
                ).delete(synchronize_session=False)
                db.query(models.Review).filter(
                    models.Review.node_id.in_(node_ids)
                ).delete(synchronize_session=False)
                db.query(models.UserNode).filter(
                    models.UserNode.node_id.in_(node_ids)
                ).delete(synchronize_session=False)
                db.query(models.Session).filter(
                    models.Session.node_id.in_(node_ids)
                ).delete(synchronize_session=False)
                db.query(models.Node).filter(models.Node.id.in_(node_ids)).delete(
                    synchronize_session=False
                )
            db.query(models.Concept).filter(
                models.Concept.subject_id == sid
            ).delete(synchronize_session=False)
            subj = db.get(models.Subject, sid)
            if subj is not None:
                db.delete(subj)
        db.commit()


def _new_sid(prefix="pydemo") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _adopt(app_client, sid: str, units: list[dict], source: str = "heuristic") -> dict:
    r = app_client.put(f"/api/subjects/{sid}/outline",
                       json={"units": units, "status": "active", "source": source})
    assert r.status_code == 200, r.text
    return r.json()


def _master_node(node_id: str) -> None:
    with SessionLocal() as db:
        # Node 行已由生成后的 sync_content 建好；mark_mastered 触发状态重算 + 概念证据刷新
        mark_mastered(db, "local", node_id, get_graph())
        db.commit()


def _progress(app_client, sid: str) -> dict:
    r = app_client.get(f"/api/subjects/{sid}/progress")
    assert r.status_code == 200
    return {u["id"]: u for u in r.json()["units"]}, r.json()


def _generate(app_client, sid: str, unit: str) -> dict:
    r = app_client.post(f"/api/subjects/{sid}/units/{unit}/content")
    assert r.status_code == 200, r.text
    return r.json()


class TestGenericSubjectLoop:
    def test_full_loop(self, app_client, cleanup_sids):
        sid = _new_sid()
        cleanup_sids.append(sid)
        # 1) 创建自定义学科
        r = app_client.post("/api/subjects", json={
            "label": "Python 入门", "subject_id": sid, "description": "临时示例学科（验收用，不预置）"})
        assert r.status_code == 201
        # 2) 起草（无 key 环境 = 启发式候选；不落盘）
        r = app_client.post(f"/api/subjects/{sid}/outline/draft",
                            json={"brief": "零基础学 Python", "count": 4, "group_hint": "主线"})
        assert r.status_code == 200
        cand = r.json()
        assert cand["ok"] is True and len(cand["units"]) == 4
        assert cand["source"] in ("ai", "heuristic")
        # 3) 采纳 → revision 1（active）
        outline = _adopt(app_client, sid, cand["units"])
        assert outline["revision"] == 1 and len(outline["units"]) == 4
        # 4) 地图（进度视图）：u01 开放，u02-u04 未开放（线性链）
        units, view = _progress(app_client, sid)
        assert units[f"{sid}.u01"]["open"] is True
        for i in (2, 3, 4):
            assert units[f"{sid}.u{i:02d}"]["open"] is False, f"u{i} 不应在 u01 达成前开放"
        # 5) 懒生成单元内容（学到哪条生成哪条：先试生成 u02 内容验证门禁）
        assert _generate(app_client, sid, f"{sid}.u02")["status"] == "created"
        # 6) 越级 start → 大纲门禁 409（invalid_state）
        r = app_client.post("/api/session/start", json={"node_id": f"{sid}.u02"})
        assert r.status_code == 409, r.text
        # 7) 依序达成 u01（内容生成 + 掌握）
        assert _generate(app_client, sid, f"{sid}.u01")["status"] == "created"
        assert _generate(app_client, sid, f"{sid}.u01")["status"] == "exists"  # 懒生成幂等
        _master_node(f"{sid}.u01")
        # 概念证据已实时派生（等效判定数据源）
        with SessionLocal() as db:
            n = db.query(models.UserConcept).filter(
                models.UserConcept.user_id == "local",
                models.UserConcept.subject_id == sid,
            ).count()
            assert n >= 1
        # 8) u02 解锁 → start 200（可学）；u03 仍锁
        units, _ = _progress(app_client, sid)
        assert units[f"{sid}.u02"]["open"] is True
        r = app_client.post("/api/session/start", json={"node_id": f"{sid}.u02"})
        assert r.status_code == 200, r.text
        session_id = r.json()["session"]["id"]
        assert session_id
        # 9) 大纲重生成（结构重组：u01 → u01b 改名，标签保留，后链引用同步）→ 进度不丢
        renamed = []
        for u in cand["units"]:
            nu = dict(u)
            if nu["id"] == f"{sid}.u01":
                nu["id"] = f"{sid}.u01b"
                nu["title"] = nu["title"] + "（重组）"
            nu["prereqs"] = [
                f"{sid}.u01b" if p == f"{sid}.u01" else p for p in nu["prereqs"]
            ]
            renamed.append(nu)
        outline2 = _adopt(app_client, sid, renamed)
        assert outline2["revision"] == 2
        units2, _ = _progress(app_client, sid)
        # u01b：概念命中（已掌握标签）→ 等效已掌握；其后 u02 仍开放（前置等效=达成，不卡链）
        assert units2[f"{sid}.u01b"]["status"] == "equivalent"
        assert units2[f"{sid}.u01b"]["open"] is False
        assert units2[f"{sid}.u02"]["open"] is True
        # 原内容节点 u01 仍 mastered（节点级进度本来就不丢）
        with SessionLocal() as db:
            row = db.get(models.UserNode, ("local", f"{sid}.u01"))
            assert row is not None and row.state == "mastered"
        # 10) 重置学科进度（显式）：概念与学科内容掌握清空 → 重生成后的单元回到未达成
        r = app_client.post(f"/api/subjects/{sid}/progress/reset", json={"mode": "all"})
        assert r.status_code == 200
        assert r.json()["nodes_reset"] >= 1
        units3, view3 = _progress(app_client, sid)
        assert view3["concepts_mastered"] == 0
        assert units3[f"{sid}.u01b"]["status"] == "todo"  # 重置后不再等效

    def test_start_locked_out_of_order_409_math_unaffected(self, app_client, cleanup_sids):
        """对比：math 内容（primary.0101 锚点）仍走 roadmap 门禁（回归红线不受通用改造影响）。"""
        sid = _new_sid("q")
        cleanup_sids.append(sid)
        r = app_client.post("/api/subjects", json={"label": "Q", "subject_id": sid})
        assert r.status_code == 201
        # 通用大纲 1 单元，无前置
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": [
                               {"id": f"{sid}.q1", "title": "Q1", "group": "g1",
                                "objectives": ["o"], "concept_tags": ["甲"]},
                           ], "status": "active", "source": "manual"})
        assert r.status_code == 200
        assert _generate(app_client, sid, f"{sid}.q1")["status"] == "created"
        # 通用节点可学（无前置）
        r = app_client.post("/api/session/start", json={"node_id": f"{sid}.q1"})
        assert r.status_code == 200, r.text
