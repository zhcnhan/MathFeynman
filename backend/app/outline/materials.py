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
import json
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

# ---------- R38 B2：材料角色（主教材 / 补充材料 / 未标注） ----------
# 说明：**未标注 ≠ 主教材**——未标注按导入顺序，覆盖账里注明"顺序依据：导入顺序"。
ROLE_MAIN = "main"
ROLE_SUPPLEMENT = "supplement"
ROLE_UNSET = ""
ROLES = (ROLE_MAIN, ROLE_SUPPLEMENT)
ROLE_LABELS_ZH = {ROLE_MAIN: "主教材", ROLE_SUPPLEMENT: "补充材料", ROLE_UNSET: "未标注"}

# ---------- R38 A1/A5：两个滑块（单次调用预算 / 总注入上限）的档位与内置默认 ----------
BATCH_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
INJECT_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
BUILTIN_BATCH_CHARS = 60000       # A5 内置默认：单次调用预算
BUILTIN_INJECT_MAX_CHARS = 0      # A2 内置默认：总注入上限＝不限（0）

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


def text_health(body: str, *, quality: dict | None = None, min_chars_per_page: int | None = None,
                min_page_ratio: float | None = None) -> dict:
    """材料体检（R37 S7 文本层健康度 + **R55 A 抽取体检**）→ 三档 + **人话**"所以会怎样"。

    - 页数 < ``MIN_PAGES_FOR_HEALTH``（粘贴短文本）→ 不做扫描版判定，如实标注"未判定"；
    - 页数 ≥ 3 且（每页平均字符数 < 下限 或 有文字页占比 < 下限）→ ``healthy=False``，
      note 直接给用户可执行的下一步（OCR / 换文本版），**不含糊**；
    - **R55 A**：另外给 ``extract``（认不出比例 / 拆字比例 / 公式符号 / 图片数）与
      ``grade``（好/一般/差）+ ``summary_zh``——**数字后面必须跟一句"所以会怎样"**，
      且界面上不出现内部编号/字段名（docs/13 §2）。
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
        base = {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
                "text_page_ratio": round(text_ratio, 2), "healthy": True, "checked": False,
                "note": "页数过少，未做扫描版判定（粘贴文本按可用处理）"}
    else:
        healthy = per_page >= cap and text_ratio >= ratio
        note = "" if healthy else (
            f"本书疑似扫描/图片版：{pages} 页仅提取到 {chars} 个字符"
            f"（每页约 {per_page:.0f} 字，下限 {cap}；有文字页 {nonempty}/{pages}）。"
            "请先 OCR 或改用文本版 PDF/粘贴文本后重新上传——"
            "系统不会在「没读到书」的情况下生成大纲（R37 S7）。"
        )
        base = {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
                "text_page_ratio": round(text_ratio, 2), "healthy": healthy, "checked": True,
                "note": note}
    # **R55 A**：抽取体检（粘贴文本没有 PDF 元信息 → 就地在正文上算；图片数未知记 0）
    from .pdfparse import extract_quality

    extract = dict(quality) if quality else extract_quality(text, pages=pages, images=0, image_pages=0)
    base["extract"] = extract
    base["grade"] = extract["grade"]
    base["fixed"] = bool((quality or {}).get("fixed"))
    base["summary_zh"] = _health_summary_zh(base, extract)
    return base


def _health_summary_zh(health: dict, extract: dict) -> str:
    """体检摘要（**人话**）：先说结论，再说"所以会怎样"。"""
    if not health.get("healthy"):
        return ("这份材料几乎没读到文字（像是扫描件/图片版）。"
                "请先做文字识别（OCR），或改用文字版 PDF / 直接粘贴文本后重新上传。")
    parts = [str(extract.get("grade_reason_zh") or "")]
    imgs = int(extract.get("images") or 0)
    if imgs:
        parts.append(f"另外这份材料里有 {imgs} 张图（分布在 {int(extract.get('image_pages') or 0)} 页），"
                     "图里的内容我读不到——正文提到图的地方会明确标出来，不会瞎猜。")
    if health.get("fixed"):
        parts.append("导入时已顺手修正抽取问题（认不出的字形、被空格拆开的字），原始文本也留了一份备查。")
    return "".join(p for p in parts if p)


# ---------- R55 B：指向图表/图片的指代 → "图示不可用"要显式认输 ----------
# 判据（**两条并列**，任一命中即算指代）：
#   ① **指示词**：如图 / 见图 / 参见图 / 上图 / 下图 / 图中 / 附图 / 如表 / 见下表 / 下表 / 附表…
#   ② **编号**：图 3.2 / 表 2-1 / Fig. 4 / Table 5（有编号就是明确指向某张图/表）
# 误判防护（见 NOTES §77）：
#   - 只认"图/表 + 指示词或编号"，**不认孤立的"图"字**（`地图`/`图书`/《图解…》都不会命中）；
#   - 参考文献行（`[12] …`）、含网址/DOI/ISBN 的行**整行跳过**（那里的"图"是书名/刊名的一部分）。
_FIG_DEICTIC = re.compile(
    r"(?:如|见|参见|根据|结合)\s*(?:上|下|本|附)?\s*(?:图|表)|"
    r"(?:上|下|本|附)\s*(?:图|表)\s*(?:中|所示|显示|给出|列出)|"
    r"图中|如下图|如下表|见下表|见附图"
)
_FIG_NUMBERED = re.compile(
    r"(?:图|表)\s*\d{1,2}(?:\s*[.\-]\s*\d{1,2})*(?!\d)|"
    r"(?:Fig(?:ure)?|Tab(?:le)?)\.?\s*\d{1,2}(?!\d)"
)
_REF_LINE = re.compile(r"^\s*[\[\(]\s*\d{1,3}\s*[\]\)]|https?://|doi:|DOI:|ISBN")


def figure_refs(text: str) -> list[str]:
    """一段文字里"指向图表/图片"的指代片段（去重、保序、最多 8 条）。

    同一个位置的重叠命中（`如图 1.1` → 指示词"如图" + 编号"图 1.1"）**只留最长的那个**
    （给用户看的是"图 1.1"，不是"如图、图 1.1"）。
    """
    found: list[str] = []
    for line in str(text or "").splitlines():
        if _REF_LINE.search(line):      # 参考文献/网址行：不算（书名里的"图"不误判）
            continue
        spans = [(m.start(), m.end(), m.group(0)) for m in _FIG_DEICTIC.finditer(line)]
        spans += [(m.start(), m.end(), m.group(0)) for m in _FIG_NUMBERED.finditer(line)]
        spans.sort()
        picked: list[tuple[int, int, str]] = []
        for st, en, txt in spans:
            if picked and st < picked[-1][1]:            # 与本簇已选片段重叠
                if (en - st) > (picked[-1][1] - picked[-1][0]):
                    picked[-1] = (st, en, txt)           # 留更长的（编号比指示词更清楚）
                continue
            picked.append((st, en, txt))
        found.extend(t.strip() for _, _, t in picked)
    out: list[str] = []
    for f in found:
        if f and f not in out:
            out.append(f)
    return out[:8]


def annotated_entry_text(entry_text: str) -> tuple[str, list[str], int]:
    """把条目正文按段落过一遍：**引用了图/表的段落**加显式标注 → ``(新文本, 指代列表, 标注段数)``。

    只加标注、**不删正文**（不静默改内容）：模型看到标注就知道"这里的信息我读不到，不许猜"。
    """
    paras = re.split(r"(\n\s*\n)", str(entry_text or ""))
    refs: list[str] = []
    marked = 0
    out: list[str] = []
    for seg in paras:
        if seg.strip() and not seg.isspace():
            hits = figure_refs(seg)
            if hits:
                refs.extend(h for h in hits if h not in refs)
                marked += 1
                seg = FIGURE_ANNOTATION.format(refs="、".join(hits[:3])) + "\n" + seg
        out.append(seg)
    return "".join(out), refs, marked


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
                 url: str = "", kind: str | None = None, filename: str = "",
                 quality: dict | None = None, raw_text: str = "",
                 mode: str = "", pages_file: str = "", page_count: int = 0,
                 toc: list[dict] | None = None) -> dict:
    """本地/联网引用入库（文本必填；分节文本按段落/标题切分存正文）。

    kind ∈ local|web|pdf（缺省按 url 推导：有 url=web、无=local；pdf 由 C2 解析器显式传入）；
    filename 记录源文件名（PDF/文档导入的展示与追溯）。
    R37 S7：入库时计算文本层健康度并写入 frontmatter（扫描版 → 中文告知，见 ``text_health``）。
    **R55**：``quality`` ＝ 抽取体检（PDF 路径传入，含图片数等 PDF 才有的信息）；
    ``raw_text`` ＝ **原始抽取文本**（与修正后不同则另存 `*.raw.txt` 备查，见 NOTES §77 C3）。
    **R56 第 3 步**：``mode="all_ai"`` 标记这份材料属于**图示教材模式**（全 AI 模式）——
    ``pages_file`` 指向 `*.pages.json`（每页"读到了什么"的结构化记录），``page_count`` 是页数。
    这是**既有材料层的一个字段**，不是第二套材料机制（正文仍是这份 `.md`）。
    **R67 任务 C**：``toc`` ＝ **PDF 自带书签**（``[{title, page, level}]``）——有就另存一份
    `*.toc.json` 并在 frontmatter 里留 ``toc_file``：认章时**优先用书签**（书自己写的目录），
    没有书签才回落"解析目录页文字"。这一步**不改正文一个字节**。
    """
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise OutlineError("材料标题与正文不能为空")
    bookmarks = [dict(x) for x in (toc or []) if isinstance(x, dict) and str(x.get("title") or "").strip()]
    effective_kind = kind or ("web" if url else "local")
    if effective_kind not in ("local", "web", "pdf", "pages"):
        raise OutlineError(f"材料 kind 非法: {effective_kind!r}")
    mode = (mode or "").strip()
    if mode not in ("", "all_ai"):
        raise OutlineError(f"材料模式非法: {mode!r}（只支持空或 all_ai）")
    fixed = bool(raw_text.strip()) and raw_text.strip() != text
    if quality is None and fixed:
        # **R55 A**：只给了"修正后的文本 + 原始抽取"（粘贴/外部工具路径）时，体检照**原始抽取**算
        # ——如实告诉用户"这份 PDF 抽出来有多脏"，而不是因为我们已经修好了就报"很干净"。
        from .pdfparse import extract_quality

        quality = extract_quality(raw_text, pages=max(1, len(_PAGE_MARK.findall(raw_text))),
                                  images=0, image_pages=0)
    health = text_health(text, quality=quality)
    health["fixed"] = fixed
    health["summary_zh"] = _health_summary_zh(health, health["extract"])
    entry_id = "mat-" + hashlib.sha1(f"{subject_id}:{title}:{url}:{text[:80]}".encode("utf-8")).hexdigest()[:10]
    p = materials_dir(subject_id) / f"{_slug(title)}-{entry_id[4:]}.md"
    raw_name = (p.with_suffix("").name + ".raw.txt") if fixed else ""
    toc_name = (p.with_suffix("").name + ".toc.json") if bookmarks else ""
    health["raw_file"] = raw_name      # 界面/接口据此显示"原始文本留档"（老材料为空串）
    health["toc_file"] = toc_name      # R67 C：书签目录留档（老材料为空串）
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
        # **R55 A/C**：抽取体检 + "已做抽取修正"留痕（不静默改内容）
        meta_lines += [
            f"extract_grade: {health['grade']}",
            f"unrecognized_ratio: {health['extract']['unrecognized_ratio']}",
            f"broken_space_ratio: {health['extract']['broken_space_ratio']}",
            f"formula_symbols: {health['extract']['formula_symbols']}",
            f"image_count: {health['extract']['images']}",
            f"image_pages: {health['extract']['image_pages']}",
            f"extract_fixed: {'yes' if fixed else 'no'}",
        ]
        if fixed:  # C3：原始抽取文本另存一份（供事后核查"是抽取错了，还是模型编了"）
            (p.parent / raw_name).write_text(raw_text, encoding="utf-8")
            meta_lines.append(f"raw_file: {raw_name}")
        # **R67 任务 C**：PDF 自带书签目录另存一份（认章优先用它；正文一字不动）
        if toc_name:
            (p.parent / toc_name).write_text(
                json.dumps({"bookmarks": bookmarks}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            meta_lines.append(f"toc_file: {toc_name}")
        # **R56 第 3 步**：图示教材模式标记（这条材料的"来源模式"）
        if mode:
            meta_lines += [f"mode: {mode}", f"page_count: {int(page_count or 0)}"]
            if pages_file:
                meta_lines.append(f"pages_file: {pages_file}")
        meta_lines += ["", "---", ""]
        p.write_text("\n".join(meta_lines) + "\n" + text + "\n", encoding="utf-8")
    if fixed:
        # **R55 C3 ＋ R39 铁则**：改了用户给的正文就必须留痕（改了什么、原文在哪）
        from ..service import ledger as _ledger

        ex = dict(health.get("extract") or {})
        _ledger.note(
            _ledger.CAT_MATERIAL, f"材料《{title}》· 抽取修正",
            f"导入时做了抽取修正：原始抽取里有 {int(ex.get('unrecognized') or 0)} 个认不出的字形、"
            f"{int(ex.get('broken_space_lines') or 0)} 行字被空格拆开——已按通用规则修正，"
            f"注入给模型的是修正后的文本；原始抽取另存 {raw_name} 备查",
            impact=_ledger.SCOPE_SUBJECT, remedy=_ledger.REMEDY_YES, subject_id=subject_id,
            detail={"kind": "extract_fixed", "raw_file": raw_name,
                    "unrecognized": int(ex.get("unrecognized") or 0),
                    "broken_space_lines": int(ex.get("broken_space_lines") or 0),
                    "unrecognized_ratio": float(ex.get("unrecognized_ratio") or 0.0)},
        )
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
            role_raw = str(fm.get("role", "")).strip().lower()
            return {
                "id": fm.get("id", p.stem),
                "title": fm.get("title", p.stem),
                "source": fm.get("source", "本地导入"),
                "url": fm.get("url", ""),
                "kind": fm.get("kind", "local"),
                "file": p.name,
                "filename": fm.get("filename", ""),
                "body": body,
                "path": str(p),
                # R37 S7：入库时算的健康度（老材料没有该字段 → 现算一次，不让历史材料失去判定）
                "text_healthy": (healthy_raw != "no") if healthy_raw else None,
                # R38 B2：材料角色（main=主教材 / supplement=补充材料）；老材料无该字段
                # → 视为"未标注"（按导入顺序，覆盖账里注明）
                "role": role_raw if role_raw in ("main", "supplement") else "",
                # **R56 第 3 步**：材料来源模式（空 = 文字教材路径；all_ai = 图示教材模式）
                "mode": str(fm.get("mode", "")).strip(),
                "page_count": _as_int(fm.get("page_count")),
                "pages_file": str(fm.get("pages_file", "")).strip(),
                # **R67 任务 C**：PDF 自带书签目录（`*.toc.json`；老材料为空 → 回落目录页解析）
                "toc_file": str(fm.get("toc_file", "")).strip(),
                # **R55 A/C**：入库时算好的抽取体检 + "已做抽取修正"留痕（老材料无 → 读时现算）
                "extract_meta": {
                    "grade": fm.get("extract_grade", ""),
                    "fixed": str(fm.get("extract_fixed", "")).strip().lower() == "yes",
                    "raw_file": fm.get("raw_file", ""),
                    "images": _as_int(fm.get("image_count")),
                    "image_pages": _as_int(fm.get("image_pages")),
                    "unrecognized_ratio": _as_float(fm.get("unrecognized_ratio")),
                    "broken_space_ratio": _as_float(fm.get("broken_space_ratio")),
                    "formula_symbols": _as_int(fm.get("formula_symbols")),
                },
            }
    return None


def _merge_extract_meta(health: dict, meta: dict) -> None:
    """把入库时留痕的抽取体检信息合并进现值（**图片数/修正留痕只有入库时知道**）。

    幂等：只补"现值算不出来"的那几项，不改文本指标本身。
    """
    if not meta:
        return
    ex = dict(health.get("extract") or {})
    for key, src in (("images", "images"), ("image_pages", "image_pages")):
        if meta.get(src):
            ex[key] = int(meta[src])
    if meta.get("grade"):
        health["grade"] = str(meta["grade"])
    if meta.get("fixed"):
        health["fixed"] = True
    health["raw_file"] = str(meta.get("raw_file") or "")
    health["extract"] = ex
    health["summary_zh"] = _health_summary_zh(health, ex)


def _as_int(v) -> int:
    try:
        return int(float(str(v)))
    except Exception:
        return 0


def _as_float(v) -> float:
    try:
        return float(str(v))
    except Exception:
        return 0.0


def _load_pages_doc(subject_id: str, entry: dict) -> dict:
    """读某份材料留档的页面记录（`*.pages.json`）；没有/读坏了 → 空 dict（**不猜**）。"""
    name = str((entry or {}).get("pages_file") or "")
    if not name:
        return {}
    f = materials_dir(subject_id) / name
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def import_state(subject_id: str, entry: dict) -> dict:
    """**R67 任务 A**：这份材料"上次读到哪了"（读 `*.pages.json` 里的 `progress` 块）。

    - 正在读 → ``state="importing"``（重启后仍留着；界面据此说"上次没读完，还剩哪些页"）；
    - 读完/取消 → ``state="done" / "cancelled"``；
    - 老材料（没有 `progress` 块）→ 用页面记录自己的页数说话，``state=""``（**不编状态**）。
    """
    doc = _load_pages_doc(subject_id, entry)
    pages = list(doc.get("pages") or [])
    render = dict(doc.get("render") or {})
    p = dict(doc.get("progress") or {})
    if not p:
        if not pages:
            return {}
        return {"state": "", "strategy": "", "sampled": bool(render.get("sampled")),
                "read": len(pages), "total": len(pages), "pending": [], "failed": [],
                "book_total": len(pages), "unread": [], "updated_at": "", "note_zh": ""}
    pending = list(p.get("pending") or [])
    return {"state": str(p.get("state") or ""), "strategy": str(p.get("strategy") or ""),
            "sampled": bool(p.get("sampled")), "read": int(p.get("read") or 0),
            "total": int(p.get("total") or 0), "pending": pending,
            # **R67 D/F**：这本书**还有哪几页没读**（快读没进计划的页也算"没读"）
            "book_total": int(p.get("book_total") or 0),
            "unread": list(p.get("unread") or pending),
            "failed": list(p.get("failed") or []), "updated_at": str(p.get("updated_at") or ""),
            "note_zh": str(p.get("note_zh") or "")}


def switch_suggestion(subject_id: str, entry: dict, health: dict) -> dict:
    """**R67 任务 E**：这份材料"该走哪条路"+ 能不能**一键改道**（人话，不堆术语）。

    - 只看文字（文字教材路径）但**图很多** → 建议改走"连图一起看"（图里的内容才读得到）；
    - 连图一起看（图示教材模式）且原始 PDF 还在缓存里 → 可以改走"只看文字"（更快更省）。
    """
    from . import pdfrender

    mid = str(entry.get("id") or "")
    cached = bool(mid) and pdfrender.pdf_cache_path(subject_id, mid).exists()
    mode = str(entry.get("mode") or "")
    ex = dict((health or {}).get("extract") or {})
    images = int(ex.get("images") or 0)
    image_pages = int(ex.get("image_pages") or 0)
    grade = str((health or {}).get("grade") or "")
    if mode == MODE_ALL_AI:
        return {"better": "text" if cached else "",
                "reason_zh": ("这份材料现在走的是「连图一起看」：每一页都要问一次模型，更慢也更贵；"
                              "这份 PDF 的文字层也能用「只看文字」的方式读一遍（更快），两种都会留着。"
                              if cached else
                              "这份材料现在走的是「连图一起看」：看图这条路能读到公式和版式，"
                              "但判对错与评分都由模型给出，程序不替你复核。"),
                "can_switch_to_pages": False, "can_switch_to_text": cached,
                "images": images, "image_pages": image_pages, "grade": grade}
    if images >= 10 or image_pages >= 5 or grade == "差":
        return {"better": "pages",
                "reason_zh": (f"这份材料里有 {images} 张图（分布在 {image_pages} 页），"
                              "只看文字的话，图里的内容系统读不到——"
                              "如果这本书主要靠图讲，建议改用「连图一起看」把每页交给 AI 读一遍。"),
                "can_switch_to_pages": cached, "can_switch_to_text": False,
                "images": images, "image_pages": image_pages, "grade": grade}
    return {"better": "", "reason_zh": "", "can_switch_to_pages": cached,
            "can_switch_to_text": False, "images": images, "image_pages": image_pages,
            "grade": grade}


def list_materials(db, subject_id: str) -> list[dict]:
    d = materials_dir(subject_id)
    out = []
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e:
            health = text_health(e.get("body", ""))
            if e.get("text_healthy") is False:
                health["healthy"] = False
            _merge_extract_meta(health, e.get("extract_meta") or {})
            out.append({"id": e["id"], "title": e["title"], "source": e["source"],
                        "url": e["url"], "kind": e["kind"], "file": e["file"],
                        "filename": e.get("filename", ""),
                        # **R56 第 3 步**：来源模式（界面据此显示"当前是哪个模式"）+ 页数
                        "mode": e.get("mode", ""),
                        "mode_zh": MODE_LABELS_ZH.get(e.get("mode", "") or "", ""),
                        "page_count": int(e.get("page_count") or 0),
                        # R38 B2：材料角色（未标注 → main 并标注 explicit=False，按导入顺序）
                        "role": e.get("role") or ROLE_UNSET,
                        "role_explicit": bool(e.get("role")),
                        "role_zh": ROLE_LABELS_ZH.get(e.get("role") or ROLE_UNSET),
                        # **R67 任务 A**：这份材料"上次读到哪了"（进度块；老材料为空）
                        "import_state": import_state(subject_id, e),
                        # **R67 任务 E**：该走哪条路 + 能不能一键改道（按材料特征给建议）
                        "suggest": switch_suggestion(subject_id, e, health),
                        "text_health": health})
    return out


def reparse_material(db, subject_id: str, material_id: str) -> dict:
    """**R55 C4**：重新做一次"抽取修正"（给已有材料用；**幂等**）。

    - 源文本优先取 `*.raw.txt`（**原始抽取**，R55 C3 留档）；没有就用手上的正文（老材料）；
    - 修正后写回材料正文（**不改原始上传文件**——PDF 字节本来就没留；**不动已生成的内容文件**）；
    - 幂等：修正过的文本再修正一次**不会有任何变化**（`changed=False`，也不重复留档）；
    - 返回 ``{id,title,changed,text_health}``：界面据此如实说"改了什么/没改什么"。
    """
    from .pdfparse import _clean, _merge_broken_spaces, _fold_private_use, extract_quality

    d = materials_dir(subject_id)
    for p in d.glob("*.md"):
        e = _parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        raw = p.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(raw)
        raw_name = str(fm.get("raw_file") or "")
        raw_src = body
        if raw_name and (d / raw_name).exists():
            raw_src = (d / raw_name).read_text(encoding="utf-8")
        fixed, _ = _fold_private_use(raw_src)
        fixed, _ = _merge_broken_spaces(fixed)
        fixed = fixed.strip()
        changed = fixed != body.strip()
        if changed and not raw_name:
            # 老材料（导入时没留档）→ 先把**原始抽取**存一份，再改正文（不静默改内容）
            raw_name = p.with_suffix("").name + ".raw.txt"
            (d / raw_name).write_text(body, encoding="utf-8")
        if changed:
            fm["raw_file"] = raw_name
            fm["extract_fixed"] = "yes"
        quality = extract_quality(fixed, pages=_as_int(fm.get("text_pages")) or 1,
                                  images=_as_int(fm.get("image_count")),
                                  image_pages=_as_int(fm.get("image_pages")))
        fm["extract_grade"] = quality["grade"]
        fm["unrecognized_ratio"] = quality["unrecognized_ratio"]
        fm["broken_space_ratio"] = quality["broken_space_ratio"]
        fm["formula_symbols"] = quality["formula_symbols"]
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["", "---", ""]
        p.write_text("\n".join(lines) + fixed + "\n", encoding="utf-8")
        health = text_health(fixed, quality=quality)
        health["fixed"] = str(fm.get("extract_fixed") or "") == "yes"
        health["summary_zh"] = _health_summary_zh(health, health["extract"])
        if changed:
            # **R55 C4 ＋ R39 铁则**：重写了用户材料的正文 → 必须留痕（改了什么、原文在哪）
            from ..service import ledger as _ledger

            _ledger.note(
                _ledger.CAT_MATERIAL, f"材料《{e['title']}》· 重新整理文字",
                "按你的要求重做了一次抽取修正：修正后的文本已写回材料"
                f"（原始抽取留档 {raw_name} 备查）；原始上传文件与已生成的内容文件**没有改动**",
                impact=_ledger.SCOPE_SUBJECT, remedy=_ledger.REMEDY_YES, subject_id=subject_id,
                detail={"kind": "extract_reparsed", "raw_file": raw_name,
                        "unrecognized_ratio": quality["unrecognized_ratio"],
                        "broken_space_ratio": quality["broken_space_ratio"],
                        "grade": quality["grade"]},
            )
        return {"id": material_id, "title": e["title"], "changed": changed,
                "text_health": health}
    raise OutlineError(f"材料不存在: {material_id}")


def update_material_body(db, subject_id: str, material_id: str, *, text: str,
                         page_count: int | None = None) -> bool:
    """**R67 任务 A**：就地更新某份材料的正文（frontmatter 一字不动）。

    给"导入分段落盘"用：第一次落盘建材料，之后每次落盘只换正文与页数——
    **材料 id / 文件名都不变**，于是"已读的页"始终在同一份材料里越攒越多，
    不会出现"读了 60 页却有三份半截材料"。更新失败返回 False（调用方如实记账，不静默）。
    """
    d = materials_dir(subject_id)
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        raw = p.read_text(encoding="utf-8")
        fm, _body = _split_frontmatter(raw)
        if page_count is not None:
            fm["page_count"] = str(int(page_count))
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["", "---", ""]
        p.write_text("\n".join(lines) + (text or "").strip() + "\n", encoding="utf-8")
        return True
    return False


def set_material_pages_file(db, subject_id: str, material_id: str, pages_file: str) -> bool:
    """**R56 第 3 步**：把 `pages_file`（页面记录文件名）补写进材料 frontmatter。

    为什么不在 `add_material` 一次写完：入库要先拿到材料 id 才能给 `*.pages.json` 命名
    （放在 `*.md` 旁边、以 `pages-<id>` 开头）；这里只改这一行，正文一字不动。
    """
    d = materials_dir(subject_id)
    for p in d.glob("*.md"):
        e = _parse_entry(p)
        if not e or e["id"] != material_id:
            continue
        raw = p.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(raw)
        fm["pages_file"] = pages_file
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["", "---", ""]
        p.write_text("\n".join(lines) + body.strip() + "\n", encoding="utf-8")
        return True
    return False


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    fm: dict[str, str] = {}
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end > 0:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
            return fm, raw[end + 4 :].strip()
    return fm, raw.strip()


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


def material_structure(body: str, toc: list[dict] | None = None) -> dict:
    """R37 S1/S2/S8：材料正文 → **章 → 节**结构（完整正文，不截断）。

    返回 ``{"kind", "note", "entries": [MapEntry], "chapter_map": [dict]}``；
    解析器是 ``outline.bookmap``（唯一实现；大纲起草与单元出稿共用同一份地图）。
    ``toc``（**R67 任务 C**）：材料自带的**书签目录**——有就优先用（书自己写的目录），
    没有/认不出才回落目录页文字解析（回落路径与 R67 之前逐字一致）。
    """
    parsed = bookmap.parse_book(body or "", toc=toc or None)
    entries = parsed["entries"]
    return {
        "kind": parsed["kind"],
        "note": parsed["note"],
        "pages": parsed.get("pages", 0),
        "entries": entries,
        "chapter_map": bookmap.chapter_map(entries),
    }


def load_material_toc(subject_id: str, entry: dict) -> list[dict]:
    """读某份材料留档的**书签目录**（`*.toc.json`）；没有/读坏了 → 空表（回落目录页解析）。

    **只读**：文件不存在、JSON 坏掉、结构怪 —— 一律当"没有书签"，绝不让认章失败。
    """
    name = str((entry or {}).get("toc_file") or "")
    if not name:
        return []
    f = materials_dir(subject_id) / name
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out = [dict(x) for x in (data.get("bookmarks") or []) if isinstance(x, dict)]
    return out


def _material_index(db, subject_id: str) -> list[dict]:
    """材料索引（服务端用）：正文 + 章/节结构 + 健康度 + 角色（R38 B2）。"""
    out = []
    for e in _entries_with_body(subject_id):
        body = e.get("body", "")
        # **R67 任务 C**：有书签就用书签认章（没有 → 与 R67 之前逐字一致）
        structure = material_structure(body, toc=load_material_toc(subject_id, e))
        health = text_health(body)
        if e.get("text_healthy") is False:
            health["healthy"] = False
        _merge_extract_meta(health, e.get("extract_meta") or {})
        role = str(e.get("role") or "")
        out.append({
            "id": e["id"], "title": e["title"], "source": e["source"], "url": e["url"],
            "kind": e.get("kind", "local"), "filename": e.get("filename", ""),
            # **R67**：`pages_file`（页面记录文件）与 `mode` 要带给下游——
            # 否则"读到哪了 / 是不是抽样读"在覆盖账里查不到（账就说不实话了）
            "pages_file": str(e.get("pages_file") or ""), "mode": str(e.get("mode") or ""),
            "body": body, "sections": material_sections(body),
            "structure": structure, "text_health": health,
            "role": role or ROLE_UNSET, "role_explicit": bool(role),
        })
    return out


def _full_blocks(index: list[dict]) -> list[dict]:
    """R37 S1 默认口径：每份材料按章/节**完整正文**成块（不截断、不摘要）。

    **R55 B**：块内"引用了图/表的段落"加显式标注（`【图示不可用：…不要据此编造】`），
    并记下该块的 ``figure_refs`` / ``figure_marked`` / ``clean_text``（去标注、去图段的正文，
    供"事实句/题目依据不得来自图段"的校验用）。
    """
    blocks: list[dict] = []
    for m in index:
        if not m["text_health"]["healthy"]:
            continue
        for entry in m["structure"]["entries"]:
            secs = "；".join(entry.sections[:12])
            head = (f"#### [{entry.label}]（材料《{m['title']}》"
                    f"{'，节：' + secs if secs else ''}）")
            annotated, refs, marked = annotated_entry_text(entry.text)
            blocks.append({"material": m["title"], "material_id": m["id"],
                           "label": entry.label, "text": f"{head}\n{annotated}",
                           "chars": entry.chars,
                           "figure_refs": refs, "figure_marked": marked,
                           "figure_only": bool(refs) and marked >= max(1, _paragraph_count(entry.text)),
                           "clean_text": non_figure_text(entry.text),
                           "figure_text": figure_text_of(entry.text)})
    return blocks


def _paragraph_count(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()])


# **R55 B 的粒度口径**（实测见 NOTES §77）：
#   - **可见标注**用**段落**级：只要这一段里有"如图/见下表"，就在这段前面加中文警告；
#   - **"不许当依据"用句子**级：只有"引用了图/表的那一句"（＋紧随其后的 1 句，"该图显示…"
#     这类描述句往往不带"图"字）里的文字，才判定为"只落在图里"。
#   为什么不是段落级：真实教材里一"段"常常是**整页**（页内没有空行），段落级会把整页正文
#   都判成"读不到图"——实测会误丢 17 条事实句里的 10 条、6 条题目引文里的 4 条（好内容被丢）。
_SENT_SPLIT = re.compile(r"(?<=[。；！？!?;])|\n+")
FIGURE_SENTENCE_WINDOW = 2      # 引用句 + 紧随其后的 (N-1) 句
FIGURE_ANNOTATION = "【图示不可用：这里引用了图片/表格（{refs}），本系统读不到图片内容——不要据此编造】"


def figure_sentences(text: str) -> list[str]:
    """**引用了图/表的句子** ＋ 紧随其后的 ``FIGURE_SENTENCE_WINDOW - 1`` 句（去重、保序）。"""
    ss = [s.strip() for s in _SENT_SPLIT.split(str(text or "")) if s.strip()]
    out: list[str] = []
    for i, s in enumerate(ss):
        if not figure_refs(s):
            continue
        for nxt in ss[i:i + FIGURE_SENTENCE_WINDOW]:
            if nxt not in out:
                out.append(nxt)
    return out


def figure_text_of(text: str) -> str:
    """图句拼接（＝**判"只落在图里"用的文本**）。"""
    return "\n".join(figure_sentences(text))


def non_figure_text(text: str) -> str:
    """去掉图句后的正文（＝还能被当作事实句/题目依据的正文）。"""
    drop = set(figure_sentences(text))
    keep = [s for s in _SENT_SPLIT.split(str(text or "")) if s.strip() and s.strip() not in drop]
    return "\n".join(keep)


def draft_materials(db, subject_id: str, *, max_chars: int | None = None,
                    batch_chars: int | None = None,
                    inject_max_chars: int | None = None) -> dict:
    """D1（R36）＋ S1/S2/S8（R37）＋ **R38 S1/S2/S3/S4**：大纲起草的**材料注入包**（唯一入口）。

    返回:
    - ``text``：**首批**注入 prompt 的材料块（多批时见 ``batches``）；
    - ``index``：``[{id,title,source,url,body,sections,structure,text_health,role}]``
      ——**服务端校验用**（含正文与章/节地图，不下发前端）；
    - ``chapter_map``：整本书的章 → 节地图（**跨全部材料合并**；每条注明来自哪份材料）；
    - ``batches``：结构化分批（每批 ``text`` 完整可注入；按章/页边界切，**绝不截断句子**）；
    - ``used_chars``：全部批次注入的字符总量（**随书规模增长**；=0 时确实不限）；
    - ``per_call_chars``：**单次调用**的注入预算（生效值）；
    - ``budget``：``{batch_chars, inject_max_chars, batch_source, inject_source}``
      ——两个滑块的**生效值与来源**（"你设定的"/"默认"，R38 A1 必显）；
    - ``usage``：``{used_chars, batches, per_material:[…], blocked, truncated, dropped, order_basis}``
      ——**上一轮实际注入总量与批次数** + 逐材料吸纳明细（R38 A1/B1）；
    - ``dropped``：**恒为空**（R37/R38 §3 ＋ R39 铁则：**任何情况都不得静默丢材料/章节**）；
    - ``blocked``：健康度不合格（扫描/图片版）而被挡下的材料 ``[{title, note}]``（S7）；
    - ``ledger``：本次就地账目（**就地提示**通道；同时已落总账）。

    预算纪律（R37＋R38 §3 ＋ **R42 A**）：
    - **滑块 A（单次调用预算）**：默认不省成本，书太大按 ``MF_MATERIAL_BATCH_CHARS`` 在章/页边界
      分批；**调小只分更多批，绝不丢章节**（``dropped`` 恒空、覆盖账不变）；
    - **滑块 B（总注入上限 `MF_MATERIAL_INJECT_MAX_CHARS`）**：**真硬上限**（R41 §3-① 裁定）——
      跨批次累计注入字符，到顶后**在章/节边界停止**，剩余章节**整条不注入**，
      每一处未注入都进账本（中文原因）+ 进 ``usage.not_injected``（``reason=总注入上限``）；
      默认 0 = 不限，此时**行为与 R38 逐字一致**；
    - R38 A4 安全阀：按"字符 ≈ token"粗估，若**将超过模型上下文窗口** → 不硬发，改为**自动分批**
      并中文说明"本书较大，已分 N 批处理"（**任何情况不得静默失败**）。
    """
    from ..service import ledger

    budget = resolve_budget(db, subject_id, batch_chars=batch_chars,
                            inject_max_chars=(inject_max_chars if inject_max_chars is not None
                                              else max_chars))
    max_chars = int(budget["inject_max_chars"])
    per_call = int(budget["per_call_chars"])
    batch_chars = int(budget["batch_chars"])
    index = _ordered(_material_index(db, subject_id))
    blocked = [{"title": m["title"], "note": m["text_health"]["note"]}
               for m in index if not m["text_health"]["healthy"]]
    for b in blocked:  # R39 §1：被挡下的材料**必须显性**（不是只在 prompt 里提一句）
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{b['title']}》",
            "这份材料没读（看起来是扫描件或图片版，程序读不到里面的文字）：" + str(b["note"] or ""),
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "material_blocked", "title": b["title"]},
        )
    blocks = _full_blocks(index)
    # **R55 B：图示不可用要显式认输**——有块引用了图/表（系统读不到图片）→ 记账（中文原因 + 影响面）
    for m in index:
        mine = [b for b in blocks if b.get("material_id") == m["id"] and b.get("figure_refs")]
        if not mine:
            continue
        refs: list[str] = []
        for b in mine:
            for r in b["figure_refs"]:
                if r not in refs:
                    refs.append(r)
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{m['title']}》· 图示不可用",
            f"这份材料里有 {len(mine)} 段在引用图/表（{'、'.join(refs[:5])}），"
            "系统只能读文字、读不到图片——这些段落会明确标注，且**不会**被当作事实句/题目的依据",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "figure_unavailable", "title": m["title"],
                    "marked_entries": [b["label"] for b in mine],
                    "figure_refs": refs[:12]},
        )
    # R38 A4 安全阀：单次调用预算再受"模型上下文硬上限"约束（超了自动分批，不硬发）
    valve = context_valve(db, batch_chars=per_call, blocks=blocks)
    if valve["applied"]:
        ledger.note(
            ledger.CAT_MATERIAL, "材料注入（安全阀）",
            f"本书较大，已分 {valve['batch_count']} 批处理：按「字符≈token」粗估，"
            f"单次调用最多 ~{valve['limit_chars']} 字（模型上下文硬上限 {valve['context_tokens']} token），"
            "不截断正文、不漏章节",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
            detail={"kind": "context_valve", **{k: valve[k] for k in
                                                ("limit_chars", "context_tokens", "batch_count")}},
        )
    batches = valve["batches"]
    # **R42 A：滑块 B「总注入上限」＝真硬上限**（架构侧 R41 §3-①）——
    # 跨批次累计到顶后**在章/节边界停止**，剩余章节整条不注入；每一处未注入都记账 + 进 not_injected。
    # ⚠️ cap=0（默认/不限）时不改变任何行为（与 R38 逐字一致）。
    batches, cap_skipped, cap_info = _apply_inject_cap(batches, max_chars, subject_id)
    if cap_info["configured"]:
        _note_inject_cap_skips(cap_skipped, index, cap_info, subject_id)
    used = sum(len(b["text"]) for b in batches)
    # R38 B1：任何**未被注入**的章/节都显式列出（含健康度挡下、未进批次、**因总上限跳过**三种原因）
    unmapped = _unmapped_entries(index, blocks) + _cap_skip_entries(cap_skipped, index)
    for u in unmapped:
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{u['material']}》· {u['label']}",
            (u.get("reason_zh") or "这一章/节没读（它没有出现在任何一次读取里）")
            + ("：" + str(u.get("note") or "") if u.get("note") else ""),
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "entry_not_injected", **u},
        )
    if not index:
        ledger.note(ledger.CAT_MATERIAL, "材料注入", "本学科没有引用材料：本次按 brief 起草（无教材依据）",
                    impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                    detail={"kind": "no_material"})
    per_material = _per_material_usage(index, batches)
    cap_detail = {
        "configured": bool(cap_info.get("configured")),
        "cap": int(cap_info.get("cap") or 0),
        "used_chars": int(cap_info.get("used_chars") or 0),
        "remaining": int(cap_info.get("remaining") or 0),
        # **R42 A3-⑤：预算视图必须能显示"因总上限未注入的章节数"**（不许两处都没有）
        "skipped_count": int(cap_info.get("skipped_count") or 0),
        "skipped_batches": int(cap_info.get("skipped_batches") or 0),
        "skipped_chars": int(cap_info.get("skipped_chars") or 0),
        "skipped_labels": list(cap_info.get("skipped_labels") or []),
        "first_batch_over_cap": bool(cap_info.get("first_batch_over_cap")),
        "skipped_by_material": _cap_skips_by_material(cap_skipped, index),
    }
    usage = {
        "used_chars": used, "batches": len(batches),
        "injected_chars_per_batch": [len(b["text"]) for b in batches],
        "per_material": per_material,
        "blocked": blocked, "not_injected": unmapped,
        "truncated": False, "dropped": [],
        "order_basis": order_basis(index),
        "inject_cap": cap_detail,
        "context_valve": {"applied": bool(valve["applied"]), "limit_chars": valve["limit_chars"],
                          "context_tokens": valve["context_tokens"]},
    }
    pack = {"text": batches[0]["text"] if batches else "", "used_chars": used,
            "dropped": [], "truncated": False, "batches": batches, "blocked": blocked,
            "per_call_chars": int(budget["per_call_chars"]), "batch_count": len(batches),
            "budget": budget, "usage": usage,
            "ledger": ledger.current().to_list() if ledger.current() else []}
    pack.update({
        "index": index,
        "chapter_map": [{"material_id": m["id"], "material": m["title"],
                         "role": m.get("role") or (ROLE_MAIN if m.get("role_explicit") else ROLE_UNSET),
                         "role_explicit": bool(m.get("role_explicit")),
                         "kind": m["structure"]["kind"], "note": m["structure"]["note"],
                         "entries": m["structure"]["chapter_map"]} for m in index],
        "count": len(index),
        "inject_max_chars": max_chars,
        "batch_chars": batch_chars,
    })
    return pack


ROLE_MAIN = "main"                # 主教材（定顺序与范围）
ROLE_SUPPLEMENT = "supplement"    # 补充材料（只补细节与例题）
ROLE_UNSET = ""                   # 未标注（**不等于主教材**：按导入顺序，覆盖账注明）
ROLES = (ROLE_MAIN, ROLE_SUPPLEMENT)
ROLE_LABELS_ZH = {ROLE_MAIN: "主教材", ROLE_SUPPLEMENT: "补充材料", ROLE_UNSET: "未标注"}

# **R56 第 3 步**：材料来源模式（路径③＝图示教材 / 全 AI 模式；空 = 文字教材路径）
MODE_ALL_AI = "all_ai"
MODE_LABELS_ZH = {MODE_ALL_AI: "图片为主的教材（全程交给 AI 判断）", "": ""}
MODE_ENTRY_ZH = "图片为主的教材（全程交给 AI 判断）"


def subject_mode(db, subject_id: str) -> str:
    """该学科当前的来源模式：``all_ai``（图示教材）或 ``""``（文字教材）。

    口径：**只要该学科有 all_ai 材料**就算本模式（一个学科一种模式，避免两条口径打架）。
    学习会话 / 判题 / 评分据此走本模式分支（工单 §3-A 的"模式隔离"）。
    """
    for e in _entries_with_body(subject_id):
        if str(e.get("mode") or "") == MODE_ALL_AI:
            return MODE_ALL_AI
    return ""


def mode_entry_zh() -> dict:
    """导入处给用户看的**诚实边界**（工单 §2：这段比功能本身重要）。"""
    return {
        "label": MODE_ENTRY_ZH,
        "what_zh": ("把教材**每页的图片**交给 AI，由它自己读、自己出题、自己判、自己评。"
                    "程序只负责：流程顺序、提示词、把图片递过去、把每次结果原样记下来。"),
        "costs_zh": [
            "**没有独立的第二次核对**：判对错、评分都是模型的判断，程序不替你复核（数学题也一样）；",
            "**失败了不容易发现**：这类模型的错法更像「说得很有把握但其实不对」，而不是明显乱答；",
            "**更贵**：每一步都要问模型（实测一页约 0.002~0.004 元，一本书逐页读一遍约 0.3~0.6 元）。",
        ],
        "pros_zh": ("长处是**能看图、能读公式和版式**；但程序没法逐字核对引用，"
                    "依据只能记到「第几页/哪张图」。"),
        "not_better_zh": "它不比文字教材模式更可靠——只是「读得到图，但没人替你把关」。",
        "need_images_zh": ("要的是**页面图片**（PNG/JPEG/WebP）："
                           "实测 DeepSeek 的接口只收图片，**PDF 文件本身它不收**。"),
    }

BATCH_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
INJECT_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
BUILTIN_BATCH_CHARS = 60000       # A5 内置默认：单次调用预算
BUILTIN_INJECT_MAX_CHARS = 0      # A2 内置默认：总注入上限＝不限（0）


def _env_int(name: str) -> int | None:
    """环境变量里的非负整数（未设/非法 → None，**不静默当 0**）。"""
    import os

    raw = os.getenv(name)
    if raw in (None, ""):
        return None
    try:
        v = int(str(raw).strip())
    except ValueError:
        return None
    return max(0, v)


def subject_budget(db, subject_id: str) -> dict:
    """学科（滑块）里显式设过的值；``source`` ∈ subject / env / builtin。"""
    row = outline_store.get_subject(db, subject_id)
    meta = dict((row.meta_json if row is not None else None) or {})
    out: dict = {"batch_chars": None, "inject_max_chars": None, "source": "builtin"}
    b = meta.get("material_batch_chars")
    i = meta.get("material_inject_max_chars")
    if b is not None and str(b) != "":
        try:
            out["batch_chars"] = max(0, int(b))
        except (TypeError, ValueError):
            out["batch_chars"] = None
    if i is not None and str(i) != "":
        try:
            out["inject_max_chars"] = max(0, int(i))
        except (TypeError, ValueError):
            out["inject_max_chars"] = None
    if out["batch_chars"] is not None or out["inject_max_chars"] is not None:
        out["source"] = "subject"
    return out


def resolve_budget(db, subject_id: str, *, batch_chars: int | None = None,
                   inject_max_chars: int | None = None) -> dict:
    """A5 优先级：**单次请求参数 > 学科滑块 > .env > 内置默认**（逐项解析，来源可查）。

    返回 ``{batch_chars, inject_max_chars, per_call_chars, batch_source, inject_source}``。
    非法值（负数以外的怪值）由 API 层转**中文 422**；这里只做兜底解析（负 → 0）。
    """
    subj = subject_budget(db, subject_id)
    env_b = _env_int("MF_MATERIAL_BATCH_CHARS")
    env_i = _env_int("MF_MATERIAL_INJECT_MAX_CHARS")
    if env_i is None:
        env_i = _env_int("MF_OUTLINE_MATERIAL_MAX_CHARS")
    if batch_chars is not None:
        eff_b, src_b = max(0, int(batch_chars)), "request"
    elif subj["batch_chars"] is not None:
        eff_b, src_b = int(subj["batch_chars"]), "subject"
    elif env_b is not None:
        eff_b, src_b = env_b, "env"
    else:
        eff_b, src_b = BUILTIN_BATCH_CHARS, "builtin"
    if inject_max_chars is not None:
        eff_i, src_i = max(0, int(inject_max_chars)), "request"
    elif subj["inject_max_chars"] is not None:
        eff_i, src_i = int(subj["inject_max_chars"]), "subject"
    elif env_i is not None:
        eff_i, src_i = env_i, "env"
    else:
        eff_i, src_i = BUILTIN_INJECT_MAX_CHARS, "builtin"
    # R38 §3 共存口径：**单次调用预算**与**总注入上限**是两个概念——
    # - 单次调用预算 = 滑块 A（批量阈值）；A=0（不限）时再退回总上限；
    # - 总注入上限（滑块 B / 显式 env，>0）= **跨批次的累计上限**（见 ``draft_materials`` 的
    #   ``remaining`` 递减），R38 A1 说它是"想设花费天花板的用户"用的；
    # - ⚠️ 滑块 A **不得为了让总上限生效而被放大**：A=0 是"不限"，不是"每次装 60000"。
    if eff_b > 0:
        per_call = eff_b if eff_i <= 0 else min(eff_i, eff_b)
    else:
        per_call = eff_i  # A=不限 → 由 A4 安全阀兜底
    return {
        "batch_chars": eff_b, "inject_max_chars": eff_i, "per_call_chars": per_call,
        "batch_source": src_b, "inject_source": src_i,
        "batch_source_zh": SOURCE_LABELS_ZH.get(src_b, src_b),
        "inject_source_zh": SOURCE_LABELS_ZH.get(src_i, src_i),
    }


SOURCE_LABELS_ZH = {
    "request": "本次操作临时设的",
    "subject": "你设定的（本学科）",
    "env": "配置文件里设的",
    "builtin": "默认",
}


def set_budget(db, subject_id: str, *, batch_chars: int | None = None,
               inject_max_chars: int | None = None) -> dict:
    """写入学科滑块（复用 ``subjects.meta_json``，**不新建表**）；非法值 → ``OutlineError``（中文 422）。"""
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    meta = dict(row.meta_json or {})
    if batch_chars is not None:
        meta["material_batch_chars"] = _validate_budget("单次调用预算", batch_chars)
    if inject_max_chars is not None:
        meta["material_inject_max_chars"] = _validate_budget("总注入上限", inject_max_chars)
    row.meta_json = meta
    db.commit()
    from ..service import ledger

    ledger.note(
        ledger.CAT_MATERIAL, f"材料注入预算（学科 {subject_id}）",
        "用户调整了材料注入预算滑块：单次调用预算="
        + _budget_zh(meta.get("material_batch_chars")) + "，总注入上限="
        + _budget_zh(meta.get("material_inject_max_chars"))
        + "。调小单次预算**只是分成更多批，不会少学章节**（覆盖账不变）",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"batch_chars": meta.get("material_batch_chars"),
                "inject_max_chars": meta.get("material_inject_max_chars")},
    )
    return budget_view(db, subject_id)


def _validate_budget(label: str, value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise OutlineError(f"{label}非法：{value!r}（必须是整数，单位＝字符；0 = 不限）") from e
    if v < 0:
        raise OutlineError(f"{label}非法：{v}（不能为负数；0 = 不限）")
    if v > 5_000_000:
        raise OutlineError(f"{label}非法：{v}（上限 5,000,000 字符；0 = 不限）")
    return v


def _budget_zh(v) -> str:
    if v is None or str(v) == "":
        return "（未设，用默认）"
    return "不限" if int(v) == 0 else f"{int(v):,} 字符"


def budget_view(db, subject_id: str) -> dict:
    """R38 A1 必显数据（**R42 A3-⑤ 增补**）：两档当前值 + 来源 + 上一轮实际注入总量/批次数
    + **因总注入上限未注入的章节数** + 逐材料明细。

    ⚠️ **两个滑块的承诺不同**（R42 A1，界面必须分开写清）：
    滑块 A 调小只是分更多批（不丢章节）；滑块 B 是**真上限**（超了就真的不注入，但明说哪些没进去）。
    """
    eff = resolve_budget(db, subject_id)
    index = _material_index(db, subject_id)
    blocks = _full_blocks(index)
    valve = context_valve(db, batch_chars=int(eff["per_call_chars"]), blocks=blocks)
    keep, skipped, cap = _apply_inject_cap(valve["batches"], int(eff["inject_max_chars"]), subject_id)
    used = sum(len(b["text"]) for b in keep)
    row = outline_store.get_subject(db, subject_id)
    meta = dict((row.meta_json if row is not None else None) or {})
    return {
        "subject_id": subject_id,
        "batch_chars": {"value": int(eff["batch_chars"]), "source": eff["batch_source"],
                        "source_zh": eff["batch_source_zh"],
                        "set": meta.get("material_batch_chars")},
        "inject_max_chars": {"value": int(eff["inject_max_chars"]), "source": eff["inject_source"],
                             "source_zh": eff["inject_source_zh"],
                             "set": meta.get("material_inject_max_chars")},
        "per_call_chars": int(eff["per_call_chars"]),
        "tiers": {
            "batch": [{"label": lb, "value": v} for lb, v in BATCH_TIERS],
            "inject": [{"label": lb, "value": v} for lb, v in INJECT_TIERS],
        },
        # R42 A1：两个滑块各自的承诺（前端直接渲染，**不许**一句话糊两个滑块）
        # **R52 B**：改成用户能看懂的人话（不再出现"注入/批次/覆盖账/丢弃"这类词）
        "promises_zh": {
            "batch_chars": "一次读不完就分成几次读，**一章都不会少**。",
            "inject_max_chars": "**读到上限就停**，没读到的章节都会明确列出来。",
        },
        "last_usage": {
            "used_chars": used,
            "batch_count": len(keep),
            "per_material": _per_material_usage(index, keep, skipped),
            "truncated": False,
            "dropped": [],
            "order_basis": order_basis(index),
            "summary_zh": (f"共读了 {used:,} 字，分 {len(keep)} 次"
                           if keep else "还没有可读的教材"),
            # R42 A2：因总注入上限未注入的章节数（**不许两处都没有**）
            "cap_skipped_count": int(cap.get("skipped_count") or 0),
            "cap_skipped_labels": list(cap.get("skipped_labels") or []),
            "cap_skipped_by_material": _cap_skips_by_material(skipped, index),
            "note_zh": "调小只是分成几次读，**一章都不会少**。",
            "cap_note_zh": (
                f"总量已经读完，还有 {int(cap.get('skipped_count') or 0)} 章/节**没读**（下方向你列明）"
                if int(cap.get("skipped_count") or 0) else ""),
        },
        "inject_cap": {
            "configured": bool(cap.get("configured")),
            "cap": int(cap.get("cap") or 0),
            "used_chars": int(cap.get("used_chars") or 0),
            "remaining": int(cap.get("remaining") or 0),
            "skipped_count": int(cap.get("skipped_count") or 0),
            "skipped_chars": int(cap.get("skipped_chars") or 0),
            "skipped_labels": list(cap.get("skipped_labels") or []),
            "skipped_by_material": _cap_skips_by_material(skipped, index),
            "first_batch_over_cap": bool(cap.get("first_batch_over_cap")),
        },
        "context_valve": {"applied": bool(valve["applied"]), "context_tokens": valve["context_tokens"],
                          "limit_chars": valve["limit_chars"]},
        "materials": [{"id": m["id"], "title": m["title"], "role": m.get("role") or ROLE_UNSET,
                       "role_explicit": bool(m.get("role_explicit")),
                       "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
                       "healthy": m["text_health"]["healthy"], "chars": len(m.get("body") or ""),
                       "entries": len((m["structure"] or {}).get("entries") or []),
                       "note": m["text_health"]["note"]} for m in index],
        "not_injected": _unmapped_entries(index, blocks) + _cap_skip_entries(skipped, index),
    }


def set_material_role(db, subject_id: str, material_id: str, role: str) -> dict:
    """R38 B2：标主教材 / 补充材料（写入材料 frontmatter；主教材定顺序与范围）。"""
    if role not in ROLES:
        raise OutlineError(f"材料角色非法：{role!r}（∈ {ROLES}）")
    d = materials_dir(subject_id)
    hit = None
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e and e["id"] == material_id:
            hit = (p, e)
            break
    if hit is None:
        raise OutlineError(f"材料不存在: {material_id}")
    p, _ = hit
    raw = p.read_text(encoding="utf-8")
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        head = raw[4:end]
        body = raw[end + 4:]
        lines = [ln for ln in head.splitlines() if not ln.strip().startswith("role:")]
        lines.append(f"role: {role}")
        p.write_text("---\n" + "\n".join(lines) + "\n---" + body, encoding="utf-8")
    from ..service import ledger

    ledger.note(ledger.CAT_MATERIAL, f"材料《{hit[1]['title']}》",
                f"用户把该材料标为「{ROLE_LABELS_ZH[role]}」"
                + ("（主教材定顺序与范围）" if role == ROLE_MAIN else "（只补细节与例题）"),
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                detail={"material_id": material_id, "role": role})
    return {"material_id": material_id, "role": role, "role_zh": ROLE_LABELS_ZH[role]}


def order_basis(index: list[dict]) -> str:
    """R38 B2：顺序依据——有显式角色按角色（主教材在前），否则按**导入顺序**并注明。"""
    if any(m.get("role_explicit") for m in index):
        return "角色（主教材定顺序与范围，补充材料只补细节与例题）"
    return "导入顺序"


def _ordered(index: list[dict]) -> list[dict]:
    """按"主教材在前 + 导入顺序"排序（无显式角色 → 纯导入顺序，不改行为）。"""
    if not any(m.get("role_explicit") for m in index):
        return list(index)
    return sorted(index, key=lambda m: 0 if (m.get("role_explicit") and m.get("role") == ROLE_MAIN) else 1)


def _per_material_usage(index: list[dict], batches: list[dict],
                        skipped: list[dict] | None = None) -> list[dict]:
    """逐材料吸纳明细（注入了多少字 / 几批 / 哪些章进了批次 / **哪些因总上限被跳过**）。"""
    label_to_material: dict[str, str] = {}
    for m in index:
        for e in (m["structure"] or {}).get("entries") or []:
            label_to_material[str(e.label)] = m["title"]
    batch_of: dict[str, set[int]] = {m["title"]: set() for m in index}
    for i, b in enumerate(batches):
        for lab in b.get("labels") or []:
            title = label_to_material.get(str(lab))
            if title:
                batch_of.setdefault(title, set()).add(i + 1)
    skipped_of: dict[str, list[str]] = {m["title"]: [] for m in index}
    for b in skipped or []:
        for src in _block_sources(b):
            title = str(src.get("material") or "")
            if not title:
                title = label_to_material.get(str(src.get("label") or ""), "")
            if title:
                skipped_of.setdefault(title, []).append(str(src.get("label") or ""))
    out = []
    for m in index:
        ent = (m["structure"] or {}).get("entries") or []
        chars_total = len(m.get("body") or "")
        skipped_labels = skipped_of.get(m["title"]) or []
        # **R55 B**：这份材料里"引用了图/表"的章/节（界面据此告诉用户"哪些段落读不到图"）
        fig_entries = [str(e.label) for e in ent if figure_refs(str(e.text or ""))]
        out.append({
            "material_id": m["id"], "title": m["title"],
            "role": m.get("role") or ROLE_UNSET,
            "role_explicit": bool(m.get("role_explicit")),
            "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
            "chars_total": chars_total,
            "entries_total": len(ent),
            "entries_chars_total": sum(int(e.chars) for e in ent),
            "batches": sorted(batch_of.get(m["title"]) or []),
            "injected": m["text_health"]["healthy"] and not skipped_labels,
            "blocked_reason": "" if m["text_health"]["healthy"] else m["text_health"]["note"],
            # R42：因**总注入上限**跳过的章/节（按材料分组，供界面就地展示）
            "cap_skipped": skipped_labels,
            "cap_skipped_count": len(skipped_labels),
            # **R55 A/B**：抽取体检（三档 + 图片数）+ 图示不可用清单
            "health_grade": str(m["text_health"].get("grade") or ""),
            "health_summary_zh": str(m["text_health"].get("summary_zh") or ""),
            "image_count": int((m["text_health"].get("extract") or {}).get("images") or 0),
            "figure_unavailable": fig_entries,
            "figure_unavailable_count": len(fig_entries),
        })
    return out


def _unmapped_entries(index: list[dict], blocks: list[dict]) -> list[dict]:
    """**未被注入任何批次**的章/节（R38 B1：必须显式列出，不许只在 prompt 尾部提一句）。"""
    in_blocks = {(str(b.get("material_id") or ""), str(b.get("label") or "")) for b in blocks}
    out: list[dict] = []
    for m in index:
        if not m["text_health"]["healthy"]:
            out.append({"material": m["title"], "material_id": m["id"],
                        "label": "（整份材料）", "chars": len(m.get("body") or ""),
                        "note": "这份材料像扫描件/图片版，读不到文字，整份没读"})
            continue
        for e in (m["structure"] or {}).get("entries") or []:
            if (str(m["id"]), str(e.label)) not in in_blocks:
                out.append({"material": m["title"], "material_id": m["id"], "label": e.label,
                            "chars": int(e.chars), "note": "该章/节未进入任何注入批次"})
    return out


def estimate_tokens(chars: int) -> int:
    """R38 A4：按「字符 ≈ token」粗估（保守口径——宁可不发也不发不可能成功的请求）。"""
    return max(0, int(chars or 0))


def context_valve(db, *, batch_chars: int, blocks: list[dict]) -> dict:
    """R38 A4 **安全阀**：单次调用不得越过模型上下文硬上限；超了自动分批 + 中文说明。

    返回 ``{"applied", "limit_chars", "context_tokens", "batches", "batch_count"}``。
    - 有效预算 = ``min(用户单次预算, 上下文可容纳字符)``（0/不限 → 取上下文可容纳量）；
    - 单块自身仍超上限时：先在**页边界**切（``bookmap.split_entries``，不切断句子）；
      仍超 → 自成一批并**记账**（"单章超上下文"），绝不静默截断。
    """
    s = get_settings()
    ctx = max(0, int(getattr(s, "context_token_limit", 0) or 0))
    # 预留：prompt 模板 + 地图 + 输出（按上下文 45% 或固定 8k 中取小，避免把窗口吃满）
    reserve = min(max(2048, ctx // 5), 40000) if ctx else 0
    limit = max(0, ctx - reserve) if ctx else 0
    applied = False
    eff_batch = int(batch_chars or 0)
    if ctx and limit and (eff_batch <= 0 or eff_batch > limit):
        eff_batch = limit
        applied = True
    blocks2 = list(blocks)
    oversized: list[dict] = []
    if ctx and limit:
        from . import bookmap

        split: list[dict] = []
        for b in blocks2:
            if len(str(b.get("text") or "")) <= limit:
                split.append(b)
                continue
            parts = _split_block_at_pages(b, limit)
            if parts:
                split.extend(parts)
                applied = True
            else:
                oversized.append(b)
                split.append(b)
        blocks2 = split
    batches = _make_batches(blocks2, eff_batch)
    if oversized:
        from ..service import ledger

        for b in oversized[:5]:
            ledger.note(
                ledger.CAT_MATERIAL, f"材料《{b.get('material', '')}》· {b.get('label', '')}",
                f"该章/节自身约 {len(str(b.get('text') or '')):,} 字，超过单次调用上下文硬上限"
                f"（~{limit:,} 字）：已**独立成批**（不截断、不丢弃），建议调大模型上下文或拆分该章",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM,
                detail={"kind": "block_over_context", "chars": len(str(b.get("text") or "")),
                        "limit": limit},
            )
    return {"applied": applied, "limit_chars": limit, "context_tokens": ctx,
            "batches": batches, "batch_count": len(batches),
            "oversized_blocks": len(oversized)}


def _split_block_at_pages(block: dict, limit: int) -> list[dict]:
    """把超上限的块在**页边界**切成多块（不截断句子）；页结构对不上 → 返回空（调用方另行记账）。"""
    from . import bookmap

    pages = bookmap.PAGE_MARK.findall(str(block.get("text") or ""))
    if len(pages) <= 1:
        return []
    entry = bookmap.MapEntry(label=str(block.get("label") or ""),
                             text=str(block.get("text") or ""),
                             pages=[f"第 {n} 页" for n in pages])
    parts = bookmap.split_entries([entry], max_chars=limit)
    if len(parts) <= 1:
        return []
    return [{"material": block.get("material", ""), "material_id": block.get("material_id", ""),
             "label": p.label, "text": f"#### [{p.label}]（材料《{block.get('material', '')}》）\n{p.text}",
             "chars": p.chars} for p in parts]


def _apply_inject_cap(batches: list[dict], inject_max_chars: int,
                      subject_id: str) -> tuple[list[dict], list[dict], dict]:
    """**R42 A（架构侧 R41 §3-① 裁定）**：滑块 B「总注入上限」＝**真硬上限**。

    与滑块 A 的承诺**不同**（这是本批最重要的一句话）：

    - **滑块 A（单次调用预算）**：调小 → 只是分更多批，**绝不丢章节**（``dropped`` 恒空、覆盖账不变）；
    - **滑块 B（总注入上限）**：**是真上限**——跨批次累计正文注入字符，到达上限后**在章/节边界停止**，
      剩余章节**整条不注入**；但**每一处未注入都必须在账本里有中文原因 + 覆盖账显式列出**
      （不许静默截断、不许"名不副实地不封顶"）。

    口径：
    - 累计量＝已装入批次的 ``len(text)`` 之和（跨批次递增）；
    - 触顶后**不再装入**后续批次——按章/节边界整条停，**绝不在句子中间截断**；
    - 首批总是装入（单个章/节是原子单位；宁可不截断，也不"设了上限就一章都不给"）；
    - ``cap <= 0`` → 不限，**行为与 R38 逐字一致**（不动任何东西）。

    返回 ``(kept, skipped, info)``；``info`` 含 ``configured / cap / used_chars / remaining /
    skipped_count / skipped_chars / skipped_labels / first_batch_over_cap``。
    """
    cap = int(inject_max_chars or 0)
    if cap <= 0:
        return list(batches), [], {"configured": False, "cap": 0,
                                   "used_chars": sum(len(str(b.get("text") or "")) for b in batches),
                                   "remaining": -1, "skipped_count": 0, "skipped_chars": 0,
                                   "skipped_labels": [], "first_batch_over_cap": False}
    kept: list[dict] = []
    skipped: list[dict] = []
    used = 0
    for b in batches:
        blen = len(str(b.get("text") or ""))
        # 首批无条件装入（章/节是原子单位：宁可不截断，也不"一章都不给"）
        if not kept or used + blen <= cap:
            kept.append(b)
            used += blen
            continue
        skipped.append(b)
    skipped_chars = sum(len(str(b.get("text") or "")) for b in skipped)
    skipped_labels = [_block_labels(b) for b in skipped]
    skipped_labels = [lb for group in skipped_labels for lb in group]
    first_over = bool(kept) and used > cap
    info = {"configured": True, "cap": cap, "used_chars": used,
            "remaining": max(0, cap - used), "skipped_count": len(skipped_labels),
            "skipped_batches": len(skipped), "skipped_chars": skipped_chars,
            "skipped_labels": skipped_labels, "first_batch_over_cap": first_over}
    return kept, skipped, info


def _block_labels(block: dict) -> list[str]:
    """块/批次的标签集合（批次用 ``labels``，单块用 ``label``）。"""
    labels = [str(x) for x in (block.get("labels") or [])]
    if not labels and block.get("label"):
        labels = [str(block.get("label"))]
    return labels


def _cap_skip_entries(skipped: list[dict], index: list[dict]) -> list[dict]:
    """被总注入上限**跳过**的章/节（逐条给中文原因，进 ``not_injected`` 与账本）。"""
    by_id = {str(m["id"]): m for m in index}
    out: list[dict] = []
    for b in skipped:
        for src in _block_sources(b):
            mid = str(src.get("material_id") or "")
            m = by_id.get(mid) or {}
            out.append({
                "material": str(src.get("material") or m.get("title") or ""),
                "material_id": mid,
                "label": str(src.get("label") or ""),
                "chars": int(src.get("chars") or 0),
                "reason": "总注入上限",
                "reason_zh": "已经到「最多读多少」的上限了，这一章/节没读",
                "note": "这一章/节因为到了总量上限而**没读**（到上限时整章停下，不会把一段话读一半）",
            })
    return out


def _cap_skips_by_material(skipped: list[dict], index: list[dict]) -> list[dict]:
    """因总注入上限跳过的章节，**按材料分组**（覆盖账/预算视图用；R42 A2/A3）。"""
    by_id = {str(m["id"]): m for m in index}
    buckets: dict[str, dict] = {}
    for b in skipped:
        for src in _block_sources(b):
            mid = str(src.get("material_id") or "")
            title = str(src.get("material") or (by_id.get(mid) or {}).get("title") or "")
            bucket = buckets.setdefault(mid, {"material_id": mid, "title": title, "items": []})
            bucket["items"].append({"label": str(src.get("label") or ""),
                                    "chars": int(src.get("chars") or 0),
                                    "reason_zh": "已经到「最多读多少」的上限了，这一章/节没读"})
    return list(buckets.values())


def _note_inject_cap_skips(skipped: list[dict], index: list[dict], info: dict,
                           subject_id: str) -> None:
    """R42 A2：**每一处未注入都写一条中文账目**（不是只写一条汇总）。"""
    from ..service import ledger

    cap = int(info.get("cap") or 0)
    if info.get("first_batch_over_cap"):
        ledger.note(
            ledger.CAT_MATERIAL, "材料注入（总注入上限）",
            f"你设定的总注入上限 {cap:,} 字**小于第一章/节本身**：为不截断正文，首批仍整章注入"
            f"（实际 {int(info.get('used_chars') or 0):,} 字，超出 {max(0, int(info.get('used_chars') or 0) - cap):,} 字）——"
            "请调大上限或设 0（不限），或改用「单次调用预算」分更多批（那样不会少学章节）",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "inject_cap_first_over", "cap": cap,
                    "used_chars": int(info.get("used_chars") or 0)},
        )
    entries = _cap_skip_entries(skipped, index)
    for e in entries:
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{e['material']}》· {e['label']}",
            f"总注入上限 {cap:,} 字已用完，**本章/节未注入**（已注入 {int(info.get('used_chars') or 0):,} 字）——"
            "按章/节边界整条停止，**未在句中截断**；调大上限或设 0（不限）后重新起草即可全部纳入",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "inject_cap_skipped", "cap": cap, "label": e["label"],
                    "material": e["material"], "chars": e["chars"]},
        )


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
    materials = sorted({b["material"] for b in blocks})
    return {"text": text, "used_chars": len(text),
            "labels": [b["label"] for b in blocks],
            "materials": materials,
            # R42 A：批次保留"主要来源材料"（单材料批直给；跨材料批给材料列表）
            # ——用于「因总注入上限未注入」按材料分组（R42 A2/A3 的界面口径）。
            "material": materials[0] if len(materials) == 1 else "、".join(materials),
            "material_ids": sorted({str(b.get("material_id") or "") for b in blocks}),
            "blocks": [{"material": b["material"], "material_id": b.get("material_id", ""),
                        "label": b["label"], "chars": len(str(b.get("text") or ""))}
                       for b in blocks]}


def _block_sources(block: dict) -> list[dict]:
    """批次（或单块）里的**逐块来源**：``[{material, material_id, label, chars}]``。"""
    src = block.get("blocks")
    if src:
        return [dict(x) for x in src]
    return [{"material": str(block.get("material") or ""),
             "material_id": str(block.get("material_id") or ""),
             "label": str(block.get("label") or ""),
             "chars": len(str(block.get("text") or ""))}]


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


def coverage_summary(units: list, index: list[dict], *,
                     min_entry_chars: int | None = None) -> dict:
    """覆盖摘要（供起草候选/大纲页显示）：``{total, covered, uncovered}``。

    **R42 B1**：``uncovered`` 口径修正——**过短条目**（< ``MF_MIN_ENTRY_CHARS``）若仍是缺口，
    归入 ``skipped_short``（"标为跳过/未成为单元"），**不计入 uncovered**（它不是"该覆盖却没覆盖"，
    而是"按规则跳过"）；两者都在返回值里显式列出，便于界面解释"它去哪了"。
    """
    mapping = _covered_entries(units, index)
    cap = _min_entry_chars(min_entry_chars)
    unmapped = [key for key, ids in mapping.items() if not ids]
    short = [key for key in unmapped if _entry_chars(index, key) < cap]
    short_set = set(short)
    real = [key for key in unmapped if key not in short_set]
    return {"total": len(mapping), "covered": len(mapping) - len(unmapped),
            "uncovered": [k[1] for k in real],
            "skipped_short": {"count": len(short), "labels": [k[1] for k in short],
                              "min_chars": cap},
            "short_entry_min_chars": cap}


def _unit_content_status(unit_id: str) -> dict:
    """**R54 C**：单元内容状态——**与会话守卫/覆盖账同一实现**（`service.outline_gate.unit_content_status`）。

    同源是硬要求（工单 §3）：大纲页显示的"有没有内容"必须与"能不能进学习会话"完全一致，
    不许两处口径打架。
    """
    try:
        from ..service import outline_gate

        return outline_gate.unit_content_status(unit_id)
    except Exception:
        return {"exists": False, "usable": False, "reason_zh": "内容状态暂时读不到",
                "missing": "content", "exercises": 0, "taught_facts": 0}


def _min_entry_chars(override: int | None = None) -> int:
    """过短条目阈值（R42 B1；默认取 ``MF_MIN_ENTRY_CHARS``=200）。"""
    if override is not None:
        return max(0, int(override))
    try:
        from ..config import get_settings

        return max(0, int(getattr(get_settings(), "min_entry_chars", 200) or 0))
    except Exception:
        return 200


def _entry_chars(index: list[dict], key: tuple[str, str]) -> int:
    """地图条目字数（``(material_id, label)`` → chars；找不到 → 很大值，视作**非**过短）。"""
    mid, label = key
    for m in index:
        if str(m.get("id")) != str(mid):
            continue
        for e in (m.get("structure") or {}).get("entries") or []:
            if str(e.label) == str(label):
                return int(getattr(e, "chars", 0) or 0)
    return 10 ** 9


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
                        or "这份教材像是扫描件或图片版，程序读不到文字"}
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
    # **R42 B4（提升项）**：把依据从"章节级"细化到"**章内该节**"——
    # R40 裁决 §2-3 原文："单元的 basis.quote 目前多为章节级引用 → 应改为章内该节的引用"。
    basis = _section_level_basis(healthy, picked, unit)
    # **R55 B**：把"引用了图/表的段落"标出来（注入给模型时加显式标注），并给出
    # ① ``clean_text``（去图段后仍可当依据的正文）② ``figure_text``（只含图段）
    # ——事实句/题目依据若只落在图段里 → 出稿端必须丢弃（不许猜）。
    marked_parts: list[str] = []
    clean_parts: list[str] = []
    figure_only_parts: list[str] = []
    figure_refs_all: list[str] = []
    figure_marked = 0
    for p in picked:
        annotated, refs, marked = annotated_entry_text(str(p["text"]))
        head = f"【教材段落：{p['label']}（材料《{p['material']}》）】"
        if refs:
            p["figure_refs"] = refs
            p["figure_marked"] = marked
            figure_marked += marked
            for r in refs:
                if r not in figure_refs_all:
                    figure_refs_all.append(r)
            marked_parts.append(f"{head}\n{annotated}")
            clean_parts.append(non_figure_text(str(p["text"])))
            # 只收"引用了图/表的那一句（＋紧随其后 1 句）"，**不是整章**、也不是整页
            figure_only_parts.append(figure_text_of(str(p["text"])))
        else:
            marked_parts.append(f"{head}\n{p['text']}")
            clean_parts.append(str(p["text"]))
    total_paras = sum(_paragraph_count(str(p["text"])) for p in picked)
    figure_only = bool(figure_refs_all) and figure_marked >= max(1, total_paras)
    text = "\n\n".join(marked_parts)
    return {"text": text, "entries": [p["label"] for p in picked], "sources": sources,
            "binding_text": binding, "covered": bool(picked), "no_materials": False,
            "note": "" if picked else "教材中未检索到与本节相关的章/节",
            # **R55 B**：图段信息（校验/展示用）——`figure_text` **只含图段**（段落级，不是整章）
            "figure_refs": figure_refs_all, "figure_marked": figure_marked,
            "figure_only": figure_only,
            "clean_text": "\n\n".join(clean_parts),
            "figure_text": "\n\n".join(t for t in figure_only_parts if t.strip()) or "",
            # 章内该节的依据（有则给：basis_section/basis_quote；无 → 空，出稿端不编造）
            "basis_section": basis.get("section", ""), "basis_quote": basis.get("quote", ""),
            "basis_note": basis.get("note", "")}


def _section_level_basis(healthy: list[dict], picked: list[dict], unit) -> dict:
    """**R42 B4**：在该单元对应条目**内部**再定位到"该节"，并取该节的**逐字引文**作为依据。

    两个来源（都不编造）：
    ① ``bookmap`` 目录级结构给出的 ``entry.sections``（章 → 节）；
    ② 条目正文里**行首节名**——**R42 B4** 数字编号（``1.1 太阳系的组成``）＋
       **R46 C** 中文序数（``第一节 恒星`` / ``第二讲 …``）；教材正文常自带这种节标题。
    只有节名与单元标题/概念标签**确定性匹配**（归一化相等或互相包含）时才给；
    否则返回空（宁缺勿造，与 R36 D2 / R37 S5 口径一致）。
    """
    from ..content import citations

    want = [citations.normalize(str(getattr(unit, "title", "") or ""))]
    want += [citations.normalize(str(t)) for t in (getattr(unit, "concept_tags", None) or [])]
    want = [w for w in want if len(w) >= 2]
    if not want:
        return {}
    best: dict = {}
    for m in healthy:
        labels = {str(p.get("label")) for p in picked if p.get("material") == m["title"]}
        for e in (m.get("structure") or {}).get("entries") or []:
            if labels and e.label not in labels:
                continue
            names = [str(s) for s in (e.sections or []) if str(s).strip()]
            names += [h for h in _body_section_headings(str(e.text or ""))
                      if h not in names]
            for sec in names:
                norm = citations.normalize(sec)
                if not norm:
                    continue
                if not any(norm == w or (len(norm) >= 4 and (norm in w or w in norm)) for w in want):
                    continue
                if best and len(norm) <= len(citations.normalize(best.get("section", ""))):
                    continue
                quote = _first_quote_sentence(str(e.text), sec)
                best = {"material": m["title"], "section": sec, "quote": quote,
                        "note": ("章内该节级依据（R42 B4）：条目《" + e.label + "》下的节「"
                                 + sec + "」" + ("；引文逐字取自该节" if quote
                                                 else "（该节正文内未取到合适引文，出稿端不编造）"))}
    return best


_ZH_ORD = "一二三四五六七八九十百"
# 行首节标题（**R42 B4** 数字编号 + **R46 C** 中文序数）：`1.1 太阳系的组成` / `第一节 恒星` / `第二讲 …`
# 中文序数只认 `第<一~九十九>[节讲课篇]` 这种**明确节标记**，不做任何模糊匹配（宁缺勿造）。
_HEADING_LINE = re.compile(
    rf"^\s*(\d{{1,2}}(?:\.\d{{1,2}}){{1,2}}|第[{_ZH_ORD}]{{1,3}}[节讲课篇])\s+(\S[^\n]{{0,60}})$")
# 用于"切到下一节前"的行首标题探测（与上面同一套形态）
_NEXT_HEADING = re.compile(
    rf"(?m)^\s*(?:\d{{1,2}}(?:\.\d{{1,2}}){{1,2}}|第[{_ZH_ORD}]{{1,3}}[节讲课篇])\s+\S")


def _body_section_headings(text: str) -> list[str]:
    """条目正文里**行首节标题**（``1.1 太阳系的组成`` / ``第一节 恒星``）——不确定则返回空表。"""
    out: list[str] = []
    for line in str(text or "").splitlines():
        m = _HEADING_LINE.match(line.strip())
        if m:
            out.append(f"{m.group(1)} {m.group(2).strip()}")
    return out


def _first_quote_sentence(text: str, section: str, *, min_chars: int = 20) -> str:
    """在**该节**的正文里取**逐字**一句作为引文（短句跳过；取不到 → 空串，不编造）。

    R42 B4：先把"该节正文"从条目正文里切出来（节标题 → 下一个节标题之间），再取首句；
    这样 basis 引文才是"**章内该节**"的，而不是整章的。
    """
    from ..content import citations

    body = _section_text(str(text or ""), section)
    if not body:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[。；！？])", body) if s.strip()]
    for s in sentences:
        if len(citations.normalize(s)) >= min_chars:
            return s
    return ""


def _section_text(entry_text: str, section: str) -> str:
    """从条目正文里切出**某一节**的正文（节标题行 → 下一个节标题行之前）。

    节标题形态：``1.1 太阳系的组成`` / ``1.1.2 …``（目录里的编号节名）＋
    **R46 C**：``第一节 恒星`` / ``第二讲 …``（中文序数节名）。

    定位**空白弹性**（全角空格/多空格/制表符都认）：先按"行首标题"定位，落不到再退回子串查找。
    切不出来（该节名不在正文里）→ 返回空串（调用方不编造引文）。
    """
    body = str(entry_text or "")
    sec = str(section or "").strip()
    if not body or not sec:
        return ""
    start = -1
    parts = re.split(r"\s+", sec, maxsplit=1)
    if len(parts) == 2:  # 标题＝"前缀 + 标题文字" → 行首匹配（中间空白弹性）
        m = re.search(rf"(?m)^\s*{re.escape(parts[0])}\s+{re.escape(parts[1])}\s*$", body)
        if m:
            start = m.end()
    if start < 0:
        idx = body.find(sec)
        if idx < 0:
            return ""
        start = idx + len(sec)
    rest = body[start:]
    m2 = _NEXT_HEADING.search(rest)
    if m2 and m2.start() > 0:
        rest = rest[: m2.start()]
    return rest.strip()


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


# ---------- R37 S6 ＋ R38 B1：覆盖账本（跨全部材料） ----------
def _page_account(m: dict, blocks: list[dict], *, kept: set[tuple[str, str]],
                  skipped: set[tuple[str, str]]) -> dict:
    """**R67 任务 D**：这份材料的"读书账"——进流程多少字 / 没进去多少字 / **差在哪**。

    两个恒等式（都对得上才算"账面说实话"）：

    ① ``正文 = 成块字数 + 没成块的页文字 + 分页标记``（逐页核对，不留糊涂账）；
    ② ``成块字数 = 真进流程的 + 因上限没读的``（与 `_full_blocks` 同一批块，逐块相加）。

    "没成块的页文字"再按位置分成三类（书前页 / 书中间 / 书末页），并给出页号样例——
    用户一眼能看出"差的是封面、版权页、目录、前言、参考文献这些"。
    """
    from . import bookmap

    mid = str(m["id"])
    entries = list((m["structure"] or {}).get("entries") or [])
    body_chars = len(m.get("body") or "")
    blocks_chars = sum(int(b.get("chars") or 0) for b in blocks
                       if str(b.get("material_id") or "") == mid)
    injected = sum(int(b.get("chars") or 0) for b in blocks
                   if str(b.get("material_id") or "") == mid
                   and (mid, str(b.get("label") or "")) in kept)
    cap_chars = sum(int(b.get("chars") or 0) for b in blocks
                    if str(b.get("material_id") or "") == mid
                    and (mid, str(b.get("label") or "")) in skipped)
    pages = bookmap._split_pages(m.get("body") or "")
    used: set[str] = set()
    for e in entries:
        used |= {str(x) for x in (e.pages or [])}
    first_idx = last_idx = -1
    label_pos = {str(p["label"]): i for i, p in enumerate(pages)}
    for e in entries:
        for lb in (e.pages or []):
            i = label_pos.get(str(lb))
            if i is None:
                continue
            first_idx = i if first_idx < 0 else min(first_idx, i)
            last_idx = max(last_idx, i)
    groups: list[dict] = []
    for kind, label_zh, keep in (
        ("front", "书前页（封面、版权页、目录、前言这类）", lambda i: first_idx >= 0 and i < first_idx),
        ("back", "书末页（参考文献、索引这类）", lambda i: last_idx >= 0 and i > last_idx),
        ("middle", "书中间的页（没归到任何一章）",
         lambda i: first_idx >= 0 and first_idx <= i <= last_idx),
    ):
        hit = [p for i, p in enumerate(pages)
               if str(p["label"]) not in used and keep(i)]
        if hit:
            groups.append({"kind": kind, "label_zh": label_zh,
                           "count": len(hit), "chars": sum(len(p["text"]) for p in hit),
                           "pages": [str(p["label"]) for p in hit],
                           "sample_zh": "、".join(str(p["label"]) for p in hit[:6])
                           + ("…" if len(hit) > 6 else "")})
    unused_chars = sum(int(g["chars"]) for g in groups)
    marker_chars = max(0, body_chars - blocks_chars - unused_chars)
    return {
        "body_chars": body_chars,
        "blocks_chars": blocks_chars,
        "injected_chars": injected,
        "cap_skipped_chars": cap_chars,
        "not_injected_chars": max(0, body_chars - injected),
        "unused_page_chars": unused_chars,
        "unused_pages": sum(int(g["count"]) for g in groups),
        "marker_chars": marker_chars,
        "groups": groups,
        "checks": {
            "by_page": body_chars == blocks_chars + unused_chars + marker_chars,
            "by_block": blocks_chars == injected + cap_chars,
        },
        "note_zh": (
            ("这份材料一共 {body:,} 字，真正进入流程的是 {inj:,} 字，"
             "没进去 {gap:,} 字。").format(body=body_chars, inj=injected,
                                          gap=max(0, body_chars - injected))
            + ("；没进去的主要是" + "、".join(
                f"{g['label_zh']} {g['chars']:,} 字（{g['sample_zh']}）" for g in groups)
               if groups else "")
            + (f"；另外有 {cap_chars:,} 字是因为你设了「最多读多少」没读（整章停下）"
               if cap_chars else "")
            + (f"；分页标记与分段符号约 {marker_chars:,} 字。"
               if marker_chars else "。")),
    }


def coverage_ledger(db, subject_id: str) -> dict:
    """**覆盖账本**：章节地图 ↔ 单元映射 ↔ 单元覆盖状态（大纲页与 API 的唯一数据源）。

    R38 B1 增补（**多材料合并口径**）：
    - ``by_material``：**按材料分组**的 `已覆盖节 / 总节` + 未覆盖清单（材料页/大纲页直接渲染）；
    - ``uncovered_by_material``：未覆盖清单**按材料分组**（不许只在 prompt 尾部提一句）；
    - ``uncovered_materials``：**整份未纳入**的材料（健康度不合格/未注入）；
    - ``order_basis``：顺序依据（"角色：主教材在前" 或 "导入顺序"）；
    - ``entries[].pages`` + ``page_total/page_covered``：**章级统计、页级可下钻**（S1b）。

    返回::

        {
          "total": 章/节条目总数, "covered": …, "uncovered": […],
          "page_total": 全书页数, "page_covered": 有单元映射的页数,
          "by_material": [{material_id,title,role,role_zh,total,covered,uncovered:[…],chars}],
          "uncovered_materials": [{title,note}],
          "order_basis": "导入顺序" | "角色（…）",
          "materials": [{id,title,kind,healthy,note,kind_of_structure,structure_note,role}],
          "entries": [{material,material_id,label,chapter,chars,pages,sections,units,covered}],
          "units": [{unit_id,title,sources,status,note,grounded_facts,material_bound,dropped_exercises}]
        }
    """
    from ..content import citations

    index = _ordered(_material_index(db, subject_id))
    doc = outline_store.get_outline(subject_id)
    units = list(doc.units) if doc is not None else []
    mapping = _covered_entries(units, index)
    # **R42 A3：覆盖账如实降** —— 因「总注入上限」未注入的章节，即便有单元映射也**不算真覆盖**
    # （"没喂给模型"就谈不上"覆盖"）；同时在 not_injected 里说明它们去哪了。
    blocks = _full_blocks(index)
    eff = resolve_budget(db, subject_id)
    valve = context_valve(db, batch_chars=int(eff["per_call_chars"]), blocks=blocks)
    _keep, _skipped, cap = _apply_inject_cap(valve["batches"], int(eff["inject_max_chars"]), subject_id)
    cap_skips = _cap_skip_entries(_skipped, index)
    skipped_keys = {(str(x.get("material_id") or ""), str(x.get("label") or "")) for x in cap_skips}
    # **R67 任务 D**：逐材料的"读书账"（进流程多少字 / 没进去多少字 / 差在哪）。
    # 口径与 `_full_blocks` **同一批块**逐块相加 → 账面数字与实际成块字数对得上。
    kept_keys = {(str(b.get("material_id") or ""), str(b.get("label") or ""))
                 for batch in _keep for b in (batch.get("blocks") or [])}
    skip_keys = {(str(b.get("material_id") or ""), str(b.get("label") or ""))
                 for batch in _skipped for b in (batch.get("blocks") or [])}
    accounts = {str(m["id"]): _page_account(m, blocks, kept=kept_keys, skipped=skip_keys)
                for m in index}
    # **R67 任务 F**：哪份材料是"抽样读"的（快读会把没读的章标出来，不许装成"全书都读了"）
    read_state = {str(m["id"]): import_state(subject_id, m) for m in index}
    entries: list[dict] = []
    uncovered: list[str] = []
    skipped_short: list[dict] = []
    page_total = 0
    page_covered = 0
    short_cap = _min_entry_chars()
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            hit = sorted(set(mapping.get((m["id"], e.label)) or []))
            cap_skipped = (str(m["id"]), str(e.label)) in skipped_keys
            covered = bool(hit) and not cap_skipped
            # **R42 B1**：过短条目**不是**覆盖缺口（它是"按规则跳过/已并入"），单独归类以便解释
            is_short = int(getattr(e, "chars", 0) or 0) < short_cap
            if not covered and is_short:
                skipped_short.append({"material": m["title"], "material_id": m["id"],
                                      "label": e.label, "chars": int(e.chars)})
            elif not covered:
                uncovered.append(f"{m['title']} · {e.label}")
            pages = list(e.pages)
            page_total += len(pages)
            if covered:
                page_covered += len(pages)
            entries.append({"material": m["title"], "material_id": m["id"], "label": e.label,
                            "chapter": e.chapter, "chars": e.chars, "sections": list(e.sections),
                            "pages": pages, "units": hit, "covered": covered,
                            "short": is_short,
                            # R42：这一条"去哪了"（可解释性——不许凭空消失）；R52 B：说人话
                            "not_injected_reason": (
                                "到总量上限了" if cap_skipped
                                else ("" if covered
                                      else ("太短（已并入相邻单元或跳过）" if is_short
                                            else "没有单元对应"))),
                            "reason_zh": (
                                "因为设了总量上限，这一章/节没读" if cap_skipped
                                else ("" if covered
                                      else (f"这一条太短（{int(getattr(e, 'chars', 0) or 0)} 字 < "
                                            f"{short_cap} 字）：已并入相邻单元或跳过，**不算没出内容**"
                                            if is_short else "还没有单元对应这一章/节")))})
    # R38 B1：按材料分组统计（覆盖账跨全部材料）
    by_material: list[dict] = []
    uncovered_by_material: list[dict] = []
    uncovered_materials: list[dict] = []
    for m in index:
        mine = [e for e in entries if e["material_id"] == m["id"]]
        miss = [e for e in mine if not e["covered"]]
        fig_labels = [str(e.label) for e in (m["structure"] or {}).get("entries") or []
                      if figure_refs(str(e.text or ""))]
        by_material.append({
            "material_id": m["id"], "title": m["title"],
            "role": m.get("role") or ROLE_UNSET, "role_explicit": bool(m.get("role_explicit")),
            "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
            "total": len(mine), "covered": len(mine) - len(miss),
            "uncovered": [e["label"] for e in miss],
            "chars": len(m.get("body") or ""),
            "pages": sum(len(e["pages"]) for e in mine),
            "healthy": m["text_health"]["healthy"],
            "note": m["text_health"]["note"],
            # R42 A3：本材料因「总注入上限」未注入的章节（覆盖账里看得出"它去哪了"）
            "cap_skipped": [x["label"] for x in cap_skips if x["material_id"] == m["id"]],
            "cap_skipped_count": len([x for x in cap_skips if x["material_id"] == m["id"]]),
            # **R55 A/B**：体检三档（好/一般/差 + 人话）＋ 图片数 ＋「图示不可用」的章/节
            # ——覆盖账是**第二处可见渠道**（第一处是材料列表），两处同源同口径。
            "health_grade": str(m["text_health"].get("grade") or ""),
            "health_summary_zh": str(m["text_health"].get("summary_zh") or ""),
            "image_count": int((m["text_health"].get("extract") or {}).get("images") or 0),
            "figure_unavailable": fig_labels,
            "figure_unavailable_count": len(fig_labels),
            # **R67 任务 D**：这份材料的读书账（进流程/没进去/差在哪）——账面与成块字数同源
            "text_account": accounts.get(str(m["id"])) or {},
            # **R67 任务 F**：抽样读的事实（读了哪几页 / 还剩哪些页没读）
            "sampled": bool((read_state.get(str(m["id"])) or {}).get("sampled")),
            "read_pages": int((read_state.get(str(m["id"])) or {}).get("read") or 0),
            "planned_pages": int((read_state.get(str(m["id"])) or {}).get("total") or 0),
            "pages_pending": list((read_state.get(str(m["id"])) or {}).get("unread") or []),
            "import_state": str((read_state.get(str(m["id"])) or {}).get("state") or ""),
        })
        if miss:
            uncovered_by_material.append({
                "material_id": m["id"], "title": m["title"],
                "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
                "items": [{"label": e["label"], "chapter": e["chapter"], "chars": e["chars"],
                           "pages": e["pages"]} for e in miss],
            })
        if not m["text_health"]["healthy"]:
            uncovered_materials.append({"material_id": m["id"], "title": m["title"],
                                        "kind": "读不了（像是扫描件/图片版）",
                                        "note": m["text_health"]["note"]})
    unit_ledger = []
    for u in units:
        meta = dict(u.meta or {})
        cov = dict(meta.get("coverage") or {})
        # **R54 C**：单元"有没有内容 / 能不能学"——与**会话守卫同源**（同一实现就地取），
        # 供大纲页一眼看出"哪些还没内容"，避免点进空会话。
        content = _unit_content_status(u.id)
        unit_ledger.append({
            "unit_id": u.id, "title": u.title,
            "sources": [dict(r) for r in (u.materials or [])],
            "status": str(cov.get("status") or "未知"),
            "note": str(cov.get("note") or ""),
            "grounded_facts": int(cov.get("grounded_facts") or 0),
            "material_bound": bool(cov.get("material_bound")),
            "dropped_exercises": int(cov.get("dropped_exercises") or 0),
            "generated_at": str(cov.get("at") or ""),
            # R54 C：内容状态（同源）
            "has_content": bool(content.get("exists")),
            "usable": bool(content.get("usable")),
            "content_reason_zh": str(content.get("reason_zh") or ""),
            "exercise_count": int(content.get("exercises") or 0),
            "taught_fact_count": int(content.get("taught_facts") or 0),
            # **R55 B**：这一节的内容基本都在图里（系统读不到图）→ 没出内容；
            # 与"还没生成"区分开（原因不同、下一步不同），界面上单独标出来。
            "figure_unavailable": bool(cov.get("figure_unavailable")),
            # R42 B4：**章内该节级**依据（R40 裁决 §2-3 的提升项）——大纲页/覆盖账可显示
            "basis_section": str(cov.get("basis_section") or ""),
            "basis_quote": str(cov.get("basis_quote") or ""),
            "basis_note": str(cov.get("basis_note") or ""),
        })
    return {
        "subject": subject_id,
        "has_materials": bool(index),
        "total": len(entries),
        "covered": len(entries) - len(uncovered),
        "uncovered": uncovered,
        # **R67 任务 D**：账面总览（跨材料）——进入流程多少字 / 没进去多少字 / 差在哪。
        # ``by_material[].text_account`` 是逐材料的同一笔账；这里给"一眼看全"的合计。
        "text_account": {
            "body_chars": sum(int(a.get("body_chars") or 0) for a in accounts.values()),
            "injected_chars": sum(int(a.get("injected_chars") or 0) for a in accounts.values()),
            "blocks_chars": sum(int(a.get("blocks_chars") or 0) for a in accounts.values()),
            "not_injected_chars": sum(int(a.get("not_injected_chars") or 0)
                                      for a in accounts.values()),
            "cap_skipped_chars": sum(int(a.get("cap_skipped_chars") or 0)
                                     for a in accounts.values()),
            "unused_page_chars": sum(int(a.get("unused_page_chars") or 0)
                                     for a in accounts.values()),
            "marker_chars": sum(int(a.get("marker_chars") or 0) for a in accounts.values()),
            "all_checks_ok": all(bool((a.get("checks") or {}).get("by_page"))
                                 and bool((a.get("checks") or {}).get("by_block"))
                                 for a in accounts.values()),
            "materials": [{"material_id": m["id"], "title": m["title"],
                           **(accounts.get(str(m["id"])) or {})} for m in index],
        },
        # **R42 B1**：过短条目（按规则跳过/未成为单元）——**不计入 uncovered 缺口**，但显式列出
        "skipped_short": {"count": len(skipped_short), "labels": [x["label"] for x in skipped_short],
                          "items": skipped_short, "min_chars": short_cap},
        "short_entry_min_chars": short_cap,
        # R42 A3：**未纳入清单**（三种原因：健康度不合格 / 未进批次 / **总注入上限**），
        # 覆盖账与预算视图同源——"每一处没进去的都必须能解释"。
        "not_injected": (_unmapped_entries(index, blocks) + cap_skips),
        "inject_cap": {
            "configured": bool(cap.get("configured")),
            "cap": int(cap.get("cap") or 0),
            "used_chars": int(cap.get("used_chars") or 0),
            "remaining": int(cap.get("remaining") or 0),
            "skipped_count": int(cap.get("skipped_count") or 0),
            "skipped_labels": list(cap.get("skipped_labels") or []),
            "skipped_by_material": _cap_skips_by_material(_skipped, index),
        },
        "page_total": page_total,
        "page_covered": page_covered,
        "by_material": by_material,
        "uncovered_by_material": uncovered_by_material,
        "uncovered_materials": uncovered_materials,
        "order_basis": order_basis(index),
        "multi_material": len(index) > 1,
        "materials": [{"id": m["id"], "title": m["title"], "kind": m.get("kind", ""),
                       "healthy": m["text_health"]["healthy"],
                       "note": m["text_health"]["note"],
                       "role": m.get("role") or ROLE_UNSET,
                       "role_explicit": bool(m.get("role_explicit")),
                       "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
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
    from . import search as search_svc
    from ..service import model_config

    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    # **R56**：模型配置统一走「页面设置 > .env > 默认」的生效值
    settings = model_config.effective_settings(db)
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
    # **R61 任务 B**：这段 note 会在界面上原样显示（大纲页的「联网检索」提示）——
    # 不许出现内部变量名，只说人话 + 指向用户真能走的两条路（「本地导入」在这里）。
    provider = status.get("provider") or "none"
    if provider == "searxng":
        return ("联网检索后端未配置完成：已选 SearXNG 但还缺实例地址（要在这台机器的程序配置文件里"
                "填自托管实例地址）。配好就能用联网候选，或现在用「本地导入」上传自有/授权资料。")
    return ("联网检索后端未配置（当前没有选检索服务）。可选方案：在这台机器的程序配置文件里"
            "启用自托管 SearXNG 并填实例地址，或先用「本地导入」上传自有/授权资料。")


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
    # R38：预算滑块 + 多材料角色/合并口径
    "BATCH_TIERS",
    "INJECT_TIERS",
    "ROLE_MAIN",
    "ROLE_SUPPLEMENT",
    "ROLE_UNSET",
    "ROLE_LABELS_ZH",
    "resolve_budget",
    "subject_budget",
    "set_budget",
    "budget_view",
    "set_material_role",
    "order_basis",
    "context_valve",
    "estimate_tokens",
]
