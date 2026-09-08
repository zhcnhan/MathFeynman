"""docs/10 §3、docs/11 子步 9：纠错反馈闭环测试。"""
from __future__ import annotations

import pytest

from app.db import SessionLocal, init_db
from app.service import feedback as fb


def _fresh():
    init_db()


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
        result = fb.regenerate(db, "local", fid)
        assert result["action"] == "manual_only"  # 人工内容不自动覆盖
        db.commit()
        item = next(i for i in fb.list_feedback(db, "local") if i["id"] == fid)
        assert item["status"] == "reviewed"


def test_regenerate_missing_raises():
    _fresh()
    with SessionLocal() as db:
        with pytest.raises(KeyError):
            fb.regenerate(db, "local", 999999)
