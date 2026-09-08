"""M3 真模型冒烟（可选）：仅当 .env 配置了 LLM_API_KEY 才运行。

验收点（docs/08 M3）：费曼评分输出含逐字 evidence；坏 JSON 重试/降级由 provider 单测覆盖。
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.getenv("LLM_API_KEY") and os.getenv("MF_ALLOW_LIVE_AI") == "1"),
    reason="真模型冒烟需显式开启：设 MF_ALLOW_LIVE_AI=1（并配置 .env 的 LLM_API_KEY）后运行",
)


def _provider():
    from app.ai.gateway import gateway_factory
    from app.service.ai_sink import make_ai_log_sink

    return gateway_factory(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        heavy_model=os.getenv("LLM_MODEL_HEAVY", "deepseek-reasoner"),
        light_model=os.getenv("LLM_MODEL_LIGHT", "deepseek-chat"),
        log_sink=make_ai_log_sink(),
    )


def test_live_explain_and_feynman_evidence():
    from app.ai.calls import ExplainIn, FeynmanEvaluateIn

    gw = _provider()
    out = gw.explain_node(
        ExplainIn(
            session_id="live", node_id="middle.0102", node_title="一元一次方程的求解",
            level="middle", explanation_body="移项要变号：移项本质是等式两边同时加减同一个数。",
            worked_examples=["解方程：2x-7=13"], core_concepts=["移项", "合并同类项"],
            whitelist=["移项", "合并同类项", "等式性质"], profile_style_block="",
        )
    )
    assert out.lecture_md and len(out.lecture_md) > 20

    transcript = "解方程要移项并且移项变号，然后合并同类项把系数化为一，最后代回原方程验根。"
    ev = gw.feynman_evaluate(
        FeynmanEvaluateIn(
            session_id="live", node_id="middle.0102", task_prompt="讲解如何解 3x+5=20",
            rubric_dimensions=[{"key": "correctness", "weight": 0.4}],
            core_concepts=["移项", "合并同类项"], transcript=transcript, previous_round=None,
        )
    )
    assert ev.dimension_scores, "评分必须逐维输出"
    for ds in ev.dimension_scores:
        assert 0.0 <= ds.score <= 1.0
        assert ds.evidence_quote, "每维必须附逐字 evidence_quote（docs/05 §5）"
