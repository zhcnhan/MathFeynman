"""Phase C C4：PUT /subjects/{sid}/outline 偶发 405 复查（R23 B5 #5 留档）。

背景：B5 测试期偶见 PUT outline 405，其它模块/进程不可复现（当时以 store 落盘规避）。
复查结论：路由注册顺序健康（subjects 路由内 GET/PUT 同路径并存，FastAPI 按方法分派；
api 内无重复 /subjects/* 前缀路由）；本环境无法复现 405。以 **live 行为**锁定回归：
① PUT outline 必须可达（缺失即 404/405 而非 200）；② 反复采纳/整份重生成 outline 全 200。
若日后复现：查代理/中间层改写方法，或 Starlette 对 method-not-allowed 的处理时机。
"""
from __future__ import annotations

import uuid

from fastapi.routing import APIRoute


def _sid() -> str:
    return f"p405{uuid.uuid4().hex[:6]}"


def _mk_units(prefix: str, n: int):
    units = []
    for i in range(1, n + 1):
        units.append({
            "id": f"{prefix}.u{i:02d}", "title": f"单元 {i}", "group": "主线",
            "objectives": [f"掌握第 {i} 讲"], "concept_tags": [f"概念{i}"],
            "prereqs": [f"{prefix}.u{i - 1:02d}"] if i > 1 else [],
        })
    return units


def _walk_routes(routes):
    """递归展开 include_router 的嵌套路由（FastAPI 以 _IncludedRouter 承载子路由）。"""
    for route in routes:
        subs = getattr(route, "routes", None)
        if subs:
            yield from _walk_routes(subs)
        elif isinstance(route, APIRoute):
            yield route


def test_put_outline_route_registered_in_openapi():
    """OpenAPI 契约：PUT outline 路径已在 API 声明（注册缺失 → 不在 schema 中）。"""
    from app.main import app

    schema = app.openapi()
    path_item = schema["paths"].get("/api/subjects/{subject_id}/outline")
    assert path_item is not None, "PUT outline 未注册（openapi 缺失该路径）"
    assert "put" in path_item, path_item.keys()
    assert "get" in path_item  # GET/PUT 同路径并存（方法分派健康）


def test_repeated_put_outline_flow_no_405(app_client):
    """反复采纳/整份重生成 outline（模拟 B5 405 场景）：PUT 始终 200，无 405。"""
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": "P405", "subject_id": sid})
    assert r.status_code == 201
    try:
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": _mk_units(sid, 3), "status": "active", "source": "manual"})
        assert r.status_code == 200 and r.json()["revision"] == 1
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": _mk_units(sid, 4), "status": "active", "source": "ai"})
        assert r.status_code == 200 and r.json()["revision"] == 2
        # GET 同路径不因 PUT 存在而失效
        assert app_client.get(f"/api/subjects/{sid}/outline").status_code == 200
        # 校验端点（同路径前缀不同动作）正常
        r = app_client.post(f"/api/subjects/{sid}/outline/validate",
                            json={"units": _mk_units(sid, 5)})
        assert r.status_code == 200 and r.json()["ok"] is True
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")
