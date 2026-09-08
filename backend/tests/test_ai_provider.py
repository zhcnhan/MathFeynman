"""M3 ai.provider 单测：JSON 提取、pydantic 校验、失败重试、鉴权即停、ai_logs sink。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.calls import CALL_EXPLAIN_NODE, AiCallError
from app.ai.provider import OpenAICompatibleProvider, _extract_json

BASE = "http://provider.test/v1"


def _ok_response(content: str, usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }


def make_provider(responses: list[httpx.Response], sink=None) -> OpenAICompatibleProvider:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return OpenAICompatibleProvider(
        api_key="test-key",
        base_url=BASE,
        model_heavy="heavy-model",
        model_light="light-model",
        log_sink=sink,
        transport=httpx.MockTransport(handler),
    )


def make_recorder():
    rec: list[dict] = []

    def sink(entry: dict) -> None:
        rec.append(entry)

    return rec, sink


def _json_resp(content: str, usage=None) -> httpx.Response:
    return httpx.Response(200, json=_ok_response(content, usage))


def test_extract_json_fenced_and_noisy():
    assert _extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert _extract_json("好的，结果如下：\n{\"a\": [1, 2]}  完") == {"a": [1, 2]}
    with pytest.raises(Exception):
        _extract_json("没有 JSON")


def _explain_ok_json() -> str:
    return json.dumps({"lecture_md": "讲解内容 $$x+1$$", "asked_to_confirm": ["1+1=?"]}, ensure_ascii=False)


def test_chat_json_success_validates():
    rec, sink = make_recorder()
    provider = make_provider([_json_resp(_explain_ok_json())], sink=sink)
    outcome = provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])
    assert outcome.parsed["lecture_md"].startswith("讲解内容")
    assert outcome.prompt_tokens == 10 and outcome.completion_tokens == 5
    assert rec and rec[0]["ok"] is True and rec[0]["call_name"] == "explain_node"


def test_chat_json_retries_on_bad_json_then_succeeds():
    provider = make_provider([_json_resp("这不是 JSON"), _json_resp(_explain_ok_json())])
    outcome = provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])
    assert outcome.parsed["asked_to_confirm"] == ["1+1=?"]


def test_chat_json_retries_on_schema_violation_then_succeeds():
    # 第一次输出缺 lecture_md（schema 违规）→ 附错误重试 → 第二次合法
    bad = json.dumps({"asked_to_confirm": []})
    provider = make_provider([_json_resp(bad), _json_resp(_explain_ok_json())])
    outcome = provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])
    assert outcome.parsed["lecture_md"]


def test_chat_json_all_bad_raises_and_logs_failure():
    rec, sink = make_recorder()
    provider = make_provider([_json_resp("坏"), _json_resp("还是坏"), _json_resp("坏透了")], sink=sink)
    with pytest.raises(AiCallError):
        provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}], model="m")
    assert rec and rec[-1]["ok"] is False
    assert rec[-1]["call_name"] == "explain_node"


def test_chat_json_auth_error_stops_immediately():
    provider = make_provider([httpx.Response(401, json={"error": "unauthorized"})])
    with pytest.raises(AiCallError, match="401"):
        provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])


def test_gateway_factory_selects_by_key():
    from app.ai.gateway import OfflineGateway, gateway_factory

    off = gateway_factory(api_key="")
    assert isinstance(off, OfflineGateway)
    on = gateway_factory(api_key="sk-x", base_url=BASE, heavy_model="h", light_model="l")
    assert on.name == "openai-compatible"


# ---- R9 调用点分级 ----
def test_call_tier_assignment_r9():
    """讲解降速档（R9）：explain=light；费曼评分/追问保持 heavy。"""
    from app.ai.calls import CALLS

    assert CALLS["explain_node"].model_tier == "light"
    assert CALLS["feynman_evaluate"].model_tier == "heavy"
    assert CALLS["feynman_followup"].model_tier == "heavy"
    assert CALLS["answer_question"].model_tier == "heavy"


def test_explain_uses_light_model_on_wire():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["model"] = body["model"]
        return _json_resp(_explain_ok_json())

    provider = OpenAICompatibleProvider(
        api_key="k", base_url=BASE, model_heavy="heavy-model", model_light="light-model",
        transport=httpx.MockTransport(handler),
    )
    provider.chat_json(CALL_EXPLAIN_NODE, [{"role": "user", "content": "hi"}])
    assert seen["model"] == "light-model"  # light 档实际打到 light 模型
