"""R57 任务 A 用例：**PDF → 页图渲染（方案 a）** 与回落口径。

工单 §2.4 必交 6 条：
① 传 PDF → 按页渲染并发出（**审计里有页号**）；
② 渲染库缺失 → **回落方案 c + 中文说明**（不崩、不静默）；
③ 页数超限 → 中文 422；
④ 渲染后 `content/` 下**不新增任何永久图片**；
⑤ 150 / 200 dpi（与目标宽度）参数生效；
⑥ 路径②（pypdf 文本链路）不受影响。
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import pytest

from app.outline import pdfrender
from app.service import model_config
from r55_support import cleanup_subjects, make_subject

REPO = Path(__file__).resolve().parents[2]
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")


def sample_pdf(n_pages: int = 3) -> bytes:
    """手搓合法多页 PDF（Helvetica 真文字，595×842 pt ≈ A4）。"""
    objs: list[bytes] = []
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(n_pages):
        content = (f"BT /F1 28 Tf 60 760 Td (Planetary Science - page {i + 1}) Tj ET\n"
                   f"BT /F1 16 Tf 60 700 Td (The solar system has eight planets.) Tj ET\n"
                   f"BT /F1 14 Tf 60 560 Td (page number: {i + 1}) Tj ET").encode("latin-1")
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


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeVision:
    """假 provider：读页返回固定记录；**记下每次发出去的图片大小/类型**（证明渲染图真的发出了）。"""

    def __init__(self):
        self.calls: list[dict] = []

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        blocks = [b for m in messages for b in (m.get("content") or [])
                  if isinstance(b, dict) and b.get("type") == "image_url"]
        payload = blocks[0]["image_url"]["url"] if blocks else ""
        raw = base64.b64decode(payload.split(",", 1)[1]) if "," in payload else b""
        self.calls.append({"call": call.name, "mime": payload.split(";")[0].replace("data:", ""),
                           "bytes": len(raw), "audit": kw.get("audit") or {},
                           "label": self._label(messages)})
        return _Outcome({"page_label": self._label(messages), "readable": True,
                         "key_points": ["这一页写着 Planetary Science"],
                         "visible_text": ["Planetary Science"],
                         "figures": [], "uncertain": [], "confidence": 0.9})

    @staticmethod
    def _label(messages) -> str:
        text = ""
        for m in messages:
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    text += str(b.get("text") or "")
        import re

        hit = re.search(r"这一页的编号：([^\n]+)", text)
        return hit.group(1).strip() if hit else ""


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate(app_client, monkeypatch, tmp_path):
    """每条用例：清空模型配置、把 PDF 缓存指到临时目录（**不碰仓库缓存**）。"""
    from app import models
    from app.db import SessionLocal

    def _clear() -> None:
        with SessionLocal() as db:
            for key in model_config.KEYS:
                row = db.get(models.AppSetting, key)
                if row is not None:
                    db.delete(row)
            db.commit()
        model_config._MEMORY_KEY = ""

    _clear()
    monkeypatch.setenv("MF_PDF_CACHE_DIR", str(tmp_path / "pdf_cache"))
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r57")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    yield
    _clear()


def _content_images() -> set[str]:
    from app.content import content_root

    root = content_root()
    out = set()
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            out.add(str(p.relative_to(root)))
    return out


def _upload(app_client, sid: str, data: bytes, *, name: str = "book.pdf",
            title: str = "PDF 页面教材", pages: str = ""):
    return app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                           data={"title": title, "pages": pages},
                           files=[("files", (name, data, "application/pdf"))])


# ============================================================ ① PDF → 按页渲染并发出

def test_r57_a1_pdf_is_rendered_per_page_and_sent_with_page_numbers(app_client, sids,
                                                                    monkeypatch):
    """传 PDF → 按页渲染成图片发给模型；**审计/页面记录里有页号**；PDF 只进缓存目录。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)

    before = _content_images()
    r = _upload(app_client, sid, sample_pdf(3), pages="1-2")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["page_count"] == 2, body
    # 页号留痕：页面记录与发出去的提示词里都是「第 1 页 / 第 2 页」
    labels = [str(p.get("page_label")) for p in body["pages"]]
    assert labels == ["第 1 页", "第 2 页"], labels
    assert [c["label"] for c in fake.calls] == ["第 1 页", "第 2 页"], fake.calls
    assert all(c["call"] == "read_page" for c in fake.calls)
    # 发出去的是**渲染出来的 JPEG**（不是原始 PDF）
    assert all(c["mime"] == "image/jpeg" and c["bytes"] > 2000 for c in fake.calls), fake.calls
    # 审计元数据带学科与提示词版本（可回溯）
    assert fake.calls[0]["audit"].get("subject_id") == sid
    assert str(fake.calls[0]["audit"].get("prompt_versions") or "").endswith("read_page|default:read_page")
    # ④ 渲染后 content/ 里不新增任何永久图片
    assert _content_images() == before, "渲染出来的图片不许落进 content/"
    # PDF 只在缓存目录里（gitignored），并在页面记录里留了缓存口径
    from app.outline import mode_pages

    doc = mode_pages._pages_doc(sid, body["id"])
    assert doc["render"]["source"] == "pdf_render"
    assert doc["render"]["pages"] == [1, 2] and doc["render"]["width"] > 0
    cache = Path(pdfrender.cache_dir()) / str(doc["render"]["cache"])
    assert cache.exists() and cache.read_bytes()[:4] == b"%PDF", cache
    assert not str(cache).startswith(str(REPO / "content")), "缓存目录不能在 content/ 里"


def test_r57_a1_reread_pages_uses_cache_and_merges_by_page(app_client, sids, monkeypatch):
    """按需取页范围：只重读指定的那几页（从缓存 PDF 重渲染），同页替换、其余不动。"""
    sid = make_subject(app_client, sids)
    fake = _FakeVision()
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    up = _upload(app_client, sid, sample_pdf(4), pages="1-2").json()
    fake.calls.clear()
    r = app_client.post(f"/api/subjects/{sid}/materials/{up['id']}/read-pages",
                        json={"pages": "3"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reread"] == ["第 3 页"] and out["count"] == 1, out
    assert [s["label"] for s in fake.calls] == ["第 3 页"]
    labels = [str(p.get("page_label")) for p in out["pages"]]
    assert labels == ["第 1 页", "第 2 页", "第 3 页"], labels
    # 账本里有中文记录
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    assert any((x.get("detail") or {}).get("kind") == "pages_reread" for x in rows), rows


# ============================================================ ② 渲染库缺失 → 回落方案 c

def test_r57_a1_page_number_comes_from_us_not_the_model(app_client, sids, monkeypatch):
    """**页号留痕以我们为准**：模型把页号回错/回空，记录里仍是"我们发出去的那一页"。"""
    sid = make_subject(app_client, sids)

    class _BadLabel(_FakeVision):
        def chat_json(self, call, messages, **kw):
            out = super().chat_json(call, messages, **kw)
            out.parsed["page_label"] = "这一页"          # 模型乱回
            return out

    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: _BadLabel())
    body = _upload(app_client, sid, sample_pdf(2), pages="2").json()
    assert [str(p.get("page_label")) for p in body["pages"]] == ["第 2 页"], body["pages"]


def test_r57_a2_missing_render_lib_falls_back_to_plan_c_in_chinese(app_client, sids,
                                                                   monkeypatch):
    """渲染库缺失 → **中文 422 说明 + 两条替代路**（不崩、不静默、不假装支持）。"""
    sid = make_subject(app_client, sids)
    # 模拟"没装渲染库"：让 import pypdfium2 失败
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    import app.outline.mode_pages as mp

    ok, why = pdfrender.render_available()
    assert ok is False and "渲染组件" in why and "自己把 PDF 每页导出成图片" in why, why
    r = _upload(app_client, sid, sample_pdf(2))
    assert r.status_code == 422, r.text
    msg = r.text
    assert "导出成图片" in msg and "服务商" in msg, msg
    # 不落库
    assert app_client.get(f"/api/subjects/{sid}/materials").json()["materials"] == []
    # `/mode` 也如实告诉界面：现在不能自动渲染（界面据此把 PDF 选项禁用/给提示）
    entry = app_client.get(f"/api/subjects/{sid}/mode").json()
    assert entry["pdf_render_ready"] is False and "渲染组件" in entry["pdf_render_note_zh"]
    assert entry["pdf_render_options"]["width"] == 1024
    # 把 pypdfium2 还原（monkeypatch 会自动还原，这里只是确认恢复后的判定）
    monkeypatch.undo()
    assert pdfrender.render_available()[0] is True


# ============================================================ ③ 页数超限 → 中文 422

def test_r57_a3_too_many_pages_is_refused_in_chinese(app_client, sids, monkeypatch):
    """页数超过 `MF_PDF_MAX_PAGES` → 中文 422（不落库）。"""
    sid = make_subject(app_client, sids)
    monkeypatch.setenv("MF_PDF_MAX_PAGES", "2")
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: _FakeVision())
    r = _upload(app_client, sid, sample_pdf(3))
    assert r.status_code == 422, r.text
    assert "超过上限" in r.text and "2 页" in r.text, r.text
    assert app_client.get(f"/api/subjects/{sid}/materials").json()["materials"] == []


# ============================================================ ⑤ 参数生效（宽度/DPI）

def test_r57_a5_render_options_take_effect(app_client, monkeypatch):
    """宽度与 DPI 上限都生效：宽度是主参数，`dpi_cap` 是天花板；格式/质量可配。"""
    data = sample_pdf(1)
    base = pdfrender.render_pages(data, width=1024, dpi_cap=300)
    assert base[0]["width"] == 1024 and base[0]["format"] == "jpeg"
    assert base[0]["mime"] == "image/jpeg" and base[0]["bytes"] > 2000
    # 200 dpi 天花板：A4 595pt → 595/72*200 = 1653 px，仍按目标宽 1024 出图；但 1457 宽时受 200dpi 限
    wide = pdfrender.render_pages(data, width=1999, dpi_cap=200)
    assert wide[0]["width"] == 1652 or wide[0]["width"] == 1653, wide[0]
    assert abs(wide[0]["dpi_used"] - 200.0) < 0.6, wide[0]
    # 150 dpi 天花板
    p150 = pdfrender.render_pages(data, width=1999, dpi_cap=150)
    assert 1239 <= p150[0]["width"] <= 1241 and abs(p150[0]["dpi_used"] - 150.0) < 0.6, p150[0]
    # PNG 与质量参数
    png = pdfrender.render_pages(data, width=1024, fmt="png")
    assert png[0]["format"] == "png" and png[0]["mime"] == "image/png"
    lo = pdfrender.render_pages(data, width=1024, quality=40)
    hi = pdfrender.render_pages(data, width=1024, quality=92)
    assert lo[0]["bytes"] < hi[0]["bytes"], (lo[0]["bytes"], hi[0]["bytes"])
    # 页范围写法
    assert pdfrender.parse_pages("2-3,5", 6) == [2, 3, 5]
    with pytest.raises(pdfrender.PdfRenderError):
        pdfrender.parse_pages("9", 3)


def test_r57_a5_config_env_overrides_defaults(app_client, monkeypatch):
    """渲染参数从配置读（**不写死在代码里**）：环境变量一改，默认值就变。"""
    monkeypatch.setenv("MF_PAGE_IMAGE_WIDTH", "640")
    monkeypatch.setenv("MF_PAGE_IMAGE_FORMAT", "png")
    monkeypatch.setenv("MF_PAGE_IMAGE_DPI_CAP", "120")
    opts = pdfrender.render_options()
    assert opts == {"width": 640, "format": "png", "quality": 85, "dpi_cap": 120,
                    "max_bytes": 4 * 1024 * 1024, "max_pages": 400}, opts
    monkeypatch.setenv("MF_PAGE_IMAGE_WIDTH", "512")
    monkeypatch.setenv("MF_PAGE_IMAGE_DPI_CAP", "300")
    out = pdfrender.render_pages(sample_pdf(1))
    assert out[0]["width"] == 512 and out[0]["format"] == "png", out[0]


# ============================================================ ⑥ 路径②回归

def test_r57_a6_text_path_and_pdf_text_extraction_untouched(app_client):
    """路径②（pypdf 文本链路）照旧：PDF 文本导入仍走分页/分节 + 抽取体检（不碰渲染）。"""
    from app.outline.pdfparse import parse_pdf_bytes

    parsed = parse_pdf_bytes(sample_pdf(2), filename="t.pdf")
    assert parsed["pages"] == 2 and "Planetary Science" in parsed["body"]
    assert "quality" in parsed and parsed["quality"]["images"] == 0
    # 模式入口：本学科还没导入任何东西 → 模式为空、渲染就绪（装了库）
    sid = make_subject(app_client, [])
    view = app_client.get(f"/api/subjects/{sid}/materials").json()
    assert view["mode"] == "" and view["materials"] == []
    entry = app_client.get(f"/api/subjects/{sid}/mode").json()
    assert entry["mode"] == "" and entry["pdf_render_ready"] is True
    app_client.delete(f"/api/subjects/{sid}?hard=true")
