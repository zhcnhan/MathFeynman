"""R30 F6：费曼完整稿（首讲/终验）**边缘带复评**集成测试 —— 离线桩驱动，确定性、无 key 可跑。

规格 docs/09 R30 §F6 + §6 六条用例：
  ① 带内（0.68）→ 触发复评、取较高（0.75）→ pass/mastered；
  ② 带外（0.40 / 0.90）→ **不触发**；
  ③ 首次即 think → 不触发；
  ④ 复评更低（0.68 → 0.60）→ 取首次 0.68 且不 pass；
  ⑤ 复评抛 AiCallError → 保留首次结果且不 500；
  ⑥ 断言事件与 attempts.meta 字段，且每轮复评 ≤1 次（含跨轮不重复复评）。

桩网关按 ``strategy`` 返回可控分数：非 think = 首次分，think = 复评分。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import models
from app.ai.calls import AiCallError, FeynmanDimScore, FeynmanEvaluateOut
from app.db import SessionLocal

from test_api_flow import _reset_node
from test_feynman_v3 import (  # noqa: F401  （tests/ 非包：与既有测试同口径，pytest 已加 sys.path）
    NODE,
    _drive_to_feynman,
    _reset_db,
    _seed_primary_head,
    _step,
    _use_gateway,
    client,
)

# middle.0101 费曼 rubric：correctness .4 / own_words .2 / example_and_edge .2 / self_correction .2
DIMS = ("correctness", "own_words", "example_and_edge", "self_correction")
THRESHOLD = 0.7

# 完整稿（≥20 字；桩引文取自其中 → evidence 校验通过，评分不被降级）
TRANSCRIPT = (
    "用我的话讲：方程是含有未知数的等式；一元一次方程只有一个未知数、最高次数是一。"
    "依据是逐条核对定义；例子 x+2=5，反例 1+2=3 没有未知数。我原先以为有等号就行，"
    "其实还必须含未知数——这一点我改正了。"
)


def _card_out(score: float, *, quote: str) -> FeynmanEvaluateOut:
    """全维同分卡 → 加权综合分恒等于该分（四维权重合计 1.0）。"""
    return FeynmanEvaluateOut(
        dimension_scores=[
            FeynmanDimScore(key=k, score=score, evidence_quote=quote, comment=f"桩评分 {score}")
            for k in DIMS
        ],
        overall_note="桩评分",
        recommend_action="pass" if score >= THRESHOLD else "followup",
    )


class _ScriptedGateway:
    """按调用顺序脚本化评分：``responses[i]`` = 第 i+1 次 feynman_evaluate 的分数。

    ``None`` 表示该次抛 ``AiCallError``（模拟复评不可用）。越界调用用 ``fallback``——
    并在 ``calls`` 里留痕，测试靠"调用顺序/次数"断言暴露误触发。
    """

    name = "fake-r30-edge"

    def __init__(self, *responses: float | None, fallback: float = 0.99):
        self.responses = list(responses)
        self.fallback = fallback
        self.calls: list[str | None] = []  # 每次 feynman_evaluate 的档位（按顺序）

    def feynman_evaluate(self, ctx, *, strategy=None):
        i = len(self.calls)
        self.calls.append(strategy)
        score = self.responses[i] if i < len(self.responses) else self.fallback
        if score is None:
            raise AiCallError("feynman_evaluate", "桩：复评不可用")
        return _card_out(float(score), quote=ctx.transcript[:24])


def _recheck_events(body: dict) -> list[dict]:
    return [e for e in body["events"] if e["type"] == "feynman_edge_recheck"]


def _feynman_metas(sid: str) -> list[dict]:
    """该会话全部费曼 attempts 的 meta（按写入顺序）。"""
    with SessionLocal() as db:
        rows = (
            db.query(models.Attempt)
            .filter(models.Attempt.session_id == sid, models.Attempt.kind == "feynman")
            .order_by(models.Attempt.id.asc())
            .all()
        )
        return [json.loads(json.dumps(r.meta_json)) for r in rows]


# --------------------------------------------------------------------------
# ① 带内 0.68 → 触发复评 → 取较高 0.75 → pass
# --------------------------------------------------------------------------
def test_r30_f6_band_in_triggers_recheck_and_takes_higher(client):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    gw = _ScriptedGateway(0.68, 0.75)

    with _use_gateway(gw):
        j = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)

    assert gw.calls == ["fast", "think"], "带内且非 think → 必须以 think 复评一次（且仅一次）"
    assert j["payload"]["verdict"] == "pass"
    assert j["payload"]["combined"] == pytest.approx(0.75)
    assert j["payload"]["strategy"] == "think", "strategy 记录**实际采用**那次（复评）"
    assert j["payload"]["strategy_reason"] == "edge_recheck=think"
    assert {d["key"]: d["score"] for d in j["payload"]["dimension_scores"]} == {k: 0.75 for k in DIMS}
    ev = _recheck_events(j)
    assert len(ev) == 1
    assert ev[0] == {"type": "feynman_edge_recheck", "first": 0.68, "second": 0.75, "taken": "second"}
    assert any(e["type"] == "feynman_passed" for e in j["events"])
    assert any(e["type"] == "node_mastered" for e in j["events"])
    metas = _feynman_metas(sid)
    assert metas[-1]["recheck"] == {
        "used": True, "first_combined": 0.68, "second_combined": 0.75, "taken": "second",
    }
    assert metas[-1]["strategy"] == "think"


# --------------------------------------------------------------------------
# ② 带外（0.40 不过 / 0.90 直接过）→ 不触发
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "first,expect_pass",
    [
        (0.40, False),  # 低于带下界 0.65
        (0.90, True),   # 高于带上界 0.78
    ],
)
def test_r30_f6_out_of_band_never_rechecks(client, first, expect_pass):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    gw = _ScriptedGateway(first, fallback=0.99)  # 若被误触发，调用记录/事件会露馅

    with _use_gateway(gw):
        j = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)

    assert gw.calls == ["fast"], f"带外 {first} 不得触发复评"
    assert not _recheck_events(j), "带外不得产生 feynman_edge_recheck 事件"
    assert j["payload"]["strategy"] == "fast"
    assert j["payload"]["combined"] == pytest.approx(first)
    assert any(e["type"] == "node_mastered" for e in j["events"]) is expect_pass
    metas = _feynman_metas(sid)
    assert metas[-1]["recheck"] == {
        "used": False, "first_combined": first, "second_combined": None, "taken": "first",
    }


# --------------------------------------------------------------------------
# ③ 首次即 think → 不触发（已是 think 无可再升）
# --------------------------------------------------------------------------
def test_r30_f6_think_round_never_rechecks(client):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    gw = _ScriptedGateway(0.68)  # 本轮唯一一次评分（think 档首次）

    with _use_gateway(gw):
        j = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT, think_deep=True)

    assert gw.calls == ["think"], "本轮档位已是 think → 不再复评"
    assert not _recheck_events(j)
    assert j["payload"]["strategy"] == "think"
    assert j["payload"]["combined"] == pytest.approx(0.68)
    metas = _feynman_metas(sid)
    assert metas[-1]["recheck"] == {
        "used": False, "first_combined": 0.68, "second_combined": None, "taken": "first",
    }


# --------------------------------------------------------------------------
# ④ 复评更低（0.68 → 0.60）→ 取首次 0.68 且不 pass
# --------------------------------------------------------------------------
def test_r30_f6_lower_second_keeps_first(client):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    gw = _ScriptedGateway(0.68, 0.60)

    with _use_gateway(gw):
        j = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)

    assert gw.calls == ["fast", "think"]
    assert j["payload"]["verdict"] == "fail"
    assert j["payload"]["combined"] == pytest.approx(0.68), "取两次较高者 = 首次"
    assert j["payload"]["strategy"] == "fast", "采用首次 → 档位仍是 fast"
    assert j["payload"]["followup_question"], "未过 → 定向追问照常"
    assert not any(e["type"] == "node_mastered" for e in j["events"])
    ev = _recheck_events(j)
    assert len(ev) == 1
    assert ev[0] == {"type": "feynman_edge_recheck", "first": 0.68, "second": 0.6, "taken": "first"}
    metas = _feynman_metas(sid)
    assert metas[-1]["recheck"] == {
        "used": True, "first_combined": 0.68, "second_combined": 0.6, "taken": "first",
    }
    assert metas[-1]["strategy"] == "fast"


# --------------------------------------------------------------------------
# ⑤ 复评抛 AiCallError → 保留首次结果、不失败、不 500
# --------------------------------------------------------------------------
def test_r30_f6_recheck_error_keeps_first_result(client):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    gw = _ScriptedGateway(0.68, None)  # 第 2 次（复评）抛 AiCallError

    with _use_gateway(gw):
        j = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)  # 200：不得因复评失败而 500

    assert gw.calls == ["fast", "think"]
    assert j["payload"]["verdict"] == "fail"
    assert j["payload"]["combined"] == pytest.approx(0.68)
    assert j["payload"]["strategy"] == "fast"
    assert j["payload"]["followup_question"], "复评失败不阻断后续追问"
    ev = _recheck_events(j)
    assert len(ev) == 1 and ev[0]["second"] is None and ev[0]["taken"] == "first"
    metas = _feynman_metas(sid)
    assert metas[-1]["recheck"] == {
        "used": True, "first_combined": 0.68, "second_combined": None, "taken": "first",
    }


# --------------------------------------------------------------------------
# ⑥ 每轮复评 ≤1 次（跨轮也不重复复评同一轮）
# --------------------------------------------------------------------------
def test_r30_f6_at_most_one_recheck_per_round(client):  # noqa: F811
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    # 第 1 轮：fast 0.68 → think 复评 0.60（取首次，未过）；第 2 轮：轮次≥2 本就 think → 0.75 过
    gw = _ScriptedGateway(0.68, 0.60, 0.75)

    with _use_gateway(gw):
        j1 = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)
        calls_after_round1 = list(gw.calls)
        j2 = _step(client, sid, "feynman_submit", transcript=TRANSCRIPT)
        calls_after_round2 = list(gw.calls)

    # 第 1 轮：fast 首次 + 1 次 think 复评 = 恰好 1 次额外 heavy 调用
    assert calls_after_round1 == ["fast", "think"]
    assert len(_recheck_events(j1)) == 1
    assert j1["payload"]["verdict"] == "fail"
    # 第 2 轮：eval_rounds=1 → R12 轮次触发使本轮本身就 think → 不再复评（额外调用 0 次）
    assert calls_after_round2 == ["fast", "think", "think"]
    assert _recheck_events(j2) == [], "第 2 轮已是 think → 复评次数为 0（≤1）"
    assert j2["payload"]["verdict"] == "pass"

    metas = _feynman_metas(sid)
    assert [m["recheck"]["used"] for m in metas] == [True, False]
    assert [m["recheck"]["taken"] for m in metas] == ["first", "first"]
    assert [m["eval_rounds_done"] for m in metas] == [1, 2]
