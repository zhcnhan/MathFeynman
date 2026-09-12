"""R58 任务 B 用例：**PDF 缓存清理挂到既有定时清理**（同一套定时器，不新建机制）。

工单 §2.2 三条：① 过期文件被删 + 账本中文条目；② 幂等；③ 关闭应用不挂起。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from app.outline import pdfrender
from app.service import ai_trace, ledger

import pytest

from r58_support import isolate_model_and_cache, sample_pdf

@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    yield from isolate_model_and_cache(app_client, monkeypatch, tmp_path)



def _make_expired_cache(name: str = "s-x-mat-y.pdf") -> Path:
    d = pdfrender.cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(sample_pdf(1))
    old = time.time() - 30 * 86400          # 30 天前（保留期 7 天 → 必被清）
    os.utime(p, (old, old))
    return p


def _cache_ledger(db) -> list[dict]:
    return [x for x in ledger.list_entries(db, category=ledger.CAT_MATERIAL, limit=50)["entries"]
            if (x.get("detail") or {}).get("kind") == "pdf_cache_cleanup"]


def test_r58_b1_periodic_cleanup_removes_expired_and_ledgers():
    """**B2-①**：预置过期缓存 + 触发一次定时清理 → 文件被删 + 账本有中文条目（trigger=定时）。"""
    from app.db import SessionLocal

    f = _make_expired_cache()
    assert f.exists()
    out = ai_trace.cleanup_once("定时")          # ＝ PeriodicCleanup 每轮调用的那一个入口
    assert out["pdf_cache"]["removed_count"] == 1, out
    assert out["pdf_cache"]["trigger"] == "定时"
    assert not f.exists(), "过期缓存没被清掉"
    with SessionLocal() as db:
        rows = _cache_ledger(db)
    assert rows, "缓存清理必须记账"
    text = f"{rows[0]['object']}{rows[0]['reason']}"
    assert "PDF 页图渲染缓存清理" in text and "保留期" in text and "7 天" in text, text
    assert rows[0]["detail"]["trigger"] == "定时"


def test_r58_b2_cleanup_is_idempotent():
    """**B2-② 幂等**：连清两次 → 第二次 no-op、**不重复记账**。"""
    from app.db import SessionLocal

    _make_expired_cache("s-x-mat-z.pdf")
    first = ai_trace.cleanup_once("定时")
    assert first["pdf_cache"]["removed_count"] == 1, first
    with SessionLocal() as db:
        n1 = len(_cache_ledger(db))
    second = ai_trace.cleanup_once("定时")
    assert second["pdf_cache"]["removed_count"] == 0, second
    with SessionLocal() as db:
        n2 = len(_cache_ledger(db))
    assert n2 == n1, f"第二次清理不该再记账（{n1} → {n2}）"


def test_r58_b3_periodic_thread_stops_cleanly_without_hanging():
    """**B2-③**：既有定时器跑得起来、关得干净（不挂起）。"""
    _make_expired_cache("s-x-mat-w.pdf")
    timer = ai_trace.PeriodicCleanup(0.05).start()      # 同一套定时器
    assert timer.running() is True
    deadline = time.time() + 3.0
    while timer.runs < 1 and time.time() < deadline:
        time.sleep(0.02)
    assert timer.runs >= 1, "定时清理没有跑起来"
    assert ai_trace.cleanup_once.__module__ == "app.service.ai_trace"   # 走的就是既有实现
    t0 = time.time()
    th = timer.thread
    assert timer.stop(timeout=1.0) is True, "定时器没停下来"
    assert (time.time() - t0) < 1.5, "关闭超时（挂起了）"
    assert timer.running() is False
    # 我起的那条线程确实退出了（⚠️ 应用自己还有一条同名的常驻定时线程，不能按名字一刀切）
    assert th is not None and not th.is_alive()
    assert timer.thread is None, "stop() 之后不该再持有线程对象"
    assert not any(t.name == "yanhui-ai-trace-cleanup" and t.is_alive() and t is th
                   for t in threading.enumerate())
    # 缓存清理确实挂在同一条链上（同一个 cleanup_once 返回 pdf_cache）
    assert "pdf_cache" in ai_trace.cleanup_once("手动")
