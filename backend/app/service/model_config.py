"""service.model_config：**模型与 Key 的运行时配置**（设置页可改；R56 第 0 步）。

口径：
- **存储复用既有 `app_settings` 键值表**（键前缀 ``model.``）——不新建表、不新建第二套配置机制；
- **优先级：页面设置 > `.env` > 内置默认**（与 R38 预算滑块的优先级口径一致），
  每个字段都带 ``source``（``page`` / ``env`` / ``default``）+ 中文来源标签，界面照实显示；
- **Key 红线**（与 R39 同款纪律）：
  - 对外视图**只回** ``configured`` 布尔 + **掩码**（前 3 位 + 后 4 位），**永不回显完整 Key**；
  - 每次解析出 Key 都登记进 `ai_trace.register_secret` → 审计全文里出现即被遮蔽；
  - 配置变更**记入唯一账本**（中文：改了哪几项，**不含 Key 明文**，只记后 4 位）；
  - 可选"**只存内存不落库**"（``model.key_memory_only``）：Key 只活在进程内存里，重启要重填。
- **没配 Key 时**：程序各处统一用 `NEED_KEY_ZH` 这句中文指引（"去设置里填"），**不再**引导改 `.env`。
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from typing import Any

from .. import models
from ..config import Settings, get_settings

# ---- app_settings 键（前缀 model.） ----
K_PROVIDER = "model.provider"
K_API_KEY = "model.api_key"
K_BASE_URL = "model.base_url"
K_HEAVY = "model.heavy"
K_LIGHT = "model.light"
K_DAILY = "model.max_tokens_per_day"
K_MEMORY_ONLY = "model.key_memory_only"

KEYS = (K_PROVIDER, K_API_KEY, K_BASE_URL, K_HEAVY, K_LIGHT, K_DAILY, K_MEMORY_ONLY)

# ---- 内置默认（服务商默认 DeepSeek；OpenAI 兼容） ----
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_HEAVY = "deepseek-reasoner"
DEFAULT_LIGHT = "deepseek-chat"
DEFAULT_PROVIDER = "deepseek"

PROVIDER_LABELS_ZH = {"deepseek": "DeepSeek（默认）", "custom": "自定义（OpenAI 兼容）"}
SOURCE_LABELS_ZH = {"page": "你在这里设的", "env": ".env 配置", "default": "程序默认"}

# 没配 Key 时给用户看的唯一一句话（各处引用同一常量，口径不许分叉）
NEED_KEY_ZH = "还没有配模型 Key，去「设置 · 模型」里填一下就能用 AI 了（不用改配置文件）。"
NEED_KEY_SHORT_ZH = "还没有配模型 Key —— 去「设置 · 模型」里填一下"

# 只存内存的 Key（进程内；不落库。重启程序就要重填——界面如实说明）
_MEMORY_KEY: str = ""


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def _rows(db) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for key in KEYS:
            row = db.get(models.AppSetting, key)
            if row is not None and str(row.value or "").strip():
                out[key] = str(row.value).strip()
    except Exception:      # 表还没建/库不可用 → 一律按"页面没设"处理（退回 .env / 默认）
        return {}
    return out


def _memory_only(db) -> bool:
    try:
        return _rows(db).get(K_MEMORY_ONLY, "0") == "1"
    except Exception:
        return False


@dataclass
class Field:
    """一个生效值 + 它从哪来。"""

    value: Any
    source: str          # page | env | default

    @property
    def source_zh(self) -> str:
        return SOURCE_LABELS_ZH.get(self.source, self.source)


def _pick(rows: dict[str, str], key: str, env_value: Any, default: Any) -> Field:
    """页面 > .env > 默认（空串/None 视为"没设"）。"""
    page = rows.get(key)
    if page not in (None, ""):
        return Field(page, "page")
    if env_value not in (None, "", 0):
        return Field(env_value, "env")
    return Field(default, "default")


def resolve(db=None) -> dict[str, Field]:
    """生效的模型配置（**含完整 Key**——只在服务端内部用；对外一律走 `view()`）。"""
    own = db is None
    if own:
        from ..db import SessionLocal

        with SessionLocal() as session:
            return _resolve_with(session)
    return _resolve_with(db)


def _resolve_with(db) -> dict[str, Field]:
    rows = _rows(db)
    s = get_settings()
    memory_only = rows.get(K_MEMORY_ONLY, "0") == "1"
    page_key = rows.get(K_API_KEY, "")
    if memory_only:
        key = _MEMORY_KEY or s.llm_api_key
        key_source = "page" if _MEMORY_KEY else ("env" if s.llm_api_key else "default")
    else:
        key = page_key or s.llm_api_key
        key_source = "page" if page_key else ("env" if s.llm_api_key else "default")
    return {
        "provider": _pick(rows, K_PROVIDER, "", DEFAULT_PROVIDER),
        "api_key": Field(key or "", key_source),
        "base_url": _pick(rows, K_BASE_URL, s.llm_base_url if _env_set("LLM_BASE_URL") else "",
                          DEFAULT_BASE_URL),
        "heavy": _pick(rows, K_HEAVY, s.llm_model_heavy if _env_set("LLM_MODEL_HEAVY") else "",
                       DEFAULT_HEAVY),
        "light": _pick(rows, K_LIGHT, s.llm_model_light if _env_set("LLM_MODEL_LIGHT") else "",
                       DEFAULT_LIGHT),
        "max_tokens_per_day": _pick(
            rows, K_DAILY,
            s.llm_max_tokens_per_day if _env_set("LLM_MAX_TOKENS_PER_DAY") else 0, 0),
        "memory_only": Field("1" if memory_only else "0",
                             "page" if K_MEMORY_ONLY in rows else "default"),
    }


def _env_set(name: str) -> bool:
    import os

    return (os.getenv(name) or "").strip() != ""


def effective_settings(db=None) -> Settings:
    """把生效配置套进既有 `Settings`（其余字段原样）——**各调用点唯一的读取入口**。

    这样"页面设置 > .env > 默认"对所有既有的 ``settings.llm_api_key`` 判断一次性生效，
    不必在各处再写一套优先级。
    """
    r = resolve(db)
    key = str(r["api_key"].value or "")
    if key:
        from . import ai_trace

        ai_trace.register_secret(key)      # 审计兜底：这个 Key 一旦出现在全文里就被遮蔽
    try:
        daily = int(str(r["max_tokens_per_day"].value or 0) or 0)
    except Exception:
        daily = 0
    return dataclasses.replace(
        get_settings(),
        llm_api_key=key,
        llm_base_url=str(r["base_url"].value or DEFAULT_BASE_URL),
        llm_model_heavy=str(r["heavy"].value or DEFAULT_HEAVY),
        llm_model_light=str(r["light"].value or DEFAULT_LIGHT),
        llm_max_tokens_per_day=max(0, daily),
    )


def configured(db=None) -> bool:
    return bool(str(resolve(db)["api_key"].value or "").strip())


def mask(key: str) -> str:
    """掩码：前 3 位 + … + 后 4 位（长度不足只回后 4 位；**绝不回完整 Key**）。"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "…" + k[-2:]
    return f"{k[:3]}…{k[-4:]}"


def view(db=None) -> dict:
    """**对外视图**（接口/界面用）：只有掩码 + configured，绝不回完整 Key。"""
    r = resolve(db)
    key = str(r["api_key"].value or "")
    provider = str(r["provider"].value or DEFAULT_PROVIDER)
    if provider not in PROVIDER_LABELS_ZH:
        provider = DEFAULT_PROVIDER
    return {
        "provider": provider,
        "provider_label": PROVIDER_LABELS_ZH[provider],
        "providers": [{"key": k, "label": v} for k, v in PROVIDER_LABELS_ZH.items()],
        "configured": bool(key),
        "api_key_masked": mask(key),
        "api_key_source": r["api_key"].source,
        "api_key_source_zh": r["api_key"].source_zh,
        "memory_only": str(r["memory_only"].value) == "1",
        "base_url": str(r["base_url"].value or DEFAULT_BASE_URL),
        "base_url_source_zh": r["base_url"].source_zh,
        "heavy": str(r["heavy"].value or DEFAULT_HEAVY),
        "heavy_source_zh": r["heavy"].source_zh,
        "light": str(r["light"].value or DEFAULT_LIGHT),
        "light_source_zh": r["light"].source_zh,
        "max_tokens_per_day": int(str(r["max_tokens_per_day"].value or 0) or 0),
        "daily_source_zh": r["max_tokens_per_day"].source_zh,
        # 界面照实写明的安全提示（docs/13 §2：说人话）
        "key_notice_zh": ("Key 存在这台机器的本地数据里，别把这份数据文件发给别人；"
                          "也可以勾选「只放在内存里」，那样关掉程序就要重填。"),
        "need_key_zh": NEED_KEY_ZH,
    }


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
UNSET = object()


def _set(db, key: str, value: str) -> None:
    row = db.get(models.AppSetting, key)
    if row is None:
        db.add(models.AppSetting(key=key, value=value))
    else:
        row.value = value


def save(db, *, provider: Any = UNSET, api_key: Any = UNSET, base_url: Any = UNSET,
         heavy: Any = UNSET, light: Any = UNSET, max_tokens_per_day: Any = UNSET,
         memory_only: Any = UNSET, subject_id: str = "") -> dict:
    """保存模型配置（只改传进来的项）；**变更记入唯一账本**（中文，不含 Key 明文）。

    返回对外视图（掩码 + configured）。``api_key=""`` 表示**清除** Key。
    """
    global _MEMORY_KEY
    rows_before = _rows(db)
    changed: list[str] = []
    key_updated = False

    def _apply(field_key: str, value: Any, label: str) -> None:
        if value is UNSET:
            return
        text = str(value).strip() if value is not None else ""
        old = rows_before.get(field_key, "")
        if text == old:
            return
        changed.append(f"{label}：{old or '（没设）'} → {text or '（清空，改用 .env/默认）'}")
        if text:
            _set(db, field_key, text)
        else:
            row = db.get(models.AppSetting, field_key)
            if row is not None:
                db.delete(row)

    if provider is not UNSET:
        prov = str(provider or "").strip() or DEFAULT_PROVIDER
        if prov not in PROVIDER_LABELS_ZH:
            from ..outline.schemas import OutlineError

            raise OutlineError(f"服务商只能是：{'、'.join(PROVIDER_LABELS_ZH.values())}")
        _apply(K_PROVIDER, prov, "服务商")
    _apply(K_BASE_URL, base_url, "服务地址")
    _apply(K_HEAVY, heavy, "模型名（深）")
    _apply(K_LIGHT, light, "模型名（快）")
    if max_tokens_per_day is not UNSET:
        raw = str(max_tokens_per_day).strip() if max_tokens_per_day is not None else "0"
        try:
            daily = max(0, int(float(raw or 0)))
        except Exception:
            from ..outline.schemas import OutlineError

            raise OutlineError("每天最多用多少 token 必须是数字（0 = 不限）")
        _apply(K_DAILY, str(daily) if daily else "", "每天最多用多少")
    if memory_only is not UNSET:
        _apply(K_MEMORY_ONLY, "1" if memory_only else "", "Key 是否只放在内存里")

    # Key 单独处理：选了"只放内存" → **绝不落库**（并清掉库里原来那份）
    if api_key is not UNSET:
        text = str(api_key or "").strip()
        mem = (str(memory_only).strip() not in ("", "0", "False", "false")
               if memory_only is not UNSET else _memory_only(db))
        if mem:
            if text != _MEMORY_KEY:
                key_updated = True
                changed.append(f"模型 Key（{'已清除' if not text else '已更新'}，不回显）")
            _MEMORY_KEY = text
            row = db.get(models.AppSetting, K_API_KEY)
            if row is not None:                      # 从"落库"切成"只放内存" → 清掉库里的
                db.delete(row)
        else:
            _MEMORY_KEY = ""
            old = rows_before.get(K_API_KEY, "")
            if text != old:
                key_updated = True
                changed.append(f"模型 Key（{'已清除' if not text else '已更新'}，不回显）")
            if text:
                _set(db, K_API_KEY, text)
            else:
                row = db.get(models.AppSetting, K_API_KEY)
                if row is not None:
                    db.delete(row)

    db.commit()
    if changed:
        from . import ledger

        ledger.note(
            ledger.CAT_OTHER, "模型配置",
            "改了模型设置：" + "；".join(changed) + "。Key 本身不回显（只记后 4 位）。",
            impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_YES, subject_id=subject_id,
            detail={"kind": "model_config_changed", "fields": changed,
                    "api_key_tail": mask(str(resolve(db)["api_key"].value or "")) if key_updated else "",
                    "memory_only": _memory_only(db)},
        )
    return view(db)


# ---------------------------------------------------------------------------
# 测试连接（发一次最小请求；中文报告成功/失败原因）
# ---------------------------------------------------------------------------
TEST_PROMPT = "请只回复四个字：连接正常"


def _test_client(provider):
    """发测试请求用的 HTTP 客户端（单独一个函数：测试可替换它，不触网）。"""
    return provider._client()


def test_connection(db=None, *, transport=None) -> dict:
    """发一次最小请求验证"能不能用"。失败也给**中文原因**（不抛异常给界面）。"""
    r = resolve(db)
    key = str(r["api_key"].value or "")
    if not key:
        return {"ok": False, "reason_zh": NEED_KEY_ZH, "model": "", "latency_ms": 0}
    from ..ai.provider import OpenAICompatibleProvider

    model = str(r["light"].value or DEFAULT_LIGHT)
    started = time.time()
    try:
        provider = OpenAICompatibleProvider(
            api_key=key,
            base_url=str(r["base_url"].value or DEFAULT_BASE_URL),
            model_heavy=str(r["heavy"].value or DEFAULT_HEAVY),
            model_light=model,
            log_sink=None,
            transport=transport,
        )
        client = _test_client(provider)
        resp = client.post(
            "/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": TEST_PROMPT}],
                  "max_tokens": 16, "stream": False},
        )
        latency = int((time.time() - started) * 1000)
        if resp.status_code >= 400:
            return {"ok": False, "model": model, "latency_ms": latency,
                    "reason_zh": _http_reason_zh(resp.status_code, resp.text)}
        data = resp.json()
        text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return {"ok": True, "model": model, "latency_ms": latency,
                "reason_zh": f"连接正常（模型 {model} 有回应：{text[:40] or '（空回复）'}）"}
    except Exception as e:
        return {"ok": False, "model": model,
                "latency_ms": int((time.time() - started) * 1000),
                "reason_zh": _exception_reason_zh(e)}


def _http_reason_zh(status: int, body: str) -> str:
    tail = (body or "").strip()[:160]
    if status in (401, 403):
        return f"Key 被拒了（HTTP {status}）：请检查 Key 是否填对、是否过期。{tail}"
    if status == 404:
        return (f"服务地址或模型名不对（HTTP 404）：请检查服务地址与模型名。{tail}")
    if status == 429:
        return f"请求太频繁或额度用完（HTTP 429）：稍后再试，或检查账户余额。{tail}"
    if status >= 500:
        return f"对方服务出错了（HTTP {status}）：多半是暂时的，稍后再试。{tail}"
    return f"连接失败（HTTP {status}）：{tail}"


def _exception_reason_zh(e: Exception) -> str:
    name = type(e).__name__
    text = str(e)
    if "connect" in name.lower() or "Connect" in text or "getaddrinfo" in text:
        return f"连不上服务地址（{name}）：请检查网络与服务地址是否写对。{text[:120]}"
    if "timeout" in name.lower() or "Timeout" in text:
        return f"请求超时（{name}）：网络慢或对方没响应，稍后再试。{text[:120]}"
    return f"测试连接失败（{name}）：{text[:160]}"


__all__ = [
    "K_PROVIDER", "K_API_KEY", "K_BASE_URL", "K_HEAVY", "K_LIGHT", "K_DAILY", "K_MEMORY_ONLY",
    "DEFAULT_BASE_URL", "DEFAULT_HEAVY", "DEFAULT_LIGHT", "DEFAULT_PROVIDER",
    "PROVIDER_LABELS_ZH", "SOURCE_LABELS_ZH", "NEED_KEY_ZH", "NEED_KEY_SHORT_ZH",
    "Field", "UNSET", "resolve", "effective_settings", "configured", "mask", "view", "save",
    "test_connection",
]
