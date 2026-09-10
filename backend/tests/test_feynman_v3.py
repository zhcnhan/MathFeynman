"""R27 费曼追问语义 v3（混合制）集成测试 —— 离线桩驱动，确定性、无 key 可跑。

覆盖 docs/09 R27 §7 验收三条路径 + evidence 纪律硬校验：
  ① 首讲 0.0 → 答追问（含核心词）→ 缺口维度分**真实上升**（断言 ledger 变化，
     绝不重现"两轮逐字同分"：两轮 evidence_quote/分数必须不同）；
  ② 首讲未过 → 补答补缺口 → 整合重讲含全部要点 → 整体 ≥0.7 → pass/mastered；
  ③ 补答额度尽 + 终验仍 <0.7 → 回炉 relearn（stage=explain，事件流正确）；
  ④ evidence 纪律：评分卡 evidence 必须 ⊆ 本轮文本（含补答轮），违规 → 降级标记。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.ai.calls import (
    CALL_FEYNMAN_GAP_CHECK,
    CALLS,
    FeynmanDimScore,
    FeynmanEvaluateOut,
    GapCheckOut,
)
from app.ai.gateway import offline_feynman_scores
from app.content.templates import render_exercise
from app.db import SessionLocal
from app.main import app
from app.service import feynman_ledger as fl
from app.service.library import get_library

from test_api_flow import (  # noqa: E402  （tests/ 非包：与既有测试同口径，pytest 已把 tests 加入 sys.path）
    _reset_node,
    start_practice,
    submit,
)

NODE = "middle.0101"  # 核心概念：方程 / 一元一次方程 / 未知数 / 代数式 / 等号；门槛 0.7


# --------------------------------------------------------------------------
# 模块级 fixture（与 test_api_flow 同口径：干净库 + 播种总序头部 auto 内容）
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    _reset_db()
    _seed_primary_head()
    with TestClient(app) as c:
        yield c


def _seed_primary_head() -> None:
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap
    from app.service.library import refresh_library, sync_content

    rd = load_roadmap("primary")
    pl.generate_sequence(rd, ["primary.s01", "primary.s02", "primary.s03", "primary.s04"])
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()


def _reset_db() -> None:
    from sqlalchemy import text

    from app.db import init_db
    from app.service.library import ensure_user, sync_content

    init_db()
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes", "edges", "ai_logs", "nodes", "users"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def canonical_answer(node_id: str, exercise_id: str, seed: int) -> str:
    lib = get_library()
    loaded = lib.by_id[node_id]
    ex = next(e for e in loaded.doc.exercises if e.id == exercise_id)
    return render_exercise(node_id, ex, seed).canonical_answer

# 不含任何核心概念、长度 ≥20 的"未达标首讲"（离线启发式必然判不过）
BAD = (
    "我先组织一下语言，嗯…… 这个问题其实我还没有完全想明白，让我再仔细回忆一下"
    "刚才看到的例子，再好好想一想应该怎么回答。"
)
# 答追问（含核心概念）→ 应补上 correctness 缺口
ANSWER = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"
# 整合重讲（含全部要点 + 依据 + 自纠）→ 离线启发式 ≥0.7
FULL = (
    "用我的话讲：方程就是「含有未知数的等式」，像 x+2=5 这样；一元一次方程还要满足"
    "只有一个未知数、且未知数的最高次数是 1（次数是 2 的 x²+1=5 就不算）。依据是判断时"
    "需要逐条核对定义：一加二等于三没有未知数，所以不是方程。我原先以为「有等号就行」，"
    "其实还必须含未知数——这一点我改正过来了。另外用一个反例说明边界：x+y=3 有两个未知数，"
    "也不是一元一次方程。"
)


class _OfflineFallback:
    """未显式桩掉的方法一律回落离线网关（真实路由不会因缺方法 500）。"""

    def __getattr__(self, name):
        from app.ai.gateway import OfflineGateway

        return getattr(OfflineGateway(), name)


def _use_gateway(gateway):
    """把会话服务依赖替换为使用给定网关的实例（HTTP 请求层同样生效）。"""
    import contextlib

    from app.api import deps
    from app.service.session import SessionService

    class _Combined(_OfflineFallback):
        def __getattr__(self, name):
            return getattr(gateway, name) if hasattr(gateway, name) else super().__getattr__(name)

    svc_gateway = _Combined()

    @contextlib.contextmanager
    def _ctx():
        app.dependency_overrides[deps.get_session_service] = lambda: SessionService(svc_gateway)
        try:
            yield
        finally:
            app.dependency_overrides.pop(deps.get_session_service, None)

    return _ctx()


def _drive_to_feynman(client) -> str:
    sess, pr = start_practice(client, NODE)
    sid = sess["session"]["id"]
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer(NODE, ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman", pr["step"]
    return sid


def _step(client, sid: str, action: str, **payload) -> dict:
    r = client.post("/api/session/step", json={"session_id": sid, "action": action, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# ① 首讲 0.0 → 答追问 → 缺口维度分真实上升（账本变化断言）
# --------------------------------------------------------------------------
def test_r27_path1_answer_raises_ledger_dimension(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)

    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j1["payload"]["verdict"] == "fail"
    ledger0 = j1["payload"]["ledger"]
    assert ledger0["combined"] < ledger0["threshold"]
    best0 = {d["key"]: d["best"] for d in ledger0["dimensions"]}
    card0 = {d["key"]: (d["score"], d["evidence_quote"]) for d in ledger0["dimensions"]}
    gap = j1["payload"]["followup_gap"]
    assert gap and gap["key"], "R27：追问必须定向到具体缺口（不再自由发问）"
    assert j1["payload"]["next_action"] == "answer"

    j2 = _step(client, sid, "feynman_answer", answer=ANSWER)
    assert j2["payload"]["verdict"] == "gap"
    assert j2["payload"]["gap_filled"] is True
    ledger1 = j2["payload"]["ledger"]
    best1 = {d["key"]: d["best"] for d in ledger1["dimensions"]}

    # 账本真实变化（R27 验收①：绝不重现"两轮逐字同分"）
    assert ledger1["combined"] > ledger0["combined"], (ledger0["combined"], ledger1["combined"])
    key = j2["payload"]["gap_key"]
    assert best1[key] > best0[key], f"缺口维度 {key} 必须上升：{best0} → {best1}"
    assert j2["payload"]["gap_update"]["evidence_valid"] is True
    # 且证据/分数不再与上一轮逐字相同（评分对象=本轮文本的证明）
    card1 = {d["key"]: (d["score"], d["evidence_quote"]) for d in ledger1["dimensions"]}
    assert card1[key] != card0[key]
    # 补答不能单独过关
    assert not any(e["type"] == "node_mastered" for e in j2["events"])
    assert j2["payload"]["next_action"] == "submit"
    # 缺口账本：补上的缺口从清单消失
    assert all(g["key"] != key for g in ledger1["gaps"])


# --------------------------------------------------------------------------
# ② 首讲未过 → 补答 → 整合重讲 → 整体 ≥0.7 → pass / mastered
# --------------------------------------------------------------------------
def test_r27_path2_answer_then_integrated_submit_passes(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)

    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j1["payload"]["verdict"] == "fail"
    assert j1["payload"]["rounds_done"] == 1

    j2 = _step(client, sid, "feynman_answer", answer=ANSWER)
    assert j2["payload"]["gap_filled"] is True
    assert j2["payload"]["ledger"]["combined"] < j2["payload"]["threshold"], "补答只涨账本，不能直接过关"

    j3 = _step(client, sid, "feynman_submit", transcript=FULL)
    assert j3["payload"]["mastered"] is True
    assert j3["payload"]["combined"] >= j3["payload"]["threshold"]
    assert any(e["type"] == "feynman_passed" for e in j3["events"])
    assert any(e["type"] == "node_mastered" for e in j3["events"])
    # 整体稿评分次数 = 首讲 1 + 终验 1
    assert j3["payload"]["evals_done"] == 2
    # 已掌握 → 复习排程（mastery 元数据齐全）
    assert j3["payload"]["mastery"]["next_review_due_at"]


# --------------------------------------------------------------------------
# ③ 补答额度尽 + 终验仍 <0.7 → 回炉 relearn
# --------------------------------------------------------------------------
def test_r27_path3_budgets_exhausted_relearn(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)

    # 首讲未过 → 追问
    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j1["payload"]["verdict"] == "fail"
    # 补答①：答不对（不涉及缺口核心概念，但长度足够）
    j2 = _step(
        client, sid, "feynman_answer",
        answer="我想了想，这个内容我其实还是不太确定，可能还要再翻一翻前面的讲解。",
    )
    assert j2["payload"]["verdict"] == "gap"
    assert j2["payload"]["gap_filled"] is False
    assert j2["payload"]["next_action"] == "submit"
    assert j2["payload"]["answers_done"] == 1
    # R30 F4：补答未补上 → 文案必须说清"再交一次完整讲解后才会针对该缺口再问"
    assert "再交一次完整讲解" in j2["payload"]["message"]
    assert j2["payload"]["followup_question"] is None, "补答后追问被清空（须再交完整稿换取新追问）"
    # 终验②（整合稿完全跑题）→ 仍 <0.7 → 缺口保留、可再补答一次
    j3 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j3["payload"]["verdict"] == "fail"
    assert j3["payload"]["rounds_done"] == 2
    assert j3["step"] == "feynman"
    assert j3["payload"]["followup_question"], "同一缺口答不对 → 保留缺口、可再追一次"
    # 补答②：仍未答对
    j4 = _step(
        client, sid, "feynman_answer",
        answer="还是不确定，我觉得可能跟前面那个例子有点像，但具体我也说不太清楚。",
    )
    assert j4["payload"]["gap_filled"] is False
    assert j4["payload"]["answers_done"] == 2
    # 终验③（额度尽 + 仍 <0.7）→ 回炉 relearn
    j5 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j5["step"] == "explain"
    assert any(e["type"] == "feynman_relearn" for e in j5["events"])
    assert any(e["type"] == "relearn_notice" for e in j5["events"])
    assert j5["payload"]["lecture_md"], "回炉后应重新给出讲解"
    assert j5["payload"]["evals_done"] == 0, "R17/R27：回炉必须清零轮次与预算"
    assert j5["payload"]["answers_done"] == 0
    assert not j5["payload"]["ledger"]["gaps"], "回炉后缺口账本一并清零（防旧缺口锚定新一轮）"


# --------------------------------------------------------------------------
# ④ evidence 纪律（硬校验）：评分卡 evidence 必须 ⊆ 本轮文本
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "transcript",
    [
        BAD,
        ANSWER,
        FULL,
        # LLM 常见的"改写式"引文：应被判无效
        "学生说的是另外一句话，完全不在本轮文本中。",
        "",
    ],
)
def test_r27_evidence_must_come_from_current_round_offline(transcript):
    card, _ = offline_feynman_scores(
        transcript,
        ["方程", "一元一次方程"],
        [{"key": "correctness", "weight": 1.0}, {"key": "own_words", "weight": 1.0}],
    )
    for row in card:
        if row["evidence_quote"]:
            assert fl.quote_valid(row["evidence_quote"], transcript), row
        else:
            assert transcript.strip() == ""


def test_r27_evidence_discipline_downgrades_foreign_quote(client):
    """真实模型给出"不在本轮文本中"的 evidence → 服务端标记 + 降级（不静默认可）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    good = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"

    class FakeGateway:
        name = "fake-r27"

        def feynman_evaluate(self, ctx, *, strategy=None):
            del strategy
            assert ctx.transcript == good, "R27：评分对象必须是本轮完整稿（不得拼接历史合并稿）"
            # 引文来自**其它轮次**（不在本轮文本中）→ 必须被判无效并降级
            return FeynmanEvaluateOut(
                dimension_scores=[
                    FeynmanDimScore(key="correctness", score=0.9,
                                    evidence_quote="我从上一轮的回答里抄来的句子", comment="看着像对的"),
                    FeynmanDimScore(key="own_words", score=0.8,
                                    evidence_quote="方程是含有未知数的等式", comment="用自己的话"),
                ],
                overall_note="",
                recommend_action="pass",
            )

        def feynman_gap_check(self, ctx, *, strategy=None):
            del strategy
            return GapCheckOut(gap_filled=False, dimension_updates=[], comment="未补上")

    with _use_gateway(FakeGateway()):
        j = _step(client, sid, "feynman_submit", transcript=good)
        card = {d["key"]: d for d in j["payload"]["dimension_scores"]}
        assert card["correctness"]["evidence_valid"] is False
        assert card["correctness"]["score"] == pytest.approx(0.9 * fl.EVIDENCE_PENALTY)
        assert "evidence_reason" in card["correctness"]
        assert card["own_words"]["evidence_valid"] is True
        assert card["own_words"]["score"] == 0.8
        assert j["payload"]["evidence_penalty"] is True
        assert any(e["type"] == "feynman_evidence_flagged" for e in j["events"])
        # 评分被降级后不达阈值 → 不得放过（防"没读新内容还打分"＋防幻觉抬分）
        assert not any(e["type"] == "node_mastered" for e in j["events"])


# --------------------------------------------------------------------------
# ④' R30 F5：evidence 最短长度门槛（归一化后 < 6 字视为无效）
# --------------------------------------------------------------------------
def test_r30_f5_evidence_min_length_threshold():
    """极短引文可平凡通过"子串包含" → 归一化后 < 6 字一律判无效（R28 F5 / docs/09 R30）。"""
    text = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"
    assert fl.MIN_EVIDENCE_CHARS == 6
    # 归一化后 2/4/5 字：虽为原文子串，仍判无效
    assert fl.quote_valid("方程", text) is False
    assert fl.quote_valid("方程是含", text) is False
    assert fl.quote_valid("方程是含有", text) is False
    # 归一化后 6 字（含标点/空白干扰也算数）→ 有效
    assert fl.quote_valid("方程是含有未", text) is True
    assert fl.quote_valid("方 程，是 含 有 未", text) is True
    # 原因文案可区分"过短"与"不在本轮文本中"（错误全中文）
    assert "过短" in fl.quote_invalid_reason("方程", text)
    assert "不在本轮提交文本中" in fl.quote_invalid_reason("完全不在这段话里的句子", text)


def test_r30_f5_short_quote_downgraded_end_to_end(client):
    """真实模型给"极短但在文本中"的引文 → 服务端仍标记无效 + 降级（不平凡通过）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    good = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"

    class ShortQuoteGateway:
        name = "fake-r30-f5"

        def feynman_evaluate(self, ctx, *, strategy=None):
            del strategy
            return FeynmanEvaluateOut(
                dimension_scores=[
                    FeynmanDimScore(key="correctness", score=0.9,
                                    evidence_quote="方程", comment="极短引文（原文子串）"),
                    FeynmanDimScore(key="own_words", score=0.8,
                                    evidence_quote=ctx.transcript[:12], comment="正常长度引文"),
                ],
                overall_note="",
                recommend_action="pass",
            )

    with _use_gateway(ShortQuoteGateway()):
        j = _step(client, sid, "feynman_submit", transcript=good)

    card = {d["key"]: d for d in j["payload"]["dimension_scores"]}
    assert card["correctness"]["evidence_valid"] is False, "极短引文一律无效（R30 F5）"
    assert card["correctness"]["score"] == pytest.approx(0.9 * fl.EVIDENCE_PENALTY)
    assert "过短" in card["correctness"]["evidence_reason"]
    assert card["own_words"]["evidence_valid"] is True
    assert card["own_words"]["score"] == 0.8
    assert j["payload"]["evidence_penalty"] is True
    assert any(e["type"] == "feynman_evidence_flagged" for e in j["events"])


def test_r27_gap_check_call_registered_and_light():
    spec = CALLS["feynman_gap_check"]
    assert spec is CALL_FEYNMAN_GAP_CHECK
    assert spec.model_tier == "light", "补答是轻量评估（学生答完要立刻看到涨分）"


def test_r27_gap_check_only_updates_target_dimension(client):
    """补答评估只允许更新缺口所属维度：模型多给的键被忽略（防越权改分）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    gap_key = j1["payload"]["followup_gap"]["key"]

    class MultiKeyGateway:
        name = "fake-multi"

        def feynman_gap_check(self, ctx, *, strategy=None):
            del strategy
            other = "own_words" if ctx.target_gap["key"] != "own_words" else "correctness"
            return GapCheckOut(
                gap_filled=True,
                dimension_updates=[
                    FeynmanDimScore(key=ctx.target_gap["key"], score=0.95,
                                    evidence_quote=ctx.student_answer[:20], comment="补上"),
                    FeynmanDimScore(key=other, score=0.99,
                                    evidence_quote=ctx.student_answer[:20], comment="越权"),
                ],
                comment="补上了",
            )

    with _use_gateway(MultiKeyGateway()):
        j2 = _step(client, sid, "feynman_answer", answer=ANSWER)
        assert j2["payload"]["gap_filled"] is True
        assert [u["key"] for u in j2["payload"]["dimension_updates"]] == [gap_key]
        best = {d["key"]: d["best"] for d in j2["payload"]["ledger"]["dimensions"]}
        other = "own_words" if gap_key != "own_words" else "correctness"
        assert best[other] < 0.99, "非缺口维度不得被补答修改"


def test_r27_ledger_never_downgrades_on_weaker_round():
    """账本 = 历轮最高分：后续更差的一轮不得把已认可分数拉低。"""
    ledger = fl.empty_ledger()
    dims = [{"key": "correctness", "weight": 0.4}, {"key": "own_words", "weight": 0.6}]
    fl.normalize_ledger({"ledger": ledger}, dims)
    good = "方程是含有未知数的等式"
    fl.merge_card(
        ledger,
        [{"key": "correctness", "score": 0.9, "weight": 0.4, "evidence_quote": good, "comment": "好"},
         {"key": "own_words", "score": 0.8, "weight": 0.6, "evidence_quote": good, "comment": "好"}],
        round_no=1, transcript=good,
    )
    first = fl.combined(ledger)
    fl.merge_card(
        ledger,
        [{"key": "correctness", "score": 0.1, "weight": 0.4, "evidence_quote": good, "comment": "退步"},
         {"key": "own_words", "score": 0.2, "weight": 0.6, "evidence_quote": good, "comment": "退步"}],
        round_no=2, transcript=good,
    )
    assert fl.combined(ledger) == pytest.approx(first)
    assert ledger["dims"]["correctness"]["best"] == 0.9
    assert ledger["dims"]["correctness"]["latest"] == 0.1


def test_r27_previously_acknowledged_passed_to_evaluator(client):
    """整体评分输入含 previously_acknowledged（账本已认可摘要）：没重抄已认可点不扣分。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    seen: dict = {}

    class AckGateway:
        name = "fake-ack"

        def feynman_evaluate(self, ctx, *, strategy=None):
            del strategy
            seen["ack"] = ctx.previously_acknowledged
            seen["previous_round"] = ctx.previous_round
            seen["transcript"] = ctx.transcript
            return FeynmanEvaluateOut(
                dimension_scores=[
                    FeynmanDimScore(key="correctness", score=0.85,
                                    evidence_quote=ctx.transcript[:20], comment="讲对了"),
                ],
                overall_note="",
                recommend_action="pass",
            )

    with _use_gateway(AckGateway()):
        first = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"
        j1 = _step(client, sid, "feynman_submit", transcript=first)
        assert seen["ack"] == []  # 首讲无已认可内容
        assert seen["previous_round"] is None
        assert seen["transcript"] == first, "R27：评分对象 = 本轮文本（不拼历史合并稿）"
        assert j1["payload"]["verdict"] == "fail"
        # 第二次提交更短（没重抄已认可点）→ 仍带 previously_acknowledged 上下文（不扣分依据）
        second = "为什么 x²+1=5 不算？因为它次数是二。"
        j2 = _step(client, sid, "feynman_submit", transcript=second)
        assert seen["transcript"] == second
        assert seen["ack"] and seen["ack"][0]["key"] == "correctness"
        assert seen["ack"][0]["best_score"] == pytest.approx(0.85)
        assert seen["previous_round"]["round"] == 1
        assert seen["previous_round"]["dims"][0]["key"] == "correctness"
        assert j2["payload"]["ledger"]["dimensions"]
        # 账本不因第二次更短而下降
        best = {d["key"]: d["best"] for d in j2["payload"]["ledger"]["dimensions"]}
        assert best["correctness"] >= 0.85


def test_r27_no_followup_question_means_submit_only(client):
    """无追问时（已答完缺口/额度尽）不得再发自由追问；只提示交完整稿。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j1["payload"]["followup_question"]
    j2 = _step(client, sid, "feynman_answer", answer=ANSWER)
    assert j2["payload"]["gap_filled"] is True
    j3 = client.get(f"/api/session/{sid}")
    assert j3.status_code == 200
    payload = j3.json()["payload"]
    assert payload["next_action"] == "submit"
    assert payload["followup_question"] is None
    assert payload["ledger"]["combined"] > 0
    # 已答完缺口后再发补答 → 明确中文 409（不再把补答当整体重评）
    r = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_answer", "payload": {"answer": ANSWER}},
    )
    assert r.status_code == 409, r.text
    body = json.dumps(r.json(), ensure_ascii=False)
    assert "追问" in body and "完整讲解" in body
