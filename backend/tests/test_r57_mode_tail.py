"""R57 任务 B 用例：**本模式一键大纲起草** + **设置页「读图用的模型」**。

工单 §3.1：
① 本模式一键起草大纲可用，且**不调**路径②的闸门（AST/哨兵同 R56 做法）；
② 设置页能改「读图用的模型」，保存后**生效并可回读来源**；未设时**跟随文本模型**。
"""
from __future__ import annotations

import ast
import base64
from pathlib import Path

import pytest

from app.service import model_config
from r55_support import cleanup_subjects, make_subject

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider：读页 / 排大纲两种返回；记录调用点顺序。"""

    def __init__(self, *, units: list[dict] | None = None):
        self.units = units or [
            {"title": "样张这一页", "objectives": ["说清这一页写了什么"],
             "concept_tags": ["样张"], "source_pages": ["第 1 页"]}]
        self.calls: list[str] = []

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        self.calls.append(call.name)
        if call.name == "read_page":
            return _Outcome({"page_label": "第 1 页", "readable": True,
                             "key_points": ["太阳系由太阳和八颗行星组成"],
                             "visible_text": ["8"], "figures": [], "uncertain": [],
                             "confidence": 0.9})
        if call.name == "mode_outline":
            return _Outcome({"units": self.units, "uncertain": False, "uncertain_reason": ""})
        raise AssertionError(f"没预设这个调用点的返回：{call.name}")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
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
    monkeypatch.setenv("MF_PDF_CACHE_DIR", str(tmp_path / "pdf_cache"))
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r57b")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    yield
    _clear()


def _mode_subject_with_one_page(app_client, sids, monkeypatch) -> tuple[str, object]:
    import app.outline.mode_pages as mp

    fake = _FakeProvider()
    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    sid = make_subject(app_client, sids)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "样张教材"},
                        files=[("files", ("p1.png", PNG_1PX, "image/png"))])
    assert r.status_code == 201, r.text
    return sid, fake


# ============================================================ ① 一键起草大纲

def test_r57_b1_mode_outline_one_click_and_no_book_gates(app_client, sids, monkeypatch):
    """一键起草：走 `mode_outline`；**不调**路径②的教材锚定/可答性/引文机器；页不丢。"""
    sid, fake = _mode_subject_with_one_page(app_client, sids, monkeypatch)
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: fake)

    called: list[str] = []

    def _boom(*a, **kw):        # pragma: no cover
        called.append("called")
        raise AssertionError("图示教材模式的大纲起草不许走路径②的机器")

    import app.domain.judge as judge_mod
    from app.content import answerability
    from app.outline import draft as draft_mod

    monkeypatch.setattr(judge_mod, "judge", _boom)
    monkeypatch.setattr(answerability, "gate_node", _boom)
    monkeypatch.setattr(answerability, "clean_facts", _boom)
    monkeypatch.setattr(draft_mod, "draft_outline", _boom, raising=False)

    r = app_client.post(f"/api/subjects/{sid}/mode/outline/draft", json={"brief": "零基础", "count": 0})
    assert r.status_code == 200, r.text
    out = r.json()
    assert "mode_outline" in fake.calls and not called, (fake.calls, called)
    assert out["mode"] == "all_ai" and out["units"], out
    u = out["units"][0]
    assert u["id"].startswith(f"{sid}.u") and u["materials"][0]["section"] == "第 1 页", u
    assert "页/图号" in out["note"] or "页" in out["note"], out["note"]

    # 结果可直接采纳（既有 PUT /outline 结构一致）
    adopted = app_client.put(f"/api/subjects/{sid}/outline",
                             json={"units": out["units"], "status": "active", "source": "heuristic"})
    assert adopted.status_code == 200, adopted.text


def test_r57_b1_pages_the_model_skipped_are_absorbed_not_dropped(app_client, sids, monkeypatch):
    """模型没说到的页 → **并进最后一个单元**并在响应/账本里如实列出（不会有页被静默丢掉）。"""
    import app.outline.mode_pages as mp

    fake = _FakeProvider(units=[{"title": "只看第 1 页", "objectives": ["x"],
                                 "concept_tags": ["x"], "source_pages": ["第 1 页"]}])
    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    sid = make_subject(app_client, sids)
    # 两页图 → 模型只提到第 1 页
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "两页样张"},
                        files=[("files", ("p1.png", PNG_1PX, "image/png")),
                               ("files", ("p2.png", PNG_1PX, "image/png"))])
    assert r.status_code == 201, r.text
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: fake)   # 起草也走假 provider（不触网）
    out = app_client.post(f"/api/subjects/{sid}/mode/outline/draft", json={}).json()
    assert out["absorbed_pages"] == ["第 2 页"], out
    sections = [m["section"] for m in out["units"][-1]["materials"]]
    assert "第 2 页" in sections, out["units"][-1]
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    kinds = {(x.get("detail") or {}).get("kind") for x in rows}
    assert "mode_outline_absorbed_pages" in kinds, kinds
    reason = "；".join(x["reason"] for x in rows)
    assert "并进最后一个单元" in reason, reason


def test_r57_b1_draft_requires_pages_in_chinese(app_client, sids):
    """还没导入页面 → 中文说明（不崩）。"""
    sid = make_subject(app_client, sids)
    r = app_client.post(f"/api/subjects/{sid}/mode/outline/draft", json={})
    assert r.status_code == 422, r.text
    assert "页面记录" in r.text and "图片为主的教材" in r.text, r.text


def test_r57_b1_mode_outline_service_does_not_import_book_machinery():
    """AST 查 import：模式大纲服务不 import 路径②的机器（sympy / 可答性 / 引文 / 闸门）。"""
    from app.outline import mode_generate

    tree = ast.parse(Path(mode_generate.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[-1])
            imported |= {a.name for a in node.names}
    for banned in ("sympy", "answerability", "citations", "judge", "outline_gate"):
        assert banned not in imported, f"模式大纲服务 import 了路径②的机器：{banned}"


# ============================================================ ② 读图用的模型

def test_r57_b2_vision_model_setting_roundtrip(app_client):
    """设置页能改「读图用的模型」：保存后生效、回读来源；未设时跟随文本模型。"""
    view = app_client.get("/api/settings/model").json()
    # 未设 → 跟随文本模型（快档）
    assert view["vision_model"] == view["light"] == "deepseek-flash"
    assert view["vision_model_set"] == ""
    assert "跟随文本模型" in view["vision_model_source_zh"], view["vision_model_source_zh"]

    saved = app_client.put("/api/settings/model", json={"vision_model": "deepseek-v4-pro"}).json()
    assert saved["vision_model"] == "deepseek-v4-pro", saved
    assert saved["vision_model_source_zh"] == "你在这里设的", saved
    assert saved["vision_ok"] is False, "v4-pro 不支持读图 → 前置校验应如实为假"
    back = app_client.get("/api/settings/model").json()
    assert back["vision_model"] == "deepseek-v4-pro" and back["vision_model_set"] == "deepseek-v4-pro"
    # 只回掩码：Key 相关字段不含明文
    assert back["api_key_masked"].startswith("sk-") and back["api_key_masked"].count("…") == 1
    # 账本：中文记录、且只记模型名（无 Key 明文）
    rows = app_client.get("/api/ledger").json()["entries"]
    cfg = [x for x in rows if (x.get("detail") or {}).get("kind") == "model_config_changed"]
    assert cfg and "读图用的模型" in cfg[0]["reason"], cfg[:1]
    assert "sk-" not in cfg[0]["reason"], cfg[0]["reason"]

    # 清空 → 回到跟随文本模型
    cleared = app_client.put("/api/settings/model", json={"vision_model": ""}).json()
    assert cleared["vision_model"] == cleared["light"] and cleared["vision_model_set"] == ""
    assert "跟随文本模型" in cleared["vision_model_source_zh"]


def test_r57_b2_vision_model_is_used_by_read_page(app_client, sids, monkeypatch):
    """单独指定的读图模型**真的被拿去读图**（`/mode` 与 provider 构建都看得到）。"""
    app_client.put("/api/settings/model", json={"vision_model": "deepseek-flash-vision-x"})
    sid = make_subject(app_client, sids)
    entry = app_client.get(f"/api/subjects/{sid}/mode").json()
    assert entry["vision_model"] == "deepseek-flash-vision-x", entry
    assert entry["pdf_render_ready"] is True

    seen: dict = {}
    import app.outline.mode_pages as mp

    class _P:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr("app.ai.provider.OpenAICompatibleProvider", _P)
    import app.outline.mode_pages  # noqa: F401

    mp._build_provider(None)
    assert seen.get("model_light") == "deepseek-flash-vision-x", seen
    app_client.put("/api/settings/model", json={"vision_model": ""})
