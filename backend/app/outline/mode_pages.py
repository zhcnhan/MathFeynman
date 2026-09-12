"""outline.mode_pages：**图示教材模式（全 AI 模式）的页面图片入库**（R56 第 3 步 + R57 任务 A）。

职责很小、很清楚（工单 §1：程序只负责"流程骨架 / 提示词 / 材料递送 / 记录"）：

1. **存图片**：把上传的页面图片写到该学科材料目录下的 `pages-<id>/`（不走 `*.md` 通配，不会污染材料列表）；
2. **读图片**：逐张调 `ai.vision.read_page`（＝本模式的"读教材"环节，走既有审计）；
3. **读不出来的如实记**：`readable=false` 的页**照样入库**（正文里写明"这一页读不出来 + 原因"），
   并记一条中文账 —— 不许静默当成"这一页没内容"；
4. **入库**：用**既有材料层** `materials.add_material(mode="all_ai")` 存一份 `.md`
   （正文＝各页"读到了什么"的拼接），并把结构化记录另存 `*.pages.json`（供出题/判题按页取用）。

**R57 任务 A（方案 a）**：入口也允许**直接给 PDF** —— 交给 `outline.pdfrender` **按页渲染成图片**
（一页一图、页号留痕、参数可配），图片**只在内存里**发给模型，**不往 `content/` 落大图**；
PDF 本体存进**缓存目录**（`.runtime/pdf_cache/`，`.gitignore` 覆盖 + 保留期清理），
以便"以后再读某几页"（`reread_pages`）。**没装渲染库 → 中文说明 + 回落方案 c**（用户自己导出图片）。

前置校验（工单 §3-A / R57 §2.2）：**没配能读图的模型 → 中文明确拒绝，不落库**。

**R61 任务 A**：认不出页号的旧标签（如「封面」）可以由用户**人工指定**"这一页当作第 N 页"
（`set_page_mapping` / `undo_page_mapping`，**不调用模型**）——指定后这一页就有页号、
能被引用，也可以再点重读把它读出来；指定与撤销都进账。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..ai.vision import image_block, read_page
from ..service import ledger
from . import materials as mat
from . import pdfrender

MAX_PAGES = 60                      # 一次最多多少页（避免一次导入把额度打光；可分批再传）
ALLOWED_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif")
_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif"}


def _image_cache_dir() -> Path:
    """原始页面图（用户上传的那几张）的缓存目录（**gitignored，不进 `content/`**）。"""
    d = pdfrender.cache_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_image_cache(subject_id: str, entry_id: str, i: int, name: str, data: bytes) -> str:
    suffix = Path(name).suffix.lower() or ".png"
    fn = f"{subject_id}-{entry_id.replace('mat-', '')}-page-{i:04d}{suffix}"
    (_image_cache_dir() / fn).write_bytes(data)
    return fn


def _mime_of(filename: str, given: str = "") -> str:
    mime = (given or "").strip().lower()
    if mime in ALLOWED_MIME:
        return "image/jpeg" if mime == "image/jpg" else mime
    return _MIME_BY_SUFFIX.get(Path(filename or "").suffix.lower(), "")


def import_pages(db, subject_id: str, *, title: str, files: list[tuple[str, bytes]],
                 provider=None, source: str = "页面图片导入", want: str = "",
                 pdf_pages: str = "") -> dict:
    """图片（或 PDF）→ 读取记录 → 入库（返回 ``{id, title, page_count, pages, unreadable, note_zh, cost}``）。

    ``files`` ＝ ``[(filename, bytes), ...]``（按页序）。任何一张读不出来都**不影响**入库，
    但会在正文/账本/返回值里如实标出。

    **R57**：若第一个文件是 PDF（``%PDF`` 文件头）→ 交给 `pdfrender` **按页渲染**（``pdf_pages`` 指定页范围），
    渲染库没装 → 中文报错（回落方案 c，由界面提示用户自己导出图片）。
    """
    from ..service import model_config

    ok, why = model_config.supports_vision(db)
    if not ok:
        # 工单 §3-A：前置校验不过 → 中文明确拒绝，**不落库**
        from .schemas import OutlineError

        raise OutlineError("这条路需要能读图片的模型：" + why)

    if not files:
        from .schemas import OutlineError

        raise OutlineError("还没有选择页面图片（支持 PNG / JPEG / WebP / GIF）或 PDF")
    if len(files) > MAX_PAGES:
        from .schemas import OutlineError

        raise OutlineError(f"一次最多 {MAX_PAGES} 页（现在 {len(files)} 页）——请分批上传")

    if provider is None:
        provider = _build_provider(db)

    # ---- R57 方案 a：PDF → 按页渲染（图片只在内存里；PDF 进缓存目录） ----
    render_info: dict = {}
    pdf_bytes: bytes | None = None
    first_name, first_data = files[0]
    is_pdf = b"%PDF" in bytes(first_data)[:1024]
    if is_pdf:
        pdf_bytes = bytes(first_data)
        picked = pdfrender.render_pages(pdf_bytes, pages=pdf_pages or None)
        render_info = {"source": "pdf_render", "pages": [p["page_no"] for p in picked],
                       "width": picked[0]["width"] if picked else 0,
                       "dpi": picked[0]["dpi_used"] if picked else 0,
                       "format": picked[0]["format"] if picked else "",
                       "bytes_avg": (sum(p["bytes"] for p in picked) // max(1, len(picked))),
                       "ms_total": round(sum(p["ms"] for p in picked), 1),
                       "pages_spec": str(pdf_pages or "")}
        files = [(f"page{p['page_no']:04d}.{'jpg' if p['format'] == 'jpeg' else 'png'}", p["data"])
                 for p in picked]
        # 页号留痕：渲染出来的第 N 页＝PDF 的第 N 页（页范围也保住原页号）
        page_labels = [f"第 {p['page_no']} 页" for p in picked]
    else:
        page_labels = [f"第 {i} 页" for i in range(1, len(files) + 1)]

    records: list[dict] = []
    started = time.time()
    for i, (name, data) in enumerate(files):
        mime = _mime_of(name)
        label = page_labels[i] if i < len(page_labels) else f"第 {i + 1} 页"
        if not mime:
            records.append({"page_label": label, "readable": False,
                            "unreadable_reason": f"这个文件不是支持的图片格式（{name}）"})
            continue
        out, version = read_page(
            provider, images=[image_block(data, mime=mime)],
            page_label=label, want=want or "这一页的正文要点、公式与图里画了什么",
            note=f"用户上传的{('PDF 第 ' + label.replace('第 ', '').replace(' 页', '') + ' 页渲染图') if is_pdf else '第 ' + str(i + 1) + ' 页图片'}（{name}）",
            subject_id=subject_id,
        )
        rec = out.model_dump()
        rec["image"] = name
        rec["mime"] = mime
        rec["prompt_version"] = version
        if is_pdf and i < len(render_info.get("pages", [])):
            rec["page_no"] = render_info["pages"][i]
        records.append(rec)
    elapsed_ms = int((time.time() - started) * 1000)

    text, unreadable = _digest_text(records)
    if not text.strip():
        text = "（这些页面都没有读出可用内容——每一页的原因见下）\n" + "\n".join(
            f"- {r.get('page_label')}：{r.get('unreadable_reason') or '没有内容'}" for r in records)

    entry = mat.add_material(
        db, subject_id, title=title or "页面图片教材", text=text, source=source,
        kind="pages", mode=mat.MODE_ALL_AI, page_count=len(records),
        pages_file="",          # 先入库拿到 id，再写 pages.json 回来补 frontmatter
    )
    entry_id = str(entry["id"])
    # **R57 红线**：页面图片**一律不落 `content/`**（避免仓库膨胀；渲染出来的大图尤其不许）。
    # "读到了什么"进 `*.pages.json`；原始图（或 PDF）进 **gitignored 缓存目录**，供"以后再读某几页"。
    cache_names: list[str] = []
    if is_pdf and pdf_bytes is not None:
        # PDF 进**缓存目录**（gitignored），供"以后再读某几页"；**渲染出来的图一张都不落盘**
        render_info["key"] = entry_id
        render_info["cache"] = pdfrender.save_pdf_cache(subject_id, entry_id, pdf_bytes)
    elif not is_pdf:
        for i, (name, data) in enumerate(files, start=1):
            if not _mime_of(name):
                continue
            cache_names.append(_save_image_cache(subject_id, entry_id, i, name, bytes(data)))
        render_info = {"source": "uploaded_images", "cache": cache_names}
    pages_name = f"pages-{entry_id.replace('mat-', '')}.pages.json"
    (mat.materials_dir(subject_id) / pages_name).write_text(
        json.dumps({"title": entry["title"], "pages": records, "render": render_info},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    mat.set_material_pages_file(db, subject_id, entry_id, pages_name)

    # 记账：读不出来的页 + 成本量级（工单 §5/§6：读不出来的页/图必须进账）
    if unreadable:
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{entry['title']}》· 有页面读不出来",
            f"这份材料有 {len(unreadable)} 页模型读不出来（{'、'.join(unreadable[:5])}）——"
            "这些页**没有**被当成内容用，正文与判题依据里都会写明「读不出来」",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "pages_unreadable", "pages": unreadable[:20],
                    "page_count": len(records)},
        )
    ledger.note(
        ledger.CAT_MATERIAL, f"材料《{entry['title']}》· 图示教材模式",
        f"按「图片为主的教材（全程交给 AI 判断）」导入了 {len(records)} 页："
        f"逐页让模型读了一遍（共 {elapsed_ms} 毫秒）。"
        "这个模式没有独立的第二次核对，判对错与评分都由模型给出；每一步都要问模型，所以更贵。",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"kind": "all_ai_pages_imported", "page_count": len(records),
                "unreadable": len(unreadable), "elapsed_ms": elapsed_ms},
    )
    return {"id": entry_id, "title": entry["title"], "page_count": len(records),
            "unreadable": unreadable, "pages": records, "elapsed_ms": elapsed_ms,
            "render": render_info,
            "text_health": entry.get("text_health"), "mode": mat.MODE_ALL_AI,
            "note_zh": (f"已导入 {len(records)} 页；其中 {len(unreadable)} 页读不出来"
                        if unreadable else f"已导入 {len(records)} 页，全部读到了内容"),
            "boundary": mat.mode_entry_zh()}


def _digest_text(records: list[dict]) -> tuple[str, list[str]]:
    """把页面记录拼成材料正文（**读不出来的页也写清楚**）+ 读不出来的页标签。"""
    lines: list[str] = []
    unreadable: list[str] = []
    for r in records:
        label = str(r.get("page_label") or "")
        if r.get("readable") is False:
            reason = str(r.get("unreadable_reason") or "（模型没说明原因）")
            unreadable.append(label)
            lines.append(f"【{label}】⚠️ 这一页读不出来：{reason}")
            continue
        lines.append(f"【{label}】")
        for key, title in (("key_points", "要点"), ("visible_text", "页面文字"),
                           ("formulas", "公式")):
            vals = [str(x) for x in (r.get(key) or []) if str(x).strip()]
            if vals:
                lines.append(f"{title}：" + "；".join(vals))
        for f in (r.get("figures") or []):
            lines.append(f"图：{f.get('label') or '图'}（{f.get('kind') or '图'}）："
                         f"{f.get('description') or ''}")
        unc = [str(x) for x in (r.get("uncertain") or []) if str(x).strip()]
        if unc:
            lines.append("看不清：" + "；".join(unc))
        lines.append("")
    return "\n".join(lines), unreadable


def _build_provider(db):
    from ..ai.provider import OpenAICompatibleProvider
    from ..service.ai_sink import make_ai_log_sink
    from ..service import model_config

    s = model_config.effective_settings(db)
    return OpenAICompatibleProvider(
        api_key=s.llm_api_key, base_url=s.llm_base_url,
        model_heavy=s.llm_model_heavy, model_light=model_config.vision_model(db),
        log_sink=make_ai_log_sink(),
    )


def load_pages(subject_id: str, material_id: str) -> list[dict]:
    """读回某份材料的页面记录（出题/判题按页取依据用）；没有就返回空。"""
    return list((_pages_doc(subject_id, material_id) or {}).get("pages") or [])


def _pages_doc(subject_id: str, material_id: str) -> dict | None:
    """读取整份 `*.pages.json`（页面记录 + 渲染/缓存口径）。"""
    d = mat.materials_dir(subject_id)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        name = str(e.get("pages_file") or "")
        f = d / name
        if not name or not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8")) or {}
        except Exception:
            return None
    return None


def _write_pages_doc(subject_id: str, material_id: str, records: list[dict],
                     render: dict) -> bool:
    """把页面记录写回该材料的 `*.pages.json`（与 `reread_pages` **同一条路径、同一种写法**）。

    返回是否真的写下去了（材料不存在 / 没有页面记录文件 → False，调用方自己决定怎么说话）。
    """
    d = mat.materials_dir(subject_id)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        name = str(e.get("pages_file") or "")
        if not name:
            return False
        (d / name).write_text(
            json.dumps({"title": e["title"], "pages": records, "render": render},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    return False


def reread_pages(db, subject_id: str, material_id: str, *, pages: str = "",
                 provider=None, want: str = "") -> dict:
    """**按需取页范围**：从缓存里取原始图（或 PDF 重渲染那几页）→ 再读一遍 → 合并回页面记录。

    - PDF 导入的材料：用缓存里的 **PDF** 重渲染指定页（`pdf_pages` 口径）；
    - 图片导入的材料：用缓存里的**原始页面图**；
    - 合并口径：同一页（`page_no` / `page_label`）**替换**，新页**追加**，其余不动（幂等可重跑）。
    """
    from ..service import model_config

    ok, why = model_config.supports_vision(db)
    if not ok:
        from .schemas import OutlineError

        raise OutlineError("这条路需要能读图片的模型：" + why)
    doc = _pages_doc(subject_id, material_id) or {}
    render = dict(doc.get("render") or {})
    records = list(doc.get("pages") or [])
    if not records:
        from .schemas import OutlineError

        raise OutlineError(f"材料不存在或还没有页面记录: {material_id}")
    if provider is None:
        provider = _build_provider(db)

    # **R59**：一键重读"读不出来的页"——`pages="unreadable"`
    # 口径：只挑 `readable=false` 的页；**一页都没有 → 不调用模型**（也**不记账**，没发生的事不记），
    # 只回一句中文说明（界面直接显示）。已 readable 的页**永不重读** ⇒ 天然幂等、不重复计费。
    unreadable_only = str(pages or "").strip().lower() == "unreadable"
    skipped_labels: list[str] = []
    if unreadable_only:
        bad_labels = [str(r.get("page_label") or "") for r in records if r.get("readable") is False]
        if not bad_labels:
            return {"id": material_id, "title": doc.get("title") or "", "reread": [], "count": 0,
                    "pages": records, "unreadable": [], "skipped": [], "model_calls": 0,
                    "note_zh": "这份材料没有读不出来的页，不用重读。",
                    "reason_zh": "这份材料没有读不出来的页，不用重读（没有调用模型，也没花钱）。"}
        mapped = [_label_to_page_no(x) for x in bad_labels]
        # **R60 任务 B**：页标签认不出页号（只可能来自更早版本留下的旧记录，如「封面」）→
        # **跳过这一页、如实列出**，不再 422 让用户把整份材料重导一遍（代价过大）。
        # "跳过不是静默"：下面无论走哪条路都进账本 + 在返回值里显式列出 skipped。
        skipped_labels = [lbl for lbl, num in zip(bad_labels, mapped) if not num.isdigit()]
        keep = [num for num in mapped if num.isdigit()]
        if not keep:
            # 一页都定位不到 ⇒ 没有可读的页：**不调用模型**（也就不花钱），但**要留痕**。
            note_zh = (f"这份材料有 {len(skipped_labels)} 页标着「读不出来」，"
                       f"但标签里没有页号，已跳过：{'、'.join(skipped_labels[:8])}"
                       "——要么重新导入这份材料，要么自己在上面填页号重读。")
            ledger.note(
                ledger.CAT_MATERIAL, f"材料《{doc.get('title') or material_id}》· 按页重读",
                "这些页标着「读不出来」，但标签里没有页号（旧格式），已跳过、没法一键重读："
                + "、".join(skipped_labels[:8]) + "；这一次没有调用模型，也没花钱。",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                detail={"kind": "pages_reread_skipped", "trigger": "unreadable",
                        "skipped": skipped_labels[:20], "count": 0},
            )
            return {"id": material_id, "title": doc.get("title") or "", "reread": [], "count": 0,
                    "pages": records, "unreadable": bad_labels, "skipped": skipped_labels,
                    "model_calls": 0, "note_zh": note_zh,
                    "reason_zh": note_zh + "（没有调用模型，也没花钱）"}
        pages = ",".join(keep)

    is_pdf = str(render.get("source") or "") == "pdf_render"
    rendered: list[tuple[str, str, bytes, int | None]] = []   # (label, mime, bytes, page_no)
    if is_pdf:
        cache = str(render.get("cache") or "")
        data = pdfrender.load_pdf_cache(subject_id, str(render.get("key") or material_id))
        if not data or not cache:
            from .schemas import OutlineError

            raise OutlineError("这份材料的 PDF 缓存已经清理掉了，没法按页重读——"
                               "请重新导入这份 PDF（缓存只保留一段时间）")
        picked = pdfrender.render_pages(data, pages=pages or None)
        for p in picked:
            rendered.append((f"第 {p['page_no']} 页", p["mime"], p["data"], p["page_no"]))
    else:
        names = [str(x) for x in (render.get("cache") or [])]
        picked = pdfrender.parse_pages(pages, len(names)) if pages else list(range(1, len(names) + 1))
        for n in picked:
            fn = names[n - 1] if n - 1 < len(names) else ""
            f = _image_cache_dir() / fn if fn else None
            if not fn or not f.exists():
                from .schemas import OutlineError

                raise OutlineError(f"第 {n} 页的原始图片缓存不在了，没法重读——请重新导入这张图")
            rendered.append((f"第 {n} 页", _mime_of(fn) or "image/png", f.read_bytes(), n))

    updated: list[dict] = []
    for label, mime, data_bytes, page_no in rendered:
        out, version = read_page(
            provider, images=[image_block(data_bytes, mime=mime)],
            page_label=label, want=want or "这一页的正文要点、公式与图里画了什么",
            note=f"按需重读的 {label}", subject_id=subject_id)
        rec = out.model_dump()
        rec["prompt_version"] = version
        if page_no is not None:
            rec["page_no"] = page_no
        updated.append(rec)
    merged = _merge_pages(records, updated)
    _write_pages_doc(subject_id, material_id, merged, render)
    labels = [str(r.get("page_label") or "") for r in updated]
    # 重读之后仍读不出来的页（如实回显"还剩哪几页读不出来"）
    still_bad = [str(r.get("page_label") or "") for r in merged if r.get("readable") is False]
    skip_zh = (f"另有 {len(skipped_labels)} 页标签里没有页号，已跳过："
               + "、".join(skipped_labels[:8]) + "；" if skipped_labels else "")
    ledger.note(
        ledger.CAT_MATERIAL, f"材料《{doc.get('title') or material_id}》· 按页重读",
        ("把**读不出来的页**再读一遍：" if unreadable_only else "按你的要求把 ")
        + f"{'、'.join(labels[:8])} 重新读了一遍（共 {len(updated)} 页）——"
        + ("这次仍然读不出来：" + "、".join(still_bad[:8]) + "；" if still_bad else "")
        + (skip_zh or "")
        + "页面记录已就地更新；这一步同样要问模型，所以也会花钱。",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"kind": "pages_reread", "pages": labels[:20], "count": len(updated),
                "source": render.get("source") or "",
                "trigger": ("unreadable" if unreadable_only else "pages"),
                "still_unreadable": still_bad[:20],
                "skipped": skipped_labels[:20]},
    )
    return {"id": material_id, "title": doc.get("title") or "", "reread": labels,
            "count": len(updated), "pages": merged, "unreadable": still_bad,
            "skipped": skipped_labels, "model_calls": len(updated),
            "note_zh": ((f"把读不出来的页又读了一遍（{'、'.join(labels[:8])}）"
                         + (f"；还是读不出来：{'、'.join(still_bad[:8])}" if still_bad else "；这次都读到了"))
                        if unreadable_only else f"已重新读：{'、'.join(labels[:8])}")
                       + (f"。另有 {len(skipped_labels)} 页标签里没有页号，已跳过："
                          + "、".join(skipped_labels[:8]) + "（这几页需要自己填页号重读）"
                          if skipped_labels else "")}


# ---------------------------------------------------------------------------
# **R61 任务 A**：认不出页号的旧标签（如「封面」）→ 用户**人工指定**"这一页当作第 N 页"
# ---------------------------------------------------------------------------
class PageMappingError(ValueError):
    """人工指定页号时的中文错误。

    ``status`` ＝ 这件事该用哪个 HTTP 状态回给界面（页号非法 422 / 找不到页 404 / 撞页 409）；
    所有 message 都是给人看的中文，不含任何内部字段名。
    """

    def __init__(self, message: str, *, status: int = 422):
        super().__init__(message)
        self.status = int(status)


def _clean_page_no(raw) -> int:
    """用户给的页号（**1 以上的整数**才算数；``True`` 与 "4" 这类字符串一律不接受）。"""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise PageMappingError(f"页号得是 1 以上的整数（现在给的是 {raw}）")
    return int(raw)


def _find_page_record(records: list[dict], label: str) -> dict | None:
    """按标签找那一条页面记录：先认**现在的**标签，再认人工指定前留下的**旧标签**。

    （旧标签是撤销与"重复指定同一页号"两步的入口：指定之后这一页的标签已变成「第 N 页」。）
    """
    for r in records:
        if str(r.get("page_label") or "") == label:
            return r
    for r in records:
        if (str(r.get("page_no_source") or "") == "manual"
                and str(r.get("original_label") or "") == label):
            return r
    return None


def skipped_page_labels(records: list[dict]) -> list[str]:
    """仍需用户自己说页号的页标签：**读不出来 + 标签里没有页号**（＝界面上那份清单）。"""
    return [str(r.get("page_label") or "") for r in records
            if r.get("readable") is False
            and not _label_to_page_no(str(r.get("page_label") or "")).isdigit()]


def _mapping_out(material_id: str, doc: dict, records: list[dict], *, label: str,
                 original_label: str, page_no, note_zh: str) -> dict:
    """两个端点的同一个返回形状（页面记录 + 还差哪几页没页号 + 一句中文说明）。"""
    return {"id": material_id, "title": doc.get("title") or "", "label": label,
            "original_label": original_label, "page_no": page_no, "pages": records,
            "skipped": skipped_page_labels(records), "note_zh": note_zh}


def set_page_mapping(subject_id: str, material_id: str, *, label, page_no) -> dict:
    """**R61 任务 A**：把某个认不出页号的旧标签，人工指定成"第 N 页"（**不调用模型**）。

    只动这一条记录（页标签 + 三个留痕字段），其余记录一律不碰；同一个标签指定同一个页号
    是重复点击，直接回一句中文说明，不再记一次账。
    """
    user_label = str(label or "").strip()
    doc = _pages_doc(subject_id, material_id)
    if doc is None:
        raise PageMappingError("这份材料找不到页面记录，没法指定页号", status=404)
    records = list(doc.get("pages") or [])
    page_no = _clean_page_no(page_no)
    target = _find_page_record(records, user_label)
    if target is None:
        raise PageMappingError(f"这份材料里没有标签为「{user_label}」的一页", status=404)

    original = str(target.get("original_label") or target.get("page_label") or "")
    manual = str(target.get("page_no_source") or "") == "manual"
    if manual and int(target.get("manual_page_no") or 0) == page_no:
        # 重复点了同一个「标签 → 页号」：什么都没变，就不留新账
        return _mapping_out(material_id, doc, records, label=user_label,
                            original_label=original, page_no=page_no,
                            note_zh=f"这一页已经是第 {page_no} 页了")
    current_no = _label_to_page_no(str(target.get("page_label") or ""))
    if manual or current_no.isdigit():
        raise PageMappingError(f"这一页已经有页号了（第 {current_no} 页），不用再指定")

    taken = ""
    for r in records:
        if r is target:
            continue
        if _label_to_page_no(str(r.get("page_label") or "")) == str(page_no):
            taken = str(r.get("page_label") or "")
            break
    if taken:
        raise PageMappingError(
            f"第 {page_no} 页已经有别的页了（标签是「{taken}」）——"
            "请换一个页号，或先撤销那一页的指定", status=409)

    target["original_label"] = original
    target["page_label"] = f"第 {page_no} 页"
    target["manual_page_no"] = page_no
    target["page_no_source"] = "manual"
    _write_pages_doc(subject_id, material_id, records, dict(doc.get("render") or {}))
    ledger.note(
        ledger.CAT_MATERIAL, f"材料《{doc.get('title') or material_id}》· 旧标签指定页号",
        f"用户把旧标签「{user_label}」指定为第 {page_no} 页"
        "（原来没有页号，读不出是第几页）。",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"kind": "page_mapping", "label": user_label, "original_label": original,
                "page_no": page_no},
    )
    return _mapping_out(
        material_id, doc, records, label=user_label, original_label=original, page_no=page_no,
        note_zh=(f"已把「{user_label}」当作第 {page_no} 页；想让它有内容，"
                 "可以点「重读这几页」把它读一遍（会再问一次模型，也会花钱）。"))


def undo_page_mapping(subject_id: str, material_id: str, label) -> dict:
    """**R61 任务 A**：撤销人工指定的页号，让它回到"读不出页号"的那份清单里（**不调用模型**）。

    只认得 ``page_no_source == "manual"`` 的那一页；撤销后把人工留下的三个字段去掉、
    页标签还原成旧标签，别的记录一律不动。
    """
    user_label = str(label or "").strip()
    doc = _pages_doc(subject_id, material_id)
    if doc is None:
        raise PageMappingError("这份材料找不到页面记录，没法撤销页号", status=404)
    records = list(doc.get("pages") or [])
    target = _find_page_record(records, user_label)
    if target is None or str(target.get("page_no_source") or "") != "manual":
        raise PageMappingError("这一页不是人工指定的页号，不能撤销")

    back = str(target.get("original_label") or target.get("page_label") or "")
    was = target.get("manual_page_no")
    if was is None:
        was = _label_to_page_no(str(target.get("page_label") or ""))
    target["page_label"] = back
    target.pop("manual_page_no", None)
    target.pop("page_no_source", None)
    target.pop("original_label", None)
    _write_pages_doc(subject_id, material_id, records, dict(doc.get("render") or {}))
    ledger.note(
        ledger.CAT_MATERIAL, f"材料《{doc.get('title') or material_id}》· 撤销人工指定的页号",
        f"用户撤销了「{back}」的人工页号（原来指定为第 {was} 页）。",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"kind": "page_mapping_undo", "label": back, "page_no": was},
    )
    return _mapping_out(
        material_id, doc, records, label=back, original_label=back, page_no=was,
        note_zh=f"已撤销「{back}」的人工页号，它又回到\"读不出页号\"的清单里了。")


def _label_to_page_no(label: str) -> str:
    """页标签（"第 12 页"）→ 页号字符串（"12"）；认不出来就原样返回（调用方据此跳过并列出）。"""
    import re as _re

    m = _re.search(r"第\s*(\d+)\s*页", str(label or ""))
    return m.group(1) if m else str(label or "").strip()


def _merge_pages(old: list[dict], new: list[dict]) -> list[dict]:
    """按 `page_label` 合并（新的替换同页、追加新页；保序：原顺序在前，新页在后）。

    **R61 任务 A**：人工指定过页号的那一页，重读之后**留住"这是人工指定的页号"这条留痕**
    （否则把它读出来一次，就再也没法撤销了）——只补这三个字段，模型这次读到的内容照旧覆盖。
    """
    by_label = {str(r.get("page_label") or ""): r for r in new}
    out: list[dict] = []
    used: set[str] = set()
    for r in old:
        label = str(r.get("page_label") or "")
        if label in by_label:
            fresh = by_label[label]
            if str(r.get("page_no_source") or "") == "manual":
                for key in ("original_label", "manual_page_no", "page_no_source"):
                    if key in r and key not in fresh:
                        fresh[key] = r[key]
            out.append(fresh)
            used.add(label)
        else:
            out.append(r)
    out.extend(r for k, r in by_label.items() if k not in used)
    return out


def pages_digest(db, subject_id: str) -> str:
    """该学科全部 all_ai 材料的页面记录 → 给模型看的摘要（出题/判题/答疑共用）。"""
    from ..service.mode_ai import _digest

    out: list[dict] = []
    for e in mat._entries_with_body(subject_id):
        if str(e.get("mode") or "") != mat.MODE_ALL_AI:
            continue
        out.extend(load_pages(subject_id, str(e.get("id") or "")))
    return _digest(out)


__all__ = ["MAX_PAGES", "ALLOWED_MIME", "PageMappingError", "import_pages", "load_pages",
           "pages_digest", "reread_pages", "set_page_mapping", "skipped_page_labels",
           "undo_page_mapping"]
