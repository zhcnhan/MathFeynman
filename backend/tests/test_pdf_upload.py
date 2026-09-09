"""Phase C · C2：PDF/文档上传 → 分页/分节文本 → 引用库（kind: pdf · pypdf）。

覆盖：合法小 PDF 上传（分页文本入库、kind=pdf、源文件名留痕）；非 PDF → 中文 422；
超大小上限 → 中文 422；无可提取文本（空白页）→ 中文 422；粘贴文本入口不受影响。
"""
from __future__ import annotations

import io
import uuid

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _sid() -> str:
    return f"pdf{uuid.uuid4().hex[:6]}"


def _build_pdf(pages: list[str]) -> bytes:
    """构造最小可提取文本 PDF（标准 Helvetica，ASCII 文本——测试用）。"""
    w = PdfWriter()
    for i, line in enumerate(pages):
        p = w.add_blank_page(width=612, height=792)
        res = DictionaryObject()
        font = DictionaryObject()
        f1 = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                               NameObject("/Subtype"): NameObject("/Type1"),
                               NameObject("/BaseFont"): NameObject("/Helvetica")})
        font[NameObject("/F1")] = f1
        res[NameObject("/Font")] = font
        p[NameObject("/Resources")] = res
        s = DecodedStreamObject()
        s.set_data(
            f"BT /F1 16 Tf 72 {720 - i * 30} Td ({line}) Tj ET".encode("ascii")
        )
        p[NameObject("/Contents")] = s
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class TestPdfUpload:
    def _mk(self, app_client):
        sid = _sid()
        r = app_client.post("/api/subjects", json={"label": "PDF 材料学", "subject_id": sid})
        assert r.status_code == 201, r.text
        return sid

    def test_upload_valid_pdf_sections_saved(self, app_client):
        sid = self._mk(app_client)
        try:
            pdf = _build_pdf(["Planet Science Page One", "Planet Science Page Two"])
            r = app_client.post(
                f"/api/subjects/{sid}/materials/upload-pdf",
                data={"title": "行星科学讲义"},
                files={"file": ("planet-notes.pdf", pdf, "application/pdf")},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["kind"] == "pdf"
            assert body["title"] == "行星科学讲义"
            assert body["filename"] == "planet-notes.pdf"
            assert body["pages"] == 2 and body["chars"] > 0
            # 列表可见（kind=pdf + 文件名）
            r2 = app_client.get(f"/api/subjects/{sid}/materials")
            items = r2.json()["materials"]
            assert any(m["id"] == body["id"] and m["kind"] == "pdf"
                       and m["filename"] == "planet-notes.pdf" for m in items)
            # 分页/分节文本落库
            from app.outline.materials import materials_dir

            files = list(materials_dir(sid).glob("*.md"))
            text = files[0].read_text(encoding="utf-8")
            assert "【第 1 页】" in text and "【第 2 页】" in text
            assert "Planet Science Page One" in text and "Planet Science Page Two" in text
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_upload_not_pdf_422_chinese(self, app_client):
        sid = self._mk(app_client)
        try:
            r = app_client.post(
                f"/api/subjects/{sid}/materials/upload-pdf",
                files={"file": ("note.pdf", b"this is just a text, not a pdf", "application/octet-stream")},
            )
            assert r.status_code == 422
            msg = r.json()["detail"]["error"]["message"]
            assert "不是有效的 PDF" in msg
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_upload_over_size_limit_422_chinese(self, app_client, monkeypatch):
        monkeypatch.setenv("MF_PDF_MAX_BYTES", "200")  # 200 字节上限
        sid = self._mk(app_client)
        try:
            pdf = _build_pdf(["big enough to exceed the two hundred byte limit"])
            r = app_client.post(
                f"/api/subjects/{sid}/materials/upload-pdf",
                files={"file": ("big.pdf", pdf, "application/pdf")},
            )
            assert r.status_code == 422
            msg = r.json()["detail"]["error"]["message"]
            assert "过大" in msg
        finally:
            monkeypatch.delenv("MF_PDF_MAX_BYTES", raising=False)
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_upload_no_extractable_text_422_chinese(self, app_client):
        """扫描图片版/空白页 → 提取不到文本 → 中文提示（OCR/粘贴兜底）。"""
        sid = self._mk(app_client)
        try:
            # 无文本内容的空白页 PDF
            w = PdfWriter()
            w.add_blank_page(width=612, height=792)
            buf = io.BytesIO()
            w.write(buf)
            r = app_client.post(
                f"/api/subjects/{sid}/materials/upload-pdf",
                files={"file": ("blank.pdf", buf.getvalue(), "application/pdf")},
            )
            assert r.status_code == 422
            msg = r.json()["detail"]["error"]["message"]
            assert "未能从 PDF 中提取到文本" in msg
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")

    def test_pdf_roundtrip_reader_ok(self):
        """构造的测试 PDF 可被 pypdf 再次读取（解析器真实性守卫）。"""
        pdf = _build_pdf(["Hello Planet"])
        r = PdfReader(io.BytesIO(pdf))
        assert len(r.pages) == 1
        assert "Hello Planet" in r.pages[0].extract_text()

    def test_paste_text_upload_still_works(self, app_client):
        """粘贴文本入口保留（C2 不回归 B3）。"""
        sid = self._mk(app_client)
        try:
            r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                                json={"title": "粘贴文本", "text": "行星绕恒星运行。"})
            assert r.status_code == 201
            assert r.json()["kind"] == "local"
        finally:
            app_client.delete(f"/api/subjects/{sid}?hard=true")
