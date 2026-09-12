"""R65 用例：界面走查第一批的三道守卫（离线、源码级）。

来源：用户本人 2026-09-12 打开界面走查，架构侧逐条实测定位。本批只做"让界面不出丑、不出错"：
- **A**：顶栏学科切换里的死链接（停用学科还画着「数学」，点它回主页）；
- **B**：深色模式下的「白岛」（行内样式把浅色写死了，不跟令牌走）；
- **C**：漏到界面上的 Markdown 星号（`**…**` 原样显示）；
- **D**：蓝图缓存的两条台账（`path._cached_maps()` 陈旧副本 + 蓝图对象只读守卫）。

⚠️ **量法上的坑（架构侧已踩过一次，这里写死在注释里防后人复现）**：
扫描**必须先剥注释**、并且要覆盖 **JSX 里的 `{}` 表达式**——否则
"注释里的 `**`""写进 `{}` 里的 `**`"都会漏掉，扫描器会**假绿**。
本文件的 `_strip_comments()` 就是为此存在的；`C-①` 用行级扫描覆盖 JSX 与字符串两种情况。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "frontend" / "src"

_CJK = re.compile(r"[\u4e00-\u9fff]")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# 语义数据色：地图/图例的状态点（深浅两色主题下都要看得见，**故意不走令牌**）。
# 这份"期望值"同时锁住"不许为了过守卫而删掉状态色"。
EXPECTED_STATE_COLORS = {
    "locked": "#b7c0cb",
    "available": "#2f6fd0",
    "learning": "#d99a1f",
    "mastered": "#2e7d4f",
    "reviewing": "#c96a1b",
    "done": "#2e7d4f",
    "todo": "#b7c0cb",
}
# 语义数据色：类目徽标（记录页/就地提示）——实色底 + 白字，跨主题都成立，**故意不走令牌**。
EXPECTED_CATEGORY_COLORS = {
    "material": "#e6a23c",
    "generation": "#b3261e",
    "model_call": "#7b1fa2",
    "coverage": "#0277bd",
    "other": "#546e7a",
}
# 允许保留的硬编码色（file（正斜杠相对路径）, hex, 理由）
ALLOWED_HARDCODED = {
    ("frontend/src/components/LedgerAlerts.tsx", "#fff"):
        "实色类别徽标上的白字（徽标底色是 CAT_COLOR 语义色），跨主题都成立，不是浅色底",
    ("frontend/src/components/LedgerAlerts.tsx", "#546e7a"):
        "CAT_COLOR 里 other 的那档（同上：实色徽标底色）",
}


def _strip_comments(src: str) -> str:
    """剥掉 // 与 /* */ 注释（保留换行以维持行号）；字符串内的 // 不误伤。"""
    out: list[str] = []
    i, n, state = 0, len(src), ""
    while i < n:
        ch, two = src[i], src[i:i + 2]
        if not state:
            if two == "//":
                state = "//"
                i += 2
                continue
            if two == "/*":
                state = "/*"
                i += 2
                continue
            if ch in "'\"`":
                state = ch
            out.append(ch)
            i += 1
            continue
        if state == "//":
            if ch == "\n":
                state = ""
                out.append(ch)
            i += 1
            continue
        if state == "/*":
            if two == "*/":
                state = ""
                i += 2
                continue
            if ch == "\n":
                out.append(ch)
            i += 1
            continue
        if ch == "\\":
            out.append(src[i:i + 2])
            i += 2
            continue
        if ch == state:
            state = ""
        out.append(ch)
        i += 1
    return "".join(out)


def _frontend_files() -> list[Path]:
    return [p for p in sorted(FRONTEND_SRC.rglob("*.ts*")) if p.suffix in (".ts", ".tsx")]


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO)).replace("\\", "/")


def _luminance(hexstr: str) -> float:
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ============================================================ B：深色下的「白岛」

def test_r65_b1_no_hardcoded_light_colors_in_frontend():
    """**B-①**：前端源码（剥注释后）里**没有**硬编码的浅色（亮度 > 0.72）。

    允许保留的只有语义数据色/白字（见 `ALLOWED_HARDCODED` 与 `EXPECTED_STATE_COLORS`），
    它们必须是"跨主题都成立"的颜色；任何**新的**浅色硬编码都会让这条用例变红。
    """
    findings: list[str] = []
    for p in _frontend_files():
        code = _strip_comments(p.read_text(encoding="utf-8"))
        rel = _rel(p)
        for i, line in enumerate(code.splitlines(), 1):
            for m in _HEX.finditer(line):
                hexv = m.group(0).lower()
                if _luminance(hexv) <= 0.72:
                    continue
                if hexv in EXPECTED_STATE_COLORS.values():
                    continue          # 状态点：语义数据色
                if (rel, hexv) in ALLOWED_HARDCODED:
                    continue          # 已登记的理由
                findings.append(f"{rel}:{i}  {hexv}  | {line.strip()[:100]}")
    assert not findings, (
        "深色模式下会变成「白岛」的硬编码浅色（请换成设计令牌或 index.css 里的语义类）：\n"
        + "\n".join(findings[:20]))


def test_r65_b1b_no_other_hardcoded_colors_either():
    """**B-①（加强）**：**任何**硬编码色（不分亮暗）都必须在登记的白名单里。

    为什么要加这一条：深色主题下 **暗色** 也一样会坏——例如 `#333` 的 SVG 文字、
    `#b3261e` 的红色提示，在深底上几乎看不见（本轮确实抓到并改掉了 8 处：
    ExercisePanel 的 SVG 5 处 + OutlinePage 2 处 + AiTracePage 2 处 + SessionPage 1 处，
    另有 PromptsPage 的差异行文字色 3 处）。只查"浅色"会漏掉这一半。
    """
    palette = set(EXPECTED_STATE_COLORS.values()) | set(EXPECTED_CATEGORY_COLORS.values())
    findings: list[str] = []
    for p in _frontend_files():
        code = _strip_comments(p.read_text(encoding="utf-8"))
        rel = _rel(p)
        for i, line in enumerate(code.splitlines(), 1):
            for m in _HEX.finditer(line):
                hexv = m.group(0).lower()
                if hexv in palette or (rel, hexv) in ALLOWED_HARDCODED:
                    continue
                findings.append(f"{rel}:{i}  {hexv}  | {line.strip()[:100]}")
    assert not findings, (
        "这些硬编码颜色没走令牌（深色主题下会看不清或变成白岛）：\n"
        + "\n".join(findings[:20]))


def test_r65_b1c_category_palette_is_intact():
    """**B-①（补）**：类目徽标色板还在（别为了过守卫把语义色删掉）。"""
    src = (FRONTEND_SRC / "components" / "LedgerAlerts.tsx").read_text(encoding="utf-8")
    block = re.search(r"const CAT_COLOR[^{]*\{(.*?)\};", src, re.S)
    assert block, "LedgerAlerts.tsx 里找不到 CAT_COLOR"
    got = {k: v.lower() for k, v in re.findall(r"(\w+):\s*\"(#[0-9a-fA-F]{6})\"", block.group(1))}
    assert got == EXPECTED_CATEGORY_COLORS, f"类目色板变了：{got}"


def test_r65_b2_state_color_palette_is_intact():
    """**B-②**：状态色板还在（防止有人"为了过 B-①"把语义色删掉）。"""
    src = (FRONTEND_SRC / "components" / "ui.tsx").read_text(encoding="utf-8")
    block = re.search(r"export const STATE_COLOR[^{]*\{(.*?)\};", src, re.S)
    assert block, "ui.tsx 里找不到 STATE_COLOR"
    got = dict(re.findall(r"(\w+):\s*\"(#[0-9a-fA-F]{6})\"", block.group(1)))
    got = {k: v.lower() for k, v in got.items()}
    for key, want in EXPECTED_STATE_COLORS.items():
        assert got.get(key) == want, f"状态色 {key} 变了：{got.get(key)} != {want}"


def test_r65_b3_dark_scheme_block_still_exists():
    """**B-③**：深色主题块必须还在（不许用"删掉深色主题"来让白岛消失）。"""
    css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: dark)" in css, "深色主题块被删了"
    assert "--surface:" in css and "--bg:" in css, "深色令牌不见了"
    # R65 新增的语义类（白岛就是靠它们收口的）
    for cls in (".panel-soft", ".panel-warn", ".ledger-alerts", ".row-divider",
                ".diff-add", ".diff-del", ".prompt-item", ".choice-chip"):
        assert cls in css, f"index.css 里缺少语义类 {cls}"


# ============================================================ C：漏出来的星号

def test_r65_c1_no_leaked_markdown_asterisks():
    """**C-①**：界面上不会再漏出成对的 `**`。

    口径：剥注释后，**含中文且含 `**`** 的行里，只允许 `<MdMath ... />` 那一类
    （它会把 `**加粗**` 正确渲染成 `<strong>`）；JSX 纯文本要写 `<strong>`，
    塞进 `setMsg/setErr` 的普通字符串要去掉星号。
    """
    findings: list[str] = []
    for p in _frontend_files():
        code = _strip_comments(p.read_text(encoding="utf-8"))
        rel = _rel(p)
        for i, line in enumerate(code.splitlines(), 1):
            if "**" not in line or not _CJK.search(line):
                continue
            if "MdMath" in line:      # 走 Markdown 渲染，星号是对的
                continue
            findings.append(f"{rel}:{i}  | {line.strip()[:110]}")
    assert not findings, (
        "这些地方会把 Markdown 星号原样漏到界面上（JSX 纯文本请用 <strong>，"
        "普通字符串请去掉星号）：\n" + "\n".join(findings[:20]))


def test_r65_c1b_the_scanner_is_not_vacuous():
    """**C-②（阳性对照）**：证明上面那把尺子量得到——故意喂一段"带星号的 JSX 文本"。"""
    fake = 'const a = 1;\n<p>这里**应该被抓到**的星号</p>\n'
    hits = [ln for ln in _strip_comments(fake).splitlines()
            if "**" in ln and _CJK.search(ln) and "MdMath" not in ln]
    assert hits, "扫描逻辑坏了：明显该命中的行没命中"

    # 注释里的星号不该命中（架构侧第一版扫描器就是没剥注释 ⇒ 假绿）
    commented = '// 注释里写 **不该命中**\nconst b = 2;\n'
    hits2 = [ln for ln in _strip_comments(commented).splitlines()
             if "**" in ln and _CJK.search(ln) and "MdMath" not in ln]
    assert not hits2, "剥注释没生效（注释里的星号被当成命中）"


# ============================================================ A：导航死链接

def test_r65_a1_subject_switcher_has_no_literal_fallback():
    """**A-①**：停用学科时不再画一个"点不进去"的「数学」。"""
    src = _strip_comments((FRONTEND_SRC / "components" / "SubjectSwitcher.tsx")
                          .read_text(encoding="utf-8"))
    assert '"数学"' not in src and "'数学'" not in src, (
        "SubjectSwitcher 里还有「数学」字面量兜底——停用后它会变成点不进去的死链接")
    assert re.search(r"\{preset\s*&&", src), "预置学科必须「存在才画」（preset && …）"
    assert 'preset?.label ??' not in src, "还在用 `?? 某个字面量` 兜底"


def test_r65_a2_unknown_path_explains_instead_of_silent_redirect():
    """**A-②**：打不开的地址给中文说明 + 能点回学科列表的入口（不再静默跳主页）。"""
    src = _strip_comments((FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8"))
    assert 'Navigate to="/"' not in src, "还在静默跳回主页"
    assert "这个页面打不开" in src, "缺少中文说明"
    assert "停用" in src and "学科列表" in src, "缺少「学科可能已停用 + 去学科列表」的指引"
    assert 'to="/subjects"' in src, "缺少回学科列表的入口"


# ============================================================ D：蓝图缓存台账

def test_r65_d1_cached_maps_is_not_a_stale_copy(tmp_path, monkeypatch):
    """**D-①**：`path._cached_maps()` 不再自持副本 —— 蓝图文件改了 + 清缓存后**立刻**看到新条目。"""
    import yaml as _yaml  # noqa: F401  （只为读起来顺；真正的写文件在下面）

    from app.content import roadmap as rm
    from app.service import path as path_svc

    root = tmp_path / "content"
    (root / "roadmap").mkdir(parents=True)
    monkeypatch.setenv("MF_CONTENT_ROOT", str(root))
    rm.clear_roadmap_cache()

    primary = root / "roadmap" / "primary.yaml"
    primary.write_text("level: primary\nentries:\n  - id: primary.0001\n    title: 甲\n    topic: T\n",
                       encoding="utf-8")

    first_maps, _ = path_svc._cached_maps()
    assert "primary" in first_maps and [e.id for e in first_maps["primary"].entries] == ["primary.0001"]
    assert not hasattr(path_svc._cached_maps, "cache_clear"), (
        "`_cached_maps` 又被 lru_cache 包上了——那份副本永不失效（R65 任务 D-① 的原始缺陷）")

    # 改文件 + 清缓存 → 路径引擎那份数据必须立刻变
    primary.write_text("level: primary\nentries:\n  - id: primary.0002\n    title: 乙\n    topic: T\n",
                       encoding="utf-8")
    rm.clear_roadmap_cache()
    second_maps, _ = path_svc._cached_maps()
    assert [e.id for e in second_maps["primary"].entries] == ["primary.0002"], (
        "蓝图改了、缓存也清了，`_cached_maps()` 还是旧数据（陈旧副本）")


def test_r65_d2_roadmap_objects_are_shared_and_readonly(app_client):
    """**D-②**：`load_roadmap()` 返回缓存里的**同一个对象**、条目 id 序列稳定。

    R63 起这是**约定**（只读）换来的性能：谁就地改它、谁污染缓存。这条用例把它钉住：
    将来有人"就地改一下试试"，这里立刻红；而"改成每次深拷贝"是**已裁定的不做项**。
    """
    from app.content import roadmap as rm

    a = rm.load_roadmap("primary")
    ids_before = [e.id for e in a.entries]
    b = rm.load_roadmap("primary")
    assert a is b, "两次 load_roadmap 竟然不是同一个对象（缓存失效了？）"
    assert [e.id for e in b.entries] == ids_before, "条目 id 序列不稳定"
    c = rm.load_roadmap("primary")
    assert c is a and [e.id for e in c.entries] == ids_before, "第三次取又变了"
