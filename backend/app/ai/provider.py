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
        audit: dict | None = None,    # R39 §3：{subject_id, unit_id, prompt_versions}
    ) -> ChatOutcome:
        """调用 + JSON 提取 + pydantic 校验 + 失败重试（≤ max_retries）。

        R39 §3：**每次调用一条审计**——渲染后的 system/user、原始返回、解析/校验结果、
        重试次数、token、耗时、最终结局，全部经 ``service.ai_trace`` 落档（全文落文件，
        DB 只存路径+预览+字符数）。
        """
        sink = log_sink or self.log_sink
        if model is None:
            model = self.model_for_strategy(strategy) if strategy else self.model_for(call.model_tier)
        effective_model = model
        log_tier = strategy or call.model_tier
        audit = dict(audit or {})
        subject_id = str(audit.get("subject_id") or "")
        unit_id = str(audit.get("unit_id") or "")
        prompt_versions = str(audit.get("prompt_versions") or "")
        attempts = 0
        last_error = ""
        last_usage: dict = {}
        last_latency = 0
        last_raw = ""
        total_latency = 0
        # R39 §1：**日限额拦截必须显性**（账本 + 审计各留一条，绝不静默不调用模型）
        cap = self.daily_token_cap()
        if cap > 0:
            used = self.tokens_used_today()
            if used >= cap:
                reason = (f"当日 token 额度已用尽（已用 {used} / 上限 {cap}），"
                          "本次未调用模型——请在 .env 调整 LLM_MAX_TOKENS_PER_DAY 或次日再试。")
                self._record_cap_blocked(call, reason, subject_id, unit_id, prompt_versions, sink)
                raise AiCallError(call.name, reason=reason)
        # R39 §3 的"每次调用一条"：整个重试循环合成**一条**（含 retries 与最终结局）
        first_messages = list(messages)
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
                    total_latency += latency
                    resp.raise_for_status()
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage", {})
                    last_usage = usage
                    last_latency = latency
                    last_raw = content
                    parsed = _extract_json(content)
                    validated = call.output_schema.model_validate(parsed)  # 校验再生效
                    # pydantic 校验通过前不得落库/生效：这里只做校验与规范化
                    out_dict = validated.model_dump()
                    self._audit(call, sink, first_messages, {
                        "call_name": call.name, "model": effective_model, "tier": log_tier,
                        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                        "ok": True, "error": None, "latency_ms": total_latency,
                        "subject_id": subject_id, "unit_id": unit_id,
                        "retries": attempts - 1, "outcome": "adopted",
                        "prompt_versions": prompt_versions,
                        "raw": content, "parsed": out_dict, "parse_error": "",
                    })
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
                    latency = int((time.monotonic() - t0) * 1000)
                    last_latency = latency
                    total_latency += latency
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
                        break  # 鉴权错误重试无意义
                    if attempts > call.max_retries:
                        break
                    continue  # 网络抖动 → 立即重试
                except (AiParseError, ValidationError, KeyError, IndexError, TypeError) as e:
                    last_error = f"输出校验失败: {e}"
                    latency = int((time.monotonic() - t0) * 1000)
                    last_latency = latency
                    total_latency += latency
                    messages = _messages_with_fix(messages, last_error)
            # 重试耗尽
        self._audit(call, sink, first_messages, {
            "call_name": call.name, "model": effective_model, "tier": log_tier,
            "prompt_tokens": int(last_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(last_usage.get("completion_tokens", 0) or 0),
            "ok": False, "error": last_error, "latency_ms": total_latency or last_latency,
            "subject_id": subject_id, "unit_id": unit_id,
            "retries": max(0, attempts - 1), "outcome": "failed",
            "prompt_versions": prompt_versions,
            "raw": last_raw, "parsed": None, "parse_error": last_error,
        })
        raise AiCallError(call.name, reason=last_error)

    # ---- R39 §1：日限额拦截（显性化，绝不静默） ----
    def daily_token_cap(self) -> int:
        """R39 §1：**日限额**（``LLM_MAX_TOKENS_PER_DAY``；0/空 = 不限）。"""
        try:
            from ..config import get_settings

            return max(0, int(get_settings().llm_max_tokens_per_day or 0))
        except Exception:
            return 0

    def tokens_used_today(self) -> int:
        """今日已用 token（读 ``ai_logs``；读不到 → 0，不阻塞）。"""
        try:
            import datetime as _dt

            from sqlalchemy import func, select

            from .. import models
            from ..db import SessionLocal

            start = _dt.datetime.combine(_dt.datetime.utcnow().date(), _dt.time.min)
            with SessionLocal() as db:
                stmt = select(func.coalesce(func.sum(models.AiLog.prompt_tokens), 0)
                              + func.coalesce(func.sum(models.AiLog.completion_tokens), 0)).where(
                    models.AiLog.created_at >= start)
                return int(db.execute(stmt).scalar() or 0)
        except Exception:
            return 0

    def _record_cap_blocked(self, call: CallSpec, reason: str, subject_id: str, unit_id: str,
                            prompt_versions: str, sink: LogSink | None) -> None:
        """日限额拦截 → 账本 + 审计各一条（用户界面能看见，不是只写日志）。"""
        try:
            from ..service import ledger

            ledger.note(ledger.CAT_MODEL_CALL, f"模型调用（{call.name}）", reason,
                        impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_CONFIRM,
                        subject_id=subject_id, unit_id=unit_id,
                        detail={"call_name": call.name, "kind": "daily_token_cap"})
        except Exception:
            pass
        try:
            from ..service import ai_trace

            ai_trace.write_trace(
                call_name=call.name, system="", user="", raw="", parsed=None,
                parse_error=reason, retries=0, ok=False, model="", tier=call.model_tier,
                latency_ms=0, prompt_tokens=0, completion_tokens=0,
                outcome=ai_trace.OUTCOME_FAILED, subject_id=subject_id, unit_id=unit_id,
                prompt_versions=prompt_versions, sink=sink)
        except Exception:
            pass

    @staticmethod
    def _audit(call: CallSpec, sink: LogSink | None, messages: Sequence[dict],
               entry: dict) -> None:
        """R39 §3：写审计全文文件 + 元数据入 ``ai_logs``（记录**不得阻塞**主流程）。"""
        system = ""
        user = ""
        for m in messages or []:
            if m.get("role") == "system" and not system:
                system = str(m.get("content") or "")
            elif m.get("role") == "user" and not user:
                user = str(m.get("content") or "")
        try:
            from ..service import ai_trace

            ai_trace.write_trace(
                call_name=str(entry.get("call_name") or call.name), system=system, user=user,
                raw=str(entry.get("raw") or ""), parsed=entry.get("parsed"),
                parse_error=str(entry.get("parse_error") or ""),
                retries=int(entry.get("retries") or 0), ok=bool(entry.get("ok")),
                model=str(entry.get("model") or ""), tier=str(entry.get("tier") or ""),
                latency_ms=int(entry.get("latency_ms") or 0),
                prompt_tokens=int(entry.get("prompt_tokens") or 0),
                completion_tokens=int(entry.get("completion_tokens") or 0),
                outcome=str(entry.get("outcome") or "adopted"),
                subject_id=str(entry.get("subject_id") or ""),
                unit_id=str(entry.get("unit_id") or ""),
                prompt_versions=str(entry.get("prompt_versions") or ""),
                sink=sink,
            )
            return
        except Exception:  # 审计路径任何异常都不得影响生成
            pass
        if sink:  # 最兜底：至少留元数据
            try:
                sink({k: v for k, v in entry.items() if k not in ("raw", "parsed", "parse_error")})
            except Exception:
                pass


__all__ = ["OpenAICompatibleProvider", "ChatOutcome", "LogSink", "_extract_json"]
