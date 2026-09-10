"""R30（R29 引申）：flow schema 演进的单一自愈入口 `_ensure_flow_shape`。

背景（docs/09 R29）：R27 在 `flow.feynman` 新增 `answers_done` / `followup_gap` / `ledger`，
老会话没有这些键，而分支按 `f["answers_done"]` 直接取值 → KeyError → 500（真人阻断）。
根治 = 所有"后加键"收敛到**单一自愈入口**：读会话即深度补齐默认值 + 类型校验。

覆盖三类老结构（缺键 / 错类型 / 整块缺失）：单元级（幂等、保留真实进度）+ HTTP 级（不 500）。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Session as SessionModel
from app.service.session import _ensure_flow_shape, new_flow

from test_api_flow import _reset_node
from test_feynman_v3 import (  # noqa: F401  （tests/ 非包：与既有测试同口径）
    BAD,
    NODE,
    _drive_to_feynman,
    _reset_db,
    _seed_primary_head,
    _step,
    client,
)

# R29 之前落库的老费曼块缺失的键（R27 新增）
_LEGACY_MISSING = ("answers_done", "ledger", "followup_gap")


def _load_flow(sid: str) -> dict:
    with SessionLocal() as db:
        return json.loads(json.dumps(db.get(SessionModel, sid).flow_json))


def _save_flow(sid: str, flow) -> None:
    with SessionLocal() as db:
        sess = db.get(SessionModel, sid)
        sess.flow_json = flow
        db.commit()


# --------------------------------------------------------------------------
# 单元级：三类老结构 + 幂等 + 真实进度不被覆盖
# --------------------------------------------------------------------------
def test_r30_flow_shape_missing_block_fills_defaults():
    """整块缺失：顶层 / practice / feynman / lecture_cache 一律补当前默认结构。"""
    flow = {"stage": "feynman"}  # 只有 stage（R27 之前的老结构）
    out = _ensure_flow_shape(flow)
    assert out is flow, "原地自愈并返回同一对象（调用点直接赋值落库）"
    assert set(new_flow()) <= set(out), "顶层键补齐"
    assert out["practice"] == new_flow()["practice"]
    assert out["feynman"]["answers_done"] == 0
    assert out["feynman"]["followup_gap"] is None
    assert isinstance(out["feynman"]["ledger"], dict)
    assert out["feynman"]["ledger"]["dims"] == {}
    assert out["lecture_cache"] is None
    assert out["stage"] == "feynman", "合法 stage 不被改动"


def test_r30_flow_shape_whole_flow_missing_or_wrong_type():
    """flow 整块缺失 / 非 dict → 全新默认结构（不抛异常）。"""
    assert _ensure_flow_shape(None) == new_flow()
    assert _ensure_flow_shape([]) == new_flow()
    assert _ensure_flow_shape("脏") == new_flow()


def test_r30_flow_shape_legacy_missing_keys_keeps_progress():
    """缺键（R27 前老会话）→ 补默认；已有进度（轮次/练习达标）绝不被覆盖。"""
    flow = new_flow()
    flow["stage"] = "feynman"
    flow["practice"]["passed"] = True
    flow["practice"]["streak"] = 3
    flow["feynman"]["rounds_done"] = 2
    for key in _LEGACY_MISSING:
        flow["feynman"].pop(key, None)

    out = _ensure_flow_shape(flow)
    assert out["feynman"]["answers_done"] == 0
    assert out["feynman"]["followup_gap"] is None
    assert out["feynman"]["ledger"]["gaps"] == []
    assert out["feynman"]["rounds_done"] == 2, "已有轮次保留"
    assert out["practice"]["passed"] is True and out["practice"]["streak"] == 3


def test_r30_flow_shape_wrong_types_fall_back_per_key():
    """错类型/非法取值：单键回退默认，不牵连其它字段；合法 lecture_cache 原样保留。"""
    flow = new_flow()
    flow["stage"] = 123
    flow["lecture_cache"] = "脏缓存（不是 dict）"
    flow["practice"]["streak"] = "3"
    flow["practice"]["current"] = ["脏"]
    flow["practice"]["excluded"] = {"脏": 1}
    flow["feynman"]["answers_done"] = "2"
    flow["feynman"]["last_scores"] = {"脏": 1}
    flow["feynman"]["ledger"] = []
    flow["regen_reissue_used"] = "x"
    flow["regen_think_override"] = "yes"

    out = _ensure_flow_shape(flow)
    assert out["stage"] == "explain"
    assert out["lecture_cache"] is None
    assert out["practice"]["streak"] == 0
    assert out["practice"]["current"] is None
    assert out["practice"]["excluded"] == []
    assert out["feynman"]["answers_done"] == 0
    assert out["feynman"]["last_scores"] == []
    assert out["feynman"]["ledger"]["dims"] == {}
    assert out["regen_reissue_used"] == 0
    assert out["regen_think_override"] is False

    # 合法 lecture_cache（R21）必须原样保留（否则每次响应都会重新生成讲解）
    cache = {"lecture_md": "讲义", "asks": [], "degraded": False, "strategy": "fast", "explicit": False}
    flow2 = new_flow()
    flow2["lecture_cache"] = cache
    assert _ensure_flow_shape(flow2)["lecture_cache"] == cache


def test_r30_flow_shape_is_idempotent():
    flow = {"stage": "practice", "practice": {"streak": "脏"}}
    once = json.loads(json.dumps(_ensure_flow_shape(flow)))
    twice = json.loads(json.dumps(_ensure_flow_shape(flow)))
    assert once == twice, "自愈必须幂等（可重复调用、结果一致）"


# --------------------------------------------------------------------------
# HTTP 级：三类老结构会话都不 500（R29 阻断不再复现）
# --------------------------------------------------------------------------
def _corrupt_missing_keys(flow: dict) -> None:
    for key in _LEGACY_MISSING:
        flow["feynman"].pop(key, None)


def _corrupt_wrong_types(flow: dict) -> None:
    flow["feynman"]["answers_done"] = "0"     # 字符串
    flow["feynman"]["ledger"] = []            # 数组
    flow["feynman"]["last_scores"] = "脏"
    flow["practice"]["streak"] = "3"


def _corrupt_missing_block(flow: dict) -> None:
    flow.pop("feynman", None)


@pytest.mark.parametrize(
    "corrupt", [_corrupt_missing_keys, _corrupt_wrong_types, _corrupt_missing_block],
    ids=["missing_keys", "wrong_types", "missing_block"],
)
def test_r30_legacy_flow_shapes_submit_do_not_500(client, corrupt):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    flow = _load_flow(sid)
    corrupt(flow)
    _save_flow(sid, flow)

    r = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": BAD}},
    )
    assert r.status_code == 200, f"老结构会话不得 500：{r.status_code} {r.text[:300]}"
    body = r.json()
    assert body["payload"]["verdict"] == "fail"
    assert body["payload"]["followup_question"], "老结构自愈后仍应正常出定向追问"
    assert body["payload"]["answers_done"] == 0
    assert body["payload"]["ledger"]["dimensions"], "账本视图应已补齐并随响应下发"

    # 自愈结果须落库（后续请求不再依赖内存态）
    flow = _load_flow(sid)
    assert isinstance(flow["feynman"], dict)
    assert flow["feynman"]["answers_done"] == 0
    assert isinstance(flow["feynman"]["ledger"], dict)
    assert isinstance(flow["practice"]["streak"], int)


def test_r30_legacy_flow_whole_flow_wrong_type_recovers(client):  # noqa: F811
    """flow_json 整块被改坏（非 dict）→ 恢复默认结构并回到讲解阶段（不 500）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    _save_flow(sid, [])

    r = client.get(f"/api/session/{sid}")
    assert r.status_code == 200, f"整块缺失不得 500：{r.status_code} {r.text[:300]}"
    body = r.json()
    assert body["step"] == "explain", "结构重置 → 回讲解阶段重新开始"
    assert body["payload"]["lecture_md"], "重置后仍能给出讲解（可继续学习）"


def test_r30_legacy_missing_practice_block_degrades_zh(client):  # noqa: F811
    """practice 整块缺失 → 补齐默认（练习未达标）→ 中文 409 而非 500/KeyError。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    flow = _load_flow(sid)
    flow.pop("practice", None)
    _save_flow(sid, flow)

    r = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": BAD}},
    )
    assert r.status_code == 409, r.text
    assert "练习" in json.dumps(r.json(), ensure_ascii=False)
