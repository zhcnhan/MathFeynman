"""M3 集成：真网关 schema 调用 + 失败降级不脏状态 + ai_logs 审计。"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.calls import (
    CALL_EXPLAIN_NODE,
    AiCallError,
    AnswerQuestionIn,
    ClassifyErrorIn,
    ExplainIn,
    FeynmanEvaluateIn,
)
from app.ai.gateway import OpenAICompatibleGateway, gateway_factory
from app.ai.provider import OpenAICompatibleProvider
from app.api import deps
from app.db import SessionLocal
from app.main import app
from app.service.session import SessionService

# 复用 API 流程测试的小工具（同 tests 目录；判题答案由模板渲染器复算，不依赖泄露）
from test_api_flow import canonical_answer, start_practice, submit  # noqa: E402


def _gateway_with_content(responses_content: list[str]) -> OpenAICompatibleGateway:
    queue = list(responses_content)

    def handler(request: httpx.Request) -> httpx.Response:
        content = queue.pop(0)
        body = {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        }
        return httpx.Response(200, json=body)

    provider = OpenAICompatibleProvider(
        api_key="sk-test",
        base_url="http://x/v1",
        model_heavy="hm",
        model_light="lm",
        transport=httpx.MockTransport(handler),
    )
    return OpenAICompatibleGateway(provider)


def test_openai_gateway_schema_calls():
    g = _gateway_with_content(
        [
            json.dumps({"lecture_md": "演绎讲解：一元一次方程是…$$x$$", "asked_to_confirm": ["何为解？"]}),
            json.dumps({"reply_md": "因为移项变号……", "needs_more_info": False}),
            json.dumps({"error_type": "sign_error"}),
        ]
    )
    base = dict(
        session_id="s", node_id="middle.0102", node_title="求解", level="middle",
        explanation_body="移项变号", worked_examples=[], core_concepts=["移项"],
        whitelist=["移项"], profile_style_block="",
    )
    out = g.explain_node(ExplainIn(**base))
    assert out.lecture_md.startswith("演绎讲解")
    out2 = g.answer_question(AnswerQuestionIn(**base, student_question="为什么要移项变号？"))
    assert "移项变号" in out2.reply_md
    cls = g.classify_error(ClassifyErrorIn(node_id="n", prompt="p", correct_solution="x=1", user_answer="x=-1"))
    assert cls.error_type == "sign_error"


def test_feynman_output_schema_enforced():
    # 输出含逐字 evidence 的合法结果
    content = json.dumps(
        {
            "dimension_scores": [
                {
                    "key": "correctness",
                    "score": 0.8,
                    "evidence_quote": "移项要变号",
                    "comment": "正确",
                }
            ],
            "overall_note": "基本掌握",
            "misconceptions_found": [],
            "recommend_action": "followup",
        },
        ensure_ascii=False,
    )
    g = _gateway_with_content([content])
    out = g.feynman_evaluate(
        FeynmanEvaluateIn(
            session_id="s", node_id="n", task_prompt="讲", rubric_dimensions=[{"key": "correctness", "weight": 1.0}],
            core_concepts=["移项"], transcript="移项要变号，移项要变号。", previous_round=None,
        )
    )
    assert out.dimension_scores[0].evidence_quote == "移项要变号"  # 逐字 evidence 保留
    assert out.recommend_action == "followup"


def test_service_degrade_on_ai_error_keeps_state_clean(app_client):
    """费曼评分 AiCallError → deferred（人工复核），不判过/不过，状态不脏（docs/05 §6）。"""

    class ExplodingFeynmanGateway:
        name = "exploding"

        def explain_node(self, ctx, *, strategy=None):  # 复用离线兜底内容
            from app.ai.gateway import OfflineGateway

            return OfflineGateway().explain_node(ctx, strategy=strategy)

        def answer_question(self, ctx, *, strategy=None):
            from app.ai.gateway import OfflineGateway

            return OfflineGateway().answer_question(ctx, strategy=strategy)

        def hint_on_error(self, ctx, *, strategy=None):
            from app.ai.gateway import OfflineGateway

            return OfflineGateway().hint_on_error(ctx, strategy=strategy)

        def feynman_evaluate(self, ctx, *, strategy=None):
            raise AiCallError("feynman_evaluate", "模拟：模型不可用")

        def feynman_followup(self, ctx, *, strategy=None):
            from app.ai.gateway import OfflineGateway

            return OfflineGateway().feynman_followup(ctx, strategy=strategy)

        def classify_error(self, ctx):
            from app.ai.gateway import OfflineGateway

            return OfflineGateway().classify_error(ctx)

        def generate_practice_variant(self, ctx):
            raise AiCallError("variant", "MVP 不启用")

    bad_gateway = ExplodingFeynmanGateway()
    svc = SessionService(bad_gateway)

    def override():
        return svc

    app.dependency_overrides[deps.get_session_service] = override
    try:
        c = app_client  # 共享会话级 TestClient（单 portal，避免多 with 生命周期死锁）
        sess, pr = start_practice(c, "middle.0102")
        sid = sess["session"]["id"]
        # 练习全对直到进入费曼
        for _ in range(10):
            step = pr["step"]
            if step == "feynman":
                break
            ex = pr["payload"]["exercise"]
            ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
            pr = submit(c, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
        assert pr["step"] == "feynman"
        r = c.post(
            "/api/session/step",
            json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": "移项要变号因为要保持等式两边相等；合并同类项后系数化一，最后要验根。"}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payload"]["verdict"] == "deferred"  # 评分不可用 → 人工复核，不判过/不过
        assert any(e["type"] == "feynman_deferred" for e in body["events"])
        # 状态未脏：未 mastered、会话仍在费曼可重试
        assert not any(e["type"] == "node_mastered" for e in body["events"])
        assert body["step"] == "feynman"
        with SessionLocal() as db:
            from app import models

            un = db.get(models.UserNode, ("local", "middle.0102"))
            assert un is None or un.state != "mastered"
            deferred = (
                db.query(models.Attempt)
                .filter(models.Attempt.kind == "feynman", models.Attempt.verdict == "deferred")
                .count()
            )
            assert deferred >= 1
    finally:
        app.dependency_overrides.clear()


def test_ai_logs_rows_written_on_failure():
    """provider 失败也留 ai_logs 审计（docs/05 §6）。"""
    from app.ai.gateway import OfflineGateway
    from app.service.ai_sink import make_ai_log_sink

    sink = make_ai_log_sink()
    queue = [httpx.Response(200, json={"choices": [{"message": {"content": "坏JSON"}}]})]

    def handler(request):
        return queue.pop(0)

    provider = OpenAICompatibleProvider(
        api_key="sk-x", base_url="http://x/v1", model_heavy="hm", model_light="lm",
        log_sink=sink, transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AiCallError):
        provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])
    with SessionLocal() as db:
        from app import models

        row = (
            db.query(models.AiLog)
            .filter(models.AiLog.call_name == "explain_node", models.AiLog.ok.is_(False))
            .order_by(models.AiLog.id.desc())
            .first()
        )
        assert row is not None and row.error
