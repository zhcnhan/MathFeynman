"""R42 · 任务 C（R39 尾巴）与 D（健壮性）用例。

C1 降档 think→fast **逐次记账**（架构侧 R41 §3-③）
C2 提示词 **user 模板开放编辑**（可改/可恢复默认/必填占位符对 user 同样生效）
C3 审计文件**自动按保留期清理**且**清理必须记账**
D1 `ledger.write()` 失败 → **stderr 兜底日志**（不抛异常）
D2 `ledger._CURRENT` 改 `ContextVar`（并发/嵌套不串账）
D3 既有 `print` 已并入标准 logging 并**注明豁免**（不进账本）
"""
from __future__ import annotations

import threading
import time

import pytest

from app.ai.tier import FAST, THINK, TierDecision, downgrade_of, note_downgrade, resolve
from app.service import ledger as ledger_svc


# ============================================================ C1 降档记账

def test_r42_c1_downgrade_detection_matrix():
    """降档判定矩阵：**本该 think 却跑 fast** 才算降档；base=fast 不算；保底线的 light 不算。"""
    # ① 用户单次覆盖 think_deep=false：college 底子是 think → 降档
    d = resolve(level="college", model_mode="smart", override=False)
    assert d.strategy == FAST
    info = downgrade_of(d, level="college", model_mode="smart", override=False)
    assert info and info["base"] == THINK and "单次覆盖" in info["reason_zh"]
    # ② 内容标记 thinking（本该 think）+ 单次覆盖 false → 降档
    d5 = resolve(level="middle", content_think=True, model_mode="smart", override=False)
    assert d5.strategy == FAST
    assert downgrade_of(d5, level="middle", content_think=True, model_mode="smart",
                        override=False)
    # ③ "light 保底"：base=think 时 light **仍然** think → 不是降档
    d3 = resolve(level="college", model_mode="light")
    assert d3.strategy == THINK
    assert downgrade_of(d3, level="college", model_mode="light") is None
    # ④ base=fast（middle，smart）→ 从来不是降档（不是"本该 think"）
    d4 = resolve(level="middle", model_mode="smart")
    assert d4.strategy == FAST
    assert downgrade_of(d4, level="middle", model_mode="smart") is None
    # ⑤ 降档必须**可判定**：结果必须是 fast 且 base 必须是 think
    assert downgrade_of(TierDecision(THINK, "x"), level="college") is None
    assert downgrade_of(TierDecision(FAST, "x"), level="middle") is None
    # 显式"要 think"不算降档（override=True → think）
    assert downgrade_of(TierDecision(THINK, "override=true"), level="middle",
                        model_mode="smart", override=True) is None


def test_r42_c1_downgrade_is_recorded_per_occurrence(app_client):
    """**逐次**记账（`CAT_MODEL_CALL`，中文原因）；同一降档两次 → 两条账目。"""
    d = TierDecision(FAST, "override=false")
    for _ in range(2):
        got = note_downgrade(d, subject_id="s-x", unit_id="s-x.u01", call_name="feynman_evaluate",
                             level="college", model_mode="smart", override=False)
        assert got is not None
    led = app_client.get("/api/ledger?category=model_call").json()["entries"]
    hits = [e for e in led if (e.get("detail") or {}).get("kind") == "tier_downgrade"]
    assert len(hits) >= 2, f"降档必须逐次记账；实际 {len(hits)}"
    for e in hits:
        assert "重推理档" in str(e["reason"]) and "轻档" in str(e["reason"]), e["reason"]
        assert e["remedy"], "必须写明可否补救"
        assert (e.get("detail") or {}).get("call_name")
    # 未降档 → 不记账
    assert note_downgrade(TierDecision(FAST, "base=fast"), level="middle") is None
    assert note_downgrade(TierDecision(THINK, "base=think"), level="college") is None


def test_r42_c1_session_flow_records_downgrade(app_client, monkeypatch):
    """**端到端（服务层）**：`SessionService._resolve_tier` 是决策链唯一出口——
    本该 think 的节点被单次覆盖 false → 账本出现降档条目（不用真模型）。

    制造"本该 think"：优先取 college/ai 节点；否则把该节点的 ``feynman.thinking`` 标为 True
        （基础档 = think，这是内容侧真实存在的机制），使降档可判定。
    """
    from app.content.loader import load_library
    from app.db import SessionLocal
    from app.service.session import SessionService

    lib = load_library()
    node = next((n.doc for n in lib.nodes if n.doc.level in ("college", "ai")), None)
    if node is None:
        node = next((n.doc for n in lib.nodes), None)
        if node is None:
            pytest.skip("内容库为空，跳过端到端降档用例")
        # 让基础档变成 think（内容侧既有开关），从而"覆盖 false"构成降档
        node = node.model_copy(update={
            "feynman": node.feynman.model_copy(update={"thinking": True})})
    before = len(app_client.get("/api/ledger?category=model_call").json()["entries"])
    with SessionLocal() as db:
        svc = SessionService(gateway=None)  # type: ignore[arg-type]  只测档位解析（不调模型）
        # ① 本该 think + 单次覆盖 false → 降档（应记账）
        d = svc._resolve_tier(db, node=node, override=False, call_name="feynman_evaluate")
        assert d.strategy == FAST
        # ② 显式要 think → 不降档
        d2 = svc._resolve_tier(db, node=node, override=True, call_name="feynman_evaluate")
        assert d2.strategy == THINK
    after = app_client.get("/api/ledger?category=model_call").json()["entries"]
    hits = [e for e in after if (e.get("detail") or {}).get("kind") == "tier_downgrade"
            and str(e.get("unit_id")) == node.id]
    assert len(after) >= before, "账本只增不减"
    assert hits, ("本该 think 的节点被单次覆盖为 fast → 必须留降档账目；"
                  f"该节点账目={[(e.get('object'), e.get('reason')[:30]) for e in after[:3]]}")
    assert hits[0]["remedy"], "降档必须写明可否补救"
    assert "重推理档" in str(hits[0]["reason"]), hits[0]["reason"]


# ============================================================ C2 user 模板可编辑

def test_r42_c2_user_template_is_editable_and_restorable(app_client):
    """**user 模板开放编辑**：可改 → 生成链路用它；可单字段恢复默认；删硬约束 → 中文拒存。"""
    before = app_client.get("/api/prompts/explain_node").json()
    assert "user" in before["editable_fields"], before["editable_fields"]
    raw = before["default_raw_user_template"]
    assert raw and "{node_title}" in raw
    # ① 改 user（保留全部占位符/硬约束）
    edited = raw.replace("节点：{node_title}", "节点：{node_title}（R42 自定义 user 标记）")
    assert edited != raw
    r = app_client.put("/api/prompts/explain_node", json={"user": edited})
    assert r.status_code == 200, r.text
    after = app_client.get("/api/prompts/explain_node").json()
    assert after["user_is_default"] is False and after["user_diff"], "user 也要有差异"
    assert after["is_default"] is False and after["system_is_default"] is True, "只改了 user"
    assert "R42 自定义 user 标记" in after["raw_user_template"]
    # ② 生成链路确实用改后的 user（真 provider + MockTransport）
    from app.ai.calls import AnswerQuestionIn
    from app.ai.gateway import OpenAICompatibleGateway
    from app.ai.provider import OpenAICompatibleProvider
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8"))
        seen["user"] = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"lecture_md":"x","asked_to_confirm":[]}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    p = OpenAICompatibleProvider(api_key="sk-x", base_url="http://mock.local/v1",
                                 model_heavy="mh", model_light="ml",
                                 transport=httpx.MockTransport(handler))
    OpenAICompatibleGateway(p).explain_node(ExplainIn_stub())
    assert "R42 自定义 user 标记" in seen.get("user", ""), seen.get("user", "")[:200]
    # ③ 删掉 user 的必填占位符 → 中文拒存
    broken = edited.replace("{node_title}", "")
    bad = app_client.put("/api/prompts/explain_node", json={"user": broken})
    assert bad.status_code == 422, bad.text
    msg = bad.json()["detail"]["error"]["message"]
    assert "拒绝保存" in msg and "必须保留" in msg, msg
    # ④ 单字段恢复默认（user），system 不受影响
    got = app_client.post("/api/prompts/explain_node/reset", json={"field": "user"}).json()
    assert got["user_is_default"] is True and got["is_default"] is True
    assert got["raw_user_template"] == raw
    # ⑤ system 单独改 + 单独恢复，互不影响
    sys_edited = got["default_raw_template"] + "\n（R42 system 标记）"
    app_client.put("/api/prompts/explain_node", json={"system": sys_edited})
    mid = app_client.get("/api/prompts/explain_node").json()
    assert mid["system_is_default"] is False and mid["user_is_default"] is True
    back = app_client.post("/api/prompts/explain_node/reset", json={"field": "system"}).json()
    assert back["system_is_default"] is True and back["is_default"] is True
    app_client.post("/api/prompts/reset-all")


def ExplainIn_stub():
    from app.ai.calls import ExplainIn

    return ExplainIn(session_id="s", node_id="n", node_title="恒星", level="middle",
                     explanation_body="恒星靠核聚变发光。", worked_examples=[], core_concepts=[],
                     prereq_titles=[], whitelist=[], profile_style_block="", taught_facts=[])


def test_r42_c2_all_call_sites_user_field_status(app_client):
    """所有调用点的 `user` 字段**都可读**；有 user 模板的都可编辑（与 system 一样"一处不漏"）。"""
    r = app_client.get("/api/prompts").json()
    assert r["prompts"], "应有调用点"
    with_user = [p for p in r["prompts"] if p.get("default_raw_user_template")]
    assert len(with_user) >= 10, f"多数调用点应有 user 模板；实际 {len(with_user)}"
    for p in r["prompts"]:
        assert "raw_user_template" in p, p["call_name"]
        if p.get("default_raw_user_template"):
            assert "user" in p["editable_fields"], p["call_name"]


# ============================================================ C3 自动清理 + 记账

def test_r42_c3_cleanup_is_logged_and_removes_only_expired(tmp_path, monkeypatch, app_client):
    """**自动/手动清理**：只删过保留期的文件；**清理必须记账**（"已清理哪几条"）。"""
    from app.service import ai_trace

    monkeypatch.setenv("MF_AI_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("MF_AI_TRACE_KEEP_DAYS", "30")
    old = tmp_path / "old-audit.txt"
    old.write_text("旧审计", encoding="utf-8")
    fresh = tmp_path / "fresh-audit.txt"
    fresh.write_text("新审计", encoding="utf-8")
    past = time.time() - 40 * 86400
    import os

    os.utime(old, (past, past))
    out = ai_trace.cleanup_old(None)
    assert out["count"] == 1 and out["removed"] == ["old-audit.txt"], out
    assert not old.exists() and fresh.exists(), "只应删过期文件"
    led = app_client.get("/api/ledger?category=other").json()["entries"]
    hits = [e for e in led if "审计" in str(e["object"]) and "清理" in str(e["reason"])]
    assert hits, "清理必须记账（不许静默删）"
    assert "old-audit.txt" in str(hits[0]["reason"]) or \
        "old-audit.txt" in str((hits[0].get("detail") or {}).get("files")), hits[0]


def test_r42_c3_lifespan_calls_cleanup():
    """启动钩子**确实**接上了清理（自动清理接线锁）。

    **R46 B 更新**：清理入口由 `cleanup_old` 换成 `cleanup_once`（启动/定时/手动**三处同源**），
    并新增**定时**清理的启动与关闭接线——本用例同步锁定这三处接线（意图不变、覆盖更全：
    起得来、也停得掉）。
    """
    src = (__import__("pathlib").Path(__file__).resolve().parents[1]
           / "app" / "main.py").read_text(encoding="utf-8")
    assert "cleanup_once" in src, "main.lifespan 必须调用审计保留期清理（R42 C3 → R46 B 同源入口）"
    assert "start_periodic_cleanup" in src, "R46 B：lifespan 必须启动**定时**清理"
    assert ".stop()" in src, "R46 B：应用关闭时必须停掉定时清理（干净退出）"


# ============================================================ D1 记账失败兜底日志

def test_r42_d1_write_failure_logs_to_stderr_and_does_not_raise(monkeypatch, capsys):
    """`write()` 失败 → **打 stderr 兜底日志**、返回 None、**不抛异常**（不阻塞主流程）。"""
    def boom(*a, **kw):
        raise RuntimeError("模拟数据库不可用")

    monkeypatch.setattr(ledger_svc, "SessionLocal", boom, raising=False)
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "SessionLocal", boom)
    e = ledger_svc.Entry(category=ledger_svc.CAT_OTHER, object="测试对象",
                         reason="测试原因（中文）", created_at=ledger_svc._now_iso())
    assert ledger_svc.write(e) is None
    err = capsys.readouterr().err
    assert "[ledger] 记账失败" in err and "模拟数据库不可用" in err, err


# ============================================================ D2 ContextVar 并发/嵌套

def test_r42_d2_collector_is_contextvar_and_isolated_across_threads():
    """**并发隔离**：两个线程各自的 collector 互不串账（`_CURRENT` 是 ContextVar）。"""
    import contextvars

    assert isinstance(ledger_svc._CURRENT, contextvars.ContextVar), "必须改为 ContextVar"
    results: dict[str, list[str]] = {}
    barrier = threading.Barrier(2)

    def worker(tag: str) -> None:
        with ledger_svc.collector(f"subj-{tag}") as acc:
            barrier.wait(timeout=5)          # 两个线程同时持有收集器
            acc.record(ledger_svc.CAT_OTHER, f"obj-{tag}", f"原因-{tag}")
            time.sleep(0.05)
            results[tag] = [e.object for e in acc.entries]
            cur = ledger_svc.current()
            results[f"{tag}-current"] = [e.object for e in (cur.entries if cur else [])]

    ts = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert results.get("A") == ["obj-A"], results
    assert results.get("B") == ["obj-B"], results
    assert results.get("A-current") == ["obj-A"], results
    assert results.get("B-current") == ["obj-B"], results
    assert ledger_svc.current() is None, "主线程不应残留收集器"


def test_r42_d2_collector_nesting_restores_outer():
    """**嵌套**：内层退出后自动还原外层（ContextVar token 语义）。"""
    with ledger_svc.collector("outer") as outer:
        outer.record(ledger_svc.CAT_OTHER, "外层", "外层原因")
        with ledger_svc.collector("inner") as inner:
            assert ledger_svc.current() is inner
            inner.record(ledger_svc.CAT_OTHER, "内层", "内层原因")
        assert ledger_svc.current() is outer, "退出内层后必须还原外层"
        outer.record(ledger_svc.CAT_OTHER, "外层2", "外层原因2")
        assert [e.object for e in outer.entries] == ["外层", "外层2"]
        assert [e.object for e in inner.entries] == ["内层"]
    assert ledger_svc.current() is None


# ============================================================ D3 print 处置

def test_r42_d3_no_bare_print_in_session_api_and_exemption_documented():
    """既有 `print` 已并入标准 logging，且**注明豁免**（不进账本的理由写在文档串里）。"""
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "app" / "api" / "session.py"
    src = p.read_text(encoding="utf-8")
    assert "print(" not in src, "api/session.py 不应再有裸 print"
    assert "R42 D3" in src and "豁免" in src, "必须注明豁免与理由"
    assert "logger.info" in src and "logging" in src
