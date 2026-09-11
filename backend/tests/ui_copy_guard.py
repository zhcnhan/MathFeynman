"""R52：**界面文案守卫**（源码级扫描）——"给用户看的东西必须说人话"。

背景（用户 2026-09-11 当面指令）：整个程序给用户看的文案要说人话、简洁；
**界面上不得出现内部编号 / 字段名 / 工程黑话**。

做法（前端没有测试运行器，故按工单 §5-1 授权做**源码级**扫描并纳入 pytest）：
1. 去掉注释（注释里允许保留 R 编号等内部指代）与 import 行；
2. 抽出**含中文的字符串字面量**与 **JSX 文本节点**（＝会渲染到界面的文本）；
3. 断言其中不出现禁用模式（内部编号 / 字段名 / 文件名 / 工程黑话）。

另提供**后端**扫描（`backend/app/**/*.py` 里含中文的字符串字面量）——后端有大量中文是
**账目记录/诊断说明**，本批只对"渲染成界面标签/承诺/说明"的那部分负责，故后端扫描
**只查硬模式**（编号 / 字段名 / 文件名），术语表口径由前端扫描兜住。

用法（人工盘点，不写文件）：`.\.venv\Scripts\python backend/tests/ui_copy_guard.py`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
BACKEND_APP = REPO_ROOT / "backend" / "app"

# 硬禁用（工单 §5-1 点名）：内部编号 / 字段名 / 文件名 / 依赖名
HARD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"R\d+", "内部编号（R38 这类）"),
    (r"§", "文档章节号（§）"),
    (r"docs/", "文档路径"),
    (r"schema", "字段/格式名 schema"),
    (r"inject_max_chars", "字段名 inject_max_chars"),
    (r"batch_chars", "字段名 batch_chars"),
    (r"trace_path", "字段名 trace_path"),
    (r"MF_", "环境变量名 MF_*"),
    (r"pytest", "工具名 pytest"),
    (r"roadmap", "内部名 roadmap"),
    (r"Phase\s*[A-Z]", "内部阶段名 Phase X"),
)

# 术语表（工单 §3-B2）：工程黑话 → 人话；界面上不得出现左边这些词
JARGON_TERMS: tuple[tuple[str, str], ...] = (
    ("注入", "读/读进去"),
    ("预算", "读多少"),
    ("吸纳", "读了"),
    ("落库", "存下来"),
    ("落盘", "存成文件"),
    ("拦截", "挡下"),
    ("降级", "退而求其次"),
    ("丢弃", "没用上"),
    ("截断", "被截掉"),
    ("幂等", "（不用这个词）"),
    ("溯源", "依据/来自书的哪里"),
    ("闸门", "检查"),
    ("门禁", "学习顺序门槛"),
    ("铁则", "（不用这个词）"),
    ("一切显性", "（不用这个词）"),
    ("熔断", "质量预警"),
    ("总账", "记录"),
    ("账本", "记录"),
    ("覆盖账", "章节进度"),
    ("未纳入", "没读"),
    ("未覆盖", "还没出内容"),
    ("批次", "次"),
    ("字符", "字"),
    ("蓝图", "课程安排"),
    ("节点", "知识点"),
    ("校验", "检查"),
    ("回炉", "重新学一遍"),
    ("auto", "自动生成"),
)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_STR_LIT = re.compile(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`""")
_JSX_TEXT = re.compile(r">([^<>{}]+)<")


class Finding:
    __slots__ = ("path", "line", "kind", "pattern", "text")

    def __init__(self, path: str, line: int, kind: str, pattern: str, text: str):
        self.path, self.line, self.kind, self.pattern, self.text = path, line, kind, pattern, text

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f"{self.path}:{self.line} [{self.kind}] 命中「{self.pattern}」→ {self.text[:80]}"


def strip_comments(src: str) -> str:
    """去掉 `//` 与 `/* */` 注释（保留换行以维持行号）；字符串内的 `//` 不误伤。"""
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


def _units(line: str) -> list[tuple[str, str]]:
    """一行里"会渲染的文本"单元：字符串字面量 + JSX 文本节点。返回 (kind, text)。"""
    out: list[tuple[str, str]] = []
    for m in _STR_LIT.finditer(line):
        out.append(("字符串", m.group(1) or m.group(2) or m.group(3) or ""))
    for m in _JSX_TEXT.finditer(line):
        out.append(("界面文本", m.group(1)))
    return out


def scan_source(text: str, *, rel: str, terms: tuple[tuple[str, str], ...],
                hard: tuple[tuple[str, str], ...]) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(strip_comments(text).splitlines(), start=1):
        s = line.strip()
        if s.startswith("import ") or s.startswith("} from ") or s.startswith("from "):
            continue
        for kind, unit in _units(line):
            if not _CJK.search(unit):
                continue
            for pat, why in hard:
                if re.search(pat, unit):
                    findings.append(Finding(rel, lineno, kind, f"{pat}（{why}）", unit.strip()))
            for term, plain in terms:
                if term in unit:
                    findings.append(Finding(rel, lineno, kind, f"{term} → 应为「{plain}」", unit.strip()))
    return findings


def scan_frontend(root: Path | None = None) -> list[Finding]:
    base = root or FRONTEND_SRC
    out: list[Finding] = []
    for p in sorted(base.rglob("*.ts*")):
        out += scan_source(p.read_text(encoding="utf-8"), rel=str(p.relative_to(REPO_ROOT)),
                           terms=JARGON_TERMS, hard=HARD_PATTERNS)
    return out


def scan_backend(root: Path | None = None) -> list[Finding]:
    """只查硬模式（后端中文多为账目/诊断记录，术语表口径由前端扫描兜住）。"""
    base = root or BACKEND_APP
    out: list[Finding] = []
    for p in sorted(base.rglob("*.py")):
        out += scan_source(p.read_text(encoding="utf-8"), rel=str(p.relative_to(REPO_ROOT)),
                           terms=(), hard=HARD_PATTERNS)
    return out


def report() -> int:
    for label, findings in (("前端（frontend/src）", scan_frontend()),
                            ("后端（backend/app）", scan_backend())):
        print(f"\n=== {label}：{len(findings)} 处 ===")
        for f in findings:
            print(" ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(report())
