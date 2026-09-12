"""R67 用例：**导入体验与大书可用性**（工单 `.runtime/EULER_TICKET_R67.md`）。

覆盖六件事（每条都对应工单 §1–§6 的验收口径）：

- **任务 A**：导入改后台任务（点击立刻返回 / 进度在变 / 可取消 / **已读的页留下** /
  分段落盘（中途死掉也留住已读）/ 一页都没读成**不留空材料**）；
- **任务 B**：页数上限交给用户（填 126 能一次提交；0 / 负数 / 超大 / 非数字都有中文提示）；
- **任务 C**：认章优先用 **PDF 自带书签**（有书签用书签、没书签回落目录页解析不变）；
- **任务 D**：读书账说实话（进流程 X 字 / 没进去 Y 字 / 差在哪；与 `_full_blocks` 对得上）；
- **任务 E**：两个入口说清区别 + 按材料特征给建议 + 一键改道；
- **任务 F**：三档读法 + 并行 + 批量（**逐页留痕**、串行 vs 并行逐位一致、
  限流中文、未读章节不许生成内容）。

口径说明（写清楚免得后来人误读）：
- 并行/批量的"一致性"用**同一个假模型**验证——真模型本来就有随机性，**调度**不许引入差异；
- "进程被杀"用"**磁盘上此刻的状态**"验证：任务表只在内存，材料/进度是落盘的
  ——清空任务表＝模拟重启，材料仍在、进度仍在。
"""
from __future__ import annotations

import io
import json
import re
import threading
import time
from pathlib import Path

import pytest

from r55_support import cleanup_subjects, ledger_entries, make_subject, materials
from r58_support import isolate_model_and_cache, sample_pdf

REPO = Path(__file__).resolve().parents[2]


# ============================================================ 造 PDF / 假模型


def text_pdf(page_texts: list[str]) -> bytes:
    """手搓多页 PDF（每页给定**拉丁**文本；Helvetica 真文字，595×842 pt）。"""
    objs: list[bytes] = []
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(len(page_texts)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(page_texts):
        line = text.replace("\\", "").replace("(", "[").replace(")", "]")
        content = (f"BT /F1 20 Tf 60 780 Td ({line[:120]}) Tj ET\n"
                   f"BT /F1 14 Tf 60 720 Td (page {i + 1}) Tj ET").encode("latin-1")
        page_no, cont_no = 4 + i * 2, 5 + i * 2
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                     f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cont_no} 0 R >>").encode())
        objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                    + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n"
            "%%EOF\n").encode()
    return bytes(out)


def bookmarked_pdf(page_texts: list[str], outline: list[tuple[str, int]]) -> bytes:
    """带**书签**（真目录）的多页 PDF：``outline`` ＝ ``[(标题, 0 起页号)]``。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(text_pdf(page_texts)))
    writer = PdfWriter(clone_from=reader)
    for title, page_no in outline:
        writer.add_outline_item(title, page_no)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def book_pages(n: int = 6) -> list[str]:
    return [f"BOOK PAGE {i + 1} " + ("alpha beta gamma delta " * 12) for i in range(n)]


BOOK_OUTLINE = [("封面", 0), ("目录", 1), ("第 1 章 甲", 2), ("第 2 章 乙", 4), ("参考文献", 5)]


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


def _text_of(messages) -> str:
    return "".join(str(b.get("text") or "")
                   for m in messages for b in (m.get("content") or [])
                   if isinstance(b, dict) and b.get("type") == "text")


def _page_label(messages) -> str:
    hit = re.search(r"这一页的编号：([^\n]+)", _text_of(messages))
    return hit.group(1).strip() if hit else ""


def _batch_labels(messages) -> list[str]:
    hit = re.search(r"一条都别漏）：([^\n]+)", _text_of(messages))
    if not hit:
        return []
    return [x.strip() for x in re.split(r"[、,，]", hit.group(1)) if x.strip()]


def record_of(label: str) -> dict:
    """**确定性**记录：同一页永远同一条（串行/并行/批量都该拿到这一条）。"""
    return {"page_label": label, "readable": True,
            "key_points": [f"{label}：甲要点", f"{label}：乙要点"],
            "visible_text": [f"{label} 正文第一行"], "formulas": [f"{label}: E=mc^2"],
            "figures": [{"label": f"图 {label}", "kind": "图", "description": "一张示意图"}],
            "uncertain": [], "confidence": 0.9}


class FakeVision:
    """假模型：按页号回确定记录；可注入**慢**（测进度/取消）、**失败**（测限流/单页不拖垮全局）。"""

    def __init__(self, *, slow: float = 0.0, fail_pages: set[str] | None = None,
                 fail_times: int = 10 ** 6, batch_miss: set[str] | None = None,
                 gate: threading.Event | None = None):
        self.slow = float(slow)
        self.fail_pages = set(fail_pages or ())
        self.fail_times = int(fail_times)
        self.batch_miss = set(batch_miss or ())
        self.gate = gate
        self.calls: list[tuple[str, str]] = []
        self.call_names: list[str] = []
        self._lock = threading.Lock()

    def _note(self, name: str, label: str) -> None:
        with self._lock:
            self.calls.append((name, label))
            self.call_names.append(name)

    def _fail_if_needed(self, label: str) -> None:
        if label in self.fail_pages and self.fail_times > 0:
            self.fail_times -= 1
            from app.ai.calls import AiCallError

            raise AiCallError("read_page", reason="HTTP 错误: 429 Too Many Requests")

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        if self.gate is not None:
            self.gate.wait(timeout=20)
        if self.slow:
            time.sleep(self.slow)
        if call.name == "read_page":
            label = _page_label(messages)
            self._note(call.name, label)
            self._fail_if_needed(label)
            return _Outcome(record_of(label))
        if call.name == "read_pages":
            labels = _batch_labels(messages)
            self._note(call.name, "、".join(labels))
            if labels and all(lb in self.fail_pages for lb in labels):
                from app.ai.calls import AiCallError

                raise AiCallError("read_pages", reason="HTTP 错误: 429 Too Many Requests")
            return _Outcome({"pages": [record_of(lb) for lb in labels
                                       if lb not in self.batch_miss]})
        if call.name == "mode_outline":
            self._note(call.name, "")
            return _Outcome({"units": [{"title": "甲单元", "objectives": ["懂甲"],
                                        "concept_tags": ["甲"], "source_pages": ["第 3 页"]}],
                             "uncertain": False, "uncertain_reason": ""})
        if call.name == "mode_lesson":
            self._note(call.name, "")
            return _Outcome({"lecture_md": "## 讲解\n甲。", "key_points": ["甲"],
                             "worked_examples": [], "source_pages": ["第 3 页"],
                             "uncertain": False, "uncertain_reason": ""})
        if call.name == "mode_exercise":
            self._note(call.name, "")
            return _Outcome({"exercises": [{"prompt": "甲是什么？", "kind": "short",
                                            "options": [], "answer": "甲",
                                            "explanation": "书上写着", "basis_pages": ["第 3 页"]}],
                             "uncertain": False, "uncertain_reason": ""})
        if call.name == "mode_judge":
            self._note(call.name, "")
            return _Outcome({"correct": True, "partial": False, "reason_zh": "对",
                             "uncertain": False, "uncertain_reason": "", "next_hint": ""})
        raise AssertionError(f"没预设这个调用点：{call.name}")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    from app.service import page_import

    page_import.reset_for_tests()
    yield from isolate_model_and_cache(app_client, monkeypatch, tmp_path)
    page_import.reset_for_tests()


def _patch_provider(monkeypatch, fake) -> None:
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)


def _start(app_client, sid: str, data: bytes, *, name: str = "book.pdf", **form):
    files = [("files", (name, data, "application/pdf"))]
    payload = {k: str(v) for k, v in form.items() if v not in (None, "")}
    return app_client.post(f"/api/subjects/{sid}/materials/upload-pages/start",
                           data=payload, files=files)


def _job(app_client, sid: str, job_id: str) -> dict:
    r = app_client.get(f"/api/subjects/{sid}/import-jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _wait(app_client, sid: str, job_id: str, *, timeout: float = 30.0,
          until=lambda j: j.get("status") != "running") -> dict:
    t0 = time.time()
    last: dict = {}
    while time.time() - t0 < timeout:
        last = _job(app_client, sid, job_id)
        if until(last):
            return last
        time.sleep(0.05)
    raise AssertionError(f"等这次导入结束超时了：{last}")


def _pages_file(sid: str, mid: str) -> Path:
    from app.outline import materials as mat

    d = mat.materials_dir(sid)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if e and e["id"] == mid:
            return d / str(e.get("pages_file") or "")
    raise AssertionError(f"没找到页面记录文件: {mid}")


def _pages_doc(sid: str, mid: str) -> dict:
    return json.loads(_pages_file(sid, mid).read_text(encoding="utf-8"))


# ============================================================ 任务 A：后台任务
def test_r67_a1_start_returns_at_once_and_progress_moves(app_client, sids, monkeypatch):
    """**A-①**：点击**立刻**返回（不再挂十几分钟），进度数字**在变**，读完落成一份材料。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision(slow=0.25)
    _patch_provider(monkeypatch, fake)
    t0 = time.time()
    r = _start(app_client, sid, text_pdf(book_pages(5)), title="A-① 书", max_pages="5",
               concurrency="2")
    elapsed = time.time() - t0
    assert r.status_code == 202, r.text
    job = r.json()
    print(f"[R67 A] 起任务耗时={elapsed:.3f}s（模型每页 0.25s，5 页）status={job['status']}")
    assert elapsed < 3.0, f"起任务不该等模型（实测 {elapsed:.2f}s）"
    assert job["status"] == "running" and job["id"], job
    jid = job["id"]
    # 进度：中途至少看到一次"已读 > 0 且 < 总数"
    mid = _wait(app_client, sid, jid, timeout=30,
                until=lambda j: 0 < int(j.get("done") or 0) < int(j.get("total") or 0))
    assert mid["total"] == 5 and 0 < mid["done"] < 5, mid
    assert "已读" in mid["note_zh"] and str(mid["total"]) in mid["note_zh"], mid["note_zh"]
    assert mid["current"], mid
    done = _wait(app_client, sid, jid)
    assert done["status"] == "done", done
    assert done["done"] == 5 and done["failed"] == 0, done
    assert done["material_id"], done
    listed = materials(app_client, sid)
    assert len(listed) == 1 and listed[0]["page_count"] == 5, listed
    assert listed[0]["import_state"]["state"] == "done", listed[0]["import_state"]
    assert listed[0]["import_state"]["read"] == 5, listed[0]["import_state"]


def test_r67_a2_cancel_keeps_what_was_read(app_client, sids, monkeypatch):
    """**A-②**：取消后**已读的页还在材料里**（含页号），账本有记录，剩余页如实列在"没读"里。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision(slow=0.3)
    _patch_provider(monkeypatch, fake)
    jid = _start(app_client, sid, text_pdf(book_pages(8)), title="A-② 书", max_pages="8",
                 concurrency="1").json()["id"]
    _wait(app_client, sid, jid, until=lambda j: int(j.get("done") or 0) >= 2)
    r = app_client.post(f"/api/subjects/{sid}/import-jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    done = _wait(app_client, sid, jid, timeout=30)
    assert done["status"] == "cancelled", done
    assert done["material_id"], done
    listed = materials(app_client, sid)
    assert len(listed) == 1, listed
    mat0 = listed[0]
    read = int(done["done"])
    print(f"[R67 A] 取消时：8 页的书已读 {read} 页，材料里就有这 {read} 页，"
          f"没读的 {8 - read} 页如实列着")
    assert 1 <= read < 8, (read, done)
    assert mat0["page_count"] == read, (mat0["page_count"], read)
    doc = _pages_doc(sid, mat0["id"])
    labels = [str(p.get("page_label")) for p in doc["pages"]]
    assert labels == [f"第 {i} 页" for i in range(1, read + 1)], labels
    assert doc["progress"]["state"] == "cancelled", doc["progress"]
    assert len(doc["progress"]["pending"]) == 8 - read, doc["progress"]
    rows = ledger_entries(app_client, sid, kind="all_ai_pages_imported")
    assert rows and rows[0]["detail"]["stopped"] is True, rows


def test_r67_a3_stop_before_any_page_leaves_no_empty_material(app_client, sids, monkeypatch):
    """**A-③**：一页都没读成 → **不许留一条空材料**（这里用"还没开始读就要求停"来钉死）。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    from app.outline import mode_pages as mp

    from app.db import SessionLocal

    with SessionLocal() as db:
        out = mp.import_pages(db, sid, title="空材料测试", files=[("b.pdf", text_pdf(book_pages(3)))],
                              provider=fake, max_pages=3, should_stop=lambda: True)
    assert out["id"] == "" and out["page_count"] == 0, out
    assert "空材料" in out["note_zh"], out["note_zh"]
    assert materials(app_client, sid) == [], "一页都没读成时不许留下空材料"
    assert fake.calls == [], "一页都没读就不该调用模型"
    assert ledger_entries(app_client, sid, kind="pages_import_empty"), "没读成也要留痕（不许静默）"


def test_r67_a4_partial_pages_are_on_disk_midway(app_client, sids, monkeypatch):
    """**A-④（本批最重要的修法）**：**边读边落盘**——读了几页就写几页，
    中途死掉（这里＝清空内存任务表模拟重启）之后，已读部分仍在、进度仍在。

    落盘节奏就是工单给的"每 5 页或每 30 秒"：所以"读到 7 页时，盘上至少该有 5 页"。
    """
    sid = make_subject(app_client, sids)
    fake = FakeVision(slow=0.2)
    _patch_provider(monkeypatch, fake)
    from app.service import page_import

    jid = _start(app_client, sid, text_pdf(book_pages(10)), title="A-④ 书",
                 max_pages="10").json()["id"]
    _wait(app_client, sid, jid, timeout=30, until=lambda j: int(j.get("done") or 0) >= 7)
    # 磁盘上此刻就该有材料 + 进度（不是"读完 10 页才写一次"）
    listed = materials(app_client, sid)
    assert listed, "读到 7 页了，磁盘上还什么都没有（说明还是「读完才写一次」）"
    mat0 = listed[0]
    saved = int(mat0["page_count"])
    print(f"[R67 A] 读到 7 页时，磁盘上已经有 {saved} 页（还没读完就先落盘了）")
    assert 5 <= saved <= 9, (saved, mat0["title"])
    assert mat0["import_state"]["state"] == "importing", mat0["import_state"]
    assert mat0["import_state"]["read"] == saved, mat0["import_state"]
    assert mat0["import_state"]["pending"], mat0["import_state"]
    body = _pages_doc(sid, mat0["id"])["pages"]
    assert len(body) == saved, (len(body), saved)
    assert [p["page_label"] for p in body] == [f"第 {i} 页" for i in range(1, saved + 1)]
    # 模拟"进程被杀后重启"：任务表在内存里，重启即空；材料与进度在盘上
    page_import.reset_for_tests()
    assert app_client.get(f"/api/subjects/{sid}/import-jobs/{jid}").status_code == 404
    again = materials(app_client, sid)
    assert again and again[0]["id"] == mat0["id"], again
    assert int(again[0]["page_count"]) == saved, again
    assert again[0]["import_state"]["read"] == saved, again[0]["import_state"]
    # 重启后能看到"还剩哪些页没读"，也能接着读（走**后台任务**，不再是"一个请求挂十几分钟"）
    left = again[0]["import_state"]["pending"]
    assert left and all(str(x).startswith("第 ") for x in left), left
    nums = [re.search(r"第\s*(\d+)\s*页", x).group(1) for x in left]
    jr = app_client.post(f"/api/subjects/{sid}/materials/{mat0['id']}/read-pages-job",
                         data={"pages": ",".join(nums), "max_pages": str(len(nums))})
    assert jr.status_code == 202, jr.text
    again_done = _wait(app_client, sid, jr.json()["id"], timeout=30)
    assert again_done["status"] == "done" and again_done["done"] == len(nums), again_done
    assert len(materials(app_client, sid)) == 2, materials(app_client, sid)   # 另存一份，原来那份没动


def test_r67_a5_second_import_of_same_subject_is_refused_in_chinese(app_client, sids, monkeypatch):
    """**A-⑤**：同一学科已有导入在跑 → 中文拒绝（不并排跑两份、不静默排队）。"""
    sid = make_subject(app_client, sids)
    gate = threading.Event()
    fake = FakeVision(gate=gate)
    _patch_provider(monkeypatch, fake)
    jid = _start(app_client, sid, text_pdf(book_pages(3)), max_pages="3").json()["id"]
    time.sleep(0.2)
    r2 = _start(app_client, sid, text_pdf(book_pages(3)), max_pages="3")
    assert r2.status_code == 409, r2.text
    assert "已经有一次导入在进行" in r2.text, r2.text
    gate.set()
    _wait(app_client, sid, jid)


# ============================================================ 任务 B：页数上限
def test_r67_b1_user_can_read_126_pages_in_one_go(app_client, sids, monkeypatch):
    """**B-①**：填 126 能**一次提交**（不再被程序自设的 60 挡住），而且真的读了 126 页。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    jid = _start(app_client, sid, text_pdf(book_pages(126)), title="B-① 大书",
                 max_pages="126", concurrency="4").json()["id"]
    done = _wait(app_client, sid, jid, timeout=60)
    assert done["status"] == "done", done
    assert done["total"] == 126 and done["done"] == 126, done
    assert materials(app_client, sid)[0]["page_count"] == 126
    assert len([c for c in fake.call_names if c in ("read_page", "read_pages")]) == 126


def test_r67_b2_bad_page_limits_are_plain_chinese(app_client, sids, monkeypatch):
    """**B-②**：0 / 负数 / 超大 / 非数字都有**中文提示**，不崩、不静默。"""
    sid = make_subject(app_client, sids)
    _patch_provider(monkeypatch, FakeVision())
    data = text_pdf(book_pages(3))
    cases = {"0": "1 以上", "-5": "1 以上", "999999": "最多", "abc": "数字"}
    for value, expect in cases.items():
        r = _start(app_client, sid, data, max_pages=value)
        assert r.status_code == 422, (value, r.text)
        msg = json.dumps(r.json(), ensure_ascii=False)
        assert expect in msg, (value, msg)
        assert re.search(r"[\u4e00-\u9fff]", msg), msg
        for bad in ("MF_", "R67", "§", "docs/", "schema"):
            assert bad not in msg, (value, bad, msg)
    # 读法/并发/批量三个框同样给中文提示（不崩）
    for field, value, expect in (("strategy", "飞快", "三种"), ("concurrency", "99", "最多"),
                                 ("batch_pages", "0", "1 以上")):
        r = _start(app_client, sid, data, **{field: value})
        assert r.status_code == 422, (field, r.text)
        assert expect in json.dumps(r.json(), ensure_ascii=False), (field, r.text)
    assert materials(app_client, sid) == []


# ============================================================ 任务 C：书签优先
def test_r67_c1_bookmarks_become_chapters_and_reach_the_material(app_client, sids):
    """**C-①**：有书签就用书签（权威目录）——**13 章 + 附录**这种识别；
    这里用一份带书签的小书验证：认出的章数、书末截断、页范围，以及**材料里留了书签**。"""
    from app.outline import bookmap, pdfparse

    data = bookmarked_pdf(book_pages(6), BOOK_OUTLINE)
    parsed = pdfparse.parse_pdf_bytes(data)
    assert len(parsed["bookmarks"]) == 5, parsed["bookmarks"]
    assert [b["title"] for b in parsed["bookmarks"]][2:4] == ["第 1 章 甲", "第 2 章 乙"]
    res = bookmap.parse_book(parsed["body"], toc=parsed["bookmarks"])
    assert res["kind"] == "toc", res
    labels = [e.label for e in res["entries"]]
    assert labels == ["第 1 章 甲", "第 2 章 乙"], labels
    assert res["entries"][0].pages == ["第 3 页", "第 4 页"], res["entries"][0].pages
    assert res["entries"][1].pages == ["第 5 页"], res["entries"][1].pages
    assert "书签" in res["note"] and "参考文献" in res["note"], res["note"]
    # 走真实入口：PDF → 引用库（文字路）→ 书签留档 → 覆盖账里就是这个结构
    sid = make_subject(app_client, sids)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pdf",
                        data={"title": "C-① 小书"},
                        files=[("file", ("book.pdf", data, "application/pdf"))])
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    from app.outline import materials as mat

    entry = next(p for p in mat.materials_dir(sid).glob("*.md")
                 if (mat._parse_entry(p) or {}).get("id") == mid)
    fm = mat._parse_entry(entry)
    assert fm["toc_file"] and (mat.materials_dir(sid) / fm["toc_file"]).exists(), fm
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    hit = [m for m in cov["materials"] if m["id"] == mid][0]
    assert "书签" in hit["structure_note"], hit
    entries = [e for e in cov["entries"] if e["material_id"] == mid]
    assert [e["label"] for e in entries] == ["第 1 章 甲", "第 2 章 乙"], entries


def test_r67_c2_without_bookmarks_falls_back_to_printed_toc(app_client):
    """**C-②（回落）**：**没书签**时走原来的目录页解析（行为与 R67 之前一致）。"""
    from app.outline import bookmap

    # 老口径的目录页正文（目录 + 页码 + 页首章标题）：识章结果必须还是"按目录识别"
    body = (
        "【第 1 页】\n目　录\n"
        "第1章 绪论 1\n"
        "第2章 动力学 2\n"
        "【第 2 页】\n第1章 绪论\n这一章讲绪论。\n"
        "【第 3 页】\n第2章 动力学\n这一章讲动力学。\n"
    )
    plain = bookmap.parse_book(body)
    assert plain["kind"] in ("toc", "heading"), plain
    assert len(plain["entries"]) >= 2, [e.label for e in plain["entries"]]
    assert not any("书签" in str(plain["note"]) for _ in (0,)), plain["note"]
    # 给了空书签也走回落（等价于"没有书签"）
    with_empty = bookmap.parse_book(body, toc=[])
    assert [e.label for e in with_empty["entries"]] == [e.label for e in plain["entries"]]
    # 书签里认不出章（只有"封面/目录"这类）→ 也不能把正文结构弄丢
    only_junk = bookmap.parse_book(body, toc=[{"title": "封面", "page": 1, "level": 0}])
    assert len(only_junk["entries"]) >= 2, [e.label for e in only_junk["entries"]]


def test_r67_c3_all_ai_mode_does_not_touch_chapter_recognition():
    """**C-③**：全 AI 模式**一根毛都不许变**——它走 `mode_generate`，不碰认章（源码级钉住）。"""
    gen = (REPO / "backend" / "app" / "outline" / "mode_generate.py").read_text(encoding="utf-8")
    mode_ai = (REPO / "backend" / "app" / "service" / "mode_ai.py").read_text(encoding="utf-8")
    for src in (gen, mode_ai):
        assert "bookmap" not in src and "parse_book" not in src and "material_structure" not in src
    # 反过来：认章那套（bookmap）也不认识"全 AI 模式"
    bm = (REPO / "backend" / "app" / "outline" / "bookmap.py").read_text(encoding="utf-8")
    assert "all_ai" not in bm and "MODE_ALL_AI" not in bm


# ============================================================ 任务 D：读书账
def test_r67_d1_text_account_ties_out_with_full_blocks(app_client, sids):
    """**D-①**：账面上的数字与实际成块字数**对得上**，且"没进去的字"说清了差在哪。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = make_subject(app_client, sids)
    data = bookmarked_pdf(book_pages(6), BOOK_OUTLINE)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pdf",
                        data={"title": "D-① 书"},
                        files=[("file", ("book.pdf", data, "application/pdf"))])
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    acc = cov["text_account"]
    row = [m for m in acc["materials"] if m["material_id"] == mid][0]
    assert row["checks"]["by_page"] is True, row
    assert row["checks"]["by_block"] is True, row
    assert acc["all_checks_ok"] is True, acc
    # 阳性对照：从**另一条路**独立算一遍成块字数（`_full_blocks`），必须与账面相等
    with SessionLocal() as db:
        index = mat._material_index(db, sid)
        blocks = mat._full_blocks(index)
    assert sum(int(b["chars"]) for b in blocks if b["material_id"] == mid) == row["blocks_chars"]
    assert row["blocks_chars"] > 0 and row["body_chars"] > row["blocks_chars"]
    assert row["injected_chars"] == row["blocks_chars"], row          # 没设上限 → 全部进了流程
    print(f"[R67 D] 正文 {row['body_chars']:,} 字 → 进流程 {row['injected_chars']:,} 字 / "
          f"没进去 {row['not_injected_chars']:,} 字；差在哪={[(g['kind'], g['chars']) for g in row['groups']]}")
    assert row["not_injected_chars"] == row["body_chars"] - row["injected_chars"]
    kinds = {g["kind"] for g in row["groups"]}
    assert "front" in kinds and "back" in kinds, row["groups"]       # 封面/目录 ＋ 参考文献
    assert "封面" in row["note_zh"] or "书前页" in row["note_zh"], row["note_zh"]
    assert "参考文献" in row["note_zh"] or "书末页" in row["note_zh"], row["note_zh"]
    # "看起来像全读了"这件事必须被说破：进流程 < 正文总量
    assert "没进去" in row["note_zh"], row["note_zh"]
    by = [m for m in cov["by_material"] if m["material_id"] == mid][0]
    assert by["text_account"]["body_chars"] == row["body_chars"], by


def test_r67_d2_account_marks_sampled_materials(app_client, sids, monkeypatch):
    """**D-②**：快读（抽样）之后，账上**如实标出"哪些页没读"**（不许装成"全书都读了"）。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    data = bookmarked_pdf(book_pages(6), BOOK_OUTLINE)
    jid = _start(app_client, sid, data, title="D-② 书", strategy="fast", max_pages="40").json()["id"]
    done = _wait(app_client, sid, jid)
    assert done["status"] == "done" and done["sampled"] is True, done
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    by = cov["by_material"][0]
    assert by["sampled"] is True, by
    assert by["pages_pending"], by
    assert by["read_pages"] == int(done["done"]), (by["read_pages"], done["done"])


# ============================================================ 任务 E：入口文案与改道
def test_r67_e1_suggestion_and_one_click_switch(app_client, sids, monkeypatch):
    """**E-①**：按材料特征给建议（图多 → 建议"连图一起看"）；选错了能**一键改道**。"""
    from app.outline import materials as mat

    # 建议逻辑（单元级）：图多 / 体检差 → 建议改走"连图一起看"
    many = mat.switch_suggestion("sid", {"id": "mat-x", "mode": ""},
                                 {"grade": "一般", "extract": {"images": 47, "image_pages": 30}})
    assert many["better"] == "pages", many
    assert many["can_switch_to_pages"] is False, "没有 PDF 缓存时不许假装能一键改道"
    assert "47 张图" in many["reason_zh"] and "连图一起看" in many["reason_zh"], many["reason_zh"]
    few = mat.switch_suggestion("sid", {"id": "mat-x", "mode": ""},
                                {"grade": "好", "extract": {"images": 0, "image_pages": 0}})
    assert few["better"] == "" and few["reason_zh"] == "", few

    # 真实入口：PDF → "只看文字"，材料上带出"能不能改道"，改道后能立刻起一次"连图一起看"
    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    data = bookmarked_pdf(book_pages(4), BOOK_OUTLINE[:4])
    up = app_client.post(f"/api/subjects/{sid}/materials/upload-pdf",
                         data={"title": "E-① 书"},
                         files=[("file", ("book.pdf", data, "application/pdf"))]).json()
    row = [m for m in materials(app_client, sid) if m["id"] == up["id"]][0]
    assert row["suggest"]["can_switch_to_pages"] is True, row["suggest"]
    r = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/switch-to-pages",
                        data={"max_pages": "4"})
    assert r.status_code == 202, r.text
    done = _wait(app_client, sid, r.json()["id"])
    assert done["status"] == "done" and done["done"] == 4, done
    listed = materials(app_client, sid)
    assert len(listed) == 2, listed                     # 原来那份没动，新加了一份"连图一起看"
    pages_row = [m for m in listed if m["mode"] == "all_ai"][0]
    assert pages_row["page_count"] == 4, pages_row
    assert pages_row["suggest"]["can_switch_to_text"] is True, pages_row["suggest"]


def test_r67_e2_switch_back_to_text_keeps_both(app_client, sids, monkeypatch):
    """**E-②**：反向改道也能走——"连图一起看"那份不改，另存一份"只看文字"。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    data = bookmarked_pdf(book_pages(4), BOOK_OUTLINE[:4])
    jid = _start(app_client, sid, data, title="E-② 书", max_pages="4").json()["id"]
    done = _wait(app_client, sid, jid)
    mid = done["material_id"]
    r = app_client.post(f"/api/subjects/{sid}/materials/{mid}/switch-to-text")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["id"] != mid and out["pages"] == 4, out
    listed = materials(app_client, sid)
    assert len(listed) == 2, listed
    assert [m["mode"] for m in listed].count("all_ai") == 1, listed
    assert "连图一起看" in out["note_zh"], out["note_zh"]
    # 反向：已经是"连图一起看"的，不许再"改道到连图一起看"
    again = app_client.post(f"/api/subjects/{sid}/materials/{mid}/switch-to-pages")
    assert again.status_code == 409, again.text


def test_r67_e3_frontend_says_which_entry_to_pick(app_client):
    """**E-③（源码级）**：两个入口的文案说清"只看文字 vs 连图一起看"，且都能一键改道。"""
    src = (REPO / "frontend" / "src" / "pages" / "OutlinePage.tsx").read_text(encoding="utf-8")
    assert "只看文字" in src and "连图一起看" in src, "两个入口没说清区别"
    assert "上传 PDF（只看文字）" in src, "老的 PDF 入口文案没改成人话对比"
    assert "导入页面图片 / PDF（连图一起看）" in src, "新入口文案没改成人话对比"
    assert "switch-to-pages" in src and "switch-to-text" in src, "没有一键改道的入口"
    assert "每页大约 8 秒" in src or "每页 8 秒" in src, "页数输入框旁边没有人话提示"


# ============================================================ 任务 F：三档 + 并行 + 批量
def test_r67_f1_serial_and_parallel_records_are_identical(app_client, sids, monkeypatch):
    """**F-①（对照用例，硬要求）**：同一份小材料，串行读一遍、并行读一遍 →
    **逐页记录逐位一致**（不一致就是 bug）。"""
    from app.db import SessionLocal
    from app.outline import mode_pages as mp

    sid = make_subject(app_client, sids)
    data = text_pdf(book_pages(4))
    with SessionLocal() as db:
        serial = mp.import_pages(db, sid, title="F-① 串行", files=[("b.pdf", data)],
                                 provider=FakeVision(), max_pages=4, concurrency=1)
        parallel = mp.import_pages(db, sid, title="F-① 并行", files=[("b.pdf", data)],
                                   provider=FakeVision(), max_pages=4, concurrency=4)
    a, b = serial["pages"], parallel["pages"]
    assert len(a) == len(b) == 4
    assert [x["page_label"] for x in a] == [x["page_label"] for x in b]
    for x, y in zip(a, b):
        assert x == y, (x, y)          # 逐位一致（含页号、要点、公式、图、置信度）
    print(f"[R67 F] 串行 vs 并行：{len(a)} 页逐页记录逐位一致（对比字段 {len(a[0])} 个/页）")
    assert serial["page_count"] == parallel["page_count"] == 4


def test_r67_f2_modes_read_different_page_counts(app_client, sids, monkeypatch):
    """**F-②**：三档都真的按档读（用**实际读了几页**证明）。"""
    sid = make_subject(app_client, sids)
    data = bookmarked_pdf(book_pages(8), [("封面", 0), ("目录", 1),
                                          ("第 1 章 甲", 2), ("第 2 章 乙", 5)])

    counts: dict[str, int] = {}
    for name, form in (("full", {"strategy": "full", "max_pages": "8"}),
                       ("range", {"strategy": "range", "pages": "2-3", "max_pages": "8"}),
                       ("fast", {"strategy": "fast", "max_pages": "8"})):
        fake = FakeVision()
        _patch_provider(monkeypatch, fake)
        jid = _start(app_client, sid, data, title=f"F-② {name}", **form).json()["id"]
        done = _wait(app_client, sid, jid, timeout=30)
        assert done["status"] == "done", done
        reads = len([c for c in fake.call_names if c in ("read_page", "read_pages")])
        counts[name] = reads
        assert reads == int(done["done"]) == int(done["total"]), (name, reads, done)
    assert counts["full"] == 8, counts
    assert counts["range"] == 2, counts
    assert 2 < counts["fast"] < 8, counts          # 快读：目录页 + 每章开头 2 页
    print(f"[R67 F] 三档实际读了几页：整本={counts['full']}，按页范围(2-3)={counts['range']}，"
          f"快读={counts['fast']}（这本书 8 页）")
    # 快读只挑了一部分 → 材料上如实标着"抽样读"
    fast_row = [m for m in materials(app_client, sid) if m["title"].endswith("fast")][0]
    assert fast_row["import_state"]["sampled"] is True, fast_row["import_state"]


def test_r67_f3_batch_keeps_one_record_per_page_and_refills_misses(app_client, sids, monkeypatch):
    """**F-③**：批量（一次调用 2 页）仍然**一页一条记录**；批量里漏掉的页**单独补读**。"""
    from app.db import SessionLocal
    from app.outline import mode_pages as mp

    sid = make_subject(app_client, sids)
    data = text_pdf(book_pages(4))
    fake = FakeVision(batch_miss={"第 3 页"})       # 批量返回时漏掉第 3 页
    with SessionLocal() as db:
        out = mp.import_pages(db, sid, title="F-③ 批量", files=[("b.pdf", data)],
                             provider=fake, max_pages=4, batch_pages=2, concurrency=1)
    assert out["page_count"] == 4, out
    assert [p["page_label"] for p in out["pages"]] == [f"第 {i} 页" for i in range(1, 5)]
    assert all(p["readable"] is True for p in out["pages"]), out["pages"]
    batch_calls = [c for c in fake.calls if c[0] == "read_pages"]
    single_calls = [c for c in fake.calls if c[0] == "read_page"]
    assert len(batch_calls) == 2, fake.calls        # 4 页 / 每次 2 页
    assert single_calls == [("read_page", "第 3 页")], fake.calls   # 漏的那页单独补读
    print(f"[R67 F] 批量读：一次 2 页的调用 {len(batch_calls)} 次 + 补读 {len(single_calls)} 次，"
          f"最终仍是 {out['page_count']} 页、一页一条记录")
    assert out["pages"][2]["key_points"] == record_of("第 3 页")["key_points"]


def test_r67_f4_rate_limited_page_is_chinese_and_does_not_break_the_rest(app_client, sids,
                                                                        monkeypatch):
    """**F-④**：限流/失败时**该页记成"这次没读成"（中文原因）**，其它页照读，导入不崩。"""
    sid = make_subject(app_client, sids)
    fake = FakeVision(fail_pages={"第 2 页"})
    _patch_provider(monkeypatch, fake)
    jid = _start(app_client, sid, text_pdf(book_pages(4)), title="F-④ 限流", max_pages="4",
                 concurrency="3").json()["id"]
    done = _wait(app_client, sid, jid)
    assert done["status"] == "done", done
    assert done["done"] == 4 and done["failed"] == 1, done
    assert done["unreadable"] == ["第 2 页"], done
    doc = _pages_doc(sid, done["material_id"])
    rec = [p for p in doc["pages"] if p["page_label"] == "第 2 页"][0]
    assert rec["readable"] is False and "限流" in rec["unreadable_reason"], rec
    for p in doc["pages"]:
        if p["page_label"] != "第 2 页":
            assert p["readable"] is True and p["key_points"], p
    body = doc["pages"]
    assert len(body) == 4, body                     # 一页都不少（一页一条记录）


def test_r67_f5_unread_chapter_refuses_content_generation(app_client, sids, monkeypatch):
    """**F-⑤（硬约束）**：快读排完大纲后，**没读过的单元不许生成内容**（如实说，不编造）；
    读过的那一章照旧能生成。"""
    from r55_support import adopt_outline, gen_unit, unit

    sid = make_subject(app_client, sids)
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: fake)   # 排大纲/讲解/出题也走假模型
    data = bookmarked_pdf(book_pages(8), [("封面", 0), ("目录", 1),
                                          ("第 1 章 甲", 2), ("第 2 章 乙", 5)])
    jid = _start(app_client, sid, data, title="F-⑤ 书", strategy="fast", max_pages="8").json()["id"]
    done = _wait(app_client, sid, jid)
    assert done["status"] == "done", done
    read_labels = [str(p["page_label"]) for p in _pages_doc(sid, done["material_id"])["pages"]]
    assert "第 5 页" not in read_labels, read_labels      # 第 2 章开头（第 5 页）这次没读到
    print(f"[R67 F] 快读这本书：读了 {read_labels}（第 5 页没有读到）")
    # 排大纲（快读的产物**只用于排大纲**）：只许引用读过的页
    r = app_client.post(f"/api/subjects/{sid}/mode/outline/draft", json={"brief": "", "count": 2})
    assert r.status_code == 200, r.text
    material_title = materials(app_client, sid)[0]["title"]
    for u in r.json()["units"]:
        for ref in u["materials"]:
            assert ref["section"] in read_labels, (ref, read_labels)
    # 用户手工把单元对到"这一章的两页"上（都在已读里，大纲校验才通得过）
    both = [{"title": material_title, "section": read_labels[0]},
            {"title": material_title, "section": read_labels[1]}]
    u01 = unit(f"{sid}.u01", "读过的单元", section=read_labels[0], material=material_title)
    u01["materials"] = both
    adopt_outline(app_client, sid, [
        u01,
        unit(f"{sid}.u02", "后来没读到的单元", section=read_labels[1],
             material=material_title),
    ])
    # 让 u02 依据的那一页**变成"这次没读到"**（真实情形：这一页的记录没读成 / 材料重导时没读它）
    pf = _pages_file(sid, done["material_id"])
    doc = json.loads(pf.read_text(encoding="utf-8"))
    doc["pages"] = [p for p in doc["pages"] if p["page_label"] != read_labels[1]]
    pf.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    fake.call_names.clear()
    missed = gen_unit(app_client, sid, f"{sid}.u02")
    assert missed["status"] == "uncovered", missed
    assert "没有读到" in missed["note"] and "不编造" in missed["note"], missed["note"]
    assert "mode_lesson" not in fake.call_names and "mode_exercise" not in fake.call_names, \
        fake.call_names
    rows = ledger_entries(app_client, sid, kind="mode_unit_pages_not_read")
    assert rows and read_labels[1] in rows[0]["reason"], rows
    # 读过的那一章：正常出稿，且把"抽样读 → 有哪些页没读到"如实带上
    ok = gen_unit(app_client, sid, f"{sid}.u01")
    assert ok["status"] == "created", ok
    assert "mode_lesson" in fake.call_names and "mode_exercise" in fake.call_names, fake.call_names
    assert read_labels[1] in ok["unread_pages"], ok
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    u2 = [u for u in cov["units"] if u["unit_id"] == f"{sid}.u02"][0]
    assert u2["usable"] is False and u2["status"] == "未覆盖", u2
    assert "没有读到" in u2["note"], u2          # 覆盖账里也写着"为什么没内容"
