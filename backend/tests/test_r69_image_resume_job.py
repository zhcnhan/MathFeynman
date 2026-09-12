"""R69 任务 ③ 用例：**图片导入的"接着读"也要有缓存与进度**。

工单 §3 的背景：R67 给"接着读"做了后台任务（进度可见 / 可取消 / 已读留下），
但那条路原先要 `load_pdf_cache` 才走得通 —— **页面图片导入的材料没有 PDF**，
于是它只能回落"同步按页重读"：页一多，用户又看不到任何进度（老问题复发）。

本批的验收口径（工单 §3）：

1. 图片导入读到一半取消 → **已读页留下**、**剩余页如实列着**、**账本记下"取消"**；
2. **接着读时有进度可看**（不是干等）—— 点下去就回任务号，进度数字在变；
3. **一页都没读成时不留下空材料**；
4. 复用 R67 那套后台任务/进度/取消机制（**不另造一套**）；
5. 页图**不进 `content/`**（缓存照旧走 gitignored 的缓存目录）；
6. **逐页留痕不许破**：一页一条记录，页号跟着原图走（**不重新编号**）。

口径说明：并行/取消这类涉及线程的断言一律用**假模型**（`_build_provider` 被替换），
不触网、不花钱；"进度在变"用"轮询到 `done` 上升且期间 `status` 仍是 running"来量。
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from r55_support import cleanup_subjects, ledger_entries, make_subject, materials
from r58_support import PNG_1PX, isolate_model_and_cache

REPO = Path(__file__).resolve().parents[2]


# ============================================================ 假模型 / 小工具
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


class FakeVision:
    """假模型：按页号回确定记录；``slow`` 用来把"进度在变/取消"变成可观测的事实。"""

    def __init__(self, *, slow: float = 0.0):
        self.slow = float(slow)
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        if self.slow:
            time.sleep(self.slow)
        if call.name != "read_page":
            raise AssertionError(f"这条用例只该调用 read_page，实际是：{call.name}")
        label = _page_label(messages)
        with self._lock:
            self.calls.append(label)
        return _Outcome({"page_label": label, "readable": True,
                         "key_points": [f"{label}：甲要点"], "visible_text": [f"{label} 正文"],
                         "formulas": [], "figures": [], "uncertain": [], "confidence": 0.9})


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


def _upload_images(app_client, sid: str, count: int, **form):
    files = [("files", (f"page{i}.png", PNG_1PX, "image/png")) for i in range(1, count + 1)]
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


def _pages_doc(sid: str, mid: str) -> dict:
    from app.outline import materials as mat

    d = mat.materials_dir(sid)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if e and e["id"] == mid:
            return json.loads((d / str(e.get("pages_file") or "")).read_text(encoding="utf-8"))
    raise AssertionError(f"没找到页面记录文件: {mid}")


def _image_cache_dir() -> Path:
    from app.outline import pdfrender

    return pdfrender.cache_dir() / "images"


def _half_read_image_material(app_client, sids, monkeypatch, *, total: int = 8,
                              stop_after: int = 3):
    """造一份"读到一半被取消"的**图片**材料 → ``(sid, material, job)``。

    这是本任务所有用例的起点：图片导入（后台任务）读了几页就被停掉。
    """
    sid = make_subject(app_client, sids)
    fake = FakeVision(slow=0.25)
    _patch_provider(monkeypatch, fake)
    r = _upload_images(app_client, sid, total, title="图片书", max_pages=str(total),
                       concurrency="1")
    assert r.status_code == 202, r.text
    jid = r.json()["id"]
    _wait(app_client, sid, jid, until=lambda j: int(j.get("done") or 0) >= stop_after)
    assert app_client.post(f"/api/subjects/{sid}/import-jobs/{jid}/cancel").status_code == 200
    done = _wait(app_client, sid, jid, timeout=30)
    assert done["status"] == "cancelled", done
    listed = materials(app_client, sid)
    assert len(listed) == 1, listed
    return sid, listed[0], done, fake


# ============================================================ ① 图片导入取消
def test_r69_c1_image_import_cancel_keeps_read_pages_and_says_so(app_client, sids, monkeypatch):
    """**①**：图片导入读到一半取消 → 已读页留下（含页号）、剩余页如实列着、账本记下"取消"。"""
    sid, mat0, done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                       total=8, stop_after=3)
    read = int(done["done"])
    print(f"[R69 C] 图片导入 8 页、读到第 {read} 页时取消：材料里留下 {read} 页，"
          f"剩下 {8 - read} 页如实列着")
    assert 1 <= read < 8, (read, done)
    assert mat0["page_count"] == read, (mat0["page_count"], read)
    doc = _pages_doc(sid, mat0["id"])
    labels = [str(p.get("page_label")) for p in doc["pages"]]
    assert labels == [f"第 {i} 页" for i in range(1, read + 1)], labels
    prog = doc["progress"]
    assert prog["state"] == "cancelled", prog
    assert len(prog["pending"]) == 8 - read, prog
    assert prog["pending"] == [f"第 {i} 页" for i in range(read + 1, 9)], prog
    rows = ledger_entries(app_client, sid, kind="all_ai_pages_imported")
    assert rows and rows[0]["detail"]["stopped"] is True, rows
    assert mat0["import_state"]["pending"], mat0["import_state"]


# ============================================================ ② 接着读＝后台任务
def test_r69_c2_resume_image_material_is_a_job_with_visible_progress(app_client, sids,
                                                                    monkeypatch):
    """**②（本任务的核心）**：图片材料的"接着读"**点下去就回任务号**，进度数字在变。

    这里钉三件事：
    ① 立刻 202 返回，而且返回时就带着**要读哪几页**（`planned`/`total`）——不是干等；
    ② 期间能轮询到 `status=running` 且 `done` 在涨（进度真的在动）；
    ③ 读完落成**一份新材料**，**页号跟着原图走**（第 5…8 页，不是第 1…4 页）。
    """
    sid, mat0, done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                       total=8, stop_after=3)
    read = int(done["done"])
    pending = list(mat0["import_state"]["pending"])
    nums = [re.search(r"第\s*(\d+)\s*页", x).group(1) for x in pending]
    assert nums, pending

    slow = FakeVision(slow=0.25)
    _patch_provider(monkeypatch, slow)
    t0 = time.time()
    jr = app_client.post(f"/api/subjects/{sid}/materials/{mat0['id']}/read-pages-job",
                         data={"pages": ",".join(nums), "strategy": "range",
                               "max_pages": str(len(nums)), "concurrency": "1"})
    elapsed_ms = int((time.time() - t0) * 1000)
    assert jr.status_code == 202, jr.text
    job = jr.json()
    assert elapsed_ms < 5000, elapsed_ms
    assert job["status"] == "running" and job["id"], job
    assert job["source_kind"] == "images", job          # 走的是"原始页面图"，不是 PDF

    # ② 进度**看得见**（不是干等）：轮询到"任务还没结束、但 done 已经在涨"那一刻。
    #    ⚠️ 不能断言"202 返回时 total 就填好了"——任务号是立刻回的，`total` 由后台线程稍后填。
    snapshot = None
    t1 = time.time()
    while time.time() - t1 < 20:
        cur = _job(app_client, sid, job["id"])
        if cur.get("status") != "running":
            break
        if int(cur.get("done") or 0) >= 1:
            snapshot = cur
            break
        time.sleep(0.03)
    assert snapshot is not None, "接着读过程中没能观察到「正在读：已读 N / 共 M 页」"
    assert snapshot["total"] == len(nums), snapshot
    assert snapshot["planned"] == pending, (snapshot["planned"], pending)
    assert "已读" in str(snapshot.get("note_zh") or ""), snapshot
    print(f"[R69 C] 接着读 {len(nums)} 页：接口 {elapsed_ms} 毫秒回任务号；"
          f"读的过程中看到「{snapshot['note_zh']}」，计划＝{'、'.join(pending)}")

    final = _wait(app_client, sid, job["id"], timeout=30)
    assert final["status"] == "done", final
    assert final["done"] == len(nums), final
    assert final["pending"] == [], final

    # ③ 另存一份新材料；**页号跟着原图走**
    listed = materials(app_client, sid)
    assert len(listed) == 2, listed
    new = next(m for m in listed if m["id"] != mat0["id"])
    new_doc = _pages_doc(sid, new["id"])
    new_labels = [str(p.get("page_label")) for p in new_doc["pages"]]
    assert new_labels == pending, (new_labels, pending)
    assert new_labels != [f"第 {i} 页" for i in range(1, len(nums) + 1)] or read == 0, \
        "接着读把页号重新编号了（第 5…8 页被写成了第 1…4 页）"
    # 原来那份**一字不动**
    old_doc = _pages_doc(sid, mat0["id"])
    assert [str(p.get("page_label")) for p in old_doc["pages"]] == \
        [f"第 {i} 页" for i in range(1, read + 1)], old_doc["pages"]
    assert old_doc["progress"]["state"] == "cancelled", old_doc["progress"]


# ============================================================ ③ 接着读也能取消
def test_r69_c3_resume_can_be_cancelled_and_keeps_what_was_read(app_client, sids, monkeypatch):
    """**③**：接着读**中途也能停**——已读的页留下（含真实页号），剩下的如实列着。"""
    sid, mat0, done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                       total=10, stop_after=2)
    pending = list(mat0["import_state"]["pending"])
    nums = [re.search(r"第\s*(\d+)\s*页", x).group(1) for x in pending]
    assert len(nums) >= 4, pending

    slow = FakeVision(slow=0.3)
    _patch_provider(monkeypatch, slow)
    jr = app_client.post(f"/api/subjects/{sid}/materials/{mat0['id']}/read-pages-job",
                         data={"pages": ",".join(nums), "max_pages": str(len(nums)),
                               "concurrency": "1"})
    assert jr.status_code == 202, jr.text
    jid = jr.json()["id"]
    _wait(app_client, sid, jid, until=lambda j: int(j.get("done") or 0) >= 1)
    assert app_client.post(f"/api/subjects/{sid}/import-jobs/{jid}/cancel").status_code == 200
    stopped = _wait(app_client, sid, jid, timeout=30)
    assert stopped["status"] == "cancelled", stopped
    got = int(stopped["done"])
    print(f"[R69 C] 接着读取消：本批 {len(nums)} 页读了 {got} 页，全部留下")
    assert 1 <= got < len(nums), (got, stopped)
    assert stopped["material_id"], stopped
    new_doc = _pages_doc(sid, stopped["material_id"])
    # 留下的页＝本批的前 `got` 页，**页标签就是真实页号**（第 5 页不是第 1 页）
    assert [str(p.get("page_label")) for p in new_doc["pages"]] == pending[:got], new_doc["pages"]
    assert new_doc["progress"]["state"] == "cancelled", new_doc["progress"]
    assert new_doc["progress"]["pending"] == pending[got:], new_doc["progress"]
    rows = ledger_entries(app_client, sid, kind="all_ai_pages_imported")
    assert rows and rows[0]["detail"]["stopped"] is True, rows


# ============================================================ ④ 一页没读成不留空材料
def test_r69_c4_resume_with_nothing_read_leaves_no_empty_material(app_client, sids, monkeypatch):
    """**④**：接着读**一页都没读成** → 不留空材料（与 R67 A-③ 同一条口径，走图片这条路）。"""
    sid, mat0, _done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                        total=6, stop_after=1)
    pending = list(mat0["import_state"]["pending"])
    assert pending, mat0["import_state"]
    fake = FakeVision()
    _patch_provider(monkeypatch, fake)
    from app.db import SessionLocal
    from app.outline import mode_pages as mp

    with SessionLocal() as db:
        src = mp.resume_source(sid, mat0["id"])
        assert src["kind"] == "images" and src["files"], src
        # 页号是**真实页号**（跟着原图走），且原料来自缓存、不是重新上传
        assert src["labels"] == pending, (src["labels"], pending)
        assert len(src["files"]) == len(pending), src["files"]
        out = mp.import_pages(db, sid, title="接着读空材料", files=src["files"],
                              page_labels=src["labels"], provider=fake, max_pages=5,
                              strategy="range", should_stop=lambda: True)
    assert out["id"] == "" and out["page_count"] == 0, out
    assert "空材料" in out["note_zh"], out["note_zh"]
    assert len(materials(app_client, sid)) == 1, "一页都没读成时不许留下空材料"
    assert fake.calls == [], "一页都没读就不该调用模型"
    assert ledger_entries(app_client, sid, kind="pages_import_empty"), "没读成也要留痕（不许静默）"


# ============================================================ ⑤ 缓存不在 → 中文说明
def test_r69_c5_missing_image_cache_is_plain_chinese_not_silent(app_client, sids, monkeypatch):
    """**⑤**：原始页面图缓存不在了 → **中文说明 + 出路**（422），**不静默降级**、不偷偷读一半。"""
    sid, mat0, _done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                        total=5, stop_after=2)
    cache = _image_cache_dir()
    victims = sorted(cache.glob(f"{sid}-*.png"))
    assert victims, f"缓存里没有这份材料的原图：{cache}"
    for p in victims:
        p.unlink()
    r = app_client.post(f"/api/subjects/{sid}/materials/{mat0['id']}/read-pages-job",
                        data={"pages": "3,4,5", "max_pages": "3"})
    assert r.status_code == 422, r.text
    msg = json.dumps(r.json(), ensure_ascii=False)
    assert "缓存" in msg and "重新导入" in msg, msg
    assert not re.search(r"[A-Za-z_]{6,}\(", msg), f"提示里混进了内部说法：{msg}"
    assert len(materials(app_client, sid)) == 1, "失败了就不该多出一份材料"


# ============================================================ ⑥ 页图不进 content/
def test_r69_c6_page_images_never_land_in_content(app_client, sids, monkeypatch):
    """**⑥（红线）**：接着读取的原始页面图只在 **gitignored 缓存目录**里，`content/` 一个大图都没有。"""
    from app.content import content_root

    sid, mat0, _done, _fake = _half_read_image_material(app_client, sids, monkeypatch,
                                                        total=4, stop_after=2)
    nums = [re.search(r"第\s*(\d+)\s*页", x).group(1)
            for x in mat0["import_state"]["pending"]]
    _patch_provider(monkeypatch, FakeVision())
    jr = app_client.post(f"/api/subjects/{sid}/materials/{mat0['id']}/read-pages-job",
                         data={"pages": ",".join(nums), "max_pages": str(len(nums))})
    assert jr.status_code == 202, jr.text
    _wait(app_client, sid, jr.json()["id"], timeout=30)
    root = content_root()
    pics = [p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif")]
    assert pics == [], f"content/ 里出现了图片：{[str(p) for p in pics[:5]]}"
    assert sorted(_image_cache_dir().glob(f"{sid}-*.png")), "原图应该在 gitignored 缓存目录里"


# ============================================================ ⑦ 界面不再静默只读前 12 页
def test_r69_c7_frontend_does_not_silently_reread_only_12_pages():
    """**⑦（源码级，照 R52/R58 先例）**：界面不再"悄悄只重读前 12 页"这种静默降级。

    仓库没有前端测试运行器 → 按既有先例断言源码：`readPendingPages` 走后台任务端点，
    而且**不再**出现"失败就只同步重读前 12 页"那段回落。
    """
    src = (REPO / "frontend" / "src" / "pages" / "OutlinePage.tsx").read_text(encoding="utf-8")
    hit = re.search(r"const readPendingPages = async[\s\S]*?\n  \};", src)
    assert hit, "没找到 readPendingPages 函数（界面结构变了？请同步这条断言）"
    body = hit.group(0)
    assert "read-pages-job" in body, body
    assert "slice(0, 12)" not in body, "「悄悄只读前 12 页」这段静默降级还在"
    assert "rereadMaterialPages" not in body, "失败还会偷偷回落到同步重读（用户看不到进度）"
