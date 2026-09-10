"""outline.materials：材料层基础（docs/14 §8 · Phase B B3；R37 教材真源化）。

- 本地导入：用户自有/授权文本 → 本地引用库（分节文本 + 来源标注，入库
  content/subjects/<sid>/materials/<slug>-<hash>.md）；
- 联网候选：search 返回候选清单（无网/未接检索后端时给提示）；select 将勾选候选
  （标题/来源/摘要）本地化入库为 web 引用——**不整本下载**；
- **R37 起（教材＝权威真源）**：
  - 注入默认**不设预算**（``MF_MATERIAL_INJECT_MAX_CHARS=0``＝不限）；按 ``bookmap`` 解析出的
    **章/节结构注入完整正文**，书太大时在章/页边界**结构化分段**（绝不"前 N 字"截断）；
  - 显式设置 ``MF_MATERIAL_INJECT_MAX_CHARS``/旧名 ``MF_OUTLINE_MATERIAL_MAX_CHARS`` > 0 时，
    沿用 R36 D4 的预算降级口径（截断留痕）——上限是**显式选择**，不再是默认；
  - 入库时检测**文本层健康度**（S7）：扫描/图片版 PDF 明确中文告知，不静默出稿；
  - 覆盖账本（S6）：章/节条目 ↔ 单元的映射由 ``coverage_ledger`` 统一算账。
来源策略 source_policy（ai|import|web|mixed，默认 ai）存 subjects.meta_json；
math（preset）同样支持（材料作讲解增强，不影响 roadmap 内容）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..config import get_settings, material_inject_budget
from ..outline import store as outline_store
from . import bookmap
from .schemas import OutlineError

POLICY_AI = "ai"
POLICY_IMPORT = "import"
POLICY_WEB = "web"
POLICY_MIXED = "mixed"
SOURCE_POLICIES = (POLICY_AI, POLICY_IMPORT, POLICY_WEB, POLICY_MIXED)
DEFAULT_POLICY = POLICY_AI

_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
_PAGE_MARK = re.compile(r"^【第\s*(\d+)\s*页】\s*$", re.M)


def _slug(s: str) -> str:
    return _SLUG.sub("_", s).strip("_")[:32] or "doc"


def materials_dir(subject_id: str) -> Path:
    d = outline_store.subject_dir(subject_id) / "materials"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- R37 S7：文本层健康度（扫描/图片版 PDF 的诚实边界） ----------
THIN_CHARS_PER_PAGE = 40      # 每页平均字符数下限（低于此值视为"没提取到文字"）
MIN_PAGES_FOR_HEALTH = 5      # 页数过少（粘贴文本/短材料）不做扫描版判定
EMPTY_PAGE_CHARS = 20         # 单页字符数低于此值视为"空白页"


def text_health(body: str, *, min_chars_per_page: int | None = None,
                min_page_ratio: float | None = None) -> dict:
    """材料文本层健康度（每页字符数 / 空白页占比）→ 中文结论。

    - 页数 < ``MIN_PAGES_FOR_HEALTH``（粘贴短文本）→ 不做扫描版判定，如实标注"未判定"；
    - 页数 ≥ 3 且（每页平均字符数 < 下限 或 有文字页占比 < 下限）→ ``healthy=False``，
      note 直接给用户可执行的下一步（OCR / 换文本版），**不含糊**。
    """
    s = get_settings()
    cap = THIN_CHARS_PER_PAGE if min_chars_per_page is None else min_chars_per_page
    ratio = 0.5 if min_page_ratio is None else min_page_ratio
    text = body or ""
    marks = _PAGE_MARK.findall(text)
    pages = len(marks) if marks else 1
    chars = len(text.strip())
    per_page = chars / pages if pages else 0
    nonempty = 0
    if marks:
        parts = re.split(r"(?m)^【第\s*\d+\s*页】\s*$", text)
        nonempty = sum(1 for p in parts if len(p.strip()) >= EMPTY_PAGE_CHARS)
    else:
        nonempty = 1 if chars >= EMPTY_PAGE_CHARS else 0
    text_ratio = (nonempty / pages) if pages else 0.0
    if pages < MIN_PAGES_FOR_HEALTH:
        return {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
                "text_page_ratio": round(text_ratio, 2), "healthy": True, "checked": False,
                "note": "页数过少，未做扫描版判定（粘贴文本按可用处理）"}
    healthy = per_page >= cap and text_ratio >= ratio
    note = "" if healthy else (
        f"本书疑似扫描/图片版：{pages} 页仅提取到 {chars} 个字符"
        f"（每页约 {per_page:.0f} 字，下限 {cap}；有文字页 {nonempty}/{pages}）。"
        "请先 OCR 或改用文本版 PDF/粘贴文本后重新上传——"
        "系统不会在「没读到书」的情况下生成大纲（R37 S7）。"
    )
    return {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
            "text_page_ratio": round(text_ratio, 2), "healthy": healthy, "checked": True,
            "note": note}


def get_policy(db, subject_id: str) -> str:
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    return str((row.meta_json or {}).get("source_policy") or DEFAULT_POLICY)


def set_policy(db, subject_id: str, policy: str) -> str:
    if policy not in SOURCE_POLICIES:
        raise OutlineError(f"来源策略非法: {policy!r}（∈ {SOURCE_POLICIES}）")
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    meta = dict(row.meta_json or {})
    meta["source_policy"] = policy
    row.meta_json = meta
    db.commit()
    return policy


def add_material(db, subject_id: str, *, title: str, text: str, source: str = "本地导入",
                 url: str = "", kind: str | None = None, filename: str = "") -> dict:
    """本地/联网引用入库（文本必填；分节文本按段落/标题切分存正文）。

    kind ∈ local|web|pdf（缺省按 url 推导：有 url=web、无=local；pdf 由 C2 解析器显式传入）；
    filename 记录源文件名（PDF/文档导入的展示与追溯）。
    R37 S7：入库时计算文本层健康度并写入 frontmatter（扫描版 → 中文告知，见 ``text_health``）。
    """
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise OutlineError("材料标题与正文不能为空")
    effective_kind = kind or ("web" if url else "local")
    if effective_kind not in ("local", "web", "pdf"):
        raise OutlineError(f"材料 kind 非法: {effective_kind!r}")
    health = text_health(text)
    entry_id = "mat-" + hashlib.sha1(f"{subject_id}:{title}:{url}:{text[:80]}".encode("utf-8")).hexdigest()[:10]
    p = materials_dir(subject_id) / f"{_slug(title)}-{entry_id[4:]}.md"
    if not p.exists():
        meta_lines = [
            "---",
            f"id: {entry_id}",
            f"title: {title}",
            f"source: {source}",
            f"url: {url}",
            f"kind: {effective_kind}",
        ]
        if filename:
            meta_lines.append(f"filename: {filename}")
        # R37 S7：健康度（明确结论 + 中文说明；扫描版在此留痕，供列表/起草闸门读取）
        meta_lines += [
            f"text_healthy: {'yes' if health['healthy'] else 'no'}",
            f"text_pages: {health['pages']}",
            f"chars_per_page: {health['chars_per_page']}",
        ]
        meta_lines += ["", "---", ""]
        p.write_text("\n".join(meta_lines) + "\n" + text + "\n", encoding="utf-8")
    return {"id": entry_id, "title": title, "source": source, "url": url,
            "kind": effective_kind, "file": p.name,
            "filename": filename or p.name, "text_health": health}


def _parse_entry(p: Path) -> dict | None:
    raw = p.read_text(encoding="utf-8")
    fm = {}
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end > 0:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
            body = raw[end + 4 :].strip()
            healthy_raw = str(fm.get("text_healthy", "")).strip().lower()
            return {
                "id": fm.get("id", p.stem),
                "title": fm.get("title", p.stem),
                "source": fm.get("source", "本地导入"),
                "url": fm.get("url", ""),
                "kind": fm.get("kind", "local"),
                "file": p.name,
                "filename": fm.get("filename", ""),
                "body": body,
                # R37 S7：入库时算的健康度（老材料没有该字段 → 现算一次，不让历史材料失去判定）
                "text_healthy": (healthy_raw != "no") if healthy_raw else None,
            }
    return None


def list_materials(db, subject_id: str) -> list[dict]:
    d = materials_dir(subject_id)
    out = []
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e:
            health = text_health(e.get("body", ""))
            if e.get("text_healthy") is False:
                health["healthy"] = False
            out.append({"id": e["id"], "title": e["title"], "source": e["source"],
                        "url": e["url"], "kind": e["kind"], "file": e["file"],
                        "filename": e.get("filename", ""),
                        "text_health": health})
    return out


def delete_material(db, subject_id: str, material_id: str) -> bool:
    d = materials_dir(subject_id)
    removed = False
    for p in d.glob("*.md"):
        e = _parse_entry(p)
        if e and e["id"] == material_id:
            p.unlink(missing_ok=True)
            removed = True
    return removed


def materials_summaries(db, subject_id: str, *, limit_chars: int = 220) -> list[dict]:
    """**R36 遗留口径**（每份材料正文前 ``limit_chars`` 字摘要）——R37 起**不再用于注入**。

    保留仅为兼容既有调用/演示（材料列表摘要）；教材注入一律走 ``draft_materials``/``unit_material_pack``
    的**完整正文**路径（R37 S1：不用"前 N 字"糊弄）。
    """
    out = []
    for e in list_materials(db, subject_id):
        body = e.get("body", "")
        out.append({
            "title": e["title"],
            "source": e["source"],
            "url": e["url"],
            "summary": body[:limit_chars] + ("…" if len(body) > limit_chars else ""),
        })
    return out


# ---------- R36 D1/D2/D4：大纲起草读材料（可选输入）＋逐单元溯源 ----------

DEFAULT_INJECT_MAX_CHARS = 0      # R37 S1：默认**不限**（0＝不设预算；旧值 6000 属 R36 D4 口径）
LEGACY_SECTION_CHARS = 400        # 每节摘要字符上限（**仅在显式设上限时**的降级口径）
MAX_SECTIONS_PER_MATERIAL = 12    # 每份材料最多展示的节数（同上，仅降级口径）
DEFAULT_BATCH_CHARS = 60000       # R37 S1：单次调用的结构化分段阈值（按章/页边界切，不截断）

_HEADING_MARK = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def inject_budget() -> int:
    """生效的注入上限（0 = 不限）；见 ``config.material_inject_budget``。"""
    return material_inject_budget()


def batch_budget() -> int:
    """单次调用的结构化分段阈值（字符）；0 = 不分段。"""
    return max(0, int(get_settings().material_batch_chars or 0))


def _entries_with_body(subject_id: str) -> list[dict]:
    """材料条目（含正文 body）——服务端校验/注入用；对外 API 不下发正文。"""
    out = []
    for p in sorted(materials_dir(subject_id).glob("*.md")):
        e = _parse_entry(p)
        if e:
            out.append(e)
    return out


def material_sections(body: str, *, max_sections: int = MAX_SECTIONS_PER_MATERIAL,
                      section_chars: int = LEGACY_SECTION_CHARS) -> list[dict]:
    """把材料正文切成"可引用的节"：PDF 的 `【第 N 页】` → Markdown 标题 → 段落兜底。

    返回 ``[{label, text}]``：label＝章节名（第 N 页 / 标题 / 第 N 节）。
    text 已按 ``section_chars`` 截断——**仅用于显式设上限时的降级口径**（R36 D4）；
    R37 默认路径用 ``bookmap`` 的章/节**完整正文**（见 ``material_structure``）。
    """
    raw = (body or "").strip()
    if not raw:
        return []
    sections: list[dict] = []
    buf: list[str] = []
    label = ""

    def _flush() -> None:
        nonlocal buf, label
        text = "\n".join(buf).strip()
        if text:
            cut = len(text) > section_chars
            sections.append({
                "label": label or f"第 {len(sections) + 1} 节",
                "text": text[:section_chars] + ("…" if cut else ""),
            })
        buf = []

    for line in raw.splitlines():
        s = line.strip()
        m = _PAGE_MARK.match(s)
        if m:
            _flush()
            label = f"第 {m.group(1)} 页"
            continue
        h = _HEADING_MARK.match(s)
        if h:
            _flush()
            label = h.group(1).strip()
            continue
        buf.append(line)
    _flush()
    return sections[:max_sections]


def material_structure(body: str) -> dict:
    """R37 S1/S2/S8：材料正文 → **章 → 节**结构（完整正文，不截断）。

    返回 ``{"kind", "note", "entries": [MapEntry], "chapter_map": [dict]}``；
    解析器是 ``outline.bookmap``（唯一实现；大纲起草与单元出稿共用同一份地图）。
    """
    parsed = bookmap.parse_book(body or "")
    entries = parsed["entries"]
    return {
        "kind": parsed["kind"],
        "note": parsed["note"],
        "pages": parsed.get("pages", 0),
        "entries": entries,
        "chapter_map": bookmap.chapter_map(entries),
    }


def _material_index(db, subject_id: str) -> list[dict]:
    """材料索引（服务端用）：正文 + 章/节结构 + 健康度。"""
    out = []
    for e in _entries_with_body(subject_id):
        body = e.get("body", "")
        structure = material_structure(body)
        health = text_health(body)
        if e.get("text_healthy") is False:
            health["healthy"] = False
        out.append({
            "id": e["id"], "title": e["title"], "source": e["source"], "url": e["url"],
            "kind": e.get("kind", "local"), "filename": e.get("filename", ""),
            "body": body, "sections": material_sections(body),
            "structure": structure, "text_health": health,
        })
    return out


def _full_blocks(index: list[dict]) -> list[dict]:
    """R37 S1 默认口径：每份材料按章/节**完整正文**成块（不截断、不摘要）。"""
    blocks: list[dict] = []
    for m in index:
        if not m["text_health"]["healthy"]:
            continue
        for entry in m["structure"]["entries"]:
            secs = "；".join(entry.sections[:12])
            head = (f"#### [{entry.label}]（材料《{m['title']}》"
                    f"{'，节：' + secs if secs else ''}）")
            blocks.append({"material": m["title"], "material_id": m["id"],
                           "label": entry.label, "text": f"{head}\n{entry.text}",
                           "chars": entry.chars})
    return blocks


def draft_materials(db, subject_id: str, *, max_chars: int | None = None,
                    batch_chars: int | None = None) -> dict:
    """D1（R36）＋ S1/S2/S8（R37）：大纲起草的**材料注入包**（唯一入口）。

    返回:
    - ``text``：**首批**注入 prompt 的材料块（多批时见 ``batches``）；
    - ``index``：``[{id,title,source,url,body,sections,structure,text_health}]``
      ——**服务端校验用**（含正文与章/节地图，不下发前端）；
    - ``chapter_map``：整本书的章 → 节地图（跨材料合并；S2 覆盖校验的尺子）；
    - ``batches``：结构化分批（每批 ``text`` 完整可注入；按章/页边界切，**绝不截断句子**）；
    - ``used_chars``：全部批次注入的字符总量（**随书规模增长**；=0 时确实不限）；
    - ``per_call_chars``：**单次调用**的注入预算（生效值）；
    - ``dropped``：**恒为空**（R37/R38 §3 ＋ R39 铁则：**任何情况都不得静默丢材料/章节**——
      预算只决定"每次喂多少"，总覆盖面由分批保证）；
    - ``blocked``：健康度不合格（扫描/图片版）而被挡下的材料 ``[{title, note}]``（S7）。

    预算纪律（R37＋R38 §3）：默认**不省成本**（``MF_MATERIAL_INJECT_MAX_CHARS=0``）——整本书按结构
    完整注入，仅按 ``MF_MATERIAL_BATCH_CHARS`` 在章/页边界分成多次调用；**预算上限＝单次调用预算**
    （取 ``min(预算, 分批阈值)``），**不因预算小就丢章节**（单节超预算时整节注入，宁可不截断）。
    每日 token 上限仍由 ``LLM_MAX_TOKENS_PER_DAY``（provider 侧）保护。
    """
    if max_chars is None:
        max_chars = inject_budget()
    if batch_chars is None:
        batch_chars = batch_budget()
    index = _material_index(db, subject_id)
    blocked = [{"title": m["title"], "note": m["text_health"]["note"]}
               for m in index if not m["text_health"]["healthy"]]
    # R37/R38 §3：预算＝**单次调用**预算；总覆盖面由结构分批保证（绝不丢章节，R39 铁则）
    if max_chars and max_chars > 0:
        per_call = max_chars if batch_chars <= 0 else min(max_chars, batch_chars)
    else:
        per_call = batch_chars
    batches = _make_batches(_full_blocks(index), per_call)
    used = sum(len(b["text"]) for b in batches)
    pack = {"text": batches[0]["text"] if batches else "", "used_chars": used,
            "dropped": [], "truncated": False, "batches": batches, "blocked": blocked,
            "per_call_chars": per_call, "batch_count": len(batches)}
    pack.update({
        "index": index,
        "chapter_map": [{"material_id": m["id"], "material": m["title"],
                         "kind": m["structure"]["kind"], "note": m["structure"]["note"],
                         "entries": m["structure"]["chapter_map"]} for m in index],
        "count": len(index),
        "inject_max_chars": max_chars,
        "batch_chars": batch_chars,
    })
    return pack


def _make_batches(blocks: list[dict], batch_chars: int) -> list[dict]:
    """按章/节边界把材料块分批（``batch_chars<=0`` → 单批含全部）。

    **绝不丢正文**：单个章/节块自身超过预算时，它自成一批**整块注入**（不截断、不丢弃）——
    预算只影响"每批装多少块"，不影响"总共装哪些块"（R37 S1 ＋ R38 §3 ＋ R39 铁则）。
    """
    if not blocks:
        return []
    if batch_chars <= 0:
        return [_batch_of(blocks)]
    out: list[dict] = []
    cur: list[dict] = []
    size = 0
    for b in blocks:
        if cur and size + len(b["text"]) > batch_chars:
            out.append(_batch_of(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b["text"])
    if cur:
        out.append(_batch_of(cur))
    return out


def _batch_of(blocks: list[dict]) -> dict:
    text = "\n\n".join(b["text"] for b in blocks)
    return {"text": text, "used_chars": len(text),
            "labels": [b["label"] for b in blocks],
            "materials": sorted({b["material"] for b in blocks})}


def valid_sections(hit: dict) -> set[str]:
    """材料的**合法溯源标签**全集（归一化后）：章/节地图标签 ∪ 页标签 ∪ 分节标签。"""
    from ..content import citations

    labels: set[str] = set()
    for sec in hit.get("sections") or []:
        labels.add(citations.normalize(str(sec.get("label") or "")))
    structure = hit.get("structure") or {}
    for entry in structure.get("entries") or []:
        labels.add(citations.normalize(entry.label))
        for pg in entry.pages:
            labels.add(citations.normalize(pg))
    return {x for x in labels if x}


def canonical_section(hit: dict, section: str) -> str | None:
    """把溯源 section **收敛成教材章节地图里的规范标签**（模型爱加方括号/空格 → 此处归一）。

    只在"归一化后等于某个条目/节标签"时收敛（页标签与逐字引文原样保留——它们各有语义）。
    返回 None = 不是已知标签（调用方再走引文包含校验）。
    """
    from ..content import citations

    norm = citations.normalize(section)
    if not norm:
        return None
    for sec in hit.get("sections") or []:
        if citations.normalize(str(sec.get("label") or "")) == norm:
            return str(sec.get("label"))
    for e in (hit.get("structure") or {}).get("entries") or []:
        if citations.normalize(e.label) == norm:
            return e.label
    return None


def check_unit_material(ref: dict, index: list[dict]) -> tuple[dict | None, str]:
    """D2（R36）＋ R37 S2：校验单个 ``{title, section}`` 溯源引用 → ``(规范化引用 | None, 中文问题)``。

    规则：① ``title`` 必须真实存在于该学科引用库；② ``section`` 必须是该材料的**真实章/节/页标签**
    （``bookmap`` 的章节地图或 ``material_sections`` 的节名）**或逐字出自其正文的引文**——
    后者复用 ``content.citations`` 的同一把尺子（归一化 + ≥6 字 + 子串包含），
    与 R35 S2 的 basis 引文纪律同源，不另写一份。
    命中的章/节标签会被**收敛为规范标签**（模型复制来的方括号/空格不落盘）。
    """
    from ..content import citations

    title = str((ref or {}).get("title") or "").strip()
    section = str((ref or {}).get("section") or "").strip()
    if not title:
        return None, "材料溯源项缺少材料标题（title）"
    hit = next((m for m in index if m["title"] == title), None)
    if hit is None:
        return None, f"材料溯源不成立：该学科引用库里没有名为「{title}」的材料"
    if not section:
        return None, f"材料《{title}》的溯源缺少 section（须给出真实章节名或逐字引文）"
    canonical = canonical_section(hit, section)
    if canonical is not None:
        return {"title": hit["title"], "section": canonical}, ""
    if citations.normalize(section) in valid_sections(hit):
        return {"title": hit["title"], "section": section}, ""
    ok, reason = citations.check(section, hit["body"], where=f"材料《{hit['title']}》正文")
    if ok:
        return {"title": hit["title"], "section": section}, ""
    return None, f"材料《{hit['title']}》溯源不成立：{reason}"


# ---------- R37 S2：章节全覆盖校验（未映射 → 违规） ----------
def _covered_entries(units: list, index: list[dict]) -> dict[tuple[str, str], list[str]]:
    """算账：地图条目 → 覆盖它的单元 id 列表。

    单元的一条 ``{title, section}`` 溯源**算覆盖**当且仅当：
    ① section 归一化后等于条目标签 / 该条目的任一页标签；或
    ② section 是**逐字引文**（≥6 字）且落在该条目正文内（同 ``citations`` 的尺子，不另写一份）。
    """
    from ..content import citations

    mapping: dict[tuple[str, str], list[str]] = {}
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            mapping[(m["id"], e.label)] = []
    for u in units:
        refs = (u.materials if hasattr(u, "materials") else (u or {}).get("materials")) or []
        uid = u.id if hasattr(u, "id") else str((u or {}).get("id") or "")
        for r in refs:
            title = str((r or {}).get("title") or "").strip()
            section = str((r or {}).get("section") or "").strip()
            norm = citations.normalize(section)
            if not norm:
                continue
            for m in index:
                if title and m["title"] != title:
                    continue
                for e in (m.get("structure") or {}).get("entries") or []:
                    labels = {citations.normalize(e.label)} | {citations.normalize(p) for p in e.pages}
                    body = citations.normalize(e.text)
                    if norm in labels or (len(norm) >= citations.MIN_QUOTE_CHARS and norm in body):
                        bucket = mapping.setdefault((m["id"], e.label), [])
                        if uid and uid not in bucket:
                            bucket.append(uid)
    return mapping


def coverage_problems(units: list, index: list[dict]) -> list[str]:
    """S2：每个地图条目（章/节）必须被 ≥1 个单元的溯源映射到；未映射 → 中文违规。

    ``index``：``draft_materials()["index"]`` 或 ``materials._material_index()``；
    空/无结构条目（无材料、未识别结构）→ 不报（退化为现状）。
    """
    mapping = _covered_entries(units, index)
    if not mapping:
        return []
    total = len(mapping)
    unmapped = [key[1] for key, ids in mapping.items() if not ids]
    if not unmapped:
        return []
    return [f"教材覆盖不全：{len(unmapped)}/{total} 个章/节条目没有任何单元对应"
            "（教材＝权威真源，不得悄悄丢章节）。未映射：" + "、".join(unmapped[:8])
            + ("…" if len(unmapped) > 8 else "")
            + "。请为每个条目至少派生 1 个单元（小条目可合并，但合并后 materials 必须列出全部被合并的条目标签）。"]


def coverage_summary(units: list, index: list[dict]) -> dict:
    """覆盖摘要（供起草候选/大纲页显示）：``{total, covered, uncovered:[标签]}``。"""
    mapping = _covered_entries(units, index)
    unmapped = [key[1] for key, ids in mapping.items() if not ids]
    return {"total": len(mapping), "covered": len(mapping) - len(unmapped), "uncovered": unmapped}


# ---------- R37 S3/S4：单元出稿的教材注入包 ----------
def unit_material_pack(db, subject_id: str, unit, *, batch_chars: int | None = None) -> dict:
    """单元出稿用的**教材注入包**（S3/S4 的唯一入口）。

    - 单元有 ``materials: [{title, section}]`` → 取对应章/节的**完整正文**（按标签匹配；
      标签对不上时退回该材料全文里包含该引文的章）；
    - 单元没有溯源（手工大纲）→ 用单元标题/概念标签在章节地图里做**确定性关键词检索**，
      取命中的章（找不到 → ``covered=False``，出稿端如实报"教材未覆盖此单元"，不编造）；
    - 返回 ``{"text", "entries", "sources", "binding_text", "covered", "note"}``：
      ``binding_text``＝该学科**全部材料正文**（S5 教材锚定校验的原文），``text``＝本次注入正文。
    """
    index = _material_index(db, subject_id)
    healthy = [m for m in index if m["text_health"]["healthy"]]
    if not index:
        return {"text": "", "entries": [], "sources": [], "binding_text": "",
                "covered": False, "no_materials": True, "note": "本学科没有引用材料"}
    if not healthy:
        return {"text": "", "entries": [], "sources": [{"title": m["title"]} for m in index],
                "binding_text": "", "covered": False, "no_materials": False,
                "note": "；".join(m["text_health"]["note"] for m in index)
                        or "该学科材料未通过文本层健康度检查（疑似扫描版）"}
    binding = "\n\n".join(f"《{m['title']}》\n{m['body']}" for m in healthy)
    picked: list[dict] = []
    sources: list[dict] = []
    refs = list(getattr(unit, "materials", None) or [])
    for ref in refs:
        title = str((ref or {}).get("title") or "").strip()
        section = str((ref or {}).get("section") or "").strip()
        for m in healthy:
            if title and m["title"] != title:
                continue
            hit = _entry_for_section(m, section)
            if hit is not None:
                picked.append({"material": m["title"], "label": hit.label, "text": hit.text})
                sources.append({"title": m["title"], "section": hit.label, "match": "declared"})
                break
    if not picked:  # 无溯源 / 溯源没落上 → 关键词检索（确定性；找不到就如实说未覆盖）
        for m in healthy:
            hit = _entry_by_terms(m, unit)
            if hit is not None:
                picked.append({"material": m["title"], "label": hit.label, "text": hit.text})
                sources.append({"title": m["title"], "section": hit.label, "match": "retrieved"})
    text = "\n\n".join(f"【教材段落：{p['label']}（材料《{p['material']}》）】\n{p['text']}"
                       for p in picked)
    return {"text": text, "entries": [p["label"] for p in picked], "sources": sources,
            "binding_text": binding, "covered": bool(picked), "no_materials": False,
            "note": "" if picked else "教材中未检索到与本节相关的章/节"}


def _entry_for_section(m: dict, section: str):
    """按标签匹配章/节条目（归一化比较）；失败则用引文包含关系定位所在条目。"""
    from ..content import citations

    entries = (m.get("structure") or {}).get("entries") or []
    if not entries:
        return None
    if section:
        norm = citations.normalize(section)
        for e in entries:
            if norm == citations.normalize(e.label) or norm in {citations.normalize(x) for x in e.pages}:
                return e
        for e in entries:
            if norm and norm in citations.normalize(e.text):
                return e
    return None


def entry_order(index: list[dict]) -> dict[str, int]:
    """章节地图条目的**书序**索引（归一化标签/页标签 → 位置）。

    R37 S2 复用点：大纲收尾据此把单元按**书序**排列（分批起草的批间顺序不可信，
    书的结构才是顺序真源）。返回空 dict = 没有可用的结构。
    """
    from ..content import citations

    order: dict[str, int] = {}
    i = 0
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            for key in [e.label, *e.pages]:
                norm = citations.normalize(str(key or ""))
                if norm and norm not in order:
                    order[norm] = i
            i += 1
    return order


def unit_order_key(unit, order: dict[str, int], default: int) -> int:
    """单元在书序中的位置（取它映射到的**最早**条目；没有映射 → ``default``）。"""
    from ..content import citations

    best = None
    refs = (unit.materials if hasattr(unit, "materials") else (unit or {}).get("materials")) or []
    for r in refs:
        norm = citations.normalize(str((r or {}).get("section") or ""))
        pos = order.get(norm)
        if pos is not None and (best is None or pos < best):
            best = pos
    return best if best is not None else default


def match_entry(m: dict, title: str = "", tags: list[str] | None = None):
    """确定性关键词检索：用标题/概念标签在章节地图里找最相关的条目（分数 0 → None）。

    R37 复用点：单元出稿的"无溯源回落"与大纲收尾的"溯源被剔除后回捞"共用同一实现。
    """
    from ..content import citations

    terms = [str(title or "")] + [str(t) for t in (tags or [])]
    grams: list[str] = []
    for t in terms:
        norm = citations.normalize(t)
        if len(norm) >= 2:
            grams += [norm[i:i + 3] for i in range(max(1, len(norm) - 2))]
    best = None
    best_score = 0
    for e in (m.get("structure") or {}).get("entries") or []:
        body = citations.normalize(e.text + " " + " ".join(e.sections))
        score = sum(1 for g in grams if g and g in body)
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 1 else None


def _entry_by_terms(m: dict, unit):
    """``match_entry`` 的单元适配（保留旧调用点语义）。"""
    return match_entry(m, getattr(unit, "title", "") or "",
                       list(getattr(unit, "concept_tags", None) or []))


def material_ids_for_titles(db, subject_id: str, titles: list[str]) -> tuple[list[str], list[str]]:
    """D3：材料标题 → material_id（按首次出现序去重）；返回 ``(ids, 未找到的标题)``。"""
    by_title = {e["title"]: e["id"] for e in _entries_with_body(subject_id)}
    ids: list[str] = []
    missing: list[str] = []
    for t in titles:
        t = str(t or "").strip()
        if not t:
            continue
        mid = by_title.get(t)
        if mid is None:
            missing.append(t)
            continue
        if mid not in ids:
            ids.append(mid)
    return ids, missing


# ---------- R37 S6：覆盖账本 ----------
def coverage_ledger(db, subject_id: str) -> dict:
    """**覆盖账本**：章节地图 ↔ 单元映射 ↔ 单元覆盖状态（大纲页与 API 的唯一数据源）。

    返回::

        {
          "total": 章/节条目总数,
          "covered": 已覆盖条目数,
          "uncovered": [未覆盖条目标签…],
          "materials": [{id,title,kind,healthy,note,kind_of_structure,structure_note}],
          "entries": [{material, label, chapter, chars, sections, units:[unit_id…]}],
          "units": [{unit_id, title, sources:[{title,section}], status, note, grounded_facts,
                     material_bound, dropped_exercises}]
        }
    """
    from ..content import citations

    index = _material_index(db, subject_id)
    doc = outline_store.get_outline(subject_id)
    units = list(doc.units) if doc is not None else []
    mapping = _covered_entries(units, index)
    entries: list[dict] = []
    uncovered: list[str] = []
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            hit = sorted(set(mapping.get((m["id"], e.label)) or []))
            if not hit:
                uncovered.append(f"{m['title']} · {e.label}")
            entries.append({"material": m["title"], "label": e.label, "chapter": e.chapter,
                            "chars": e.chars, "sections": list(e.sections), "units": hit,
                            "covered": bool(hit)})
    unit_ledger = []
    for u in units:
        meta = dict(u.meta or {})
        cov = dict(meta.get("coverage") or {})
        unit_ledger.append({
            "unit_id": u.id, "title": u.title,
            "sources": [dict(r) for r in (u.materials or [])],
            "status": str(cov.get("status") or "未知"),
            "note": str(cov.get("note") or ""),
            "grounded_facts": int(cov.get("grounded_facts") or 0),
            "material_bound": bool(cov.get("material_bound")),
            "dropped_exercises": int(cov.get("dropped_exercises") or 0),
            "generated_at": str(cov.get("at") or ""),
        })
    return {
        "subject": subject_id,
        "has_materials": bool(index),
        "total": len(entries),
        "covered": len(entries) - len(uncovered),
        "uncovered": uncovered,
        "materials": [{"id": m["id"], "title": m["title"], "kind": m.get("kind", ""),
                       "healthy": m["text_health"]["healthy"],
                       "note": m["text_health"]["note"],
                       "structure_kind": m["structure"]["kind"],
                       "structure_note": m["structure"]["note"]} for m in index],
        "entries": entries,
        "units": unit_ledger,
    }


def search_candidates(db, subject_id: str, query: str) -> dict:
    """联网候选（Phase C C1：检索后端 provider 抽象；默认未启用 → 明确中文提示）。

    返回：{items: [{title,url,source,summary,reason?}], note: str, backend: {configured,provider,url}}。
    - 未配置 provider → 提示"未配置检索后端…可用本地导入"（items 空）；
    - 配置 SearXNG → 真实检索 →（配 LLM_API_KEY）LLM 整理候选清单 → items。
    """
    from ..config import get_settings
    from . import search as search_svc

    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    settings = get_settings()
    status = search_svc.provider_status(settings)
    if not status.get("configured"):
        return {"items": [], "note": _no_backend_note(status), "backend": status}
    try:
        raw = search_svc.search_web(query, settings=settings)
    except search_svc.SearchBackendError as e:
        return {"items": [], "note": f"联网检索失败：{e}", "backend": status}
    if not raw:
        return {"items": [], "note": "未检索到与查询匹配的候选：可换关键词重试，或使用「本地导入」上传自有/授权资料。",
                "backend": status}
    items = _refine_candidates(db, row, query, raw, settings)
    return {"items": items, "note": "", "backend": status}


def _no_backend_note(status: dict) -> str:
    provider = status.get("provider") or "none"
    if provider == "searxng":
        return ("联网检索后端未配置完成：已选 SearXNG 但缺少实例地址（设 MF_SEARXNG_URL）。"
                "配置后可用联网候选，或现在用「本地导入」上传自有/授权资料。")
    return ("联网检索后端未配置（当前无检索 provider）。可选方案：自托管 SearXNG（设 "
            "MF_SEARCH_PROVIDER=searxng 与 MF_SEARXNG_URL），或先用「本地导入」上传自有/授权资料。")


def _refine_candidates(db, subj, query: str, raw: list[dict], settings) -> list[dict]:
    """LLM 整理候选（配 LLM_API_KEY 时；输出 url 回滤原始集防杜撰；失败/无 key → 原始直出）。"""
    if not settings.llm_api_key:
        return raw[: max(1, settings.search_max_items)]
    try:
        from ..ai.calls import CALL_SEARCH_CANDIDATES
        from ..ai.provider import OpenAICompatibleProvider
        from ..service.ai_sink import make_ai_log_sink

        provider = OpenAICompatibleProvider(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url,
            model_heavy=settings.llm_model_heavy, model_light=settings.llm_model_light,
            log_sink=make_ai_log_sink(),
        )
        sys = (
            "你是资料检索助理。给定一次联网检索的**原始结果清单**与学习者的学科背景，"
            "挑选最适合作为**学习参考材料**的条目（优先：权威/可读/与学科目标相关），"
            '输出 JSON：{"items":[{"title","url","source","summary","reason"}]}。'
            "要求：只从原始结果中挑选（禁止自造 url）；3–8 条；summary 为 1–2 句要点摘要；"
            "reason 一句说明为何适合做学习材料。"
        )
        user = (
            f"学科：{subj.id}（{subj.label or ''}）\n"
            f"检索词：{query}\n原始结果：\n"
            + "\n".join(f"- {r.get('title', '')} | {r.get('url', '')} | {r.get('summary', '')[:200]}"
                        for r in raw[:12])
        )
        outcome = provider.chat_json(
            CALL_SEARCH_CANDIDATES,
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            strategy="fast",
        )
        valid_urls = {r.get("url") for r in raw}
        refined = []
        for it in (outcome.parsed.get("items") or []):
            url = str(it.get("url") or "").strip()
            if url not in valid_urls:  # 防 LLM 杜撰来源
                continue
            title = str(it.get("title") or "").strip()
            summary = str(it.get("summary") or "").strip()
            if not title or not summary:
                continue
            refined.append({
                "title": title,
                "url": url,
                "source": str(it.get("source") or next(
                    (r.get("source", "") for r in raw if r.get("url") == url), "")),
                "summary": summary,
                "reason": str(it.get("reason") or ""),
            })
        if refined:
            return refined[: max(1, settings.search_max_items)]
        return raw[: max(1, settings.search_max_items)]  # LLM 整理失败 → 原始直出
    except Exception:
        return raw[: max(1, settings.search_max_items)]  # AI 异常不阻塞检索流


def select_candidates(db, subject_id: str, items: list[dict],
                      *, fetch_pages: bool = False) -> list[dict]:
    """勾选候选 → 本地化引用（标题/来源/摘要入库；**不整本下载**）。

    fetch_pages=True（用户勾选动作）→ 对 http(s) 公开网页抓正文入库（大小上限/失败回落摘要）；
    书籍类 URL/非 html 不抓取（PDF 走 C2 用户上传路径）。
    """
    from . import search as search_svc

    saved = []
    for it in items:
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or "").strip()
        summary = str(it.get("summary") or "").strip()
        if not title or not (summary or url):
            continue
        text = summary + ("\n（来源：" + url + "）" if url else "")
        if fetch_pages and url:
            fetched = search_svc.fetch_page_text(url)
            if fetched:
                text = ("（以下为该公开网页正文的本地化摘录，用户勾选抓取：）\n\n"
                        + fetched + "\n\n【原始候选摘要】\n" + summary)
        saved.append(add_material(db, subject_id, title=title, text=text,
                                  source=str(it.get("source") or url or "联网候选"), url=url))
    if not saved:
        raise OutlineError("请勾选至少 1 条候选（标题与摘要不能为空）")
    return saved


__all__ = [
    "SOURCE_POLICIES",
    "DEFAULT_POLICY",
    "DEFAULT_INJECT_MAX_CHARS",
    "DEFAULT_BATCH_CHARS",
    "materials_dir",
    "get_policy",
    "set_policy",
    "add_material",
    "list_materials",
    "delete_material",
    "materials_summaries",
    "text_health",
    "material_sections",
    "material_structure",
    "inject_budget",
    "batch_budget",
    "draft_materials",
    "valid_sections",
    "canonical_section",
    "check_unit_material",
    "coverage_problems",
    "coverage_summary",
    "coverage_ledger",
    "match_entry",
    "entry_order",
    "unit_order_key",
    "unit_material_pack",
    "material_ids_for_titles",
    "search_candidates",
    "select_candidates",
]
