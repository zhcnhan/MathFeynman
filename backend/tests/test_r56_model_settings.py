"""R56 第 0 步用例：**模型与 Key 的设置页**（用户点名"程序里本来就没有这个入口"）。

口径（实现见 `service/model_config.py` ＋ `api/settings_api.py`）：
- 存储复用既有 `app_settings` 键值表（**不新建表**）；
- **优先级：页面设置 > `.env` > 内置默认**，每个字段都带"当前值来自哪里"；
- **Key 红线**：接口只回掩码 + `configured`；审计/提示词/账本里都不许出现完整 Key；
- 没配 Key 时，各处统一中文指引"去设置里填"，**不许**再引导改 `.env`。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.service import ai_trace, model_config
from r55_support import cleanup_subjects, make_subject, upload_text_material

PAGE_KEY = "sk-page-wins-0123456789abcd"
ENV_KEY = "sk-env-loses-9876543210fedc"
MAT_TITLE = "测试教材"
MAT_BODY = ("【第 1 页】\n第1章 恒星\n恒星是靠内部核聚变发光发热的球状天体。\n"
            "恒星内部的氢在高温高压下聚变为氦，并释放出巨大的能量。\n")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate_model_settings(app_client):
    """每条用例前后都清空模型配置（整个测试轮共用一份临时库，**不许把 Key 留在库里**）。"""
    from app import models
    from app.db import SessionLocal

    def _clear() -> None:
        with SessionLocal() as db:
            for key in model_config.KEYS:
                row = db.get(models.AppSetting, key)
                if row is not None:
                    db.delete(row)
            db.commit()
        model_config._MEMORY_KEY = ""

    _clear()
    yield
    _clear()


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _RecordingProvider:
    """假 provider：记下**构造时用的 Key**（证明生效配置来自页面设置），并回一份能过校验的大纲。"""

    keys: list[str] = []
    calls: list[list[dict]] = []

    def __init__(self, *, api_key="", base_url="", model_heavy="", model_light="",
                 log_sink=None, transport=None):
        self.api_key = api_key
        type(self).keys.append(api_key)
        type(self).calls.append([])

    def chat_json(self, call, messages, **kw):      # noqa: ARG002
        type(self).calls[-1].append(list(messages))
        return _Outcome({"units": [{
            "title": "恒星的内部", "objectives": ["掌握恒星的内部"], "concept_tags": ["恒星"],
            "group": "教材", "prereqs": [], "difficulty": 1,
            "materials": [{"title": MAT_TITLE, "section": "第1章 恒星"}]}]})


@pytest.fixture
def fake_provider(monkeypatch):
    """把 draft 路径用的 provider 换成假的（**不联网**；只验"用哪份配置"）。"""
    _RecordingProvider.keys = []
    _RecordingProvider.calls = []
    import app.ai.provider as prov

    monkeypatch.setattr(prov, "OpenAICompatibleProvider", _RecordingProvider)
    return _RecordingProvider


def _all_texts(root: Path) -> str:
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            try:
                out.append(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return "\n".join(out)


# ============================================================ ① 未配 Key → 中文指引

def test_r56_0_1_missing_key_points_to_settings_page_not_env(app_client, sids, monkeypatch):
    """未配 Key（也清掉 `.env` 的）→ 需要模型的路径给**中文指引"去设置里填"**，且不提 `.env`。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, MAT_BODY, title=MAT_TITLE)

    r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
    assert r.status_code == 422, r.text
    msg = json.dumps(r.json(), ensure_ascii=False)
    assert "设置" in msg and "模型" in msg, msg
    assert ".env" not in msg and "LLM_API_KEY" not in msg, msg
    # 大纲起草的离线账目也指向设置页
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    reasons = "；".join(str(x.get("reason") or "") for x in rows)
    assert "设置" in reasons and ".env" not in reasons, reasons
    # 视图里给出同一句话（界面直接用）
    view = app_client.get("/api/settings/model").json()
    assert view["configured"] is False
    assert "设置" in view["need_key_zh"] and ".env" not in view["need_key_zh"]


# ============================================================ ② 保存 Key → 只回掩码

def test_r56_0_2_saved_key_never_echoed_only_mask(app_client, monkeypatch):
    """保存 Key → 回读**只有掩码 + configured**；整个响应体里没有完整 Key。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    r = app_client.put("/api/settings/model", json={"api_key": PAGE_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["api_key_masked"] == f"{PAGE_KEY[:3]}…{PAGE_KEY[-4:]}"
    assert PAGE_KEY not in json.dumps(body, ensure_ascii=False)

    got = app_client.get("/api/settings/model").json()
    assert got["configured"] is True and got["api_key_masked"].endswith(PAGE_KEY[-4:])
    assert PAGE_KEY not in json.dumps(got, ensure_ascii=False)
    # 整个设置接口（含 /settings 汇总）都不回显
    all_settings = app_client.get("/api/settings").json()
    assert PAGE_KEY not in json.dumps(all_settings, ensure_ascii=False)
    assert all_settings["model"]["api_key_masked"].endswith(PAGE_KEY[-4:])
    # 清除 Key → configured 变回 false（界面据此显示"未配置"）
    assert app_client.put("/api/settings/model", json={"api_key": ""}).json()["configured"] is False


# ============================================================ ⑤ 优先级：页面 > .env

def test_r56_0_5_page_settings_beat_env(app_client, fake_provider, sids, monkeypatch):
    """页面设置覆盖 `.env`：来源标注为"你在这里设的"，且**真的用页面这份去调模型**。"""
    monkeypatch.setenv("LLM_API_KEY", ENV_KEY)
    monkeypatch.setenv("LLM_MODEL_LIGHT", "env-light-model")
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY, "light": "page-light-model",
                                            "base_url": "https://page.example/v1"})

    view = app_client.get("/api/settings/model").json()
    assert view["api_key_source"] == "page" and view["api_key_source_zh"] == "你在这里设的"
    assert view["light"] == "page-light-model" and view["light_source_zh"] == "你在这里设的"
    assert view["base_url"] == "https://page.example/v1"
    assert view["configured"] is True

    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, MAT_BODY, title=MAT_TITLE)
    r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
    assert r.status_code == 200, r.text
    assert fake_provider.keys and fake_provider.keys[-1] == PAGE_KEY, fake_provider.keys

    # 清掉页面 Key → 立刻回到 `.env` 那份（来源跟着变）
    app_client.put("/api/settings/model", json={"api_key": ""})
    back = app_client.get("/api/settings/model").json()
    assert back["api_key_source"] == "env" and back["configured"] is True
    assert back["api_key_masked"].endswith(ENV_KEY[-4:])
    app_client.put("/api/settings/model", json={"api_key": ""})   # 收尾：不把 .env 那份留在库里
    monkeypatch.setenv("LLM_API_KEY", "")


# ============================================================ ③ Key 不进审计/账本/提示词

def test_r56_0_3_key_never_in_trace_ledger_prompts(app_client, fake_provider, sids, monkeypatch):
    """造一次真实调用（走假 provider，不联网）后：审计全文 / 账本 / 提示词里都搜不到完整 Key。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY})
    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, MAT_BODY, title=MAT_TITLE)
    r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
    assert r.status_code == 200, r.text

    # ① 审计全文目录（conftest 已把它隔离到临时目录）
    trace_dir = ai_trace.trace_dir()
    if trace_dir.exists():
        assert PAGE_KEY not in _all_texts(trace_dir), "审计全文里出现了完整 Key"
    # ② 账本（含"模型配置"这条变更记录）
    rows = app_client.get("/api/ledger").json()["entries"]
    assert PAGE_KEY not in json.dumps(rows, ensure_ascii=False)
    assert PAGE_KEY not in json.dumps(
        app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"], ensure_ascii=False)
    # ③ 发给模型的提示词（假 provider 留下了原文）
    sent = json.dumps(fake_provider.calls, ensure_ascii=False)
    assert PAGE_KEY not in sent, "提示词里出现了完整 Key"
    # ④ 兜底：redact 对"设置页填的 Key"（不带 sk- 前缀也能遮）
    ai_trace.register_secret("my-custom-key-abcdef")
    assert "my-custom-key-abcdef" not in ai_trace.redact("Key=my-custom-key-abcdef（自定义服务商）")
    # ⑤ 账本里那条"模型配置"记录写明"不回显"
    cfg_rows = [x for x in rows if (x.get("detail") or {}).get("kind") == "model_config_changed"]
    assert cfg_rows, "改配置必须记账"
    assert "不回显" in str(cfg_rows[0]["reason"])
    app_client.put("/api/settings/model", json={"api_key": ""})


# ============================================================ ⑥ 改配置进账本且不含明文

def test_r56_0_6_config_change_is_ledgered_without_key_plaintext(app_client):
    """改配置 → 账本一条中文记录（改了哪几项），**不含 Key 明文**（只记后 4 位掩码）。"""
    app_client.put("/api/settings/model", json={"api_key": "", "base_url": "", "heavy": "", "light": ""})
    app_client.put("/api/settings/model", json={"heavy": "deepseek-reasoner-x"})
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY, "max_tokens_per_day": 123456})

    rows = app_client.get("/api/ledger").json()["entries"]
    cfg = [x for x in rows if (x.get("detail") or {}).get("kind") == "model_config_changed"]
    assert len(cfg) >= 2, "每次配置变更都要有账目"
    text = json.dumps(cfg, ensure_ascii=False)
    assert "模型配置" in text and "deepseek-reasoner-x" in text, text
    assert PAGE_KEY not in text, "账本里出现了完整 Key"
    assert cfg[0]["detail"]["api_key_tail"].endswith(PAGE_KEY[-4:])
    # 数字非法 → 中文 422
    bad = app_client.put("/api/settings/model", json={"max_tokens_per_day": "很多"})
    assert bad.status_code == 422 and "数字" in bad.text, bad.text
    app_client.put("/api/settings/model", json={"api_key": "", "max_tokens_per_day": 0})


# ============================================================ ④ 测试连接：成功/失败各一条

def test_r56_0_4a_test_connection_reports_success_in_chinese(app_client, monkeypatch):
    """「测试连接」成功 → 中文报告（含用了哪个模型）。"""
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY, "light": "deepseek-flash"})

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "连接正常"}}]}

    class _Client:
        def post(self, url, json=None):        # noqa: A002
            return _Resp()

    monkeypatch.setattr(model_config, "_test_client", lambda provider: _Client(), raising=False)
    out = app_client.post("/api/settings/model/test").json()
    assert out["ok"] is True, out
    assert "连接正常" in out["reason_zh"] and "deepseek-flash" in out["reason_zh"], out
    app_client.put("/api/settings/model", json={"api_key": ""})


def test_r56_0_4b_test_connection_reports_failure_in_chinese(app_client, monkeypatch):
    """「测试连接」失败 → 中文说清是哪类问题（Key 被拒 / 地址不对 / 连不上），不抛异常。"""
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY, "light": "deepseek-flash"})

    class _Resp:
        status_code = 401
        text = '{"error":{"message":"Authentication Fails"}}'

        @staticmethod
        def json():
            return {}

    class _Client:
        def post(self, url, json=None):        # noqa: A002
            return _Resp()

    monkeypatch.setattr(model_config, "_test_client", lambda provider: _Client(), raising=False)
    out = app_client.post("/api/settings/model/test").json()
    assert out["ok"] is False, out
    assert "Key" in out["reason_zh"] and "401" in out["reason_zh"], out

    # 没配 Key 时也如实说（中文指引去设置页）
    app_client.put("/api/settings/model", json={"api_key": ""})
    none = app_client.post("/api/settings/model/test").json()
    assert none["ok"] is False and "设置" in none["reason_zh"], none


# ============================================================ 附：只存内存不落库

def test_r56_0_7_memory_only_key_is_not_written_to_db(app_client):
    """勾选"只放在内存里" → Key **不落库**（库里查不到），但生效、且视图照实标注。"""
    app_client.put("/api/settings/model", json={"api_key": PAGE_KEY, "memory_only": True})
    view = app_client.get("/api/settings/model").json()
    assert view["configured"] is True and view["memory_only"] is True

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        row = db.get(models.AppSetting, model_config.K_API_KEY)
        assert row is None, "选了只放内存，Key 不该落库"
    # 收尾：清掉内存里的 Key，免得污染后续用例
    app_client.put("/api/settings/model", json={"api_key": "", "memory_only": False})
    assert app_client.get("/api/settings/model").json()["configured"] is False
