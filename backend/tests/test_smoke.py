"""骨架冒烟测试：DB 建表 + API 可达 + content 深校验门。

（内容库状态随里程碑变化，此处只断言结构与不变量，不断言具体数量。）
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app import models
from app.content.cli import validate_library
from app.main import app


@pytest.fixture()
def tmp_db(tmp_path: Path):
    """用临时 SQLite 库建表，避免污染默认库。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'smoke.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_create_all_tables(tmp_db: Session):
    inspector = inspect(tmp_db.bind)
    expected = {
        "users",
        "nodes",
        "edges",
        "user_nodes",
        "sessions",
        "attempts",
        "reviews",
        "ai_logs",
        "relearn_logs",
    }
    assert expected <= set(inspector.get_table_names())


def test_api_health_and_shapes(app_client):
    c = app_client
    assert c.get("/api/health").json()["ok"] is True

    d = c.get("/api/dashboard")
    assert d.status_code == 200
    body = d.json()
    for k in ("recommended_node", "due_reviews", "breakpoints", "stats"):
        assert k in body
    for k in ("mastered", "learning", "available", "locked", "consecutive_days", "today_done"):
        assert isinstance(body["stats"][k], int)

    g = c.get("/api/graph")
    assert g.status_code == 200
    gb = g.json()
    assert "nodes" in gb and "edges" in gb
    for n in gb["nodes"]:
        for k in ("id", "title", "level", "topic", "state"):
            assert k in n
    for e in gb["edges"]:
        assert {"node", "prereq"} <= set(e)


def test_content_validate_current_library():
    # 内容库必须通过深校验：结构/环/模板可渲染/答案可验算（docs/04 §7）
    report = validate_library()
    assert report.ok is True
    assert report.nodes_loaded >= 0
    assert report.exercises_checked >= 0
