"""R61 任务 A 用例：旧标签（认不出页号，如「封面」）由用户**人工指定**"这一页当作第 N 页"。

工单 `.runtime/EULER_TICKET_R61.md` §2 的四条：
1. 指定成功 → 这一页**有页号、能被引用**、**不再出现在"跳过"清单里**、**进账**（中文原因）；
2. **可撤销** → 回到"跳过并列出"的样子，撤销也留痕；
3. **页号冲突**（这个页号已被别的页占用）→ 中文 409，**不静默覆盖**；
4. **非法页号**（0 / 负数 / 非数字）→ 中文 422，一个字节都不改。
（外加：重复点"同一个标签 → 同一个页号"＝重复点击，第二次只回一句中文说明，不再留第二条账。）

口径：这一步**不调用模型**（用例逐条断言假 provider 的调用次数没变），重读才花模型的钱。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest

from r55_support import cleanup_subjects, make_subject

from r58_support import isolate_model_and_cache, sample_pdf

BOOK_PAGES = 6          # 样本 PDF 有 6 页，但只导入 1-3 页（第 4 页留着，供人工指定用）

# 用户可见文案里**不许出现**的内部字样 / 黑话（沿用 R52/R59/R60 的文案守卫口径）
FORBIDDEN = ("R61", "§", "docs/", "MF_", "schema", "batch_chars", "inject_max_chars",
             "trace_path", "pytest", "roadmap", "注入", "预算", "吸纳", "落库", "降级",
             "丢弃", "截断", "幂等", "溯源", "闸门", "总账", "账本", "节点", "批次",
             "字符", "校验")


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


# ---------------------------------------------------------------- 共用小工具（照 R60 的写法）

def _upload(app_client, sid: str, fake: _FakeVision, monkeypatch, *, pages: str = "1-3"):
    """6 页 PDF 只导入前 3 页（第 4 页留空，正好给"人工指定"用）。"""
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": "PDF 页面教材", "pages": pages},
                        files=[("files", ("book.pdf", sample_pdf(BOOK_PAGES), "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()


def _pages_file(app_client, sid: str, mid: str) -> Path:
    from app.outline import materials as mat

    d = mat.materials_dir(sid)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if e and e["id"] == mid:
            return d / str(e.get("pages_file") or "")
    raise AssertionError("没找到页面记录文件")


def _pages(app_client, sid: str, mid: str) -> list[dict]:
    f = _pages_file(app_client, sid, mid)
    return json.loads(f.read_text(encoding="utf-8"))["pages"]


def _page(app_client, sid: str, mid: str, idx: int) -> dict:
    return _pages(app_client, sid, mid)[idx]


def _patch_page(app_client, sid: str, mid: str, idx: int, *, label: str, readable: bool) -> None:
    f = _pages_file(app_client, sid, mid)
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["pages"][idx]["page_label"] = label
    doc["pages"][idx]["readable"] = readable
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def _map_page(app_client, sid: str, mid: str, label: str, page_no):
    return app_client.post(f"/api/subjects/{sid}/materials/{mid}/page-mapping",
                           json={"label": label, "page_no": page_no})


def _undo_page(app_client, sid: str, mid: str, label: str):
    return app_client.delete(
        f"/api/subjects/{sid}/materials/{mid}/page-mapping/{quote(label)}")


def _reread(app_client, sid: str, mid: str, pages: str = "unreadable"):
    return app_client.post(f"/api/subjects/{sid}/materials/{mid}/read-pages",
                           json={"pages": pages})


def _ledger_kind(app_client, sid: str, kind: str) -> list[dict]:
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    return [x for x in rows if str((x.get("detail") or {}).get("kind") or "") == kind]


def _msg(resp) -> str:
    """响应里的中文说明（错误或说明），用来做"说人话"断言。"""
    return json.dumps(resp.json(), ensure_ascii=False)


def _assert_plain_chinese(text: str) -> None:
    for bad in FORBIDDEN:
        assert bad not in text, f"用户可见文案里有内部字样/黑话 {bad}: {text}"


def _legacy_page(app_client, sid: str, fake: _FakeVision, monkeypatch, idx: int = 0):
    """导入 + 把第一页做成"旧标签（认不出页号）+ 读不出来"的样子（＝要人工填页号的那一页）。"""
    up = _upload(app_client, sid, fake, monkeypatch)
    _patch_page(app_client, sid, up["id"], idx, label="封面", readable=False)
    return up


# ============================================================ 1. 指定成功 → 有页号、不再被跳过

def test_r61_a1_legacy_label_can_be_given_a_page_number(app_client, sids, monkeypatch):
    """**①**：旧标签「封面」→ 指定"当作第 4 页" → 200；记录里有页号、有旧标签留痕、进账；
    而且**不再出现在"跳过"清单里**、**能被正常引用**（重读那几页能读到它）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _legacy_page(app_client, sid, fake, monkeypatch)

    # 指定之前：它确实在"跳过并列出"的清单里（否则后面那句"不再跳过"等于没说）
    before = _reread(app_client, sid, up["id"]).json()
    assert before["skipped"] == ["封面"] and before["count"] == 0, before

    calls_before = len(fake.calls)
    r = _map_page(app_client, sid, up["id"], "封面", 4)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(fake.calls) == calls_before, "指定页号这一步不该问模型（也就没花钱）"
    assert body["page_no"] == 4 and body["label"] == "封面", body
    assert body["original_label"] == "封面" and body["skipped"] == [], body
    assert "封面" in body["note_zh"] and "第 4 页" in body["note_zh"], body["note_zh"]
    _assert_plain_chinese(body["note_zh"])

    rec = _page(app_client, sid, up["id"], 0)
    assert rec["page_label"] == "第 4 页" and rec["manual_page_no"] == 4, rec
    assert rec["original_label"] == "封面" and rec["page_no_source"] == "manual", rec
    assert rec["readable"] is False, "指定页号不该顺手改「这一页读没读出来」"
    # 其余记录与顺序都没动
    assert [p["page_label"] for p in _pages(app_client, sid, up["id"])] == ["第 4 页", "第 2 页", "第 3 页"]

    rows = _ledger_kind(app_client, sid, "page_mapping")
    assert len(rows) == 1, rows
    assert rows[0]["detail"] == {"kind": "page_mapping", "label": "封面",
                                 "original_label": "封面", "page_no": 4}, rows[0]
    assert "封面" in rows[0]["reason"] and "第 4 页" in rows[0]["reason"], rows[0]
    _assert_plain_chinese(rows[0]["reason"])

    # 指定之后：一键重读"读不出来的页"**不再跳过它**，而是真的读第 4 页
    fake.calls.clear()
    out = _reread(app_client, sid, up["id"])
    assert out.status_code == 200, out.text
    res = out.json()
    assert res["skipped"] == [], res
    assert res["reread"] == ["第 4 页"] and res["count"] == 1, res
    assert fake.calls == ["第 4 页"], fake.calls
    got = {p["page_label"]: p for p in res["pages"]}
    assert got["第 4 页"]["readable"] is True, got["第 4 页"]
    assert got["第 4 页"]["page_no"] == 4, "重读之后这一页要按页号 4 被引用"
    # 读出来之后，"这是人工指定的页号"这条留痕仍在（不然读一次就没法撤销了）
    assert got["第 4 页"]["manual_page_no"] == 4, got["第 4 页"]
    assert got["第 4 页"]["page_no_source"] == "manual", got["第 4 页"]
    assert got["第 4 页"]["original_label"] == "封面", got["第 4 页"]
    # 仍然能撤销「封面」→ 回到旧标签
    assert _undo_page(app_client, sid, up["id"], "封面").status_code == 200


# ============================================================ 2. 撤销 → 回到"跳过并列出"

def test_r61_a2_undo_puts_it_back_into_the_skipped_list(app_client, sids, monkeypatch):
    """**②**：撤销人工页号 → 页标签回到「封面」、人工字段全没了、撤销留痕；
    再点一键重读 → 它**又**出现在"跳过"清单里（一处都没留下）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _legacy_page(app_client, sid, fake, monkeypatch)
    assert _map_page(app_client, sid, up["id"], "封面", 4).status_code == 200

    calls_before = len(fake.calls)
    r = _undo_page(app_client, sid, up["id"], "封面")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(fake.calls) == calls_before, "撤销也不该问模型"
    assert body["skipped"] == ["封面"], body
    assert "封面" in body["note_zh"] and "撤销" in body["note_zh"], body["note_zh"]
    _assert_plain_chinese(body["note_zh"])

    rec = _page(app_client, sid, up["id"], 0)
    assert rec["page_label"] == "封面", rec
    for gone in ("manual_page_no", "page_no_source", "original_label"):
        assert gone not in rec, f"撤销之后不该还留着 {gone}: {rec}"

    rows = _ledger_kind(app_client, sid, "page_mapping_undo")
    assert len(rows) == 1, rows
    assert rows[0]["detail"]["kind"] == "page_mapping_undo", rows[0]
    assert "封面" in rows[0]["reason"] and "第 4 页" in rows[0]["reason"], rows[0]
    _assert_plain_chinese(rows[0]["reason"])

    later = _reread(app_client, sid, up["id"]).json()
    assert later["skipped"] == ["封面"] and later["count"] == 0, later
    assert later["model_calls"] == 0, later


# ============================================================ 3. 页号冲突 → 中文 409，不覆盖

def test_r61_a3_page_number_conflict_is_refused(app_client, sids, monkeypatch):
    """**③**：两个旧标签，先把「封面」指定成第 4 页；再想把「插图」也指定成第 4 页
    → **中文 409**，第二个标签**一个字节都没改**，也不留新账。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _upload(app_client, sid, fake, monkeypatch)
    _patch_page(app_client, sid, up["id"], 0, label="封面", readable=False)
    _patch_page(app_client, sid, up["id"], 1, label="插图", readable=False)
    assert _map_page(app_client, sid, up["id"], "封面", 4).status_code == 200

    rows_before = _ledger_kind(app_client, sid, "page_mapping")
    calls_before = len(fake.calls)
    r = _map_page(app_client, sid, up["id"], "插图", 4)
    assert r.status_code == 409, r.text
    msg = _msg(r)
    assert "已经有别的页了" in msg and "第 4 页" in msg, msg
    assert "换一个页号" in msg and "撤销" in msg, msg
    _assert_plain_chinese(msg)

    second = _page(app_client, sid, up["id"], 1)
    assert second["page_label"] == "插图", second
    assert "manual_page_no" not in second and "page_no_source" not in second, second
    assert [p["page_label"] for p in _pages(app_client, sid, up["id"])] == ["第 4 页", "插图", "第 3 页"]
    assert len(_ledger_kind(app_client, sid, "page_mapping")) == len(rows_before) == 1
    assert len(fake.calls) == calls_before


# ============================================================ 4. 非法页号 → 中文 422，什么都不改

@pytest.mark.parametrize("bad", [0, -1, "abc"])
def test_r61_a4_bad_page_number_is_chinese_422(app_client, sids, monkeypatch, bad):
    """**④**：页号 0 / 负数 / 非数字 → **中文 422**、不含内部字样，且**一个字节都不改**。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _legacy_page(app_client, sid, fake, monkeypatch)

    r = _map_page(app_client, sid, up["id"], "封面", bad)
    assert r.status_code == 422, (bad, r.text)
    msg = _msg(r)
    assert "页号得是 1 以上的整数" in msg and "现在给的是" in msg, msg
    _assert_plain_chinese(msg)

    rec = _page(app_client, sid, up["id"], 0)
    assert rec["page_label"] == "封面" and "manual_page_no" not in rec, rec
    assert _ledger_kind(app_client, sid, "page_mapping") == []
    assert _ledger_kind(app_client, sid, "page_mapping_undo") == []
    assert _reread(app_client, sid, up["id"]).json()["skipped"] == ["封面"]


# ============================================================ 5. 重复点击 = 同一个请求（不再留账）

def test_r61_a5_second_click_is_the_same_request(app_client, sids, monkeypatch):
    """**⑤**：同一个「标签 → 页号」连点两次 → 第二次 200 + 一句中文说明，**不再留第二条账**。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _legacy_page(app_client, sid, fake, monkeypatch)
    assert _map_page(app_client, sid, up["id"], "封面", 4).status_code == 200

    second = _map_page(app_client, sid, up["id"], "封面", 4)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["page_no"] == 4 and body["skipped"] == [], body
    assert "已经是第 4 页了" in body["note_zh"], body["note_zh"]
    _assert_plain_chinese(body["note_zh"])
    assert len(_ledger_kind(app_client, sid, "page_mapping")) == 1
    assert _page(app_client, sid, up["id"], 0)["page_label"] == "第 4 页"


# ============================================================ 6. 边界：只管人工指定的那一页

def test_r61_a6_only_manual_pages_can_be_undone(app_client, sids, monkeypatch):
    """**⑥**：撤销只认人工指定过的那一页（别的页 / 没这一页 → 中文 422）；
    指定一个材料里没有的标签 → 中文 404。都不留账。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    up = _upload(app_client, sid, fake, monkeypatch)

    r1 = _undo_page(app_client, sid, up["id"], "第 1 页")          # 自己就有页号，不是人工指定的
    assert r1.status_code == 422, r1.text
    assert "不是人工指定的页号，不能撤销" in _msg(r1), _msg(r1)
    _assert_plain_chinese(_msg(r1))

    r2 = _undo_page(app_client, sid, up["id"], "附录")             # 材料里根本没有这个标签
    assert r2.status_code == 422, r2.text
    assert "不是人工指定的页号，不能撤销" in _msg(r2), _msg(r2)

    r3 = _map_page(app_client, sid, up["id"], "附录", 4)           # 指定一个不存在的标签
    assert r3.status_code == 404, r3.text
    assert "没有标签为「附录」的一页" in _msg(r3), _msg(r3)
    _assert_plain_chinese(_msg(r3))

    assert _ledger_kind(app_client, sid, "page_mapping") == []
    assert _ledger_kind(app_client, sid, "page_mapping_undo") == []
    assert [p["page_label"] for p in _pages(app_client, sid, up["id"])] == ["第 1 页", "第 2 页", "第 3 页"]
