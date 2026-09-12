"""outline.pdfparse：PDF → 分页/分节文本（docs/14 §8 · Phase C C2）。

- 解析器：pypdf（BSD-3-Clause，纯 Python，Python 3.14 兼容；backend/pyproject 依赖）；
- 上传边界（错误一律中文，docs/13 §2）：非 PDF / 损坏 → PdfParseError；
  文件大小上限（MF_PDF_MAX_BYTES，默认 20MB）、页数上限（MF_PDF_MAX_PAGES，默认 400）、
  每页文本上限（防畸形页刷爆内存）——超限给中文错误提示；
- 产出：分页文本 sections（每页一条：页码 + 正文），并组装为带页标记的整段正文
  （引用材料入库 kind=pdf，分节可追溯"第 N 页"）；
- **R55 C：抽取修正**（只影响**新导入**；原始抽取文本一并返回，供事后核查"是抽取错了还是模型编了"）：
  ① 私用区字形 → 真标点（**已知码位表 + 通用兜底**两层，见 `_PUA_KNOWN` / `_fold_private_use`）；
  ② 拆字空格合并（汉字之间直接合并；拉丁单字母只在"疑似被拆开的词"上合并，见 `_merge_broken_spaces`）；
  ③ 同时算出**抽取体检**指标（认不出比例 / 拆字比例 / 公式符号 / 图片数），供导入时如实告知；
- 版权边界：仅解析**用户自行上传**的自有/授权 PDF（不整本下载书籍）。
"""
from __future__ import annotations

import io
import re

from ..config import get_settings

PDF_MAGIC = b"%PDF"


class PdfParseError(ValueError):
    """PDF 解析失败（message 中文，供 API 层直接映射 422）。"""

# ---------------------------------------------------------------------------
# R55 C1：私用区字形 → 真标点（**逐条用真实材料核对**得出的表；见 NOTES §77）
# ---------------------------------------------------------------------------
# 只放**已验证**的码位；不在表里的私用区字符按"认不出"如实保留（体检会把它算进比例）。
_PUA_KNOWN: dict[int, str] = {
    0x1001BA: " ",   # 目录**点线引导符**（`第１章　绪　论 １􀆺􀆺􀆺`）→ 删除填充（留一个空格防粘连）
    0x1001B0: ".",   # **句点/缩写点**（`C o 􀆰,L t d`→`Co.,Ltd`；`J􀆰L i s s a u e r`→`J.Lissauer`）
    0x100170: "·",   # 人名**间隔号**（`伊姆克 􀆰德帕特`→`伊姆克·德帕特`）
    0x1001B3: "'",   # **撇号**（`P e o p l e 􀆵 s`→`People's`；`P l a n c k 􀆵 s`→`Planck's`）
    0x1000FC: "",    # 页眉装饰字形（与 U+1000FD/FE/FF 同类：`􀅰▮ 　 　 　 　􀅰`）
    0x1000FD: "",
    0x1000FE: "",
    0x1000FF: "",
}

# 私用区范围（与 content/citations.py 同一套：BMP 私用区 + 两个补充私用区）
_PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))
# 同一码位连排 ≥ 3 → 视为**排版填充**（目录点线/表格线）：任何书都适用（通用兜底第一层）
_PUA_RUN_FILL = 3


def is_private_use(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _PUA_RANGES)


def _fold_private_use(text: str) -> tuple[str, dict]:
    """私用区字形处理（两层）→ ``(新文本, 统计)``。

    - **已知码位表**：按真实材料逐条核对后的映射（点线→空格、句点、间隔号、撇号、页眉装饰→删）；
    - **通用兜底**：同一码位**连排 ≥3** → 判为排版填充（目录点线/表格线）→ 折叠成一个空格；
      其余**未知**私用区字符**原样保留**（不猜、不乱删；体检里如实计入"认不出"）。
    """
    out: list[str] = []
    i, n = 0, len(text)
    stats = {"mapped": 0, "fill_run": 0, "unknown": 0}
    while i < n:
        ch = text[i]
        if not is_private_use(ch):
            out.append(ch)
            i += 1
            continue
        # 连排同码位（通用兜底）
        j = i
        while j < n and text[j] == ch:
            j += 1
        if j - i >= _PUA_RUN_FILL:
            out.append(" ")
            stats["fill_run"] += j - i
            i = j
            continue
        known = _PUA_KNOWN.get(ord(ch))
        if known is not None:
            out.append(known)
            stats["mapped"] += j - i
        else:
            out.append(text[i:j])
            stats["unknown"] += j - i
        i = j
    return "".join(out), stats


# ---------------------------------------------------------------------------
# R55 C2：拆字空格合并（**保守**：宁可漏合，不许把正常缩写/列举粘连）
# ---------------------------------------------------------------------------
_CJK = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
# 拆字行 = 含"汉字 空格 汉字"或"单字母 空格 单字母"（后者＝S o l a r 这种被拆开的词）
_BROKEN_CJK = re.compile(rf"[{_CJK}][ \t]+[{_CJK}]")
_BROKEN_LATIN = re.compile(r"(?<![A-Za-z])[A-Za-z][ \t][A-Za-z](?![A-Za-z])")
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")
# 间隔号两侧的空格（汉字·汉字）一并去掉：`伊姆克 ·德帕特` → `伊姆克·德帕特`
_MIDDOT_SPACE = re.compile(rf"(?<=[{_CJK}])[ \t]*[\u00b7\u30fb][ \t]*(?=[{_CJK}])")
# "被拆开"的拉丁词：由 1~3 个字母的小片段 + 单个空格组成的连续序列（如 `S o l a r`、
# `P l a n e t a ryS c i e n c e s`——真实材料里同一行会混着 1 字母与 2~3 字母的碎片）。
_ISO_RUN = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]{1,3}[ \t]){2,}[A-Za-z]{1,3}(?![A-Za-z])")
MIN_LATIN_RUN = 5      # 合并后的词至少这么长 → `A B C`/`A B C D` 这类缩写/列举不动
MIN_LATIN_DENSITY = 0.6  # 该行"被拆"程度不够就不合并（正常英文行不动）
MIN_ISOLATED = 5       # 该行至少要有这么多"孤立单字母"，否则不动（正常英文几乎没有）


def _merge_broken_spaces(text: str) -> tuple[str, int]:
    """合并"字被拆开"的空格 → ``(新文本, 合并次数)``。

    口径（复核见 NOTES §77）：
    1. **汉字之间**的空格 → 直接合并（中文正文不该有词间空格，风险低）；
    2. **拉丁字母**：只合并行内"**小碎片（1~3 个字母）+ 单空格**"的连续序列，且要同时满足
       ① 序列长度 ≥ ``MIN_LATIN_RUN``（默认 5，`S o l a r` 会并、`A B C`/`A B C D` 不动）；
       ② 该行孤立单字母 ≥ ``MIN_ISOLATED``（默认 5）；
       ③ 该行孤立单字母占该行字母数 ≥ ``MIN_LATIN_DENSITY``（正常英文行不会被误并）；
       ④ 该行字母**不是清一色大写**（`A B C D E F` / `I V X L` 这类选项/缩写行一律不动）。
    """
    text = _MIDDOT_SPACE.sub("·", text)
    n_cjk = len(_CJK_SPACE.findall(text))
    text = _CJK_SPACE.sub("", text)
    merged = n_cjk

    def fix_line(line: str) -> str:
        nonlocal merged
        letters = len(re.findall(r"[A-Za-z]", line))
        isolated = len(re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", line))
        uppers = len(re.findall(r"[A-Z]", line))
        if (letters == 0 or isolated < MIN_ISOLATED
                or isolated < MIN_LATIN_DENSITY * letters
                or (letters >= MIN_LATIN_RUN and uppers == letters)):
            return line

        def repl(m: re.Match) -> str:
            nonlocal merged
            word = re.sub(r"[ \t]", "", m.group(0))
            if len(word) < MIN_LATIN_RUN:
                return m.group(0)
            merged += 1
            return word

        return _ISO_RUN.sub(repl, line)

    return "\n".join(fix_line(ln) for ln in text.split("\n")), merged


# ---------------------------------------------------------------------------
# R55 A：抽取体检指标（在**清洗前**的原始抽取文本上算——这才是"这份 PDF 抽得好不好"）
# ---------------------------------------------------------------------------
def extract_quality(raw: str, *, pages: int, images: int, image_pages: int) -> dict:
    """抽取体检：认不出字符占比 / 拆字空格行占比 / 公式符号数 / 图片数 + 好·一般·差 三档。

    - ``unrecognized_ratio``：私用区等"没有对应字符"的字形占比（清洗**前**算，
      所以"修正过的字"仍会如实计入"这份 PDF 抽出来有多脏"）；
    - ``broken_space_ratio``：**含"汉字 空格 汉字"或孤立单字母被拆**的行占比；
    - ``formula_symbols``：`$ √ ∫ ∑ ^ _ ≤ ≥ ± × ÷ ∞ π` 计数（≈0 → 公式基本在图片里）；
    - ``images`` / ``image_pages``：图片数与含图页数（pypdf 能数到的）。
    """
    text = raw or ""
    lines = text.splitlines() or [""]
    pua = sum(1 for ch in text if is_private_use(ch))
    unrecognized = pua + text.count("\ufffd")
    ratio = unrecognized / max(1, len(text))
    broken = sum(1 for ln in lines if _BROKEN_CJK.search(ln) or _BROKEN_LATIN.search(ln))
    broken_ratio = broken / max(1, len(lines))
    # "拆得厉害"的行（一行里 ≥3 处）：判档用它——只出现一处的行（如正常的 `A 站`）不该拉低整份材料
    heavy = sum(1 for ln in lines
                if len(_BROKEN_CJK.findall(ln)) + len(_BROKEN_LATIN.findall(ln)) >= 3)
    heavy_ratio = heavy / max(1, len(lines))
    formula = sum(text.count(s) for s in ("$", "√", "∫", "∑", "^", "_", "≤", "≥", "±", "×", "÷", "∞", "π"))
    grade, why = _grade_extract(ratio, heavy_ratio, formula, pages)
    return {
        "pages": int(pages), "chars": len(text),
        "unrecognized": int(unrecognized), "unrecognized_ratio": round(ratio, 4),
        "broken_space_lines": int(broken), "broken_space_ratio": round(broken_ratio, 4),
        "broken_space_heavy_lines": int(heavy), "broken_space_heavy_ratio": round(heavy_ratio, 4),
        "formula_symbols": int(formula),
        "images": int(images), "image_pages": int(image_pages),
        "grade": grade, "grade_reason_zh": why,
    }


# 阈值取值理由（见 NOTES §77）：认不出 >5% 就会让"讲公式/图"的部分不可靠；20% 以上基本没法用。
UNRECOGNIZED_BAD = 0.05
UNRECOGNIZED_WARN = 0.005
BROKEN_SPACE_BAD = 0.6
BROKEN_SPACE_WARN = 0.2


def _grade_extract(ratio: float, broken_ratio: float, formula: int, pages: int) -> tuple[str, str]:
    """好 / 一般 / 差 + 一句人话原因（"所以会怎样"）。

    ⚠️ 这里的 ``broken_ratio`` 传进来的是**"拆得厉害的行"占比**（一行 ≥3 处），
    不是"只要有一处"的那个宽口径（后者只作为指标展示）——偶尔一处（如正常英文缩写）
    不该把整本书判低。
    """
    if ratio >= UNRECOGNIZED_BAD:
        return "差", (f"有 {ratio * 100:.1f}% 的字认不出来（目录点线、特殊符号这类字形）；"
                      "讲公式和图的部分可能不可靠，建议换更清晰的版本，或先做文字识别（OCR）。")
    if ratio >= UNRECOGNIZED_WARN or broken_ratio >= BROKEN_SPACE_BAD:
        bits = []
        if ratio >= UNRECOGNIZED_WARN:
            bits.append(f"有 {ratio * 100:.1f}% 的字认不出来")
        if broken_ratio >= BROKEN_SPACE_BAD:
            bits.append(f"有 {broken_ratio * 100:.0f}% 的行把字拆得比较厉害（`S o l a r` 这种），"
                        "系统会自动合并")
        return "一般", "；".join(bits) + "。多数情况能用，个别地方可能需要你自己核对。"
    if broken_ratio >= BROKEN_SPACE_WARN:
        return "一般", (f"有 {broken_ratio * 100:.0f}% 的行把字拆得比较厉害（系统会自动合并），"
                        "内容本身没有明显缺失。")
    return "好", "这份材料读起来很清楚，可以直接用。"


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def parse_pdf_bytes(data: bytes, *, filename: str = "") -> dict:
    """解析 PDF 字节 → ``{sections, pages, chars, body, raw_body, quality}``。

    ``body`` ＝ **修正后**（注入给模型用）；``raw_body`` ＝ **原始抽取**（留档供核查）。
    """
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
    raw_sections: list[dict] = []
    chars = 0
    images = 0
    image_pages = 0
    for i in range(total_pages):
        try:
            text = str(reader.pages[i].extract_text() or "")
        except Exception:  # 单页失败不整体崩溃（跳过该页并留痕）
            text = ""
        try:  # R55 A：图片数（数不到就当 0，不影响文本链路）
            n_img = len(list(reader.pages[i].images))
        except Exception:
            n_img = 0
        images += n_img
        image_pages += 1 if n_img else 0
        raw = _clean_raw(text)
        text = _clean(text)
        if len(text) > per_page_cap:
            text = text[:per_page_cap] + "\n…（该页文本过长，已按上限截取）"
        sections.append({"page": i + 1, "text": text})
        raw_sections.append({"page": i + 1, "text": raw[:per_page_cap]})
        chars += len(text)
    if chars == 0:
        raise PdfParseError(
            "未能从 PDF 中提取到文本（可能为扫描图片版；请改用文本粘贴，或先做 OCR 后上传）"
        )
    raw_body = "\n\n".join(f"【第 {sec['page']} 页】\n{sec['text']}" for sec in raw_sections)
    body = "\n\n".join(f"【第 {sec['page']} 页】\n{sec['text']}" for sec in sections)
    quality = extract_quality(raw_body, pages=total_pages, images=images, image_pages=image_pages)
    return {"sections": sections, "pages": total_pages, "chars": chars, "body": body,
            "raw_body": raw_body, "quality": quality}


def _clean_raw(text: str) -> str:
    """清洗**前的**原始抽取文本（只归一行尾/空白，不动字形）——留档与体检口径。"""
    text = re.sub(r"\r\n?", "\n", text or "")
    return text.strip()


def _clean(text: str) -> str:
    """抽取修正（R55 C）：先修字形（私用区），再合并拆字空格，最后归空白。"""
    text = re.sub(r"\r\n?", "\n", text or "")
    text, _ = _fold_private_use(text)
    text, _ = _merge_broken_spaces(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


__all__ = [
    "PdfParseError", "parse_pdf_bytes", "PDF_MAGIC",
    "extract_quality", "is_private_use", "_fold_private_use", "_merge_broken_spaces", "_clean",
]
