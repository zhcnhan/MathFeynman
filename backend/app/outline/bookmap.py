"""app.outline.bookmap：教材结构解析（R37 S1/S2/S8）——"章 → 节"的**书本地图**。

唯一职责：把材料正文（PDF 分页文本 / Markdown / 纯文本）解析成**结构化地图**，供两处共用
（不新建平行机制，两处读同一份地图）：

- **S2/S8 大纲起草**：先产出章节地图，再由它派生单元；每个地图条目必须映射到 ≥1 个单元，
  未映射 → 违规（不得悄悄丢）；
- **S3/S4 单元出稿**：按单元映射到的章/节注入**完整正文**（不是"前 N 字"摘要）。

识别顺序（确定性、可解释，逐级降级并如实报告来源）：

1. ``toc``：正文含目录（"目　录" + 页码导引线）→ 解析「章/节 + 页码」条目，再用页面的
   **运行页码**（PDF 抽取里页首的页码）把目录页码映射到物理页 → 得到精确的章边界；
2. ``heading``：Markdown 标题（``#``）/ 行首"第 N 章"；
3. ``page``：都没有 → 按页块切分（PDF 页），如实标注"未识别到章结构"；
4. ``text``：连页标记都没有 → 按段落窗口切分。

设计约束（与 R37 一致）：
- **不截断**：条目文本一律是完整正文；过大时在**章/页边界**切分成多个条目（S1"结构化分段"）；
- **不猜**：识别不到结构就降级并写明 ``kind``/``note``，绝不假装读到了目录；
- 学科无关：只用排版特征（章/节/页），无任何学科特判。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 页标记（PDF 解析产物）：`【第 N 页】`
PAGE_MARK = re.compile(r"^【第\s*(\d+)\s*页】\s*$", re.M)
# 私用区（PDF 页首页码/装饰字形）——与 content.citations 的口径一致（那边用于引文归一化）
_PUA = "[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]"
_PUA_RUN = re.compile(rf"({_PUA})\1{{1,}}")      # 目录导引线（同一私用字形连排）
_PUA_ANY = re.compile(_PUA)
# 目录行（折叠全角/空格后）：`第1章 绪论 1` / `附录A 符号列表 792` / `1.1 太阳系的组成 2`
_TOC_CHAPTER = re.compile(r"^(第\s*(\d{1,3})\s*章|附\s*录\s*([A-Za-z]))\s*(.*?)\s*(\d{1,4})$")
_TOC_SECTION = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,2})\s+(.*?)\s*(\d{1,4})$")
# Markdown 标题
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# 正文行首章标题（无目录时的降级路径）：允许前缀页码/装饰字形
_CHAPTER_ANY = re.compile(r"第\s*(\d{1,3}|[０-９]{1,3}|[一二三四五六七八九十]{1,3})\s*章")
_APPENDIX_ANY = re.compile(r"附\s*录\s*([A-Za-zＡ-Ｚ])")
# 书末页（参考文献/索引/致谢…）：不是可教内容，不进地图（如实记 note）
_BACK_MATTER = re.compile(r"^(参\s*考\s*文\s*献|原\s*书\s*索\s*引|索\s*引|致\s*谢|后\s*记)")
# **R67 任务 C**：书签里的"书前页"（封面/版权/目录/前言…）——同样不是可教内容
_FRONT_MATTER = re.compile(
    r"^(封\s*面|封\s*底|版\s*权|扉\s*页|目\s*录|前\s*言|序\s*言|序|推\s*荐|译\s*者|作\s*者|"
    r"内\s*容\s*简\s*介|出\s*版|致\s*谢|引\s*言|凡\s*例|术\s*语|原\s*书\s*索\s*引)")
# 书签里的章/附录写法（中英兼顾；`第 1 章` / `第1章` / `Chapter 3` / `附录 A` / `Appendix B`）
_BM_CHAPTER = re.compile(r"^\s*(第\s*[0-9０-９]{1,3}\s*章|第\s*[一二三四五六七八九十]{1,3}\s*章|"
                         r"chapter\s*[0-9]{1,3})", re.I)
_BM_APPENDIX = re.compile(r"^\s*(附\s*录\s*[A-Za-zＡ-Ｚ]|appendix\s*[A-Za-z])", re.I)


@dataclass
class MapEntry:
    """地图条目＝**覆盖单位**（单元必须映射到它）；``text`` 是完整正文（不截断）。"""

    label: str                     # 章标签（如"第3章 太阳加热与能量传输"）或页块标签
    chapter: str = ""              # 所属章（自身即章时相同；页块降级时为空）
    text: str = ""
    pages: list[str] = field(default_factory=list)   # 物理页标签（"第 N 页"）
    sections: list[str] = field(default_factory=list)  # 章 → 节标签（S2 章节地图）

    @property
    def chars(self) -> int:
        return len(self.text)


def _fold(s: str) -> str:
    """全角 ASCII → 半角（与引文尺子同一折算；目录抽取必须做，见 citations.normalize）。"""
    return "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in (s or ""))


def _norm_line(raw: str) -> str:
    """目录行归一：折叠全角、私用字形（导引线→空格 / 其它→小数点）、数字内空格、压空白。

    PDF 抽取常见：全角数字（１）、被空格拆开的数字（"３ １" = 31）、
    私用区字形当小数点（"１ 􀆰 １" = 1.1）与导引线（"􀆺􀆺􀆺"）。
    不归一化就没有可靠的目录解析（这也是引文尺子归一化的同源理由）。
    """
    s = _fold(raw)
    s = _PUA_RUN.sub(" ", s)
    s = _PUA_ANY.sub(".", s)
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s*\.\s*", ".", s)
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _split_pages(body: str) -> list[dict]:
    """PDF 分页正文 → ``[{label, text}]``；无页标记返回空。"""
    if not PAGE_MARK.search(body or ""):
        return []
    pages: list[dict] = []
    buf: list[str] = []
    label = ""
    for line in (body or "").splitlines():
        m = PAGE_MARK.match(line.strip())
        if m:
            if label:
                pages.append({"label": label, "text": "\n".join(buf).strip()})
            label = f"第 {m.group(1)} 页"
            buf = []
            continue
        if label:
            buf.append(line)
    if label:
        pages.append({"label": label, "text": "\n".join(buf).strip()})
    return pages


def _running_page_no(page_text: str) -> int | None:
    """PDF 页首**运行页码**（页眉/页脚）：``􀅰 ３ １ 􀅰 第２章 …`` → 31。

    只取首行里"私用字形夹着的数字段"（页眉页码），数字 >4000 视为误命中（不返回）。
    """
    for line in (page_text or "").splitlines()[:2]:
        if not line.strip():
            continue
        m = re.search(rf"{_PUA}\s*([0-9\uFF10-\uFF19][0-9\uFF10-\uFF19\s]{{0,6}}?)\s*{_PUA}",
                      _fold(line))
        if m:
            digits = re.sub(r"\D", "", m.group(1))
            if digits and 0 < int(digits) <= 4000:
                return int(digits)
        return None
    return None


def _toc_block(pages: list[dict]) -> tuple[list[dict], int]:
    """找出目录块：返回 (目录页, 目录结束的物理页下标+1)。无目录 → ([], 0)。"""
    start = -1
    for i, p in enumerate(pages):
        head = _norm_line(p["text"][:80])
        if "目录" in head.replace(" ", ""):
            start = i
            break
    if start < 0:
        return [], 0
    block = [pages[start]]
    end = start + 1
    for j in range(start + 1, len(pages)):
        raw = pages[j]["text"]
        if len(_PUA_RUN.findall(raw)) >= 2:  # 目录页特征：导引线连排
            block.append(pages[j])
            end = j + 1
            continue
        break
    return block, end


def _parse_toc(block: list[dict]) -> list[dict]:
    """目录块 → ``[{label, num, page, sections:[标签]}]``（章 + 该章下的节）。"""
    chapters: list[dict] = []
    for p in block:
        for raw in p["text"].splitlines():
            s = _norm_line(raw)
            if not s:
                continue
            m = _TOC_CHAPTER.match(s)
            if m:
                if m.group(2):
                    label = f"第{int(m.group(2))}章 {m.group(4)}".strip()
                    kind = "chapter"
                else:
                    label = f"附录{m.group(3).upper()} {m.group(4)}".strip()
                    kind = "appendix"
                chapters.append({"label": label, "kind": kind,
                                 "page": int(m.group(5)), "sections": []})
                continue
            m2 = _TOC_SECTION.match(s)
            if m2 and chapters and m2.group(1).count(".") == 1:  # 只取章下的一级节
                chapters[-1]["sections"].append(f"{m2.group(1)} {m2.group(2)}".strip())
    return chapters


def _chapters_from_toc(pages: list[dict], toc: list[dict], body_start: int) -> list[MapEntry]:
    """目录条目 + 运行页码 → 章正文（每章 = 起始物理页 → 下一章起始页前）。"""
    by_page_no: dict[int, int] = {}
    for i in range(body_start, len(pages)):
        n = _running_page_no(pages[i]["text"])
        if n is not None and n not in by_page_no:
            by_page_no[n] = i
    starts: list[int] = []
    for ch in toc:
        idx = by_page_no.get(ch["page"])
        if idx is None:  # 运行页码缺失 → 用章标题在该页正文里出现来定位（仅在正文区间找）
            idx = _find_title_page(pages, body_start, ch["label"])
        if idx is None:  # 仍找不到 → 按目录顺序与已知起点插值（保底：不丢章）
            idx = starts[-1] + 1 if starts else body_start
        starts.append(max(body_start, min(idx, len(pages) - 1)))
    # 起点必须单调不减（页码乱序/重复都不破坏"章序=书序"）
    for i in range(1, len(starts)):
        if starts[i] <= starts[i - 1]:
            starts[i] = min(starts[i - 1] + 1, len(pages) - 1)
    out: list[MapEntry] = []
    for i, ch in enumerate(toc):
        end = starts[i + 1] if i + 1 < len(toc) else len(pages)
        part = pages[starts[i]:max(end, starts[i] + 1)]
        out.append(MapEntry(
            label=ch["label"], chapter=ch["label"],
            text="\n\n".join(f"【{p['label']}】\n{p['text']}" for p in part).strip(),
            pages=[p["label"] for p in part], sections=list(ch.get("sections") or []),
        ))
    return out


def _find_title_page(pages: list[dict], start: int, label: str) -> int | None:
    """在正文区间里找"章标题出现在页首"的物理页。"""
    from ..content import citations

    core = _CHAPTER_ANY.sub("", label)
    core = _APPENDIX_ANY.sub("", core).strip()
    if len(citations.normalize(core)) < 2:
        return None
    for i in range(start, len(pages)):
        if citations.normalize(core) in citations.normalize(pages[i]["text"][:200]):
            return i
    return None


# ---------------------------------------------------------------------------
# **R67 任务 C**：PDF 自带书签（权威目录）→ 章/附录条目
#
# 为什么优先书签：书签是**书自己写的目录**（干净标题 + 指到页），而目录页的印刷文字要靠
# 全角数字/私用字形导引线去猜（实测某 126 页教材：书签 31 条干净标题，目录页文字只认出 2 条，
# 结果 101 页被塞进「第2章」）。**没有书签才回落**到原来的目录页解析（`_parse_toc`）。
# ---------------------------------------------------------------------------
def _bookmark_kind(title: str) -> str:
    """书签条目的类别：``chapter`` / ``appendix`` / ``other``（只看开头写法，不做模糊匹配）。"""
    s = _fold(str(title or "")).strip()
    if _BM_APPENDIX.match(s):
        return "appendix"
    if _BM_CHAPTER.match(s):
        return "chapter"
    return "other"


def _bookmark_items(toc: list[dict]) -> list[dict]:
    """书签原样条目 → 归一后的 ``[{title, page(1起，0=没指到页), level, kind}]``。"""
    out: list[dict] = []
    for b in toc or []:
        if not isinstance(b, dict):
            continue
        title = str(b.get("title") or "").strip()
        if not title:
            continue
        try:
            page = int(b.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        try:
            level = int(b.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        out.append({"title": title, "page": max(0, page), "level": level,
                    "kind": _bookmark_kind(title)})
    return out


def _chapters_from_bookmarks(pages: list[dict], toc: list[dict]) -> tuple[list[MapEntry], str]:
    """书签 → ``(章/附录条目, 中文说明)``；书签不可用 → ``([], "")``（调用方回落目录页解析）。

    - 顶层书签里认得出「第 N 章 / 附录 X」→ **只把它们当章**（封面/版权/目录/前言/参考文献/
      索引/术语这些不是可教内容，如实写进说明里）；它们之间的页照旧归上一章（**不丢页**）；
    - 顶层书签里一个章/附录写法都没有（有的书按节/按主题做书签）→ 退一步用**全部顶层书签**
      （去掉封面/目录/参考文献这类明显不是正文的），说明里写明这一层退让；
    - 书签**指不到页**（`page=0`）→ 先按"标题出现在哪一页"找，找不到就顺延一页（保证章序单调、
      不丢章）；这也是手册里 `附录 G` 那种"书签没有目标页"的真实情形。
    """
    items = _bookmark_items(toc)
    if not items:
        return [], ""
    top = [it for it in items if it["level"] == 0] or items
    teach = [it for it in top if it["kind"] in ("chapter", "appendix")]
    fallback = False
    if not teach:
        teach = [it for it in top
                 if not (_FRONT_MATTER.search(_fold(it["title"]))
                         or _BACK_MATTER.search(_fold(it["title"])))]
        fallback = True
    if not teach:
        return [], ""
    total = len(pages)
    body_start = 0
    # **书末边界**：书签里第一个「参考文献/索引/术语…」页起不算正文（它不是可教内容）。
    # 没有这一步，最后一个附录会把参考文献/索引一路吞进去（实测某书附录 G 会吞 34 页）。
    back_start = total
    for it in top:
        if it["kind"] != "other" or not it["page"]:
            continue
        if _BACK_MATTER.search(_fold(it["title"])) or _FRONT_MATTER.search(_fold(it["title"])):
            if _BACK_MATTER.search(_fold(it["title"])):
                back_start = min(back_start, int(it["page"]) - 1)
    # 章/附录起始页（0 起下标）
    starts: list[int] = []
    for it in teach:
        idx: int | None = None
        if it["page"]:
            cand = int(it["page"]) - 1
            if 0 <= cand < total:
                idx = cand
        if idx is None:
            idx = _find_title_page(pages, (starts[-1] + 1) if starts else body_start, it["title"])
        if idx is None:
            idx = starts[-1] + 1 if starts else body_start
        starts.append(max(body_start, min(idx, total - 1)))
    for i in range(1, len(starts)):          # 起点单调不减（章序＝书序）
        if starts[i] <= starts[i - 1]:
            starts[i] = min(starts[i - 1] + 1, total - 1)
    # 章下的**书签节**（level>0 且落在本章页范围内）→ 该章的 sections（S2 章节地图用）
    lower = [it for it in items if it["level"] > 0]
    out: list[MapEntry] = []
    for i, it in enumerate(teach):
        end = min(starts[i + 1] if i + 1 < len(teach) else total, max(back_start, starts[i] + 1))
        part = pages[starts[i]:max(end, starts[i] + 1)]
        secs = [s["title"] for s in lower
                if starts[i] < (int(s["page"]) - 1 if s["page"] else starts[i]) < end]
        out.append(MapEntry(
            label=it["title"], chapter=it["title"],
            text="\n\n".join(f"【{p['label']}】\n{p['text']}" for p in part).strip(),
            pages=[p["label"] for p in part], sections=list(dict.fromkeys(secs)),
        ))
    kept = {"chapter": 0, "appendix": 0}
    for it in teach:
        kept[it["kind"]] = kept.get(it["kind"], 0) + 1
    names = [it["title"] for it in teach]
    others = [it["title"] for it in top if it not in teach]
    note = (f"按 PDF 自带的目录（书签）识别出 {kept['chapter']} 章 + {kept['appendix']} 个附录"
            if not fallback else
            f"PDF 自带目录里没有「第 N 章」写法，按书签的 {len(names)} 条正文条目划分")
    if others:
        note += f"；另有 {len(others)} 条不是正文（{'、'.join(others[:6])}{'…' if len(others) > 6 else ''}）没算作章"
    if back_start < total:
        note += f"；从第 {back_start + 1} 页起（参考文献/索引）不算正文，已截去其后 {total - back_start} 页"
    return out, note


def _chapters_from_headings(pages: list[dict]) -> list[MapEntry]:
    """降级路径：正文页里行首即"第 N 章"/"附录 X"的页作为章起点。"""
    starts: list[tuple[int, str]] = []
    for i, p in enumerate(pages):
        for line in p["text"].splitlines()[:3]:
            s = _norm_line(line)
            if not s:
                continue
            m = _CHAPTER_ANY.match(s) or _APPENDIX_ANY.match(s)
            if m:
                starts.append((i, s[:40]))
            break
    if not starts:
        return []
    out: list[MapEntry] = []
    for k, (i, label) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(pages)
        part = pages[i:max(end, i + 1)]
        out.append(MapEntry(label=label, chapter=label,
                            text="\n\n".join(f"【{p['label']}】\n{p['text']}" for p in part).strip(),
                            pages=[p["label"] for p in part]))
    return out


def _chapters_from_md(body: str) -> list[MapEntry]:
    """Markdown 标题（``#``/``##``）→ 章条目（章节层次由标题级数决定）。"""
    entries: list[MapEntry] = []
    cur_label = ""
    cur_level = 0
    buf: list[str] = []
    parent = ""

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if cur_label and text:
            entries.append(MapEntry(label=cur_label, chapter=parent or cur_label, text=text))
        buf = []

    for line in (body or "").splitlines():
        m = _MD_HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            if level <= 2:
                flush()
                if level == 1:
                    parent = m.group(2).strip()
                cur_label = m.group(2).strip()
                cur_level = level
                continue
        buf.append(line)
    flush()
    if cur_level == 1 and entries:  # 全部是一级标题 → 各自成章
        for e in entries:
            e.chapter = e.label
    return entries


def _chapters_from_blocks(pages: list[dict], window: int = 4,
                          unit_chars: int = 8000) -> list[MapEntry]:
    """最后降级：把页**合并成"章级"单元**（完整正文，页号保留用于溯源）。

    R38 S1b：PDF 没有标题/目录时，**不许**一页一个条目（那会把覆盖账变成几百行噪音、
    也让"按章生成"无从谈起）——按 ``unit_chars``（目标节大小，默认 8000 字）把相邻页
    累积成一个单元；单元正文里保留 ``【第 N 页】`` 页标记，**页级明细仍可下钻**。
    单个单元永不截断正文（只影响"每单元装几页"）。
    """
    if not pages:
        return []
    target = max(0, int(unit_chars or 0))
    if target <= 0:  # 目标大小关闭 → 退回固定页窗口
        window = max(1, int(window or 1))
        groups = [pages[i:i + window] for i in range(0, len(pages), window)]
    else:
        groups: list[list[dict]] = []
        cur: list[dict] = []
        size = 0
        for p in pages:
            plen = len(p.get("text") or "")
            if cur and size + plen > target:
                groups.append(cur)
                cur, size = [], 0
            cur.append(p)
            size += plen
        if cur:
            groups.append(cur)
    out: list[MapEntry] = []
    for part in groups:
        label = (f"{part[0]['label']}–{part[-1]['label']}" if len(part) > 1 else part[0]["label"])
        out.append(MapEntry(label=label, chapter="",
                            text="\n\n".join(f"【{p['label']}】\n{p['text']}" for p in part).strip(),
                            pages=[p["label"] for p in part]))
    return out


def parse_book(body: str, *, page_unit_chars: int | None = None,
               toc: list[dict] | None = None) -> dict:
    """教材正文 → 章节地图（唯一入口）。

    返回 ``{"kind": toc|heading|md|page|text, "entries": [MapEntry], "note": 中文说明}``。
    ``kind`` 如实标注识别路径（前端/日志据此判断"这本书的结构读到了什么程度"）。
    ``page_unit_chars``（R38 S1b）：无标题/目录的 PDF 按页**合并成章级单元**的目标大小
    （默认取 ``MF_PAGE_UNIT_CHARS``＝8000；0 = 关闭合并，退回固定 4 页窗口）。
    ``toc``（**R67 任务 C**）：材料自带的**书签目录**（``[{title, page, level}]``，page 为 1 起页号）
    ——有书签就**优先用书签**（权威目录）；书签认不出章/附录、或压根没有书签 → 回落原来的
    目录页文字解析，行为与 R67 之前**逐字一致**。
    """
    body = body or ""
    if page_unit_chars is None:
        try:
            from ..config import get_settings

            page_unit_chars = int(get_settings().page_unit_chars or 0)
        except Exception:
            page_unit_chars = 8000
    pages = _split_pages(body)
    entries: list[MapEntry] = []
    kind = "text"
    note = ""
    back_cut = ""
    if pages and toc:
        # **R67 任务 C**：有书签 → 先用书签（不做"按正文页首截书末"那一步：书签已经给出边界）
        entries, bm_note = _chapters_from_bookmarks(pages, toc)
        if entries:
            kind = "toc"
            note = bm_note
    if pages and not entries:
        end = _back_matter_start(pages)
        if end is not None:
            back_cut = "；已按书末『参考文献/索引』截去其后页面（不是可教内容）"
            pages = pages[:end]
        toc_block, body_start = _toc_block(pages)
        printed = _parse_toc(toc_block) if toc_block else []
        if len(printed) >= 2:
            entries = _chapters_from_toc(pages, printed, body_start)
            kind = "toc"
            note = f"按目录识别出 {len(entries)} 章/附录"
        else:
            entries = _chapters_from_headings(pages)
            if entries:
                kind = "heading"
                note = f"未读到目录，按页首章标题识别出 {len(entries)} 章"
        if not entries:
            entries = _chapters_from_blocks(pages, unit_chars=int(page_unit_chars or 0))
            kind = "page"
            pages_n = len(pages)
            note = (f"未识别到章结构：按页合并成 {len(entries)} 个章级单元"
                    f"（共 {pages_n} 页，目标每单元约 {max(1, int(page_unit_chars or 0))} 字；"
                    "正文完整、未截断，页号保留可下钻）"
                    if int(page_unit_chars or 0) > 0 else
                    "未识别到章结构：按页块切分（正文完整，未截断）")
    elif not pages:
        entries = _chapters_from_md(body)
        if entries:
            kind = "md"
            note = f"按 Markdown 标题识别出 {len(entries)} 节"
        else:
            entries = _text_windows(body)
            kind = "text"
            note = "未识别到章结构：按段落窗口切分（正文完整，未截断）"
    entries = [e for e in entries if e.text.strip()]
    return {"kind": kind, "entries": entries, "note": note + back_cut, "pages": len(pages)}


def _back_matter_start(pages: list[dict]) -> int | None:
    """书末页起点（首个"参考文献/索引/致谢"页）；找不到返回 None。"""
    for i, p in enumerate(pages):
        for line in p["text"].splitlines()[:3]:
            s = _norm_line(line)
            if not s or re.fullmatch(r"[.0-9]+", s):
                continue  # 空行 / 纯页码页首（页眉）——继续看下一行
            if _BACK_MATTER.search(s[:24]):
                return i
            break
    return None


def _text_windows(body: str, chunk_chars: int = 6000) -> list[MapEntry]:
    """纯文本兜底：按空行段落累积到 ``chunk_chars`` 切分（不切断段落）。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    out: list[MapEntry] = []
    buf: list[str] = []
    size = 0
    for p in paras:
        if buf and size + len(p) > chunk_chars:
            out.append(MapEntry(label=f"第 {len(out) + 1} 段", text="\n\n".join(buf)))
            buf, size = [], 0
        buf.append(p)
        size += len(p)
    if buf:
        out.append(MapEntry(label=f"第 {len(out) + 1} 段", text="\n\n".join(buf)))
    return out


def split_entries(entries: list[MapEntry], max_chars: int) -> list[MapEntry]:
    """S1 结构化分段：把超长条目**在页边界**切成多个条目（保证单次注入放得下）。

    切分后的条目仍是完整正文片段（不是"前 N 字"），label 带页范围，覆盖校验按条目做。
    ``max_chars <= 0``（不限）→ 原样返回。
    """
    if max_chars is None or max_chars <= 0:
        return list(entries)
    out: list[MapEntry] = []
    for e in entries:
        if e.chars <= max_chars or len(e.pages) <= 1:
            out.append(e)
            continue
        page_texts = _page_texts(e)
        if len(page_texts) != len(e.pages):
            out.append(e)  # 页结构对不上：宁可不切（保持完整），由调用方按调用点处理
            continue
        buf: list[str] = []
        labels: list[str] = []
        size = 0
        for label, text in zip(e.pages, page_texts):
            if buf and size + len(text) > max_chars:
                out.append(MapEntry(label=_range_label(e.label, labels), chapter=e.chapter,
                                    text="\n\n".join(f"{lb}\n{t}" for lb, t in zip(labels, buf)),
                                    pages=list(labels), sections=list(e.sections)))
                buf, labels, size = [], [], 0
            buf.append(text)
            labels.append(label)
            size += len(text)
        if buf:
            out.append(MapEntry(label=_range_label(e.label, labels), chapter=e.chapter,
                                text="\n\n".join(f"{lb}\n{t}" for lb, t in zip(labels, buf)),
                                pages=list(labels), sections=list(e.sections)))
    return out


def _page_texts(entry: MapEntry) -> list[str]:
    """条目正文 → 逐页文本（与 ``entry.pages`` 一一对应；对不上时返回空表）。"""
    texts: list[str] = []
    cur: list[str] = []
    started = False
    for line in entry.text.splitlines():
        if PAGE_MARK.match(line.strip()):
            if started:
                texts.append("\n".join(cur).strip())
            started = True
            cur = []
            continue
        if started:
            cur.append(line)
    if started:
        texts.append("\n".join(cur).strip())
    if started and len(texts) < len(entry.pages):  # 末尾空页：补齐占位（不改变页序）
        texts += [""] * (len(entry.pages) - len(texts))
    return texts if started and len(texts) == len(entry.pages) else []


def _range_label(base: str, labels: list[str]) -> str:
    if not labels:
        return base
    if len(labels) == 1:
        return f"{base}（{labels[0]}）"
    return f"{base}（{labels[0]}–{labels[-1]}）"


def chapter_map(entries: list[MapEntry]) -> list[dict]:
    """对外/给 AI 的**章节地图**（不含正文；只给标签/字数/节表）。"""
    out: list[dict] = []
    for e in entries:
        out.append({
            "label": e.label,
            "chapter": e.chapter or e.label,
            "chars": e.chars,
            "pages": list(e.pages),
            "sections": list(e.sections),
        })
    return out


__all__ = ["PAGE_MARK", "MapEntry", "parse_book", "split_entries", "chapter_map"]
