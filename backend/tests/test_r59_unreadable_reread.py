"""R59 用例：**一键重读"读不出来的页"**（`pages="unreadable"`）。

工单 §1.3 四条：
① 只有第 2 页读不出来 → 调 `pages="unreadable"` → **只重读第 2 页**，并如实列出
   "重读了哪几页 / 还剩哪几页读不出来"；
② 全部可读 → **中文说明 + 不调用模型**（断言没有新的模型调用、也不记账）；
③ **幂等**：连点两次，第二次不重复读已可读的页（读出来的页不会被再读一次）；
④ **前端源码级**：按钮存在、文案说人话、无内部编号/字段名（沿用既有文案守卫口径）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from r55_support import cleanup_subjects, make_subject

from r58_support import isolate_model_and_cache, sample_pdf

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    yield from isolate_model_and_cache(app_client, monkeypatch, tmp_path)


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeVision:
    """假 provider：按页号回记录；**可以指定哪些页读不出来**（第一次读时）。

    ``bad_first``：第一次被读到时返回 `readable=False` 的页号集合（用于造"读不出来"的样本）；
    之后（重读时）默认都读得出来（模拟"换了清晰图/重试成功"）。
    """

    def __init__(self, *, bad_first: set[int] | None = None):
        self.bad_first = set(bad_first or ())
        self.calls: list[str] = []
        self.n = 0

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        text = "".join(str(b.get("text") or "")
                       for m in messages for b in (m.get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "text")
        hit = re.search(r"这一页的编号：([^\n]+)", text)
        label = hit.group(1).strip() if hit else ""
        m = re.search(r"第\s*(\d+)\s*页", label)
        page_no = int(m.group(1)) if m else 0
        self.n += 1
        self.calls.append(label)
        if page_no in self.bad_first:
            self.bad_first.discard(page_no)           # 只在第一次读不出来
            return _Outcome({"page_label": label, "readable": False,
                             "unreadable_reason": "整页是模糊扫描图，字太小读不出来",
                             "key_points": [], "visible_text": [], "figures": [],
                             "uncertain": [], "confidence": 0.1})
        return _Outcome({"page_label": label, "readable": True,
                         "key_points": [f"{label} 的要点（第 {self.n} 次读）"],
                         "visible_text": [], "figures": [], "uncertain": [], "confidence": 0.9})


def _upload(app_client, sid: str, fake: _FakeVision, monkeypatch, *, pages: str = "1-3"):
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "PDF 页面教材", "pages": pages},
                        files=[("files", ("b.pdf", sample_pdf(3), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()


def test_r59_1_unreadable_only_rereads_those_pages(app_client, sids, monkeypatch):
    """**①**：只有第 2 页读不出来 → 只重读第 2 页；如实列出重读了哪几页、还剩哪几页。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision(bad_first={2})
    up = _upload(app_client, sid, fake, monkeypatch)
    assert up["unreadable"] == ["第 2 页"], up["unreadable"]
    fake.calls.clear()

    out = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                          json={"pages": "unreadable"}).json()
    assert out["reread"] == ["第 2 页"], out
    assert out["count"] == 1 and fake.calls == ["第 2 页"], (out, fake.calls)
    assert out["unreadable"] == [], "重读后第 2 页已经可读，不该再列在读不出来里"
    assert "读不出来" in out["note_zh"] and "第 2 页" in out["note_zh"], out["note_zh"]
    # 第 1/3 页没有被再读一次（model_calls 就是 1）
    assert out["model_calls"] == 1
    merged = {p["page_label"]: p for p in out["pages"]}
    assert merged["第 2 页"]["readable"] is True
    assert "第 4 次读" in merged["第 2 页"]["key_points"][0], merged["第 2 页"]
    # 账目沿用既有 pages_reread 口径（中文），并注明这是"重读读不出来的页"
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    hits = [x for x in rows if (x.get("detail") or {}).get("kind") == "pages_reread"]
    assert hits and hits[0]["detail"]["trigger"] == "unreadable", hits[:1]
    assert "读不出来的页" in hits[0]["reason"] and "第 2 页" in hits[0]["reason"], hits[0]


def test_r59_2_all_readable_makes_no_model_call(app_client, sids, monkeypatch):
    """**②**：全部可读 → 中文说明 + **不调用模型**（也不记账）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()                     # 谁都不坏
    up = _upload(app_client, sid, fake, monkeypatch)
    assert up["unreadable"] == [], up["unreadable"]
    before_calls = len(fake.calls)
    rows_before = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    n_before = len([x for x in rows_before if (x.get("detail") or {}).get("kind") == "pages_reread"])

    out = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                          json={"pages": "unreadable"}).json()
    assert out["count"] == 0 and out["reread"] == [], out
    assert out["model_calls"] == 0, out
    assert len(fake.calls) == before_calls, "没有读不出来的页就不许再调模型"
    assert "没有读不出来的页" in out["note_zh"], out["note_zh"]
    assert "没有调用模型" in out["reason_zh"], out["reason_zh"]
    rows_after = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    n_after = len([x for x in rows_after if (x.get("detail") or {}).get("kind") == "pages_reread"])
    assert n_after == n_before, "什么都没发生就不该记账"
    # 页面记录原样（没被改动）
    assert out["pages"] == up["pages"]


def test_r59_3_idempotent_second_click_does_not_reread(app_client, sids, monkeypatch):
    """**③ 幂等**：连点两次 → 第二次算不出"读不出来的页"，于是 no-op（不再读、不再记账）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision(bad_first={1, 3})
    up = _upload(app_client, sid, fake, monkeypatch)
    assert up["unreadable"] == ["第 1 页", "第 3 页"], up["unreadable"]
    first = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                            json={"pages": "unreadable"}).json()
    assert first["count"] == 2 and set(first["reread"]) == {"第 1 页", "第 3 页"}, first
    assert first["unreadable"] == [], first
    calls_after_first = len(fake.calls)

    second = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                             json={"pages": "unreadable"}).json()
    assert second["count"] == 0 and second["model_calls"] == 0, second
    assert len(fake.calls) == calls_after_first, "第二次点不该再读任何一页"
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    hits = [x for x in rows if (x.get("detail") or {}).get("kind") == "pages_reread"]
    assert len(hits) == 1, f"第二次 no-op 不该再记账（现有 {len(hits)} 条）"


def test_r59_4_frontend_button_is_plain_chinese():
    """**④（前端源码级）**：按钮存在、说人话、调 `unreadable`、提示如实、无内部字样。"""
    src = (REPO / "frontend" / "src" / "pages" / "OutlinePage.tsx").read_text(encoding="utf-8")
    assert "把读不出来的页再读一遍" in src, "缺少一键重读按钮"
    assert '"unreadable"' in src or "'unreadable'" in src, "按钮没有把 unreadable 传给后端"
    assert "没有读不出来的页就不会调用模型" in src, "按钮提示应说明「没有就不调用模型」"
    assert "还是读不出来" in src, "应如实回显「还剩哪几页读不出来」"
    assert "没有需要重读的页" in src, "no-op 时也要给人一句说明（别像「点了没反应」）"
    block = src.split("const rereadMaterialPages")[1][:2200]
    for bad in ("R59", "§", "docs/", "read_pages", "MF_", "unreadable_pages"):
        assert bad not in block, f"重读相关文案里有内部字样 {bad}"


def test_r59_5_legacy_label_is_not_a_cryptic_error(app_client, sids, monkeypatch):
    """**⑤（边界）**：旧记录里"读不出来"的页认不出是第几页 → **不把内部解析报错甩给用户**。

    ⚠️ **R60 任务 B 起口径变了**（架构侧裁定"跳过并列出"）：本用例随裁决更新——
    现在**不再 422**，而是**跳过该页并如实列出**（这条用例保住的是"绝不出现
    「页范围写法看不懂」这种内部报错"这一点；完整的跳过语义见
    `test_r60_page_cap_and_legacy_labels.py::test_r60_b1_*`）。
    """
    import json

    from app.outline import materials as mat

    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _upload(app_client, sid, fake, monkeypatch)
    d = mat.materials_dir(sid)
    touched = False
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if not e or e["id"] != up["id"]:
            continue
        pf = d / str(e.get("pages_file") or "")
        doc = json.loads(pf.read_text(encoding="utf-8"))
        doc["pages"][0]["page_label"] = "封面"          # 更早版本可能留下这种标签
        doc["pages"][0]["readable"] = False
        pf.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        touched = True
        break
    assert touched, "没找到页面记录文件"

    r = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                        json={"pages": "unreadable"})
    assert r.status_code == 200, r.text
    body = json.dumps(r.json(), ensure_ascii=False)
    assert "页范围写法看不懂" not in body, "绝不把内部解析报错甩给用户"
    assert "认不出是第几页" not in body, "R60 起改成跳过并列出，不再用这句拒掉整个操作"
    assert "封面" in body and "跳过" in body, body
    assert r.json()["skipped"] == ["封面"], body
