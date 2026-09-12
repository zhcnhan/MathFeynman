"""R61 任务 B 用例：**报错文案去掉内部变量名**（说人话 + 指向用户真能改的地方）。

工单 `.runtime/EULER_TICKET_R61.md` §3（= docs/09 R61 §3-2/§3-3）：
1. `pdfrender` 的单页体量保护报错原来带着内部变量名（用户根本改不了那个变量）→
   改为**中文 + 可操作**（说清第几页、多大、去哪儿改）；
2. **全仓扫一遍**：`backend/app` 的**用户可见文案**里内部变量名命中必须 **0**；
3. 回归：R60 的 `a4` 用例按新文案更新后，**断言意图不变**（仍是"造错必报中文"）。

本文件是**自包含**的（不 import `ui_copy_guard`，避免与 R52 那套口径耦合）：
- B-①：真造一次"单页太大"，检查**实际抛出来的**中文报错；
- B-②/B-③：**AST 源码级**扫描 `backend/app/**/*.py` 的**每一条 `raise`**（含 f-string 的字面量部分），
  断言其中没有内部变量名/表名；B-③ 额外报出**扫了多少文件**（防止在空集上假绿）。

排除口径（为什么这样扫，见 `_docstring_nodes` / `_raise_strings` 的注释）：
- **docstring**（模块/类/函数的第一段字符串）不是给用户看的东西 → 排除；
- `os.getenv("MF_…")` 这类**参数**不在 `raise` 子树里，天然扫不到（那是配置读取，不是文案）；
- 注释根本不进 AST（源码级扫描只看字符串字面量）；
- 账目/审计/诊断里允许有内部名，但**账目原因会显示在记录页**——本用例的 `raise` 口径覆盖
  "抛给用户看的报错"，账目文案由 B-④ 的动态用例与既有 `test_r52_ui_copy_plain_language.py` 兜住。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND_APP = REPO / "backend" / "app"

# 硬禁用（工单 §3-2-② 点名）：内部环境变量名 / 内部表名。
# ⚠️ 允许清单**故意留空**——R61 之后 `backend/app` 的 raise 文案里一处都不该有；
# 若将来确有必须保留的正当例外，在这里加 (相对路径, 行号, 理由) 三元组并写明原因。
_BANNED: tuple[tuple[str, str], ...] = (
    (r"\bMF_[A-Z0-9_]+", "内部环境变量名 MF_*（用户改不了）"),
    (r"\b(?:LLM|HF|OPENAI|DEEPSEEK)_[A-Z0-9_]+", "内部环境变量名（例如各家的 API Key）"),
    (r"\b(?:app_settings|prompt_overrides|ai_logs|content_ledger)\b", "数据库内部表名"),
)
ALLOWLIST: tuple[tuple[str, int, str], ...] = ()

_CJK = re.compile(r"[\u4e00-\u9fff]")
# 单页报错里**不许**出现的其它内部说法（R61 任务 B 的"说人话"面）
_INTERNAL_EXTRA = ("docs/", "schema")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """模块/类/函数**第一段字符串**（docstring）的节点 id —— 这些不是用户可见文案。"""
    out: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            out.add(id(body[0].value))
    return out


def _raise_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """每条 ``raise`` → ``[(行号, 字符串片段)]``。

    **f-string 的"字面量部分"也算**（`ast.walk` 会走到 `JoinedStr` 里的 `Constant`）；
    `{变量}` 的取值部分不是字面量，扫不到——这正是我们要的（动态值不是硬编码的内部名）。
    docstring 节点显式排除（虽然 `raise` 子树里通常不会有，写出来是为了口径明确、防将来变形）。
    """
    skip = _docstring_nodes(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and id(sub) not in skip:
                out.append((int(getattr(sub, "lineno", getattr(node, "lineno", 0))), sub.value))
    return out


def scan_app_raises(root: Path | None = None) -> tuple[list[Path], list[str]]:
    """扫 ``backend/app/**/*.py`` 的 raise 文案 → ``(扫到的文件列表, 命中列表)``。

    命中串给人看：``相对路径:行号 命中「…」（为什么）→ 原文``（失败信息里直接可用）。
    """
    base = root or BACKEND_APP
    files = sorted(base.rglob("*.py"))
    allowed = {(str(rel).replace("\\", "/"), int(line)) for rel, line, _why in ALLOWLIST}
    findings: list[str] = []
    for p in files:
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for line, text in _raise_strings(tree):
            if (rel, line) in allowed:
                continue
            for pat, why in _BANNED:
                hit = re.search(pat, text)
                if hit:
                    findings.append(f"{rel}:{line} 命中「{hit.group(0)}」（{why}）→ {text.strip()[:90]}")
    return files, findings


def _assert_plain(msg: str) -> None:
    """一条用户可见报错的通用体检：中文 + 无内部名 + 无内部编号/字段名。"""
    assert _CJK.search(msg), f"报错不是中文：{msg!r}"
    assert not re.search(r"MF_[A-Z_]+", msg), f"报错里有内部环境变量名：{msg!r}"
    assert not re.search(r"(LLM|HF|OPENAI|DEEPSEEK)_[A-Z_]+", msg), f"报错里有内部环境变量名：{msg!r}"
    assert not re.search(r"R\d+", msg), f"报错里有内部编号：{msg!r}"
    for bad in _INTERNAL_EXTRA:
        assert bad not in msg, f"报错里有内部说法「{bad}」：{msg!r}"


# ============================================================ B-① 单页太大：中文 + 可操作

def test_r61_b1_single_page_too_big_is_plain_chinese():
    """**B-①**：造"单页太大" → **中文**报错、**不含内部变量名**、**含可操作指引**。

    修复前这条是：``第 1 页渲染出来太大（48 KB > 1 KB）——请把目标宽度调小（MF_PAGE_IMAGE_WIDTH）后重试``。
    """
    from r58_support import sample_pdf

    from app.outline import pdfrender

    with pytest.raises(pdfrender.PdfRenderError) as e:
        pdfrender.render_pages(sample_pdf(2), pages="1", max_bytes=1024)
    msg = str(e.value)
    _assert_plain(msg)
    # 可操作指引：必须告诉用户**去哪儿改**（出图宽度 / 设置入口），不能只说"失败了"
    assert ("宽度" in msg or "设置" in msg), f"报错没有可操作指引：{msg!r}"
    # 数字照实留（"说人话"不等于把页号/体量删掉）
    assert "第 1 页" in msg and "KB" in msg, f"报错丢了页号或体量：{msg!r}"
    # 给足体量上限 → 同一页正常出图（说明这条报错只来自体量保护，不是别的问题）
    ok = pdfrender.render_pages(sample_pdf(2), pages="1", max_bytes=4 * 1024 * 1024)
    assert len(ok) == 1 and ok[0]["page_no"] == 1


# ============================================================ B-② 全仓 raise 文案扫描

def test_r61_b2_no_internal_names_in_user_visible_backend_copy():
    """**B-②**：AST 扫 `backend/app` 的每一条 `raise` 文案 → 内部变量名/表名命中 = 0。"""
    _files, findings = scan_app_raises()
    assert not findings, (
        "用户可见报错里出现了内部变量名/表名（工单 §3-2-② 要求 0 命中）：\n"
        + "\n".join(findings))


def test_r61_b3_scan_covers_whole_app_and_reports_zero():
    """**B-③**：同一次扫描**报出扫了多少文件**并断言 0 命中（不许在空集上假绿）。"""
    files, findings = scan_app_raises()
    print(f"[R61 B] 扫了 backend/app 下 {len(files)} 个 .py 文件，raise 文案命中 {len(findings)} 处")
    assert len(files) >= 30, f"只扫到 {len(files)} 个文件，这个守卫可能扫空了（本该 ≥30）"
    assert findings == [], "\n".join(findings)


# ============================================================ B-④ R60/R59 报错也干净（钉住）

def test_r61_b4_r60_page_cap_errors_are_still_plain_chinese():
    """**B-④**：R60 改过的页数/页范围报错**本来就是干净的**——这里钉住，防回退。"""
    from r58_support import sample_pdf

    from app.outline import pdfrender

    with pytest.raises(pdfrender.PdfRenderError) as e1:      # 整本超页数上限
        pdfrender.render_pages(sample_pdf(3), max_pages=1)
    with pytest.raises(pdfrender.PdfRenderError) as e2:      # 页范围写法看不懂
        pdfrender.parse_pages("abc", 3)
    with pytest.raises(pdfrender.PdfRenderError) as e3:      # 页数超出这本书
        pdfrender.parse_pages("9", 3)
    for msg in (str(e1.value), str(e2.value), str(e3.value)):
        _assert_plain(msg)
    # 页数超限的替代路必须仍是**真的能走**的那条（R60 A-③ 的口径）
    assert "指定页范围" in str(e1.value), str(e1.value)
    assert "只读其中一段" not in str(e1.value), str(e1.value)
    assert "拆分后分批导入" not in str(e1.value), str(e1.value)
