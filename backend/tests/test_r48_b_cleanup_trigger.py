"""R48 任务 B 用例：清理账目带 `trigger`（P2，R47 §4-2）。

`cleanup_once(reason)` 的 `reason`（`启动` / `定时` / `手动`）写进清理账目的 `detail.trigger`，
便于事后分辨"这次是谁清的"；**账目文案本身不变**（仍是"按保留期（N 天）清理审计全文文件：…"）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import models
from app.db import SessionLocal
from app.service import ai_trace

MANUAL_REASON_HEAD = "按保留期"


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))
    monkeypatch.setenv("MF_AI_TRACE_KEEP_DAYS", "0")
    ai_trace._reset_naming_state()
    yield d
    ai_trace._reset_naming_state()


def _old_file(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("很久以前的审计全文", encoding="utf-8")
    return p


def _cleanup_entries() -> list[dict]:
    """清理账目（按文案前缀过滤；新→旧）。"""
    with SessionLocal() as db:
        rows = (db.query(models.ContentLedger)
                .filter(models.ContentLedger.category == "other")
                .order_by(models.ContentLedger.id.desc()).all())
    return [{"id": int(r.id), "object": r.object or "", "reason": r.reason or "",
             "detail": dict(r.detail_json or {})}
            for r in rows if MANUAL_REASON_HEAD in str(r.reason or "")]


def _entry_for(name: str) -> dict:
    hits = [e for e in _cleanup_entries() if name in (e["detail"].get("files") or [])]
    assert hits, f"没找到包含 {name} 的清理账目：{[e['detail'].get('files') for e in _cleanup_entries()[:3]]}"
    return hits[0]


def test_r48_b1_cleanup_ledger_detail_carries_trigger(trace_dir, app_client):
    """**必交**：`detail.trigger` 等于传入的 reason（中文），三种触发者都可分辨，文案不变。"""
    # ① 定时（内核路径：PeriodicCleanup 每 N 小时调的就是它）
    _old_file(trace_dir, "r48b-定时.txt")
    out = ai_trace.cleanup_once("定时")
    assert out["count"] == 1 and out["trigger"] == "定时", out
    e = _entry_for("r48b-定时.txt")
    assert e["detail"]["trigger"] == "定时", e["detail"]
    assert e["detail"]["keep_days"] == 0 and e["detail"]["files"], e["detail"]
    # **既有文案不变**
    assert e["reason"].startswith("按保留期（0 天）清理审计全文文件："), e["reason"]
    assert "账本留痕，不静默消失" in e["reason"], e["reason"]
    assert e["object"] == "AI 对话审计文件（1 个）", e["object"]

    # ② 启动（lifespan 用的就是 "启动"）
    _old_file(trace_dir, "r48b-启动.txt")
    ai_trace.cleanup_once("启动")
    assert _entry_for("r48b-启动.txt")["detail"]["trigger"] == "启动"
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert 'cleanup_once("启动")' in src, "lifespan 必须用「启动」作为 trigger（口径别漂）"

    # ③ 手动（HTTP 入口也走同一实现）
    _old_file(trace_dir, "r48b-手动.txt")
    r = app_client.post("/api/ai-traces/cleanup", json={"keep_days": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trigger"] == "手动" and body["count"] == 1, body
    assert body["keep_days"] == 0 and body["removed"] == ["r48b-手动.txt"], body
    assert _entry_for("r48b-手动.txt")["detail"]["trigger"] == "手动"

    # 三种触发者的账目并存且互不混淆
    triggers = sorted({e["detail"]["trigger"] for e in _cleanup_entries()
                       if e["detail"].get("trigger")})
    assert {"启动", "定时", "手动"} <= set(triggers), triggers
    # 自动清理（非手动）仍带中文 trigger；全部账目原因仍为中文
    for e in _cleanup_entries():
        assert any("\u4e00" <= ch <= "\u9fff" for ch in e["reason"])
