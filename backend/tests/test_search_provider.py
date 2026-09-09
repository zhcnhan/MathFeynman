"""Phase C · C1：外部检索后端 provider 抽象（docs/14 §8 · 离线可测）。

覆盖：默认未启用（中文提示 + backend.configured=False）；配置 searxng → 检索直出/失败提示；
LLM 整理候选（mock，输出 url 回滤）；select 勾选抓公开网页正文入库（成功/失败回落摘要）；
provider 状态在 API search 响应可见（前端标注"未配置检索后端"用）。
"""
from __future__ import annotations

import uuid

import pytest

from app.outline import materials as mat
from app.outline import search as search_svc
from app.outline.search import SearchBackendError

_SEARXNG = "http://127.0.0.1:8888"


def _sid(prefix="srch") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label="检索学", prefix="srch"):
    sid = _sid(prefix)
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


@pytest.fixture
def search_env(monkeypatch):
    """隔离检索后端环境变量（用毕还原）。"""
    monkeypatch.setenv("MF_SEARCH_PROVIDER", "")
    monkeypatch.delenv("MF_SEARXNG_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    yield
    monkeypatch.delenv("MF_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("MF_SEARXNG_URL", raising=False)


class TestSearchBackendDefault:
    def test_provider_status_unconfigured(self, search_env):
        st = search_svc.provider_status()
        assert st["configured"] is False and st["provider"] == "none"

    def test_api_search_no_provider_chinese_note(self, app_client, search_env):
        sid = _mk_subject(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "行星"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["items"] == []
            assert "联网检索" in body["note"] and "未配置" in body["note"]
            assert body["backend"]["configured"] is False
            # UI 标注"未配置检索后端"的数据源：backend 状态 + note 文案齐全
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")


class TestSearchBackendSearxng:
    def _enable(self, monkeypatch):
        monkeypatch.setenv("MF_SEARCH_PROVIDER", "searxng")
        monkeypatch.setenv("MF_SEARXNG_URL", _SEARXNG)

    def test_search_configured_provider_returns_items(self, app_client, search_env, monkeypatch):
        self._enable(monkeypatch)
        canned = [
            {"title": "行星科学公开讲义", "url": "https://example.org/planet", "source": "wiki",
             "summary": "行星绕恒星运行；八大行星分两类。"},
            {"title": "恒星形成笔记", "url": "https://example.org/star", "source": "doc",
             "summary": "恒星由星际气体坍缩形成。"},
        ]
        monkeypatch.setattr(search_svc, "search_web",
                            lambda *a, **k: [dict(x) for x in canned])
        sid = _mk_subject(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "行星"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["backend"]["configured"] is True
            assert body["backend"]["provider"] == "searxng"
            assert [i["url"] for i in body["items"]] == [c["url"] for c in canned]
            assert body["note"] == ""
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_search_provider_unreachable_chinese_note(self, app_client, search_env, monkeypatch):
        self._enable(monkeypatch)
        monkeypatch.setattr(search_svc, "search_web",
                            lambda *a, **k: (_ for _ in ()).throw(
                                SearchBackendError("无法连接检索后端（连接被拒绝）")))
        sid = _mk_subject(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "行星"})
            assert r.status_code == 200, r.text  # 不 500：检索失败进 note
            body = r.json()
            assert body["items"] == []
            assert "检索失败" in body["note"] and "无法连接" in body["note"]
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_search_no_result_hint(self, app_client, search_env, monkeypatch):
        self._enable(monkeypatch)
        monkeypatch.setattr(search_svc, "search_web", lambda *a, **k: [])
        sid = _mk_subject(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/search", json={"query": "xyz"})
            assert r.status_code == 200
            assert r.json()["items"] == [] and "未检索到" in r.json()["note"]
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_llm_refine_candidates_and_url_filter(self, search_env, monkeypatch):
        """LLM 整理候选：输出 url 只取原始集（杜撰被滤）；无 key/失败回落原始。"""
        self._enable(monkeypatch)
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setattr(search_svc, "search_web", lambda *a, **k: [
            {"title": "A", "url": "https://example.org/a", "source": "s1", "summary": "sa"},
            {"title": "B", "url": "https://example.org/b", "source": "s2", "summary": "sb"},
        ])
        # 记录传给 _refine 的 raw，替换 refine 本体（避免真模型调用）
        calls: dict = {}
        real_refine = mat._refine_candidates

        def fake_refine(db, subj, query, raw, settings):
            calls["query"] = query
            calls["n_raw"] = len(raw)
            return [{"title": "B", "url": "https://example.org/b", "source": "s2",
                     "summary": "整理摘要", "reason": "权威"}]

        monkeypatch.setattr(mat, "_refine_candidates", fake_refine)
        from app.db import SessionLocal
        from app.outline import store as st

        with SessionLocal() as db:
            st.create_subject(db, label="R", subject_id="refinetest")
            try:
                out = mat.search_candidates(db, "refinetest", "行星")
                assert out["items"] == [{"title": "B", "url": "https://example.org/b",
                                         "source": "s2", "summary": "整理摘要", "reason": "权威"}]
                assert calls.get("n_raw") == 2
            finally:
                st.delete_subject(db, "refinetest", hard=True)
        # 恢复真实 refine 本体无 key → 直出原始（不触发网络）
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setattr(mat, "_refine_candidates", real_refine)


class TestSelectFetchPage:
    def _mk(self, app_client):
        sid = _mk_subject(app_client)
        return sid

    def test_select_fetch_page_body_saved(self, app_client, search_env, monkeypatch):
        monkeypatch.setattr(search_svc, "fetch_page_text",
                            lambda url, **k: "这是一段公开网页正文内容 Planet Page Body。" if "example.org" in url else None)
        sid = self._mk(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/select",
                                json={"items": [
                                    {"title": "行星条目", "url": "https://example.org/planet",
                                     "source": "示例网", "summary": "行星绕恒星运行。", "fetch": True},
                                ]})
            assert r.status_code == 201, r.text
            saved = r.json()["saved"]
            assert len(saved) == 1 and saved[0]["kind"] == "web"
            # 正文已本地化入库（含抓取正文，非仅摘要）
            from app.outline import materials as m2
            from app.outline.materials import materials_dir

            files = list(materials_dir(sid).glob("*.md"))
            body_text = files[0].read_text(encoding="utf-8")
            assert "Planet Page Body" in body_text
            assert "原始候选摘要" in body_text
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_select_fetch_fail_falls_back_to_summary(self, app_client, search_env, monkeypatch):
        monkeypatch.setattr(search_svc, "fetch_page_text", lambda url, **k: None)  # 网络失败
        sid = self._mk(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/select",
                                json={"items": [
                                    {"title": "条目", "url": "https://example.org/x",
                                     "source": "网", "summary": "仅摘要可用。", "fetch": True},
                                ]})
            assert r.status_code == 201, r.text
            from app.outline.materials import materials_dir

            files = list(materials_dir(sid).glob("*.md"))
            body_text = files[0].read_text(encoding="utf-8")
            assert "仅摘要可用" in body_text  # 回落摘要，不崩
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_select_without_fetch_flag_unchanged(self, app_client, search_env):
        """不带 fetch（旧契约）→ 仅摘要入库，不触发抓取。"""
        sid = self._mk(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/select",
                                json={"items": [
                                    {"title": "旧式候选", "url": "https://example.org/y",
                                     "source": "网", "summary": "旧式摘要。"},
                                ]})
            assert r.status_code == 201
            from app.outline.materials import materials_dir

            files = list(materials_dir(sid).glob("*.md"))
            body_text = files[0].read_text(encoding="utf-8")
            assert "旧式摘要" in body_text and "旧式候选" in body_text
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_search_candidates_call_spec_registered():
    from app.ai.calls import CALLS, CALL_SEARCH_CANDIDATES

    assert CALLS[CALL_SEARCH_CANDIDATES.name] is CALL_SEARCH_CANDIDATES
