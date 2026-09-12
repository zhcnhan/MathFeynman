"""outline.pdfrender：**PDF → 页图渲染**（R57 任务 A · 图示教材模式"方案 a"）。

口径（工单 §2）：

- **可选依赖**：`pypdfium2`（许可 BSD-3-Clause / Apache-2.0，PDFium 打包在 wheel 里，
  无系统依赖）＋ `Pillow`。写在 `backend/pyproject.toml` 的 `[project.optional-dependencies].render`。
  **没装不许崩**：`render_available()` 给中文原因，调用方回落"方案 c"（让用户自己导出图片）。
- **按页渲染**：一次一页（沿用 `read_page` 一页一图的分片口径），支持页范围（`"1-5,8"`）；
  **绝不预渲染整本永久落盘**——图片只在内存里交给模型，**PDF 本体**存进**缓存目录**
  （默认 `.runtime/pdf_cache/`，`.gitignore` 覆盖，按保留期清理），`content/` 里不出现大图。
- **参数可配**（都在 `config.py`，别写死在代码里）：目标宽度（默认 1024 px，实测一页 ≈960 token）、
  格式（jpeg/png）、JPEG 质量（默认 85）、DPI 上限（默认 200）、单页字节上限、页数上限
  （沿用 `MF_PDF_MAX_PAGES`）。
- 页号**必须留痕**：返回的每一页都带 `page_no`（1 起）与渲染参数（宽/高/实际 dpi/字节/耗时），
  与"依据指到页/图号"的口径一致。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

from ..config import get_settings

FORMATS = ("jpeg", "png")
_MIME = {"jpeg": "image/jpeg", "png": "image/png"}


class PdfRenderError(ValueError):
    """渲染失败（消息一律中文，供 API 直接映射 422）。"""


# ---------------------------------------------------------------------------
# 可选依赖检测（**没装不许崩**，也不许假装支持）
# ---------------------------------------------------------------------------
def render_available() -> tuple[bool, str]:
    """能不能渲染 → ``(可用?, 中文原因)``。"""
    try:
        import pypdfium2  # noqa: F401
    except Exception:
        return False, ("这台机器上没装「渲染组件」（可选依赖 pypdfium2 + Pillow），"
                       "所以 PDF 还不能自动转成页面图片。两条路：① 自己把 PDF 每页导出成图片"
                       "（PNG/JPEG）再用上面那个入口上传；② 换一个能直接收 PDF 的服务商"
                       "（去「设置 · 模型」改服务地址与模型名即可）。")
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return False, ("这台机器上缺 Pillow（可选依赖），所以 PDF 还不能转成页面图片。"
                       "两条路：① 自己把 PDF 每页导出成图片（PNG/JPEG）后上传；"
                       "② 换一个能直接收 PDF 的服务商（在「设置 · 模型」里改）。")
    return True, "这台机器可以自动把 PDF 转成页面图片（pypdfium2 + Pillow 都在）"


def render_options() -> dict:
    """生效的渲染参数（来自 `config.py`／环境变量，可配）。"""
    s = get_settings()
    fmt = str(s.page_image_format or "jpeg").lower().replace("jpg", "jpeg")
    if fmt not in FORMATS:
        fmt = "jpeg"
    return {"width": max(64, int(s.page_image_width or 1024)),
            "format": fmt,
            "quality": min(95, max(30, int(s.page_image_quality or 85))),
            "dpi_cap": max(36, min(600, int(s.page_image_dpi_cap or 200))),
            "max_bytes": max(64 * 1024, int(s.page_image_max_bytes or 0)),
            "max_pages": max(1, int(s.pdf_max_pages or 400))}


# ---------------------------------------------------------------------------
# 页范围
# ---------------------------------------------------------------------------
def parse_pages(spec: str | list[int] | tuple[int, ...] | None, total: int) -> list[int]:
    """页范围 → 页号列表（1 起，去重、升序）。``None``/空 = 全部页。"""
    total = max(0, int(total))
    if spec in (None, "", []):
        return list(range(1, total + 1))
    if isinstance(spec, (list, tuple)):
        nums = [int(x) for x in spec]
    else:
        nums = []
        for part in str(spec).replace("，", ",").replace("－", "-").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, _, b = part.partition("-")
                try:
                    lo, hi = int(a), int(b)
                except ValueError:
                    raise PdfRenderError(f"页范围写法看不懂：{part!r}（示例：1-5,8，从 1 开始数）")
                if hi < lo:
                    lo, hi = hi, lo
                nums.extend(range(lo, hi + 1))
            else:
                try:
                    nums.append(int(part))
                except ValueError:
                    raise PdfRenderError(f"页范围写法看不懂：{part!r}（示例：1-5,8，从 1 开始数）")
    picked = sorted({n for n in nums if n >= 1})
    bad = [n for n in picked if n > total]
    if bad:
        raise PdfRenderError(f"要读的页超出这本书的范围：这本书只有 {total} 页，"
                             f"你要的是第 {'、'.join(str(x) for x in bad[:5])} 页")
    if not picked:
        raise PdfRenderError("没有选中任何一页（页号从 1 开始数）")
    return picked


# ---------------------------------------------------------------------------
# 渲染（内存里出图；**不落永久图片**）
# ---------------------------------------------------------------------------
def render_pages(data: bytes, *, pages: str | list[int] | None = None, width: int | None = None,
                 fmt: str | None = None, quality: int | None = None, dpi_cap: int | None = None,
                 max_pages: int | None = None, max_bytes: int | None = None) -> list[dict]:
    """PDF 字节 → ``[{page_no, mime, data, width, height, dpi_used, ms, bytes}]``（**内存里**）。

    - ``pages``：页范围（``"1-5,8"``；空 = 全部页）；
    - 出图宽度优先按 ``width``（默认 1024 px），同时受 ``dpi_cap`` 限制
      （实际 dpi = min(目标宽隐含 dpi, dpi_cap)），**两个参数都生效**；
    - 页数上限＝``max_pages``（默认沿用 `MF_PDF_MAX_PAGES`）；超限**中文报错**；
    - 单页超过 ``max_bytes`` → 先降质量重出一次；仍超 → 中文报错（不静默发超大图）。
    """
    ok, why = render_available()
    if not ok:
        raise PdfRenderError(why)
    opts = render_options()
    width = int(width or opts["width"])
    fmt = str(fmt or opts["format"]).lower().replace("jpg", "jpeg")
    if fmt not in FORMATS:
        raise PdfRenderError(f"图片格式只能是 jpeg 或 png，收到 {fmt!r}")
    quality = int(quality or opts["quality"])
    dpi_cap = float(dpi_cap or opts["dpi_cap"])
    max_pages = int(max_pages or opts["max_pages"])
    max_bytes = int(max_bytes if max_bytes is not None else opts["max_bytes"])

    if not data or b"%PDF" not in data[:1024]:
        raise PdfRenderError("这不是有效的 PDF（文件头没有 %PDF 标记）")

    import pypdfium2 as pdfium
    from PIL import Image  # noqa: F401  （确保 to_pil() 可用）

    try:
        doc = pdfium.PdfDocument(io.BytesIO(data))
    except Exception as e:
        raise PdfRenderError(f"PDF 打不开（文件可能损坏或加密）：{type(e).__name__}") from e
    # **R58 任务 A（真缺陷修复）**：PDFium 的原生句柄必须**显式关闭**——
    # 之前只 `PdfDocument(...)`，句柄要等 GC 才释放：长跑进程反复导入 PDF 会累积原生内存，
    # **出错路径必然泄漏**（例如"某页图太大"抛错那条分支，doc 永远不会被关）。
    # 口径：`try/finally` 包住，`finally` 里关 doc；循环里的 page / bitmap 也各自关掉。
    # ⚠️ 关闭顺序：`to_pil()` 可能与 bitmap 共享内存（零拷贝），所以 **bitmap 要等编码完再关**。
    try:
        try:
            total = len(doc)
        except Exception as e:
            raise PdfRenderError(f"PDF 页数读不出来（文件可能损坏）：{type(e).__name__}") from e
        if total <= 0:
            raise PdfRenderError("这份 PDF 没有任何页面")
        if total > max_pages:
            raise PdfRenderError(f"这份 PDF 有 {total} 页，超过上限 {max_pages} 页——"
                                 "请拆分后分批导入，或只读其中一段（页范围）")

        picked = parse_pages(pages, total)
        out: list[dict] = []
        for page_no in picked:
            page = doc[page_no - 1]
            try:
                w_pt, h_pt = page.get_size()
                dpi = min(width / max(1.0, w_pt) * 72.0, float(dpi_cap))
                scale = dpi / 72.0
                t0 = time.perf_counter()
                try:
                    bitmap = page.render(scale=scale)
                except Exception as e:
                    raise PdfRenderError(f"第 {page_no} 页渲染失败：{type(e).__name__}") from e
                try:
                    img = bitmap.to_pil()
                    data_bytes, px_w, px_h = _encode_with_limit(
                        img, fmt=fmt, quality=quality, max_bytes=max_bytes, page_no=page_no)
                finally:
                    bitmap.close()          # 原生位图先关（图已编码完）
                    try:
                        img.close()         # PIL 侧也放掉（可能是零拷贝视图）
                    except Exception:
                        pass
                out.append({"page_no": page_no, "mime": _MIME[fmt], "data": data_bytes,
                            "width": px_w, "height": px_h,
                            "dpi_used": round(dpi, 1), "bytes": len(data_bytes),
                            "ms": round((time.perf_counter() - t0) * 1000, 1), "format": fmt})
            finally:
                page.close()                # 每页的页对象也关（别等 GC）
        return out
    finally:
        doc.close()                         # **成功/出错/中断都关**（这条就是本次修的真缺陷）


def _encode(img, fmt: str, quality: int) -> io.BytesIO:
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.convert("RGB").save(buf, format="JPEG", quality=int(quality), optimize=True)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf


def _encode_with_limit(img, *, fmt: str, quality: int, max_bytes: int,
                       page_no: int) -> tuple[bytes, int, int]:
    """编码（超字节上限先降质量重试一次）→ ``(字节, 宽, 高)``。

    与 R57 的行为逐位一致：正常路径只编码一次、质量不变；只有超限时才降 25 质量重出一次。
    宽高在**编码时**就取下来（图片随后会被关掉，不能再取）。
    """
    px_w, px_h = int(img.width), int(img.height)
    buf = _encode(img, fmt, quality)
    if max_bytes and buf.getbuffer().nbytes > max_bytes:
        buf = _encode(img, fmt, max(30, quality - 25))       # 先降质量重试一次
    data_bytes = buf.getvalue()
    if max_bytes and len(data_bytes) > max_bytes:
        raise PdfRenderError(f"第 {page_no} 页渲染出来太大（{len(data_bytes) // 1024} KB > "
                             f"{max_bytes // 1024} KB）——请把目标宽度调小"
                             "（MF_PAGE_IMAGE_WIDTH）后重试")
    return data_bytes, px_w, px_h


# ---------------------------------------------------------------------------
# PDF 缓存（**不进 content/**；进 .gitignore；按保留期清理）
# ---------------------------------------------------------------------------
def cache_dir() -> Path:
    return Path(get_settings().pdf_cache_dir)


def save_pdf_cache(subject_id: str, key: str, data: bytes) -> str:
    """把上传的 PDF 存进缓存目录（供"以后再读某几页"用），返回文件名。"""
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{_safe(subject_id)}-{_safe(key)}.pdf"
    (d / name).write_bytes(data)
    return name


def load_pdf_cache(subject_id: str, key: str) -> bytes | None:
    p = cache_dir() / f"{_safe(subject_id)}-{_safe(key)}.pdf"
    return p.read_bytes() if p.exists() else None


def cleanup_pdf_cache(keep_days: int | None = None, *, note: bool = True,
                      trigger: str = "手动") -> dict:
    """按保留期清理缓存（**先记账再删**，与审计清理同款口径）。

    **R58 任务 B**：``trigger`` 写进账目 ``detail.trigger``（``启动`` / ``定时`` / ``手动``）——
    与 R48 B 的审计清理口径**完全一致**；本函数被既有 `ai_trace.cleanup_once` 复用
    （启动/定时/手动三处**同一套定时器**，不新建第二个机制）。
    异常只 warning、不抛（清理不影响主流程）。
    """
    import datetime as _dt

    days = int(get_settings().pdf_cache_keep_days if keep_days is None else keep_days)
    days = max(0, days)
    d = cache_dir()
    removed: list[str] = []
    freed = 0
    if d.exists():
        cut = _dt.datetime.now().timestamp() - days * 86400
        for p in sorted(d.glob("*.pdf")):
            try:
                if p.stat().st_mtime < cut:
                    freed += p.stat().st_size
                    p.unlink()
                    removed.append(p.name)
            except Exception:
                continue
    if note and removed:
        from ..service import ledger

        ledger.note(ledger.CAT_MATERIAL, "PDF 页图渲染缓存清理",
                    f"按保留期（{days} 天）清掉了 {len(removed)} 个渲染用的 PDF 缓存文件"
                    f"（释放 {freed // 1024} KB）——缓存里只有你上传的 PDF，页面图片本来就没落盘",
                    impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_YES,
                    detail={"kind": "pdf_cache_cleanup", "trigger": str(trigger or "手动"),
                            "removed": removed[:20],
                            "keep_days": days, "freed_bytes": freed})
    return {"keep_days": days, "removed": removed, "removed_count": len(removed),
            "freed_bytes": freed, "dir": str(d), "trigger": str(trigger or "手动")}


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))[:64] or "x"


__all__ = ["FORMATS", "PdfRenderError", "render_available", "render_options", "parse_pages",
           "render_pages", "cache_dir", "save_pdf_cache", "load_pdf_cache", "cleanup_pdf_cache"]
