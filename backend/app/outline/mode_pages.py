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

**R67 任务 A/B/F**（导入体验与大书可用性）：

- **读法三档**（用户自己挑）：``fast``（目录页 + 每章开头几页，够排大纲）/ ``range``（用户给的页范围，现在已有）
  / ``full``（整本精读）。快读**如实标注"哪几页是抽样读的"**，且**没读过的章不许生成内容**；
- **提速**（可选）：``concurrency``（同时读 3–5 页，有上限）＋ ``batch_pages``（一次调用塞 2–4 页）；
- **逐页留痕不许破**：并行/批量之后仍然**一页一条记录**（页号 + 读到什么），批量里漏掉的页会**单独补读**；
- **出错也不丢数据**：单页读失败只把那一页记成"这次没读成 + 中文原因"，**不影响其它页**；
- **分段落盘**：每读若干页（或每若干秒）就把已读部分写进材料（`checkpoint`），
  中途取消/进程被杀，**已读的页留着**；**一页都没读成时不落空材料**；
- **页数上限交给用户**（默认 60，硬天花板防手滑填错数量级）。
"""
from __future__ import annotations

import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..ai.vision import image_block, read_page
from ..service import ledger
from . import materials as mat
from . import pdfrender

MAX_PAGES = 60                      # **兼容旧名**：一次最多多少页（＝界面输入框的默认值）
DEFAULT_MAX_PAGES = MAX_PAGES       # R67 B：默认值（用户可在界面上改）
HARD_MAX_PAGES = 2000               # R67 B：硬天花板（防手滑填错数量级；正常书撞不到）
ALLOWED_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif")
_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif"}

# **R67 任务 F**：读法三档 + 两项提速（都可配、都可关）
STRATEGY_FAST = "fast"              # 快：目录页 + 每章开头若干页（够排大纲）
STRATEGY_RANGE = "range"            # 中：按用户给的页范围读（既有能力）
STRATEGY_FULL = "full"              # 全：整本精读
STRATEGIES = (STRATEGY_FAST, STRATEGY_RANGE, STRATEGY_FULL)
STRATEGY_LABELS_ZH = {STRATEGY_FAST: "快读（挑着读）", STRATEGY_RANGE: "按页范围读",
                      STRATEGY_FULL: "整本精读"}
FAST_PAGES_PER_CHAPTER = 2          # 快读时每章开头读几页
FAST_MAX_PAGES = 40                 # 快读一次最多读多少页（够排大纲就停）
DEFAULT_CONCURRENCY = 3             # 同时读几页（1 = 一页一页来）
MAX_CONCURRENCY = 8                 # 并发上限（再高容易被服务商限流）
DEFAULT_BATCH_PAGES = 1             # 一次调用读几页（1 = 逐页调用，与既有行为一致）
MAX_BATCH_PAGES = 4
CHECKPOINT_EVERY_PAGES = 5          # 每读这么多页落一次盘（R67 A：中途死掉要留住已读）
CHECKPOINT_EVERY_SECONDS = 30.0     # 或者每这么久落一次盘（两者谁先到算谁）
UNREADABLE_RETRY_NOTE = "这次没读成"


class PagePlanError(ValueError):
    """页数/读法/并发这类"用户填的值"不合法（message 一律中文，供 API 映射 422）。"""


def parse_page_limit(raw, *, default: int = DEFAULT_MAX_PAGES) -> int:
    """页数上限（用户填的）：空 → ``default``；非法/超天花板 → **中文** ``PagePlanError``。

    R67 任务 B：上限**不再由程序拍死**（以前写死 60，126 页的书只能分三次导）——
    用户想读 200 页就填 200；这里只挡住"手滑填错数量级"（``HARD_MAX_PAGES``）与非数字。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return max(1, int(default))
    if isinstance(raw, bool):
        raise PagePlanError("一次读多少页要填 1 以上的整数（页号从 1 开始数）")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise PagePlanError(
            f"一次读多少页要填个数字（现在填的是「{str(raw).strip()[:20]}」）——例如 60、126、200") from None
    if value < 1:
        raise PagePlanError(f"一次读多少页要填 1 以上的整数（现在填的是 {value}）——想少读就填小一点的数")
    if value > HARD_MAX_PAGES:
        raise PagePlanError(f"一次最多读 {HARD_MAX_PAGES:,} 页（现在填的是 {value:,}）——"
                            f"请填小一点的数，或分成几次读")
    return value


def parse_concurrency(raw, *, default: int = DEFAULT_CONCURRENCY) -> int:
    """同时读几页（1–``MAX_CONCURRENCY``）；空 → ``default``；非法 → 中文报错。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return max(1, min(MAX_CONCURRENCY, int(default)))
    if isinstance(raw, bool):
        raise PagePlanError("同时读几页要填 1 以上的整数")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise PagePlanError(f"同时读几页要填个数字（现在填的是「{str(raw).strip()[:20]}」）——例如 3") from None
    if value < 1:
        raise PagePlanError(f"同时读几页要填 1 以上的整数（现在填的是 {value}）；想一页一页来就填 1")
    if value > MAX_CONCURRENCY:
        raise PagePlanError(f"同时读几页最多 {MAX_CONCURRENCY}（现在填的是 {value}）——"
                            f"填太大容易被服务商限流，也会更容易读失败")
    return value


def parse_batch_pages(raw, *, default: int = DEFAULT_BATCH_PAGES) -> int:
    """一次调用读几页（1–``MAX_BATCH_PAGES``；1 = 逐页调用，与既有行为一致）。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return max(1, min(MAX_BATCH_PAGES, int(default)))
    if isinstance(raw, bool):
        raise PagePlanError("一次读几页要填 1 以上的整数")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise PagePlanError(f"一次读几页要填个数字（现在填的是「{str(raw).strip()[:20]}」）——例如 1 或 2") from None
    if value < 1:
        raise PagePlanError(f"一次读几页要填 1 以上的整数（现在填的是 {value}）；一页一页来就填 1")
    if value > MAX_BATCH_PAGES:
        raise PagePlanError(f"一次读几页最多 {MAX_BATCH_PAGES}（现在填的是 {value}）")
    return value


def parse_strategy(raw, *, has_range: bool = False) -> str:
    """读法：空 → 给了页范围就 ``range``、否则 ``full``；非法值 → 中文报错。"""
    s = str(raw or "").strip().lower()
    if not s:
        return STRATEGY_RANGE if has_range else STRATEGY_FULL
    if s not in STRATEGIES:
        raise PagePlanError(f"读法只能选「快读 / 按页范围读 / 整本精读」三种之一（现在给的是「{s[:20]}」）")
    return s


def read_options() -> dict:
    """界面要显示的读法选项 + 默认值（**人话**，不含内部说法）。"""
    return {
        "strategies": [{"value": s, "label": STRATEGY_LABELS_ZH[s]} for s in STRATEGIES],
        "default_strategy": STRATEGY_FULL,
        "default_max_pages": DEFAULT_MAX_PAGES,
        "hard_max_pages": HARD_MAX_PAGES,
        "default_concurrency": DEFAULT_CONCURRENCY,
        "max_concurrency": MAX_CONCURRENCY,
        "default_batch_pages": DEFAULT_BATCH_PAGES,
        "max_batch_pages": MAX_BATCH_PAGES,
        "fast_pages_per_chapter": FAST_PAGES_PER_CHAPTER,
        "checkpoint_every_pages": CHECKPOINT_EVERY_PAGES,
        "seconds_per_page_hint": 8,
        "note_zh": ("读得越多越慢、越贵，大约每页 8 秒；"
                    "想快点排大纲可以先选「快读」，回头再补读没读到的页。"),
    }


def plan_fast_pages(pdf_bytes: bytes, *, max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """**快读**选页：目录页 + 每章开头 ``FAST_PAGES_PER_CHAPTER`` 页（够排大纲）。

    返回 ``{"pages": [页号…], "note_zh": …, "bookmark_count": n, "sampled": True}``。
    没有书签（或书签里认不出章）时**如实说**：只抽目录页 + 开头的若干页（仍标成"抽样读"）。
    """
    from . import pdfparse

    max_pages = max(1, int(max_pages or DEFAULT_MAX_PAGES))
    marks = pdfparse.pdf_bookmarks(pdf_bytes)
    chapters = [_bookmark_page(m) for m in marks
                if _bookmark_text_kind(str(m.get("title") or "")) in ("chapter", "appendix")]
    chapters = [p for p in chapters if p and p > 0]
    toc_pages = _toc_page_numbers(pdf_bytes)
    picked: list[int] = list(toc_pages)
    for start in chapters:
        for i in range(FAST_PAGES_PER_CHAPTER):
            picked.append(start + i)
    if not chapters:
        # 没有可用的章书签 → 抽"目录页 + 开头几页"（如实标注是抽样）
        picked += list(range(1, min(4, max_pages) + 1))
    uniq = sorted({p for p in picked if p >= 1})[:max(FAST_MAX_PAGES, max_pages)][:max_pages]
    note = (f"快读：目录页 {('、'.join('第 %d 页' % p for p in toc_pages) or '（没找到目录页）')} "
            f"+ 每章开头 {FAST_PAGES_PER_CHAPTER} 页，共 {len(uniq)} 页"
            if chapters else
            f"快读：这本书的书签里没有「第 N 章」这样的章名，只能抽目录页与开头几页，共 {len(uniq)} 页")
    return {"pages": uniq, "note_zh": note, "bookmark_count": len(marks), "sampled": True,
            "chapter_count": len(chapters), "toc_pages": toc_pages}


def _bookmark_page(m: dict) -> int:
    try:
        return int(m.get("page") or 0)
    except (TypeError, ValueError):
        return 0


def _bookmark_text_kind(title: str) -> str:
    """书签标题是不是"章/附录"（与 `bookmap` 同一套写法判定，不另立一份口径）。"""
    from . import bookmap

    return bookmap._bookmark_kind(title)


def _toc_page_numbers(pdf_bytes: bytes, *, limit: int = 3) -> list[int]:
    """目录页页号（页首写着「目录」的那几页）；找不到 → 空表（**不猜**）。"""
    from . import pdfparse

    try:
        parsed = pdfparse.parse_pdf_bytes(pdf_bytes)
    except Exception:
        return []
    out: list[int] = []
    for sec in parsed.get("sections") or []:
        head = str(sec.get("text") or "")[:60].replace(" ", "").replace("\u3000", "")
        if "目录" in head or "目次" in head:
            out.append(int(sec.get("page") or 0))
        if len(out) >= limit:
            break
    return [p for p in out if p >= 1]


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
                 pdf_pages: str = "", max_pages=None, strategy: str = "",
                 concurrency: int = 1, batch_pages: int = DEFAULT_BATCH_PAGES,
                 on_event=None, should_stop=None, checkpoint: dict | None = None) -> dict:
    """图片（或 PDF）→ 读取记录 → 入库（返回 ``{id, title, page_count, pages, unreadable, note_zh, …}``）。

    ``files`` ＝ ``[(filename, bytes), ...]``（按页序）。任何一张读不出来都**不影响**入库，
    但会在正文/账本/返回值里如实标出。

    **R57**：若第一个文件是 PDF（``%PDF`` 文件头）→ 交给 `pdfrender` **按页渲染**（``pdf_pages`` 指定页范围），
    渲染库没装 → 中文报错（回落方案 c，由界面提示用户自己导出图片）。

    **R67**（全部是**可选参数**，都不传＝与 R67 之前逐字一致）：

    - ``max_pages``：一次最多读多少页（默认 60；**用户可改**，硬天花板见 ``HARD_MAX_PAGES``）；
    - ``strategy``：读法（``fast`` 挑着读 / ``range`` 按页范围 / ``full`` 整本）；
    - ``concurrency``：同时读几页（默认 1＝逐页，与既有行为一致）；
    - ``batch_pages``：一次调用读几页（默认 1＝逐页调用）；
    - ``on_event``：进度回调（**只报进度，不改数据**）：``{"kind": "start|render|page|checkpoint|end", …}``；
    - ``should_stop``：取消判断（返回 True 就**不再往下读**，已读的页照样留下）；
    - ``checkpoint``：分段落盘口径（``{"every_pages": n, "every_seconds": s, "state": "importing"}``）
      ——给了就"每读若干页/若干秒"写一次材料；不给＝最后一次性写（既有行为）。
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
    limit = parse_page_limit(max_pages)
    if len(files) > limit:
        from .schemas import OutlineError

        raise OutlineError(f"一次最多读 {limit} 页（现在选了 {len(files)} 页）——"
                           f"可以填大一点，也可以少选一些、分批导入")
    strat = parse_strategy(strategy, has_range=bool(str(pdf_pages or "").strip()))
    strat_explicit = bool(str(strategy or "").strip())      # 调用方**显式**给了读法才在说明里念它
    conc = parse_concurrency(concurrency) if concurrency else 1
    batch = parse_batch_pages(batch_pages) if batch_pages else DEFAULT_BATCH_PAGES

    if provider is None:
        provider = _build_provider(db)

    emit = _emitter(on_event)
    started = time.time()
    plan = _plan_page_reads(files, pdf_pages=pdf_pages, limit=limit, strategy=strat,
                            limit_explicit=max_pages is not None and str(max_pages).strip() != "",
                            on_event=emit, should_stop=should_stop)
    planned: list[dict] = plan["planned"]
    if not planned:
        from .schemas import OutlineError

        raise OutlineError("没有选中任何一页（页号从 1 开始数）")
    emit({"kind": "start", "total": len(planned),
          "labels": [p["label"] for p in planned],
          "strategy": strat, "note_zh": plan["note_zh"]})

    sink = _PageMaterialSink(
        db, subject_id, title=title or "页面图片教材", source=source, strategy=strat,
        planned_labels=[p["label"] for p in planned], checkpoint=checkpoint,
        render_info_base=plan["render_info"], is_pdf=plan["is_pdf"],
        pdf_bytes=plan["pdf_bytes"], files=plan["files"], on_event=emit,
        sampled=bool(plan["sampled"]), source_kind=plan["source_kind"],
        book_labels=list(plan.get("book_labels") or []))

    result = _run_page_reads(provider, planned, subject_id=subject_id, want=want,
                             is_pdf=plan["is_pdf"], concurrency=conc, batch_pages=batch,
                             on_event=emit, should_stop=should_stop, sink=sink)
    records: list[dict] = result["records"]
    elapsed_ms = int((time.time() - started) * 1000)

    text, unreadable = _digest_text(records)
    if not text.strip():
        text = "（这些页面都没有读出可用内容——每一页的原因见下）\n" + "\n".join(
            f"- {r.get('page_label')}：{r.get('unreadable_reason') or '没有内容'}" for r in records)
    state = "cancelled" if result["stopped"] else "done"
    entry_id, entry = sink.finish(records, text, unreadable, state=state)

    if not entry_id:
        # **一页都没读成 → 不留空材料**（R67 A：要么有内容，要么什么都别落）
        ledger.note(
            ledger.CAT_MATERIAL, f"导入（{mat.MODE_ENTRY_ZH}）",
            f"这次一页都没读完（{'已取消' if result['stopped'] else '没有读出任何一页'}），"
            "所以**没有**存下任何材料——不会留下一条空材料",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
            detail={"kind": "pages_import_empty", "strategy": strat,
                    "total": len(planned), "read": len(records)},
        )
        return {"id": "", "title": title or "页面图片教材", "page_count": 0, "pages": [],
                "unreadable": [], "elapsed_ms": elapsed_ms, "render": plan["render_info"],
                "text_health": None, "mode": mat.MODE_ALL_AI, "strategy": strat,
                "sampled": bool(plan["sampled"]), "planned": [p["label"] for p in planned],
                "read_pages": 0, "stopped": bool(result["stopped"]),
                "note_zh": ("已取消：一页都没读完，所以没有存材料（也没留下空材料）"
                            if result["stopped"] else
                            "这些页面一页都没读出来，所以没有存材料（不会留下空材料）"),
                "boundary": mat.mode_entry_zh()}

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
    pending = [p["label"] for p in planned
               if p["label"] not in {str(r.get("page_label") or "") for r in records}]
    ledger.note(
        ledger.CAT_MATERIAL, f"材料《{entry['title']}》· 图示教材模式",
        f"按「{mat.MODE_ENTRY_ZH}」导入了 {len(records)} 页："
        f"逐页让模型读了一遍（共 {elapsed_ms} 毫秒）"
        + (f"；**已取消**，还有 {len(pending)} 页没读（已读的都在材料里）" if pending else "")
        + (f"；读法＝{STRATEGY_LABELS_ZH.get(strat, strat)}"
           + (f"（抽样读，只挑了 {len(records)} 页）" if plan["sampled"] else "") if strat else "")
        + "。这个模式没有独立的第二次核对，判对错与评分都由模型给出；每一步都要问模型，所以更贵。",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"kind": "all_ai_pages_imported", "page_count": len(records),
                "unreadable": len(unreadable), "elapsed_ms": elapsed_ms,
                "strategy": strat, "sampled": bool(plan["sampled"]),
                "planned": len(planned), "pending": pending[:40],
                "stopped": bool(result["stopped"])},
    )
    return {"id": entry_id, "title": entry["title"], "page_count": len(records),
            "unreadable": unreadable, "pages": records, "elapsed_ms": elapsed_ms,
            "render": plan["render_info"],
            "text_health": entry.get("text_health"), "mode": mat.MODE_ALL_AI,
            "strategy": strat, "sampled": bool(plan["sampled"]),
            "planned": [p["label"] for p in planned], "read_pages": len(records),
            "pending_pages": pending, "stopped": bool(result["stopped"]),
            "note_zh": (
                (f"已导入 {len(records)} 页（读法：{STRATEGY_LABELS_ZH.get(strat, strat)}）"
                 + (f"；其中 {len(unreadable)} 页读不出来" if unreadable else "，全部读到了内容")
                 + (f"；还有 {len(pending)} 页没读（已读的已经存下来了）" if pending else ""))
                if strat_explicit or plan["sampled"] or pending
                else (f"已导入 {len(records)} 页；其中 {len(unreadable)} 页读不出来"
                      if unreadable else f"已导入 {len(records)} 页，全部读到了内容")),
            "boundary": mat.mode_entry_zh()}


def _emitter(on_event):
    """进度回调的安全包装（**进度上报失败绝不影响导入本身**）。"""
    def emit(ev: dict) -> None:
        if on_event is None:
            return
        try:
            on_event(dict(ev))
        except Exception:
            pass
    return emit


def _read_failure_reason(e: Exception) -> str:
    """单页读失败 → **中文**原因（限流/超时/网络/服务商报错都说清楚，且写明出路）。"""
    name = type(e).__name__
    text = str(e)
    if "429" in text or "rate" in text.lower() or "限流" in text:
        return (f"{UNREADABLE_RETRY_NOTE}：服务商在限流（同时读得太快），"
                "把「同时读几页」调小一点再重读这一页就好")
    if "timeout" in text.lower() or "超时" in text:
        return f"{UNREADABLE_RETRY_NOTE}：这次等模型等超时了，可以过一会重读这一页"
    if "401" in text or "403" in text:
        return f"{UNREADABLE_RETRY_NOTE}：模型服务说这次调用没被允许（多半是密钥或权限问题）"
    return f"{UNREADABLE_RETRY_NOTE}：{name}：{text[:160] or '没有说明原因'}"


def _plan_page_reads(files: list[tuple[str, bytes]], *, pdf_pages: str, limit: int,
                     strategy: str, limit_explicit: bool = False, on_event=None,
                     should_stop=None) -> dict:
    """把"用户选的文件/PDF + 读法"变成**逐页待读清单**（页号留痕、快读选页、范围校验）。

    ⚠️ 这里**只做选页与渲染**，不调用模型（快读选页用的是书签/目录，本地就能算）。
    """
    emit = _emitter(on_event)
    render_info: dict = {}
    pdf_bytes: bytes | None = None
    first_name, first_data = files[0]
    is_pdf = b"%PDF" in bytes(first_data)[:1024]
    sampled = False
    plan_note = ""
    source_kind = "uploaded_images"
    if is_pdf:
        source_kind = "pdf_render"
        pdf_bytes = bytes(first_data)
        pages_spec = str(pdf_pages or "")
        if strategy == STRATEGY_FAST and not pages_spec:
            # **R67 F**：快读＝目录页 + 每章开头几页（书签就是"章"的权威来源）
            fast = plan_fast_pages(pdf_bytes, max_pages=limit)
            pages_spec = ",".join(str(p) for p in fast["pages"])
            sampled = True
            plan_note = str(fast["note_zh"])
        emit({"kind": "render", "note_zh": "正在把 PDF 逐页转成图片…",
              "pages_spec": pages_spec, "strategy": strategy})
        picked = pdfrender.render_pages(pdf_bytes, pages=pages_spec or None,
                                        max_pages=(limit if limit_explicit else None))
        if not picked:
            from .schemas import OutlineError

            raise OutlineError("这份 PDF 没有渲染出任何页面（请检查页范围）")
        render_info = {"source": "pdf_render", "pages": [p["page_no"] for p in picked],
                       "width": picked[0]["width"] if picked else 0,
                       "dpi": picked[0]["dpi_used"] if picked else 0,
                       "format": picked[0]["format"] if picked else "",
                       "bytes_avg": (sum(p["bytes"] for p in picked) // max(1, len(picked))),
                       "ms_total": round(sum(p["ms"] for p in picked), 1),
                       "pages_spec": str(pages_spec or ""),
                       "sampled": bool(sampled)}
        labels = [f"第 {p['page_no']} 页" for p in picked]
        book_labels = [f"第 {i} 页" for i in range(1, _pdf_page_count(pdf_bytes) + 1)] or labels
        planned = [{"name": f"page{p['page_no']:04d}." + ("jpg" if p["format"] == "jpeg" else "png"),
                    "data": p["data"], "label": label, "page_no": p["page_no"],
                    "mime": p["mime"],
                    "note": f"用户上传的 PDF 第 {p['page_no']} 页渲染图"} 
                   for p, label in zip(picked, labels)]
        files = [(it["name"], it["data"]) for it in planned]
        if len(planned) > limit:
            raise PagePlanError(f"这次要读 {len(planned)} 页，超过上限 {limit} 页——"
                                f"请把页范围缩小一些，或把上限填大一点")
    else:
        if strategy == STRATEGY_FAST and len(files) > 6:
            # 页面图片没有目录可挑：快读＝先读前几张（**如实标成抽样**）
            files = list(files[:6])
            sampled = True
            plan_note = "快读：这些是页面图片、没有目录可挑，先读你选的前 6 张（抽样读）"
        render_info = {"source": "uploaded_images", "cache": [], "sampled": bool(sampled)}
        labels = [f"第 {i} 页" for i in range(1, len(files) + 1)]
        book_labels = list(labels)
        planned = []
        for i, (name, data) in enumerate(files):
            mime = _mime_of(name)
            planned.append({"name": name, "data": bytes(data), "label": labels[i],
                            "page_no": i + 1, "mime": mime,
                            "note": f"用户上传的第 {i + 1} 页图片（{name}）"})
    return {"planned": planned, "render_info": render_info, "is_pdf": is_pdf,
            "pdf_bytes": pdf_bytes, "files": files, "note_zh": plan_note,
            "sampled": sampled, "source_kind": source_kind,
            # **R67 D/F**：这本书**一共**有哪些页（用于如实说"还有哪几页没读"——
            # 快读没读到的页不只在"计划里没读完"，而是压根没进计划）
            "book_labels": book_labels}


def _pdf_page_count(data: bytes) -> int:
    """这本书一共几页（只数页数，不抽文本）；数不到 → 0（调用方回落到"计划里的页"）。"""
    try:
        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# **R67 任务 A/F**：逐页读取引擎（串行/并行/批量 + 进度 + 取消 + 分段落盘）
# ---------------------------------------------------------------------------
def _run_page_reads(provider, planned: list[dict], *, subject_id: str, want: str, is_pdf: bool,
                    concurrency: int = 1, batch_pages: int = 1, on_event=None,
                    should_stop=None, sink=None) -> dict:
    """按清单读页 → ``{"records", "stopped", "failed"}``。

    **三条硬口径**（R67 §6）：
    ① **一页一条记录**（并行/批量都不许把多页糊成一坨）；
    ② **结果与串行逐页一致**（并行只是调度：同一页同一提示词，读出来的记录按**页序**入位）；
    ③ **出错不丢数据**：单页失败只把那一页记成"这次没读成 + 中文原因"，其它页照读。
    """
    total = len(planned)
    emit = _emitter(on_event)
    lock = threading.Lock()
    state = {"done": 0, "last_label": ""}

    def _note_want() -> str:
        return want or "这一页的正文要点、公式与图里画了什么"

    def read_one(item: dict) -> dict:
        """读一页（**永不抛**）：成功/失败都回一条记录。"""
        label = str(item.get("label") or "")
        mime = str(item.get("mime") or "")
        if not mime:
            return {"page_label": label, "readable": False, "image": item.get("name", ""),
                    "mime": "",
                    "unreadable_reason": f"这个文件不是支持的图片格式（{item.get('name')}）"}
        try:
            out, version = read_page(
                provider, images=[image_block(item["data"], mime=mime)],
                page_label=label, want=_note_want(), note=str(item.get("note") or ""),
                subject_id=subject_id)
            rec = out.model_dump()
        except Exception as e:                    # 单页失败**不许**影响别的页
            rec = {"page_label": label, "readable": False,
                   "unreadable_reason": _read_failure_reason(e)}
            version = ""
        rec.setdefault("page_label", label)
        rec["image"] = item.get("name", "")
        rec["mime"] = mime
        rec["prompt_version"] = version
        if is_pdf and item.get("page_no"):
            rec["page_no"] = int(item["page_no"])
        return rec

    def read_batch(items: list[dict]) -> list[dict]:
        """一次调用读 2–4 页 → **仍然一页一条记录**；批量漏掉的页**单独补读**。"""
        from ..ai.vision import read_pages_batch

        label_of = {str(it.get("label") or ""): it for it in items}
        try:
            outs = read_pages_batch(provider, pages=[{
                "label": str(it.get("label") or ""), "image": image_block(it["data"], mime=str(it["mime"]))}
                for it in items], want=_note_want(), subject_id=subject_id)
        except Exception as e:                    # 整批失败 → 逐页补读（不许整批变成"没读"）
            reason = _read_failure_reason(e)
            recs = []
            for it in items:
                rec = read_one(it)
                if rec.get("readable") is False and not str(rec.get("unreadable_reason") or ""):
                    rec["unreadable_reason"] = reason
                recs.append(rec)
            return recs
        got: dict[str, dict] = {}
        for label, rec, version in outs:
            if label not in label_of or label in got:
                continue
            rec = dict(rec)
            rec["page_label"] = label
            rec["image"] = label_of[label].get("name", "")
            rec["mime"] = str(label_of[label].get("mime") or "")
            rec["prompt_version"] = version
            if is_pdf and label_of[label].get("page_no"):
                rec["page_no"] = int(label_of[label]["page_no"])
            got[label] = rec
        out: list[dict] = []
        for it in items:                          # **按清单顺序**补齐（缺的单独读一次）
            label = str(it.get("label") or "")
            out.append(got.get(label) or read_one(it))
        return out

    def run_unit(indices: list[int]) -> list[dict]:
        """一个调度单元：1 页 → 单页调用；多页 → 批量调用（批量里漏的页会单独补读）。"""
        if len(indices) == 1:
            return [read_one(planned[indices[0]])]
        return read_batch([planned[i] for i in indices])

    def record_at(indices: list[int], recs: list[dict]) -> None:
        with lock:
            for i, rec in zip(indices, recs):
                records[i] = rec
                state["done"] += 1
                state["last_label"] = str(rec.get("page_label") or planned[i].get("label") or "")
                emit({"kind": "page", "done": state["done"], "total": total,
                      "label": state["last_label"], "readable": rec.get("readable") is not False})
            snapshot = [r for r in records if r]
        if sink is not None:
            sink.maybe(snapshot, on_event=emit)

    records: list[dict | None] = [None] * total
    stopped = False
    units: list[list[int]] = []
    if batch_pages > 1:
        for start in range(0, total, batch_pages):
            units.append(list(range(start, min(start + batch_pages, total))))
    else:
        units = [[i] for i in range(total)]

    if concurrency <= 1:
        for idxs in units:
            if should_stop is not None and should_stop():
                stopped = True
                break
            record_at(idxs, run_unit(idxs))
    else:
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
            pending: list[tuple[list[int], object]] = []
            for idxs in units:
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                pending.append((idxs, pool.submit(run_unit, idxs)))
                while len(pending) >= max(1, int(concurrency)):
                    idxs0, fut = pending.pop(0)
                    record_at(idxs0, fut.result())
            for idxs0, fut in pending:            # 取消/收尾：**在飞的页照样收回来存下**
                record_at(idxs0, fut.result())

    out_records = [r for r in records if r]
    failed = [str(r.get("page_label") or "") for r in out_records if r.get("readable") is False]
    if len(out_records) < total and not stopped:
        stopped = False
    return {"records": out_records, "stopped": stopped, "failed": failed}


class _PageMaterialSink:
    """把"已读到的页"分段落成材料（**R67 任务 A 的核心修法**）。

    - **一页都没读成 → 不建材料**（`finish` 回空 id，调用方如实说"没留下空材料"）；
    - **第一次落盘＝建材料**（正文 + `*.pages.json` + frontmatter 编号）；
    - **之后每次落盘＝就地更新**（材料 id / 文件名都不变，页面记录整份重写）；
    - 每次落盘都把 `progress`（读了几页 / 共几页 / 状态 / 哪些页还没读）写进 `*.pages.json`
      ——**进程被杀之后重启，界面据此说清"上次读到哪、还剩哪些页"**；
    - 落盘**失败不许影响读取**（记一条账，继续读；下次落盘再试）。
    """

    def __init__(self, db, subject_id: str, *, title: str, source: str, strategy: str,
                 planned_labels: list[str], checkpoint: dict | None, render_info_base: dict,
                 is_pdf: bool, pdf_bytes, files, on_event=None, sampled: bool = False,
                 source_kind: str = "", book_labels: list[str] | None = None):
        self.db = db
        self.subject_id = subject_id
        self.title = title
        self.source = source
        self.strategy = strategy
        self.planned_labels = list(planned_labels)
        self.enabled = checkpoint is not None
        self.every_pages = int((checkpoint or {}).get("every_pages") or CHECKPOINT_EVERY_PAGES)
        self.every_seconds = float((checkpoint or {}).get("every_seconds") or CHECKPOINT_EVERY_SECONDS)
        self.state = str((checkpoint or {}).get("state") or "importing")
        self.render_info_base = dict(render_info_base)
        self.is_pdf = is_pdf
        self.pdf_bytes = pdf_bytes
        self.files = files
        self.on_event = on_event
        self.sampled = bool(sampled)
        self.source_kind = source_kind
        self.book_labels = list(book_labels or planned_labels)
        self.entry_id = ""
        self.entry: dict | None = None
        self.render_info: dict = dict(render_info_base)
        self._last_write = 0.0
        self._since = 0
        self._writes = 0
        self._lock = threading.Lock()      # 并行读页时多个线程都可能来落盘 → 串行化

    # ---- 进度块（写进 `*.pages.json`：重启后界面据此说话） ----
    def _progress(self, records: list[dict], state: str) -> dict:
        read = [str(r.get("page_label") or "") for r in records]
        pending = [lb for lb in self.planned_labels if lb not in read]
        unread = [lb for lb in self.book_labels if lb not in read]
        return {"state": state, "strategy": self.strategy, "sampled": self.sampled,
                "planned": list(self.planned_labels), "read": len(records),
                "total": len(self.planned_labels), "pending": pending,
                "book_total": len(self.book_labels), "unread": unread,
                "failed": [str(r.get("page_label") or "") for r in records
                           if r.get("readable") is False],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note_zh": (f"共 {len(self.planned_labels)} 页，已读 {len(records)} 页"
                            + (f"，还有 {len(pending)} 页没读" if pending else "")
                            + ("（快读：只挑了一部分页）" if self.sampled else ""))}

    def maybe(self, records: list[dict], *, on_event=None) -> bool:
        """到点就落一次盘（页数或时间任一先到）；返回是否真的写了。"""
        if not self.enabled or not records:
            return False
        with self._lock:                   # 并行读页：同一时刻只有一个线程在落盘
            now = time.time()
            if (len(records) - self._since) < self.every_pages \
                    and (now - self._last_write) < self.every_seconds:
                return False
            return self._write(records, state=self.state, on_event=on_event or self.on_event)

    def finish(self, records: list[dict], text: str, unreadable: list[str], *,
               state: str) -> tuple[str, dict | None]:
        """最后一次落盘（含"一页都没读成 → 什么都不建"这条口径）。"""
        if not records:
            return "", None
        with self._lock:
            self._write(records, state=state, text=text, final=True, on_event=self.on_event)
        return self.entry_id, self.entry

    # ---- 落盘 ----
    def _write(self, records: list[dict], *, state: str, text: str = "", final: bool = False,
               on_event=None) -> bool:
        emit = _emitter(on_event)
        try:
            if not self.entry_id:
                body = text or _digest_text(records)[0] or "（还没有页读到内容）"
                self.entry = mat.add_material(
                    self.db, self.subject_id, title=self.title, text=body, source=self.source,
                    kind="pages", mode=mat.MODE_ALL_AI, page_count=len(records), pages_file="")
                self.entry_id = str(self.entry["id"])
                self._prepare_render_info()
            else:
                body = text or _digest_text(records)[0] or "（还没有页读到内容）"
                mat.update_material_body(self.db, self.subject_id, self.entry_id,
                                         text=body, page_count=len(records))
            pages_name = f"pages-{self.entry_id.replace('mat-', '')}.pages.json"
            doc = {"title": (self.entry or {}).get("title") or self.title,
                   "pages": records, "render": self.render_info,
                   "progress": self._progress(records, state)}
            (mat.materials_dir(self.subject_id) / pages_name).write_text(
                json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            if self._writes == 0:
                mat.set_material_pages_file(self.db, self.subject_id, self.entry_id, pages_name)
            self._last_write = time.time()
            self._since = len(records)
            self._writes += 1
            emit({"kind": "checkpoint", "material_id": self.entry_id, "read": len(records),
                  "total": len(self.planned_labels), "state": state, "saved": True})
            return True
        except Exception as e:      # **落盘失败不许影响读取**（如实记账，下次再试）
            ledger.note(
                ledger.CAT_MATERIAL, "导入分段落盘",
                f"这次没能把已读的页存下来（{type(e).__name__}：{str(e)[:120]}）——"
                "读取本身会继续，下一次落盘会再试一次",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_RETRY,
                subject_id=self.subject_id, detail={"kind": "pages_checkpoint_failed"})
            emit({"kind": "checkpoint", "material_id": self.entry_id, "read": len(records),
                  "total": len(self.planned_labels), "state": state, "saved": False,
                  "note_zh": "这一次没存下来，读取继续"})
            return False

    def _prepare_render_info(self) -> None:
        """原始图/PDF 的缓存口径（**一次性**，与既有 `*.pages.json` 的 `render` 同形）。"""
        info = dict(self.render_info_base)
        if self.is_pdf and self.pdf_bytes is not None:
            info["key"] = self.entry_id
            info["cache"] = pdfrender.save_pdf_cache(self.subject_id, self.entry_id, self.pdf_bytes)
        elif not self.is_pdf:
            names: list[str] = []
            for i, (name, data) in enumerate(self.files, start=1):
                if not _mime_of(name):
                    continue
                names.append(_save_image_cache(self.subject_id, self.entry_id, i, name, bytes(data)))
            info["cache"] = names
            info["source"] = "uploaded_images"
        self.render_info = info


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


def build_provider(db):
    """读图用的模型客户端（**公开入口**）。

    为什么要这一层：导入改后台任务之后，provider 必须在**请求线程里**建好再交给后台线程
    ——否则测试替换的"假模型"可能不生效（后台线程拿到真模型去打真接口）。
    """
    return _build_provider(db)


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


def read_page_map(db, subject_id: str) -> dict[str, dict]:
    """该学科**全部**图示教材材料的页面记录 → ``{页标签: 记录}``（同页以后面的材料为准）。"""
    out: dict[str, dict] = {}
    for e in mat._entries_with_body(subject_id):
        if str(e.get("mode") or "") != mat.MODE_ALL_AI:
            continue
        for rec in load_pages(subject_id, str(e.get("id") or "")):
            label = str(rec.get("page_label") or "")
            if label:
                out[label] = dict(rec)
    return out


def unit_page_state(db, subject_id: str, unit) -> dict:
    """某个单元"依据的页"读到了没有（**R67 任务 F 的门禁依据**）。

    单元的依据是**页/图号**（本模式的口径）：``unit.materials[].section`` 里写着「第 N 页」。
    返回 ``{"refs": 依据的页, "read": 真读到内容的页, "unread": 没读到的页,
    "records": {页: 记录}, "digest": 只含这些页的记录摘要}``。

    - ``read`` 只算**真读到内容**的页（`readable` 不是 False）；读不出来的页不算"读过"；
    - 单元没有页号依据（老大纲/手工大纲）→ ``refs`` 为空，调用方按既有口径走（不拦）。
    """
    from ..service.mode_ai import _digest

    records = read_page_map(db, subject_id)
    refs: list[str] = []
    for r in (getattr(unit, "materials", None) or []):
        sec = str((r or {}).get("section") or "").strip()
        if not sec:
            continue
        # 只认"确定是页号"的依据：① 页面记录里就有这个标签；② 写成「第 N 页」。
        # （光是一个数字 12 不能断定它是页号——宁可不当依据，也别拿它拦人）
        if sec in records or _label_to_page_no(sec) != sec:
            if sec not in refs:
                refs.append(sec)
    hits = [records[lb] for lb in refs if lb in records]
    read = [str(r.get("page_label") or "") for r in hits if r.get("readable") is not False]
    unread = [lb for lb in refs if lb not in read]
    return {"refs": refs, "read": read, "unread": unread, "records": records,
            "digest": _digest(hits) if hits else ""}


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


__all__ = ["MAX_PAGES", "DEFAULT_MAX_PAGES", "HARD_MAX_PAGES", "ALLOWED_MIME", "PageMappingError",
           "PagePlanError", "STRATEGIES", "STRATEGY_LABELS_ZH", "build_provider", "import_pages",
           "load_pages", "pages_digest", "parse_batch_pages", "parse_concurrency",
           "parse_page_limit", "parse_strategy", "plan_fast_pages", "read_options",
           "read_page_map", "reread_pages", "set_page_mapping", "skipped_page_labels",
           "undo_page_mapping", "unit_page_state"]
