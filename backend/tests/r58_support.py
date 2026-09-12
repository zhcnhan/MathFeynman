"""R58 用例共用工具：固定样本 PDF、pypdfium2「未关闭对象」计数、共用夹具。"""
from __future__ import annotations

import base64

import pytest

from app.service import model_config

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")


def sample_pdf(n_pages: int = 2) -> bytes:
    """手搓合法多页 PDF（Helvetica 真文字，595×842 pt ≈ A4；渲染结果可复现）。"""
    objs: list[bytes] = []
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(n_pages):
        content = (f"BT /F1 28 Tf 60 760 Td (Planetary Science - page {i + 1}) Tj ET\n"
                   f"BT /F1 16 Tf 60 700 Td (The solar system has eight planets.) Tj ET").encode()
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


def alive_objects() -> dict[str, int]:
    """pypdfium2 **自己维护的**未关闭对象表（弱引用）→ ``{类名: 个数}``。

    这比"退出时的日志提示"确定得多（日志受级别/关闭时序影响）。
    """
    import pypdfium2.internal as pdfium_i

    counts: dict[str, int] = {}
    for _cls, wrefs in pdfium_i.ObjectTracker.items():
        for w in list(wrefs):
            obj = w()
            if obj is not None:
                name = type(obj).__name__
                counts[name] = counts.get(name, 0) + 1
    return counts


def isolate_model_and_cache(app_client, monkeypatch, tmp_path):
    """每条用例：清空模型配置 + 把 PDF 缓存指到临时目录（**不碰仓库缓存**）。

    ⚠️ 这是**普通生成器函数**，不是 fixture：非 conftest 模块里的 autouse fixture 不会作用于
    其它模块，所以各测试文件各自 `yield from` 调用它（这样三个文件都能用同一份口径）。
    """
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
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r58")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    try:
        yield
    finally:
        _clear()
