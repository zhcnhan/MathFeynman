"""app.ai.provider：LLM Provider（docs/02 §4、05 §6）。

chat_json(call, messages)：
  1. 拼 OpenAI 兼容请求（base_url/model 按 tier/配置）；
  2. response_format json_object + 后处理剥离围栏；
  3. pydantic 校验输出 → 失败重试 ≤ max_retries（重试附错误信息要求修正）；
  4. 仍失败 → 抛 AiCallError。

- 传输用 httpx.Client（可注入 MockTransport 测试）。
- ai 层不碰 DB：日志经调用方注入的 sink（见 service.ai_sink）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Sequence

import httpx
from pydantic import BaseModel, ValidationError

from .calls import AiCallError, CallSpec

JSON_MODE = "json_object"
_MODEL_TIMEOUT_S = 90.0

LogSink = Callable[[dict], None]


class AiParseError(ValueError):
    """LLM 输出无法解析为 JSON。"""


@dataclass
class ChatOutcome:
    parsed: dict
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    raw: str = ""


def _extract_json(content: str) -> dict:
    """剥离 ```json 围栏与前后噪声，取首个 {…} 块解析。"""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        text = "\n".join(lines)
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AiParseError(f"输出中未找到 JSON 对象: {content[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise AiParseError(f"JSON 解析失败: {e}") from e


def _messages_with_fix(messages: Sequence[dict], error_note: str) -> list[dict]:
    """重试：附上错误信息要求修正（docs/05 §6 step3）。"""
    return [
        *messages,
        {
            "role": "user",
            "content": f"[系统校验失败] 你的上一条输出未通过结构校验：{error_note}。"
            "请严格按要求的 JSON 结构重新输出（只输出 JSON，不要解释）。",
        },
    ]


class OpenAICompatibleProvider:
    """OpenAI 兼容 chat completions 客户端（DeepSeek/ollama/Qwen 等）。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_heavy: str,
        model_light: str,
        log_sink: LogSink | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_heavy = model_heavy
        self.model_light = model_light
        self.log_sink = log_sink
        self._transport = transport

    def model_for(self, tier: str) -> str:
        return self.model_heavy if tier == "heavy" else self.model_light

    def model_for_strategy(self, strategy: str) -> str:
        """R12：策略档 → 模型。fast→light 档模型；think→heavy 档（深度推理）模型。"""
        return self.model_heavy if strategy == "think" else self.model_light

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=_MODEL_TIMEOUT_S,
            transport=self._transport,
        )

    def chat_json(
        self,
        call: CallSpec,
        messages: Sequence[dict],
        *,
        model: str | None = None,
        strategy: str | None = None,  # R12：fast|think → 覆盖 model 选择；空=按 call.tier
        log_sink: LogSink | None = None,
    ) -> ChatOutcome:
        """调用 + JSON 提取 + pydantic 校验 + 失败重试（≤ max_retries）。"""
        sink = log_sink or self.log_sink
        if model is None:
            model = self.model_for_strategy(strategy) if strategy else self.model_for(call.model_tier)
        effective_model = model
        log_tier = strategy or call.model_tier
        attempts = 0
        last_error = ""
        last_usage: dict = {}
        last_latency = 0
        with self._client() as client:
            while attempts <= call.max_retries:
                attempts += 1
                t0 = time.monotonic()
                try:
                    resp = client.post(
                        "/chat/completions",
                        json={
                            "model": effective_model,
                            "messages": list(messages),
                            "temperature": call.temperature,
                            "response_format": {"type": JSON_MODE},
                        },
                    )
                    latency = int((time.monotonic() - t0) * 1000)
                    resp.raise_for_status()
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage", {})
                    last_usage = usage
                    last_latency = latency
                    parsed = _extract_json(content)
                    validated = call.output_schema.model_validate(parsed)  # 校验再生效
                    # pydantic 校验通过前不得落库/生效：这里只做校验与规范化
                    out_dict = validated.model_dump()
                    if sink:
                        sink(
                            {
                                "call_name": call.name,
                                "model": effective_model,
                                "tier": log_tier,
                                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                                "ok": True,
                                "error": None,
                                "latency_ms": latency,
                            }
                        )
                    return ChatOutcome(
                        parsed=out_dict,
                        model=effective_model,
                        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                        latency_ms=latency,
                        raw=content,
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    last_error = f"HTTP 错误: {e}"
                    last_latency = int((time.monotonic() - t0) * 1000)
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
                        break  # 鉴权错误重试无意义
                    if attempts > call.max_retries:
                        break
                    continue  # 网络抖动 → 立即重试
                except (AiParseError, ValidationError, KeyError, IndexError, TypeError) as e:
                    last_error = f"输出校验失败: {e}"
                    last_latency = int((time.monotonic() - t0) * 1000)
                    messages = _messages_with_fix(messages, last_error)
            # 重试耗尽
        if sink:
            sink(
                {
                    "call_name": call.name,
                    "model": effective_model,
                    "tier": log_tier,
                    "prompt_tokens": int(last_usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(last_usage.get("completion_tokens", 0) or 0),
                    "ok": False,
                    "error": last_error,
                    "latency_ms": last_latency,
                }
            )
        raise AiCallError(call.name, reason=last_error)


__all__ = ["OpenAICompatibleProvider", "ChatOutcome", "LogSink", "_extract_json"]
