"""R58 任务 C 用例：**按需重读的界面入口**（后端已可用，本批补界面）。

工单 §3.2 两条：
① 界面能发起"重读第 N 页"→ 后端按页合并、**如实显示重读了哪几页**；
② 重读**不影响**其它页的记录。
（仓库没有前端测试运行器 → 第 ① 条的后端半段用接口断言，前端半段按 R52 先例做**源码级**断言。）
"""
from __future__ import annotations

import re
from pathlib import Path


import pytest

from r55_support import cleanup_subjects, make_subject
from r58_support import isolate_model_and_cache, sample_pdf

@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    yield from isolate_model_and_cache(app_client, monkeypatch, tmp_path)


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


REPO = Path(__file__).resolve().parents[2]


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeVision:
    """假 provider：每读一次累加一个**永不重置**的计数（便于断言"哪一页是新读的"）。"""

    def __init__(self):
        self.calls: list[str] = []
        self.n = 0

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        text = "".join(str(b.get("text") or "")
                       for m in messages for b in (m.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text")
        hit = re.search(r"这一页的编号：([^\n]+)", text)
        label = hit.group(1).strip() if hit else ""
        self.n += 1
        self.calls.append(label)
        return _Outcome({"page_label": label, "readable": True,
                         "key_points": [f"{label} 的要点（第 {self.n} 次读）"],
                         "visible_text": [], "figures": [], "uncertain": [], "confidence": 0.9})


def test_r58_c1_reread_merges_by_page_and_reports_which(app_client, sids, monkeypatch):
    """**C2-①**：重读第 2 页 → 按页合并、如实显示重读了哪几页、**其它页原样**。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)   # 导入与重读都不触网
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "PDF 页面教材", "pages": "1-3"},
                        files=[("files", ("b.pdf", sample_pdf(3), "application/pdf"))])
    assert r.status_code == 201, r.text
    up = r.json()
    fake.calls.clear()
    rr = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                         json={"pages": "2"})
    assert rr.status_code == 200, rr.text
    out = rr.json()
    assert out["reread"] == ["第 2 页"] and out["count"] == 1, out
    assert fake.calls == ["第 2 页"], fake.calls
    assert [p["page_label"] for p in out["pages"]] == ["第 1 页", "第 2 页", "第 3 页"]
    merged = {p["page_label"]: p for p in out["pages"]}
    assert "第 4 次读" in merged["第 2 页"]["key_points"][0], merged["第 2 页"]
    assert "第 4 次读" not in merged["第 1 页"]["key_points"][0], merged["第 1 页"]
    assert "第 4 次读" not in merged["第 3 页"]["key_points"][0], merged["第 3 页"]
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    hits = [x for x in rows if (x.get("detail") or {}).get("kind") == "pages_reread"]
    assert hits and "第 2 页" in hits[0]["reason"], hits


def test_r58_c2_other_pages_records_are_untouched(app_client, sids, monkeypatch):
    """**C2-② 回归**：重读第 3 页 → 第 1/2 页记录**逐字段不变**（页面记录按页隔离）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "PDF 页面教材", "pages": "1-3"},
                        files=[("files", ("b.pdf", sample_pdf(3), "application/pdf"))])
    assert r.status_code == 201, r.text
    up = r.json()
    before = {p["page_label"]: dict(p) for p in up["pages"]}
    rr = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                         json={"pages": "3"}).json()
    after = {p["page_label"]: dict(p) for p in rr["pages"]}
    assert rr["reread"] == ["第 3 页"], rr
    assert after["第 1 页"] == before["第 1 页"], "第 1 页被动了"
    assert after["第 2 页"] == before["第 2 页"], "第 2 页被动了"
    assert after["第 3 页"] != before["第 3 页"], "第 3 页应该被重读替换"
    # 页序不变（按页合并保持原顺序）
    assert [p["page_label"] for p in rr["pages"]] == ["第 1 页", "第 2 页", "第 3 页"]


def test_r58_c1_ui_exposes_reread_entry():
    """**C2-①（前端半段，源码级）**：界面有"重读这几页"入口、说人话、调用既有接口。

    仓库没有前端测试运行器（R52 先例）：源码级断言 —— ① 调 `/read-pages`；
    ② 提示里如实显示"重读了哪几页"；③ 文案不出现内部编号/字段名。
    """
    src = (REPO / "frontend" / "src" / "pages" / "OutlinePage.tsx").read_text(encoding="utf-8")
    assert "/read-pages" in src, "界面没有调用重读接口"
    assert "重读这几页" in src and "重读第几页" in src, "缺少重读入口/占位提示"
    assert "已重新读" in src and "r.reread.join" in src, "提示里没有如实显示重读了哪几页"
    assert "其它页的记录没有动" in src, "应说明只重读这几页、其它页不动"
    assert "这一步同样要问模型，也会花钱" in src, "应如实提示成本"
    block = src.split("const rereadMaterialPages")[1][:1500]
    for bad in ("R58", "§", "docs/", "read_pages", "MF_"):
        assert bad not in block, f"重读相关文案里有内部字样 {bad}"
