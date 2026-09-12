"""R60 用例：① 页数上限只约束「本次实际要读的页数」② 旧标签跳过并列出。

工单 `.runtime/EULER_TICKET_R60.md`：
- **任务 A（真缺陷）**：给了页范围就**只按范围里的页数**校验（126 页的书只要 1 页必须放行）；
  没给范围（＝整本）才按整本校验；单页体量保护（`max_bytes`）保留；
  报错**不许再建议**"或只读其中一段（页范围）"这种（修复前）走不通的路。
- **任务 B**：认不出页号的旧标签（如「封面」）→ **跳过并列出**（中文 + 账本 + 返回值 `skipped`），
  不再 422 让用户把整份材料重导一遍。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from r55_support import cleanup_subjects, make_subject

from r58_support import isolate_model_and_cache, sample_pdf

REPO = Path(__file__).resolve().parents[2]

# 工单里架构侧用的就是"126 页的书 + 上限 10 页"这个场景
BIG_PAGES, TIGHT_CAP = 126, "10"


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
    """假 provider：按页号回"读到了"；``bad_first`` 里的页**第一次**读不出来（再读就好了）。"""

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


def _upload(app_client, sid, fake, monkeypatch, *, n_pages=3, pages: str = ""):
    """把一个 n 页 PDF 交给"图示教材模式"导入（模型用假的，页数上限由调用方设）。"""
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    data = {"title": "PDF 页面教材"}
    if pages:
        data["pages"] = pages
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data=data,
                        files=[("files", ("book.pdf", sample_pdf(n_pages), "application/pdf"))])
    return r


def _pages_file(app_client, sid: str, mid: str) -> Path:
    from app.outline import materials as mat

    d = mat.materials_dir(sid)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if e and e["id"] == mid:
            return d / str(e.get("pages_file") or "")
    raise AssertionError("没找到页面记录文件")


def _patch_page(app_client, sid: str, mid: str, idx: int, *, label: str, readable: bool) -> None:
    f = _pages_file(app_client, sid, mid)
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["pages"][idx]["page_label"] = label
    doc["pages"][idx]["readable"] = readable
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def _reread_rows(app_client, sid: str) -> list[dict]:
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    return [x for x in rows if str((x.get("detail") or {}).get("kind") or "").startswith("pages_reread")]


# ============================================================ 任务 A：页数上限只约束"本次要读的页数"

def test_r60_a1_big_book_small_range_is_allowed(app_client, sids, monkeypatch):
    """**A-①**：126 页的书 + 上限 10 页，**只要第 1 页** → 必须成功，且**只读 1 页**。

    （修复前：这条会被"全书 126 页"卡住 → 中文 422；见 `.runtime/r60_before_after.out`。）
    """
    monkeypatch.setenv("MF_PDF_MAX_PAGES", TIGHT_CAP)
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    r = _upload(app_client, sid, fake, monkeypatch, n_pages=BIG_PAGES, pages="1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["page_count"] == 1, body
    assert fake.calls == ["第 1 页"], fake.calls
    assert [p["page_no"] for p in body["pages"]] == [1]
    assert body["render"]["pages"] == [1]
    # 顺带确认"上限"确实被设成了 10（免得这条用例因为上限没生效而假绿）
    assert app_client.get(f"/api/subjects/{sid}/mode").json()["pdf_render_options"]["max_pages"] == 10


def test_r60_a2_big_range_over_limit_is_refused_with_feasible_advice(app_client, sids, monkeypatch):
    """**A-②**：要读的页数**超过上限** → 中文 422，且文案**不含**走不通的那条建议。"""
    monkeypatch.setenv("MF_PDF_MAX_PAGES", TIGHT_CAP)
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    r = _upload(app_client, sid, fake, monkeypatch, n_pages=BIG_PAGES, pages="1-20")
    assert r.status_code == 422, r.text
    msg = json.dumps(r.json(), ensure_ascii=False)
    assert "这次要读 20 页" in msg and "超过上限 10 页" in msg, msg
    assert "只读其中一段" not in msg, "文案不许再建议那条（修复前）走不通的路"
    assert "拆分后分批导入" not in msg, msg
    # 不落库、也没调模型
    assert app_client.get(f"/api/subjects/{sid}/materials").json()["materials"] == []
    assert fake.calls == []


def test_r60_a3_whole_book_over_limit_still_refused(app_client, sids, monkeypatch):
    """**A-③（回归）**：**没给页范围**（＝整本）且整本超限 → 中文报错（与修复前一致）。"""
    monkeypatch.setenv("MF_PDF_MAX_PAGES", TIGHT_CAP)
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    r = _upload(app_client, sid, fake, monkeypatch, n_pages=BIG_PAGES)
    assert r.status_code == 422, r.text
    msg = json.dumps(r.json(), ensure_ascii=False)
    assert f"有 {BIG_PAGES} 页" in msg and "超过上限 10 页" in msg, msg
    # 这次的替代路是**真的能走**（指定页范围），且不再出现旧文案
    assert "指定页范围" in msg, msg
    assert "只读其中一段" not in msg and "拆分后分批导入" not in msg, msg
    assert app_client.get(f"/api/subjects/{sid}/materials").json()["materials"] == []


def test_r60_a4_single_page_size_guard_still_works(monkeypatch):
    """**A-④**：单页体量保护（`max_bytes`）**照旧在**——页数口径改了，这条不许被顺手改没。

    **R61 任务 B 更新**：文案改了（旧文案带内部变量名 `MF_PAGE_IMAGE_WIDTH`，用户改不了）——
    这里只换"锁哪句话"，**意图不变**：仍然是"造错必报中文 + 说清第几页/多大 + 给可操作指引"。
    """
    from app.outline import pdfrender

    data = sample_pdf(2)
    # 小范围（1 页）也不再受"整本页数"影响，但单页太大照样中文报错
    with pytest.raises(pdfrender.PdfRenderError) as e:
        pdfrender.render_pages(data, pages="1", max_bytes=1024)
    msg = str(e.value)
    assert "出图太大" in msg, msg                       # 旧文案是「渲染出来太大」（R61 改）
    assert "第 1 页" in msg and "KB" in msg, msg        # 页号与真实体量照实留（不是含糊其辞）
    assert "宽度" in msg or "设置" in msg, msg          # 必须给出可操作的去处（R61：出图宽度这一项的当前值在导入说明里）
    assert "MF_" not in msg and "docs/" not in msg, msg  # 不许出现内部变量名/文档路径
    assert re.search(r"[\u4e00-\u9fff]", msg), msg     # 永远中文
    # 给足体量上限 → 同一页正常出图（说明拒绝来自体量保护，不是页数口径）
    ok = pdfrender.render_pages(data, pages="1", max_bytes=4 * 1024 * 1024)
    assert len(ok) == 1 and ok[0]["page_no"] == 1 and len(ok[0]["data"]) > 2000


# ============================================================ 任务 B：旧标签跳过并列出

def test_r60_b1_legacy_label_is_skipped_listed_and_logged(app_client, sids, monkeypatch):
    """**B-①**：旧标签（没页号）→ **不再 422**：能定位的页照读，定位不到的**跳过 + 列出 + 进账本**。

    两段：
    ① 有可定位的坏页（第 3 页）＋ 一个旧标签（封面）→ 读第 3 页、跳过"封面"；
    ② 只剩旧标签 → 一页都定位不到 → 不调模型、不花钱，但**照样留痕**（"跳过不是静默"）。
    """
    sid = make_subject(app_client, sids)
    fake = _FakeVision(bad_first={3})
    up = _upload(app_client, sid, fake, monkeypatch).json()
    assert up["unreadable"] == ["第 3 页"], up["unreadable"]
    _patch_page(app_client, sid, up["id"], 0, label="封面", readable=False)   # 旧格式标签

    # ---- ① 有能定位的坏页：照读，旧标签跳过并列出 ----
    fake.calls.clear()
    out = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                          json={"pages": "unreadable"})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["skipped"] == ["封面"], body
    assert body["reread"] == ["第 3 页"] and body["count"] == 1, body
    assert fake.calls == ["第 3 页"], fake.calls
    assert "封面" in body["note_zh"] and "跳过" in body["note_zh"], body["note_zh"]
    rows = _reread_rows(app_client, sid)
    assert len(rows) == 1 and rows[0]["detail"]["skipped"] == ["封面"], rows
    assert "标签里没有页号" in rows[0]["reason"] and "封面" in rows[0]["reason"], rows[0]
    # 页面记录仍在（跳过 ≠ 删掉），仍如实标着读不出来
    keep = {p["page_label"]: p for p in body["pages"]}
    assert keep["封面"]["readable"] is False and "封面" in body["unreadable"]

    # ---- ② 只剩旧标签：不调模型、不花钱，但必须留痕（账本 + 返回值） ----
    calls_before = len(fake.calls)
    out2 = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                           json={"pages": "unreadable"})
    assert out2.status_code == 200, out2.text
    body2 = out2.json()
    assert body2["count"] == 0 and body2["model_calls"] == 0 and body2["skipped"] == ["封面"], body2
    assert len(fake.calls) == calls_before, "一页都定位不到时不许调模型"
    assert "封面" in body2["note_zh"] and "跳过" in body2["note_zh"], body2["note_zh"]
    rows2 = _reread_rows(app_client, sid)
    assert len(rows2) == 2, rows2
    assert rows2[0]["detail"]["kind"] == "pages_reread_skipped", rows2[0]
    assert rows2[0]["detail"]["skipped"] == ["封面"] and "旧格式" in rows2[0]["reason"], rows2[0]


def test_r60_b2_normal_material_is_unaffected(app_client, sids, monkeypatch):
    """**B-②（回归）**：页标签都正常时，`skipped` 恒空，一键重读/按页重读口径与 R59 一致。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision(bad_first={2})
    up = _upload(app_client, sid, fake, monkeypatch).json()
    assert up["unreadable"] == ["第 2 页"], up["unreadable"]

    out = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                          json={"pages": "unreadable"}).json()
    assert out["skipped"] == [] and out["count"] == 1 and out["reread"] == ["第 2 页"], out
    assert "跳过" not in out["note_zh"], out["note_zh"]      # 没有旧标签就别提跳过
    rows = _reread_rows(app_client, sid)
    assert rows[0]["detail"]["skipped"] == [], rows[0]

    # 全可读 → 一键重读是 no-op（不调模型、不记账），`skipped` 仍为空
    n_rows = len(_reread_rows(app_client, sid))
    calls_before = len(fake.calls)
    out2 = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                           json={"pages": "unreadable"}).json()
    assert out2["count"] == 0 and out2["skipped"] == [] and out2["model_calls"] == 0, out2
    assert len(fake.calls) == calls_before and len(_reread_rows(app_client, sid)) == n_rows

    # 按页重读（老入口）也不受影响
    out3 = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                           json={"pages": "1"}).json()
    assert out3["reread"] == ["第 1 页"] and out3["skipped"] == [], out3
    assert out3["pages"][0]["page_label"] == "第 1 页"
    # 前端源码级：跳过的页要能在界面上如实看到（不许只说"读完了"）
    src = (REPO / "frontend" / "src" / "pages" / "OutlinePage.tsx").read_text(encoding="utf-8")
    assert "skipped?: string[]" in src and "已跳过" in src, "界面没有回显被跳过的页"
    block = src.split("const rereadMaterialPages")[1][:2400]
    for bad in ("R60", "§", "docs/", "read_pages", "MF_", "pages_reread"):
        assert bad not in block, f"重读相关文案里有内部字样 {bad}"
