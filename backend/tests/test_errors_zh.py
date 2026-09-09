"""docs/13 §2：对外错误中文化抽查（test_errors_zh）。

覆盖各层典型错误，断言：
- 响应体为仓库约定结构 {"detail": {"error": {code,message}}}，message 含中文字符；
- message 不含英文堆栈（Traceback/File …/raise 等）；
- 后端缺失文案/未捕获异常 → 中文兜底（500 mock 等）。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter

# 500 mock 需要注册一条会抛异常的测试路由（用完即卸）
_TEST_500_PATH = "/api/__test_zh_500__"


def _err_of(body: dict) -> dict:
    assert "detail" in body and "error" in body["detail"], body
    return body["detail"]["error"]


def _assert_zh_error(body: dict, *, code: str = "") -> dict:
    err = _err_of(body)
    if code:
        assert err["code"] == code, body
    assert isinstance(err["message"], str) and err["message"], body
    assert any("\u4e00" <= ch <= "\u9fff" for ch in err["message"]), f"message 缺中文: {err}"
    for token in ("Traceback", 'File "', "  File ", " raise ", "ValueError:", "HTTPException"):
        assert token not in err["message"], f"message 泄漏英文堆栈: {err}"
    return err


def test_404_unknown_subject_zh(app_client):
    r = app_client.get("/api/subjects/no_such_subject_xyz")
    assert r.status_code == 404
    assert _assert_zh_error(r.json(), code="not_found")


def test_404_unknown_route_zh(app_client):
    """未知路径（Starlette 默认 404）→ 统一中文结构（不得裸显 Not Found）。"""
    r = app_client.get("/api/definitely-not-a-route-xyz")
    assert r.status_code == 404
    err = _assert_zh_error(r.json(), code="not_found")
    assert "Not Found" not in err["message"]


def test_409_invalid_state_zh(app_client):
    """大纲门禁 409（越级 start）→ 中文提示（当前节点尚未解锁）。"""
    sid = f"zhe{uuid.uuid4().hex[:6]}"
    app_client.post("/api/subjects", json={"label": "Z", "subject_id": sid})
    app_client.put(
        f"/api/subjects/{sid}/outline",
        json={
            "units": [
                {"id": f"{sid}.u01", "title": "一", "group": "g", "objectives": ["o"], "concept_tags": ["甲"]},
                {"id": f"{sid}.u02", "title": "二", "group": "g", "objectives": ["o"],
                 "concept_tags": ["乙"], "prereqs": [f"{sid}.u01"]},
            ],
            "status": "active", "source": "manual",
        },
    )
    try:
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u02/content")
        assert r.status_code == 200, r.text
        r = app_client.post("/api/session/start", json={"node_id": f"{sid}.u02"})
        assert r.status_code == 409
        _assert_zh_error(r.json(), code="invalid_state")
    finally:
        app_client.delete(f"/api/subjects/{sid}")
        from app import models as m
        from app.db import SessionLocal

        with SessionLocal() as db:
            ids = [x[0] for x in db.query(m.Node.id).filter(m.Node.id.like(f"{sid}.%")).all()]
            for nid in ids:
                db.query(m.UserNode).filter(m.UserNode.node_id == nid).delete()
                db.query(m.Session).filter(m.Session.node_id == nid).delete()
                db.query(m.Node).filter(m.Node.id == nid).delete()
            db.commit()


def test_422_request_validation_zh(app_client):
    """FastAPI 入参校验失败（类型错误/缺字段）→ 中文（字段中文名 + 类型规则）。"""
    r = app_client.post("/api/subjects", json={"label": 123})
    assert r.status_code == 422
    _assert_zh_error(r.json(), code="validation_error")
    r = app_client.post("/api/subjects", json={})
    assert r.status_code == 422
    err = _assert_zh_error(r.json(), code="validation_error")
    assert "学科名称" in err["message"] or "label" in err["message"], err
    r = app_client.post("/api/session/start", json={"node_id": 123})
    assert r.status_code == 422
    _assert_zh_error(r.json(), code="validation_error")


def test_422_manual_unit_payload_zh(app_client):
    """手动构造 OutlineUnit 校验失败（业务层 422）→ 中文提示。"""
    sid = f"zhp{uuid.uuid4().hex[:6]}"
    app_client.post("/api/subjects", json={"label": "P", "subject_id": sid})
    try:
        r = app_client.put(
            f"/api/subjects/{sid}/outline",
            json={"units": [{"id": f"{sid}.u01", "group": "g"}], "status": "active", "source": "manual"},
        )
        assert r.status_code == 422
        _assert_zh_error(r.json(), code="validation_error")
    finally:
        app_client.delete(f"/api/subjects/{sid}")


def test_500_unhandled_zh():
    """未捕获异常 → 500 中文（类别 + 查日志），不暴露 traceback/英文类名。

    用独立 TestClient（raise_server_exceptions=False）验证服务端 500 语义
    （共享 app_client 默认在未捕获异常时向测试进程抛错，非产品行为）。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    def boom():
        raise ValueError("secret-internal-detail-english")

    tmp = APIRouter()
    tmp.post(_TEST_500_PATH)(boom)
    app.include_router(tmp)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(_TEST_500_PATH)
            assert r.status_code == 500
            err = _assert_zh_error(r.json(), code="internal_error")
            assert "服务器内部错误" in err["message"]
            assert "secret-internal-detail-english" not in str(r.json())
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes
            if not getattr(r, "path", "").startswith(_TEST_500_PATH)
        ]
