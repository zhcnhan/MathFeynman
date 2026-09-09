"""outline.pdfparse：PDF → 分页/分节文本（docs/14 §8 · Phase C C2）。

- 解析器：pypdf（BSD-3-Clause，纯 Python，Python 3.14 兼容；backend/pyproject 依赖）；
- 上传边界（错误一律中文，docs/13 §2）：非 PDF / 损坏 → PdfParseError；
  文件大小上限（MF_PDF_MAX_BYTES，默认 20MB）、页数上限（MF_PDF_MAX_PAGES，默认 400）、
  每页文本上限（防畸形页刷爆内存）——超限给中文错误提示；
- 产出：分页文本 sections（每页一条：页码 + 正文），并组装为带页标记的整段正文
  （引用材料入库 kind=pdf，分节可追溯"第 N 页"）；
- 版权边界：仅解析**用户自行上传**的自有/授权 PDF（不整本下载书籍）。
"""
from __future__ import annotations

import io

from ..config import get_settings

PDF_MAGIC = b"%PDF"


class PdfParseError(ValueError):
    """PDF 解析失败（message 中文，供 API 层直接映射 422）。"""


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def parse_pdf_bytes(data: bytes, *, filename: str = "") -> dict:
    """解析 PDF 字节 → {sections: [{page,text}], pages: int, chars: int, body: str}。"""
    s = get_settings()
    if len(data) > max(1, s.pdf_max_bytes):
        raise PdfParseError(f"PDF 文件过大（上限 {_mb(max(1, s.pdf_max_bytes))}），请压缩或截取章节后上传")
    if not data or PDF_MAGIC not in data[:1024]:
        raise PdfParseError(
            "文件不是有效的 PDF（头部缺少 %PDF 标记）" + ("：" + filename if filename else "")
        )
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
    except Exception as e:
        raise PdfParseError(f"PDF 无法解析（文件可能已损坏或加密）: {type(e).__name__}") from e
    if total_pages <= 0:
        raise PdfParseError("PDF 不含任何页面")
    if total_pages > max(1, s.pdf_max_pages):
        raise PdfParseError(f"PDF 页数过多（{total_pages} 页，上限 {max(1, s.pdf_max_pages)} 页）")
    per_page_cap = max(200, s.pdf_per_page_max_chars)
    sections: list[dict] = []
    chars = 0
    for i in range(total_pages):
        try:
            text = str(reader.pages[i].extract_text() or "")
        except Exception:  # 单页失败不整体崩溃（跳过该页并留痕）
            text = ""
        text = _clean(text)
        if len(text) > per_page_cap:
            text = text[:per_page_cap] + "\n…（该页文本过长，已按上限截取）"
        sections.append({"page": i + 1, "text": text})
        chars += len(text)
    if chars == 0:
        raise PdfParseError(
            "未能从 PDF 中提取到文本（可能为扫描图片版；请改用文本粘贴，或先做 OCR 后上传）"
        )
    body = "\n\n".join(
        f"【第 {sec['page']} 页】\n{sec['text']}" for sec in sections
    )
    return {"sections": sections, "pages": total_pages, "chars": chars, "body": body}


def _clean(text: str) -> str:
    import re

    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


__all__ = ["PdfParseError", "parse_pdf_bytes", "PDF_MAGIC"]
