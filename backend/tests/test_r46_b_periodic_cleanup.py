"""R46 任务 B 用例：**审计保留期清理定时化**（§58-17-⑥）。

要求（工单 §2）：
- 启动清一次 + 之后**每 N 小时清一次**（N 可配，默认 6 小时；见 `clean_interval_hours()`）；
- 清理仍**必须记账**（"已清理哪几条"）；
- 清理**不得阻塞主流程**，异常只 warning（不清就下次再清）；
- 应用关闭**干净退出**（守护线程 + `stop()`；不留非守护线程挂住进程）；
- `POST /api/ai-traces/cleanup` 手动入口**保留**。

三条必交：
- `test_r46_b1_*`：`keep_days=0` + 预置老文件 → 定时清理路径被触发 → 文件被删 + 账本中文条目；
- `test_r46_b2_*`：清理函数**幂等**（第二次 no-op、不产生重复账目）；
- `test_r46_b3*`：关闭应用**不挂起**（TestClient 退出正常 + 线程确实停了）。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import app
from app.service import ai_trace


@pytest.fixture(autouse=True)
def _tables():
    """本模块直接调服务层（不走 TestClient），先确保表存在（临时库由 conftest 指定）。"""
    from app.db import init_db

    init_db()


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """审计目录 → 临时目录（并清掉同秒序号记忆）。"""
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))
    with ai_trace._SEQ_LOCK:
        ai_trace._SEQ_BY_KEY.clear()
    yield d
    with ai_trace._SEQ_LOCK:
        ai_trace._SEQ_BY_KEY.clear()


def _ledger_cleanups() -> list[dict]:
    with SessionLocal() as db:
        rows = (db.query(models.ContentLedger)
                .filter(models.ContentLedger.category == "other")
                .order_by(models.ContentLedger.id.desc()).all())
    return [{"id": int(r.id), "object": r.object or "", "reason": r.reason or "",
             "detail": dict(r.detail_json or {})}
            for r in rows if "保留期" in str(r.reason or "")]


def _old_file(d: Path, name: str = "20200101T000000Z-answer_question.txt") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("很久以前的审计全文", encoding="utf-8")
    return p


def test_r46_b1_scheduled_cleanup_deletes_old_and_logs_zh(trace_dir, monkeypatch):
    """**必交①**：`keep_days=0` + 预置老文件 → 定时清理路径 → **文件被删 + 账本中文条目**。"""
    monkeypatch.setenv("MF_AI_TRACE_KEEP_DAYS", "0")
    stale = _old_file(trace_dir)
    fresh = _old_file(trace_dir, "20990101T000000Z-explain_node.txt")
    # 保留期 0 天 → 连刚写的也算过期（cutoff = now）——两者都会被清；先只断言"至少清掉了老的"
    before = len(_ledger_cleanups())

    out = ai_trace.cleanup_once("定时")  # 定时路径与启动/手动**同一实现**

    assert out["keep_days"] == 0, out
    assert out["count"] >= 1, out
    assert not stale.exists(), "过期审计文件必须被删"
    assert not fresh.exists(), "保留期 0 天＝一律视为过期（口径如实）"
    assert stale.name in out["removed"], out
    hits = _ledger_cleanups()
    assert len(hits) == before + 1, [h["reason"] for h in hits]
    reason = hits[0]["reason"]
    assert "保留期" in reason and "清理" in reason, reason
    assert any("\u4e00" <= ch <= "\u9fff" for ch in reason), reason
    assert stale.name in reason, reason
    assert hits[0]["detail"]["files"] and hits[0]["detail"]["keep_days"] == 0, hits[0]
    # 清理后目录里不再有 .txt
    assert not list(trace_dir.glob("*.txt"))


def test_r46_b2_cleanup_is_idempotent(trace_dir, monkeypatch):
    """**必交②**：清理**幂等**——第二次调用 no-op（不重复记账，也没东西可删）。"""
    monkeypatch.setenv("MF_AI_TRACE_KEEP_DAYS", "0")
    _old_file(trace_dir)
    ai_trace.cleanup_once("定时")
    after_first = len(_ledger_cleanups())

    out2 = ai_trace.cleanup_once("定时")

    assert out2["count"] == 0 and out2["removed"] == [], out2
    assert len(_ledger_cleanups()) == after_first, "没有可清理项时不得再记一条"
    # 目录不存在时也不炸（幂等且安全）
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(trace_dir / "不存在"))
    out3 = ai_trace.cleanup_once("定时")
    assert out3["count"] == 0, out3


def test_r46_b3_interval_config_default_and_guard(monkeypatch):
    """间隔配置：默认 6 小时；非法/<=0 **回默认**（不许用配置把清理静默关掉）。"""
    monkeypatch.delenv("MF_AI_TRACE_CLEAN_INTERVAL_HOURS", raising=False)
    assert ai_trace.clean_interval_hours() == ai_trace.DEFAULT_CLEAN_INTERVAL_HOURS == 6.0
    for bad in ("0", "-3", "abc", ""):
        monkeypatch.setenv("MF_AI_TRACE_CLEAN_INTERVAL_HOURS", bad)
        assert ai_trace.clean_interval_hours() == 6.0, bad
    monkeypatch.setenv("MF_AI_TRACE_CLEAN_INTERVAL_HOURS", "12")
    assert ai_trace.clean_interval_hours() == 12.0


def test_r46_b4_periodic_thread_daemon_runs_and_stops_cleanly(trace_dir, monkeypatch):
    """**必交③的一部分**：定时线程＝**守护线程**、会真的周期性跑、`stop()` 后**干净退出**且幂等。"""
    monkeypatch.setenv("MF_AI_TRACE_KEEP_DAYS", "0")
    # 目录不存在 → 每轮"没东西可清"，不会写库（避免与其它用例争 SQLite 写锁）
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(trace_dir / "空目录"))

    handle = ai_trace.start_periodic_cleanup(interval_seconds=0.05)
    try:
        assert handle.running() is True
        assert handle.thread is not None and handle.thread.daemon is True, "必须守护线程（不会挂住进程）"
        # 每个调用方各持一个句柄（应用实例各管各的线程）——第二个句柄用完即停
        other = ai_trace.start_periodic_cleanup(interval_seconds=5.0)
        assert other is not handle
        assert other.stop() is True
        deadline = time.time() + 2.0
        while handle.runs < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert handle.runs >= 2, f"定时线程应真的跑过：runs={handle.runs}"
    finally:
        assert handle.stop() is True
    assert handle.running() is False
    assert handle.stop() is False, "再停一次应为 no-op（幂等）"


def test_r46_b5_app_shutdown_stops_cleanup_and_does_not_hang():
    """**必交③**：应用关闭**不挂起**——TestClient 正常退出（本用例不超时即证据），
    且 lifespan 把定时清理句柄**启动并在关闭时停掉**；手动入口仍在。"""
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        handle = getattr(app.state, "ai_trace_cleanup", None)
        assert handle is not None, "lifespan 必须启动定时清理"
        assert handle.running() is True
        assert handle.thread is not None and handle.thread.daemon is True
        # 手动入口保留（body 可省）
        manual = c.post("/api/ai-traces/cleanup", json={})
        assert manual.status_code == 200, manual.text
        assert "count" in manual.json()
        # 手动清理也走同一实现、同样记账口径（keep_days 原样回显）
        assert manual.json()["keep_days"] == ai_trace.keep_days()
    # with 退出 ＝ lifespan shutdown：线程必须已停，且进程不挂
    assert handle.running() is False, "关闭时必须干净退出（线程已停）"
    assert handle.thread is None
    assert not [t for t in __import__("threading").enumerate()
                if t.name == "yanhui-ai-trace-cleanup" and t.is_alive()]
