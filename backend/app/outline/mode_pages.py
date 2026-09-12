"""outline.mode_pages：**图示教材模式（全 AI 模式）的页面图片入库**（R56 第 3 步）。

职责很小、很清楚（工单 §1：程序只负责"流程骨架 / 提示词 / 材料递送 / 记录"）：

1. **存图片**：把上传的页面图片写到该学科材料目录下的 `pages-<id>/`（不走 `*.md` 通配，不会污染材料列表）；
2. **读图片**：逐张调 `ai.vision.read_page`（＝本模式的"读教材"环节，走既有审计）；
3. **读不出来的如实记**：`readable=false` 的页**照样入库**（正文里写明"这一页读不出来 + 原因"），
   并记一条中文账 —— 不许静默当成"这一页没内容"；
4. **入库**：用**既有材料层** `materials.add_material(mode="all_ai")` 存一份 `.md`
   （正文＝各页"读到了什么"的拼接），并把结构化记录另存 `*.pages.json`（供出题/判题按页取用）。

前置校验（工单 §3-A）：**没配能读图的模型 → 中文明确拒绝，不落库**（不做静默降级）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..ai.vision import image_block, read_page
from ..service import ledger
from . import materials as mat

MAX_PAGES = 60                      # 一次最多多少页（避免一次导入把额度打光；可分批再传）
ALLOWED_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif")
_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif"}


def pages_dir(subject_id: str, entry_id: str) -> Path:
    return mat.materials_dir(subject_id) / f"pages-{entry_id.replace('mat-', '')}"


def _mime_of(filename: str, given: str = "") -> str:
    mime = (given or "").strip().lower()
    if mime in ALLOWED_MIME:
        return "image/jpeg" if mime == "image/jpg" else mime
    return _MIME_BY_SUFFIX.get(Path(filename or "").suffix.lower(), "")


def import_pages(db, subject_id: str, *, title: str, files: list[tuple[str, bytes]],
                 provider=None, source: str = "页面图片导入", want: str = "") -> dict:
    """图片 → 读取记录 → 入库（返回 ``{id, title, page_count, pages, unreadable, note_zh, cost}``）。

    ``files`` ＝ ``[(filename, bytes), ...]``（按页序）。任何一张读不出来都**不影响**入库，
    但会在正文/账本/返回值里如实标出。
    """
    from ..service import model_config

    ok, why = model_config.supports_vision(db)
    if not ok:
        # 工单 §3-A：前置校验不过 → 中文明确拒绝，**不落库**
        from .schemas import OutlineError

        raise OutlineError("这条路需要能读图片的模型：" + why)

    if not files:
        from .schemas import OutlineError

        raise OutlineError("还没有选择页面图片（支持 PNG / JPEG / WebP / GIF）")
    if len(files) > MAX_PAGES:
        from .schemas import OutlineError

        raise OutlineError(f"一次最多 {MAX_PAGES} 页（现在 {len(files)} 页）——请分批上传")

    if provider is None:
        provider = _build_provider(db)

    records: list[dict] = []
    started = time.time()
    slugs: list[str] = []
    for i, (name, data) in enumerate(files, start=1):
        mime = _mime_of(name)
        if not mime:
            records.append({"page_label": f"第 {i} 页", "readable": False,
                            "unreadable_reason": f"这个文件不是支持的图片格式（{name}）"})
            slugs.append("")
            continue
        out, version = read_page(
            provider, images=[image_block(data, mime=mime)],
            page_label=f"第 {i} 页", want=want or "这一页的正文要点、公式与图里画了什么",
            note=f"用户上传的第 {i} 页图片（文件名 {name}）",
            subject_id=subject_id,
        )
        rec = out.model_dump()
        rec["image"] = name
        rec["mime"] = mime
        rec["prompt_version"] = version
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
    d = pages_dir(subject_id, entry_id)
    d.mkdir(parents=True, exist_ok=True)
    for i, (name, data) in enumerate(files, start=1):
        if not _mime_of(name):
            continue
        suffix = Path(name).suffix.lower() or ".png"
        (d / f"page-{i:03d}{suffix}").write_bytes(data)
    pages_name = f"{pages_dir(subject_id, entry_id).name}.pages.json"
    (mat.materials_dir(subject_id) / pages_name).write_text(
        json.dumps({"title": entry["title"], "pages": records}, ensure_ascii=False, indent=1),
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
    d = mat.materials_dir(subject_id)
    for p in sorted(d.glob("*.md")):
        e = mat._parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        name = str(e.get("pages_file") or "")
        if not name:
            return []
        f = d / name
        if not f.exists():
            return []
        try:
            return list((json.loads(f.read_text(encoding="utf-8")) or {}).get("pages") or [])
        except Exception:
            return []
    return []


def pages_digest(db, subject_id: str) -> str:
    """该学科全部 all_ai 材料的页面记录 → 给模型看的摘要（出题/判题/答疑共用）。"""
    from ..service.mode_ai import _digest

    out: list[dict] = []
    for e in mat._entries_with_body(subject_id):
        if str(e.get("mode") or "") != mat.MODE_ALL_AI:
            continue
        out.extend(load_pages(subject_id, str(e.get("id") or "")))
    return _digest(out)


__all__ = ["MAX_PAGES", "ALLOWED_MIME", "pages_dir", "import_pages", "load_pages", "pages_digest"]
