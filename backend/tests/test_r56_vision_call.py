"""R56 第 1 步用例：**把教材页/图交给模型读**（方案 A 的最小通路）。

口径：
- 图片按 OpenAI 兼容的 `image_url` data URL 发出去（实测 DeepSeek 收 png/jpeg/webp/gif；
  **PDF 文件本身不收**——这条边界记在 NOTES §79，界面上必须如实说）；
- 走**既有审计链路**（`provider.chat_json` → `ai_trace`）：发了什么、返回什么、token、耗时都能回看；
- 结构化输出经 `ReadPageOut` 校验；
- **诚实出口**：模型说读不出来（`readable=false` + 原因）时，程序原样透出，**不许**当成"读到了空内容"。

这里用 `httpx.MockTransport` 假造接口（**不联网**），只验"消息形态 + 结构化 + 审计"三件事；
真实调用的证据见 `.runtime/r56_real_vision_call.py` 的输出与 NOTES §79。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.calls import CALL_READ_PAGE
from app.ai.provider import OpenAICompatibleProvider
from app.ai.vision import ALLOWED_IMAGE_MIME, image_block, read_page
from app.service import ai_trace

PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
           "BQIAX8jx0gAAAABJRU5ErkJggg==")


class _Sink:
    """收集审计元数据（真实链路里 sink 是**可调用对象**，把索引写进 `ai_logs`）。"""

    def __init__(self):
        self.rows: list[dict] = []

    def __call__(self, entry: dict) -> None:
        self.rows.append(dict(entry))


def _provider(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="sk-test-r56", base_url="https://example.invalid/v1",
        model_heavy="heavy-x", model_light="light-x", log_sink=_Sink(),
        transport=httpx.MockTransport(handler),
    )


def test_r56_1_image_block_is_openai_compatible_data_url():
    """图片块形态：`image_url` + data URL；格式白名单之外**中文报错**（不静默发错）。"""
    block = image_block(PNG_1PX, mime="image/png")
    assert block["type"] == "image_url"
    assert block["image_url"]["url"].startswith("data:image/png;base64,")
    assert block["image_url"]["url"].endswith(PNG_1PX)
    assert image_block(b"\x89PNG", mime="image/jpeg")["image_url"]["url"].startswith("data:image/jpeg")
    for mime in ALLOWED_IMAGE_MIME:
        assert image_block(b"x", mime=mime)["type"] == "image_url"
    with pytest.raises(ValueError) as e:
        image_block(b"x", mime="application/pdf")
    assert "图片格式" in str(e.value)


def test_r56_1_read_page_sends_image_and_returns_structured_result():
    """一次读页调用：**请求里真的有图片块**、返回经 schema 校验、审计记下 token/耗时/提示词版本。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.update(body)
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "page_label": "第 12 页", "readable": True, "unreadable_reason": "",
                "key_points": ["太阳系由太阳和八颗行星组成"],
                "visible_text": ["图 1.1 太阳系示意图"],
                "formulas": ["a^2+b^2=c^2"],
                "figures": [{"label": "图 1.1", "kind": "示意图",
                             "description": "中心是太阳，外围是行星轨道"}],
                "uncertain": ["右下角小字看不清"], "confidence": 0.8,
            }, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120},
        })

    sink = _Sink()
    provider = OpenAICompatibleProvider(
        api_key="sk-test-r56", base_url="https://example.invalid/v1",
        model_heavy="heavy-x", model_light="light-x", log_sink=sink,
        transport=httpx.MockTransport(handler))
    out, version = read_page(
        provider, images=[image_block(PNG_1PX, mime="image/png")],
        page_label="第 12 页", want="这一页的正文要点与图", note="扫描页", subject_id="s-x")

    assert out.readable is True and out.page_label == "第 12 页"
    assert out.key_points and out.figures[0]["label"] == "图 1.1"
    assert out.confidence == 0.8 and out.uncertain
    # 消息形态：system + user（文本块 + 图片块），图片块在消息里真的发出去了
    msgs = seen["messages"]
    assert msgs[0]["role"] == "system"
    kinds = [b["type"] for b in msgs[1]["content"]]
    assert kinds == ["text", "image_url"], kinds
    assert msgs[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    # 结构化输出（JSON 模式）+ 审计（token/耗时/提示词版本/结局）
    assert seen["response_format"] == {"type": "json_object"}
    assert version, "提示词版本标签必须带上（审计要能对照是哪一版提示词）"
    assert sink.rows, "每次调用都必须留审计元数据"
    assert sink.rows[-1]["prompt_tokens"] == 900
    assert sink.rows[-1]["call_name"] == CALL_READ_PAGE.name
    assert sink.rows[-1]["ok"] is True
    assert sink.rows[-1]["prompt_versions"] == version
    assert sink.rows[-1]["trace_path"], "审计全文文件路径也要留下（可回看完整 prompt/返回）"


def test_r56_1_unreadable_page_must_say_so_not_fake_content():
    """**诚实出口**：模型读不出来时，结构化结果必须带中文原因，程序**原样透出**（不伪造内容）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "page_label": "第 40 页", "readable": False,
                "unreadable_reason": "整页是一张模糊的扫描图，字太小且被水印盖住，读不出正文",
                "key_points": [], "visible_text": [], "formulas": [], "figures": [],
                "uncertain": ["只能看出页面上有一张剖面图"], "confidence": 0.1,
            }, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 60},
        })

    out, _ = read_page(_provider(handler), images=[image_block(PNG_1PX, mime="image/png")],
                       page_label="第 40 页", subject_id="s-x")
    assert out.readable is False
    assert "读不出" in out.unreadable_reason or "看不清" in out.unreadable_reason
    assert out.key_points == [] and out.confidence < 0.3
    # 读不出来**不等于**报错：调用本身是成功的（审计里 ok=True），只是内容为空 + 原因
    assert out.unreadable_reason.strip()


def test_r56_1_key_never_leaks_into_messages_or_trace(tmp_path, monkeypatch):
    """审计全链路里不出现 Key：请求体只有图片+文本，审计全文里只有 prompt/返回。"""
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(tmp_path))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"readable":true,"key_points":["x"]}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    provider = OpenAICompatibleProvider(
        api_key="sk-secret-r56-key", base_url="https://example.invalid/v1",
        model_heavy="h", model_light="l", log_sink=None,
        transport=httpx.MockTransport(handler))
    read_page(provider, images=[image_block(PNG_1PX)], page_label="第 1 页")
    assert "sk-secret-r56-key" not in json.dumps(seen, ensure_ascii=False)
    files = list(tmp_path.rglob("*.txt"))
    for f in files:
        assert "sk-secret-r56-key" not in f.read_text(encoding="utf-8")
