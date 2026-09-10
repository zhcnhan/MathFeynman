"""R29 回归（真人阻断热修）：R27 之前落库的老会话可直接续走费曼。

背景：老会话 ``flow.feynman`` 无 ``answers_done`` / ``followup_gap`` / ``ledger`` 键，
而费曼分支用 ``f["answers_done"]``（非 ``.get``）取值 → 首讲未过时
``KeyError: 'answers_done'`` → 500（用户在前端看到"会话不可用"）。
修复：``_ensure_invariants`` 按当前默认结构回填缺失键（不覆盖已有值）。
"""
from __future__ import annotations

import json

from app.db import SessionLocal
from app.models import Session as SessionModel

from test_feynman_v3 import (  # noqa: F401  （与既有测试同口径：tests/ 非包，pytest 已加 sys.path）
    BAD,
    NODE,
    _drive_to_feynman,
    _reset_db,
    _seed_primary_head,
    client,
)

_LEGACY_MISSING = ("answers_done", "ledger", "followup_gap")


def _make_legacy(sid: str) -> None:
    """把会话的 feynman 段回退为 R27 之前的旧结构（缺新键）。"""
    with SessionLocal() as db:
        sess = db.get(SessionModel, sid)
        flow = json.loads(json.dumps(sess.flow_json))
        for key in _LEGACY_MISSING:
            flow["feynman"].pop(key, None)
        sess.flow_json = flow
        db.commit()


def test_r29_legacy_session_submit_does_not_500(client):  # noqa: F811
    _reset_db()
    _seed_primary_head()
    sid = _drive_to_feynman(client)
    _make_legacy(sid)

    with SessionLocal() as db:
        flow = json.loads(json.dumps(db.get(SessionModel, sid).flow_json))
        assert not any(k in flow["feynman"] for k in _LEGACY_MISSING), "前置：确为老结构"

    # 首讲未过（离线启发式必然判不过）→ 修复前在此抛 KeyError: 'answers_done' → 500
    r = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": BAD}},
    )
    assert r.status_code == 200, f"老会话阻断回归：{r.status_code} {r.text[:300]}"
    body = r.json()
    assert body["payload"]["verdict"] == "fail"
    assert body["payload"]["followup_question"], "未过后应给出定向追问"
    assert body["payload"]["answers_done"] == 0
    assert body["payload"]["ledger"]["dimensions"], "账本视图应已回填并随响应下发"

    # 回填须落库（后续请求不再依赖内存态）
    with SessionLocal() as db:
        flow = json.loads(json.dumps(db.get(SessionModel, sid).flow_json))
        assert flow["feynman"]["answers_done"] == 0
        assert isinstance(flow["feynman"]["ledger"], dict)

    # 老会话可继续补答（feynman_answer 同样依赖 answers_done / followup_gap）
    r2 = client.post(
        "/api/session/step",
        json={
            "session_id": sid,
            "action": "feynman_answer",
            "payload": {"answer": "方程是含有未知数的等式；一元一次方程只有一个未知数且次数为一。"},
        },
    )
    assert r2.status_code == 200, f"老会话补答阻断：{r2.status_code} {r2.text[:300]}"
    assert r2.json()["payload"]["verdict"] == "gap"
    assert r2.json()["payload"]["answers_done"] == 1
