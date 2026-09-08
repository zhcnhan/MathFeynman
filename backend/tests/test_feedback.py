"""docs/10 §3、docs/11 子步 9 + 工单 B 段：纠错反馈闭环与"重生成替换"消费管线测试。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app import models as m
from app.content import content_root, stages_dir
from app.db import SessionLocal, init_db
from app.service import feedback as fb
from app.service.library import refresh_library


def _fresh():
    init_db()


def _gen_auto_node() -> str:
    """在内容库生成一条 primary auto 节点（primary.s22 数与运算），返回节点 id。"""
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap

    roadmap = load_roadmap("primary")
    res = pl.generate_sequence(roadmap, ["primary.s22"])[0]
    assert res.status == "ok", res.errors
    refresh_library()
    return "primary.s22"


def _auto_path(node_id: str) -> Path:
    fn = f"node_{node_id.replace('.', '_')}_auto.md"
    for cand in [content_root() / "_drafts" / fn, *(stages_dir().rglob(fn))]:
        if cand.exists():
            return Path(cand)
    raise AssertionError(f"找不到 {node_id} 生成文件")


def _cleanup(node_id: str) -> None:
    for p in [_auto_path(node_id)]:
        p.unlink(missing_ok=True)
    with SessionLocal() as db:
        db.query(m.Feedback).filter(m.Feedback.node_id == node_id).delete(synchronize_session=False)
        db.query(m.Edge).filter((m.Edge.node_id == node_id) | (m.Edge.prereq_id == node_id)).delete(synchronize_session=False)
        db.query(m.UserNode).filter(m.UserNode.node_id == node_id).delete(synchronize_session=False)
        db.query(m.Node).filter(m.Node.id == node_id).delete(synchronize_session=False)
        db.commit()
    refresh_library()


def test_record_list_and_source():
    _fresh()
    with SessionLocal() as db:
        r1 = fb.record(db, "local", node_id="middle.0101", kind="lecture", message="讲解里符号写反了")
        r2 = fb.record(db, "local", node_id="middle.0102", kind="exercise", message="题目答案有误", exercise_id="ex1")
        assert r1["status"] == "pending" and r1["source"] == "human"
        db.commit()
        items = fb.list_feedback(db, "local", status="pending")
        assert len(items) >= 2
        kinds = {i["kind"] for i in items}
        assert {"lecture", "exercise"} <= kinds
        assert all(i["status"] == "pending" for i in items)


def test_regenerate_human_node_marks_only():
    _fresh()
    with SessionLocal() as db:
        rec = fb.record(db, "local", node_id="middle.0101", kind="content", message="再核对一遍")
        db.commit()
        fid = rec["id"]
        result = fb.regenerate(db, "local", fid, wait=True)
        assert result["action"] == "manual_only"  # 人工内容不自动覆盖
        db.commit()
        item = next(i for i in fb.list_feedback(db, "local") if i["id"] == fid)
        assert item["status"] == "reviewed"


def test_regenerate_missing_raises():
    _fresh()
    with SessionLocal() as db:
        with pytest.raises(KeyError):
            fb.regenerate(db, "local", 999999)


# ---------------------------------------------------------------------------
# 工单 B 段：auto 节点"重生成替换"消费管线
# ---------------------------------------------------------------------------

def test_auto_regen_success_atomic_replace_and_clear():
    _fresh()
    node_id = _gen_auto_node()
    try:
        path = _auto_path(node_id)
        with SessionLocal() as db:
            rec = fb.record(db, "local", node_id=node_id, kind="content", message="这个讲解不对，请重写")
            db.commit()
            fid = rec["id"]

            def drafter(entry, errors=None):
                raw = __import__("app.content.pipeline", fromlist=["stub_drafter"]).stub_drafter(entry)
                return raw.replace(f"title: {entry.title}", f"title: {entry.title}（重生成版）", 1)

            result = fb.regenerate(db, "local", fid, wait=True, drafter=drafter)
            db.commit()
        assert result["action"] == "regenerated", result
        assert "重生成版" in path.read_text(encoding="utf-8")  # 文件已原子替换
        with SessionLocal() as db:
            items = {i["id"]: i for i in fb.list_feedback(db, "local", node_id=node_id)}
            it = items[fid]
            assert it["status"] == "regenerated" and "已自动重生成替换" in it["result"]
            row = db.get(m.Node, node_id)
            assert row is not None and "重生成版" in row.title  # 库内节点已随内容刷新
    finally:
        _cleanup(node_id)


def test_auto_regen_failed_keeps_original():
    _fresh()
    node_id = _gen_auto_node()
    try:
        path = _auto_path(node_id)
        before = hashlib.md5(path.read_bytes()).hexdigest()
        with SessionLocal() as db:
            rec = fb.record(db, "local", node_id=node_id, kind="lecture", message="请修正")
            db.commit()
            fid = rec["id"]

            def bad_drafter(entry, errors=None):
                return "这不是合法节点（缺 front-matter）"

            result = fb.regenerate(db, "local", fid, wait=True, drafter=bad_drafter)
            db.commit()
        assert result["action"] == "failed", result
        assert result.get("errors"), result
        assert hashlib.md5(path.read_bytes()).hexdigest() == before  # 原内容保留
        with SessionLocal() as db:
            it = fb.list_feedback(db, "local", node_id=node_id)[0]
            assert it["status"] == "failed" and it["result"]
    finally:
        _cleanup(node_id)


def test_auto_regen_without_key_marks_failed_no_stub():
    """未配 LLM_API_KEY（conftest 默认空）：不回落 stub 占位，保留原内容记 failed。"""
    _fresh()
    node_id = _gen_auto_node()
    try:
        path = _auto_path(node_id)
        before = hashlib.md5(path.read_bytes()).hexdigest()
        with SessionLocal() as db:
            rec = fb.record(db, "local", node_id=node_id, kind="exercise", message="题目要改")
            db.commit()
            fid = rec["id"]
            result = fb.regenerate(db, "local", fid, wait=True)  # drafter=None → make_ai_drafter()=None
            db.commit()
        assert result["action"] == "failed", result
        assert "LLM_API_KEY" in result["message"]
        assert hashlib.md5(path.read_bytes()).hexdigest() == before
    finally:
        _cleanup(node_id)
