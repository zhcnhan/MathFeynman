"""content.verify：**语义自检闸门**（R35 §12）——模板题的"答案与题面语义是否自洽"。

病根（架构侧结论）：`answer_expr` 与题干由**同一次 LLM 调用同时产出** → 它**自证**；
既有 validate 只验"可渲染/可解析/constraint 成立"，**把 answer_expr 当真理** →
永远验不出"答案与题面语义矛盾"（负数、半个苹果、LCM 写成 a*b…）。

三层（**学科无关是第一原则**）：
1. **通用层（所有学科）**：渲染 N 个 seed → 结果必须满足**内容显式声明**的领域谓词
   （`semantics.domain`: `nonneg` / `integer` / `ratio`）。吃的是**声明**，不是猜题面关键词。
   另有一条**学段政策**：`level ∈ 小学学段` 的节点默认 `nonneg+integer`（小学内容不出现负数/半个苹果；
   数学课标事实，非"数学分支"）；内容可显式声明 `domain` 覆盖它。
2. **L1 验算插件层（按学科注册）**：`math` 是第一个实例（sympy 独立验算 `expect` 与 `answer_expr` +
   逐条检查 `requires` 是否被 `constraint` 保证）。将来"数值+单位""代码沙箱"按**同一接口**注册。
3. **没有 L1 验算器的学科**：答案对错机器验不了 —— 如实标注 `l1=None`（**不是漏做**）；
   它们仍必须过通用层 + R35 可答性 + 既有护栏（人工锚点/纠错反馈/熔断）。

实现红线：
- **禁止** `if subject == "math"` 之类的分支；验算器一律经注册表解析（`register_l1` / `l1_for`）。
- 通用层谓词**必须由内容声明**（推不出来就要求声明，不猜）。
- `constraint` **必须强制题面里的每一个条件**（`requires`）；违反 → 拒绝入库。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .schemas import LEVELS, BasisDoc, ExerciseDoc, NodeDoc, TemplateDoc
from .templates import render_exercise

PRIMARY_LEVEL = "primary"

# §13 裁决 4：数学模板必须能独立验算（未声明 expect = **违规**，不再只是 finding）
NO_EXPECT_PROBLEM = ("未声明 semantics.expect：本模板的答案**无法独立验算**"
                     "（数学模板必须声明「答案的独立算式」；不得让 answer_expr 自证）")
# 非数学学科：如实分界（不判违规，但必须**显式标注**并计入护栏统计）
NO_L1_MARKER = "本模板无独立验算（该学科未注册 L1 验算插件——如实分界，仅通用层+可答性+护栏）"

# 题面"条件性表述"的关键词（**仅用于体检时的结构性提示**：说了条件却没声明 semantics → 无法验证；
# 绝不用于自动判定对错——判定只认内容声明的 domain/expect/requires）
CONDITION_HINTS = ("其中", "倍数", "余数", "商", "按", "还剩", "剩下", "至少", "不超过", "最多", "不少于",
                   "平均", "比", "率", "占")


@dataclass
class TemplateVerdict:
    """单个模板题的闸门结论。problems=违规（拒绝入库）；findings=无法验证（须声明/无验算器）。"""

    node_id: str
    ex_id: str
    ok: bool = True
    seeds_checked: int = 0
    domain: dict = field(default_factory=dict)
    l1: str | None = None
    l1_available: bool = False          # §13 裁决 4：非数学学科必须**显式标注**"无独立验算"
    verified: bool = False              # 是否真的被独立验算过（有 L1 且声明了 expect）
    problems: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id, "ex_id": self.ex_id, "ok": self.ok,
            "seeds_checked": self.seeds_checked, "domain": self.domain, "l1": self.l1,
            "l1_available": self.l1_available, "verified": self.verified,
            "problems": self.problems, "findings": self.findings, "samples": self.samples[:3],
        }


# ---------------------------------------------------------------------------
# 命名空间 / 学科解析（不写学科分支：只做命名空间映射）
# ---------------------------------------------------------------------------
def subject_of(node_id: str) -> str:
    """内容节点 id → 学科（math preset 的 level 命名空间归 math；其余首段即 subject id）。"""
    prefix = node_id.split(".", 1)[0]
    return "math" if prefix in LEVELS else prefix


# ---------------------------------------------------------------------------
# L1 验算插件注册表
# ---------------------------------------------------------------------------
class L1Verifier(Protocol):
    """L1 结构化可验插件（docs/14 §2.4 的实例接口）。"""

    name: str

    def verify(self, *, node_id: str, ex: ExerciseDoc, tpl: TemplateDoc, params: dict[str, Any],
               answer: str, semantics: dict) -> tuple[list[str], list[str]]:
        """返回 (problems, findings)。"""
        ...


_L1_VERIFIERS: dict[str, L1Verifier] = {}
_BUILTINS_LOADED = False


def register_l1(subject: str, verifier: L1Verifier) -> None:
    _L1_VERIFIERS[subject] = verifier


def _load_builtin_verifiers() -> None:
    """惰性加载内置插件（插件模块在导入时自行注册；此处不含任何学科分支）。"""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from . import l1_math  # noqa: F401  （导入即注册 "math"）


def l1_for(subject: str) -> L1Verifier | None:
    _load_builtin_verifiers()
    return _L1_VERIFIERS.get(subject)


# ---------------------------------------------------------------------------
# 通用层：领域谓词（吃声明；无声明 → finding，不猜）
# ---------------------------------------------------------------------------
def effective_domain(doc: NodeDoc, tpl: TemplateDoc) -> tuple[dict, bool]:
    """生效的领域谓词 = 内容声明 ∪ 学段政策。返回 (domain, declared)。

    **学段政策只加 `nonneg`**（小学内容不出现负数——数学课标事实，与学科无关的学段政策）；
    `integer` **必须由内容显式声明**：只有内容知道"答案是不是离散量"（分数加法、百分比、单位换算
    在小学同样合法），猜关键词会误杀（实测：同分母分数加法被判"非整数"是假阳性）。
    """
    declared = (tpl.semantics or {}).get("domain") if isinstance(tpl.semantics, dict) else None
    dom = dict(declared) if isinstance(declared, dict) else {}
    if doc.level == PRIMARY_LEVEL:
        dom.setdefault("nonneg", True)
    return dom, bool(isinstance(declared, dict) and declared)


def _as_number(text: str) -> float | None:
    """答案文本 → 数值（支持 3/5、-8、55/2、0.3 等；非数值返回 None）。走统一求值实现。"""
    from . import exprs

    s = (text or "").strip()
    if not s:
        return None
    # 方程解展示形如 "x = 2"（判题本身接受裸数字）→ 取等号右侧的数值
    m = re.fullmatch(r"[A-Za-z]\s*=\s*(.+)", s)
    if m:
        s = m.group(1).strip()
    try:
        return exprs.eval_number(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


def static_prompt_text(tpl: TemplateDoc) -> str:
    """把题干里的参数占位替换成标记，得到**作者写的静态文本**（含"如 x=5"这类示例）。

    用于题面泄漏判定：答案若出现在**静态文本**里 → 泄漏；参数值出现在题干里属正常（题目本身）。
    """
    text = str(tpl.prompt or "")
    for name in (tpl.params or {}):
        text = text.replace("{" + str(name) + "}", "\u27e6" + str(name) + "\u27e7")
    return text


_HINT_SEG_RE = re.compile(r"[（(]([^（()）]*)[）)]|(?:如|例如)([^，。；;）)]*)")


def hint_segments(tpl: TemplateDoc) -> list[str]:
    """题干的**提示/示例片段**（括号内、或「如/例如」之后）——泄漏只可能出在这里。"""
    static = static_prompt_text(tpl)
    out: list[str] = []
    for m in _HINT_SEG_RE.finditer(static):
        seg = (m.group(1) or m.group(2) or "").strip()
        if seg:
            out.append(seg)
    return out


def leak_problems(tpl: TemplateDoc, rendered_prompt: str, answer: str, *, seed: int) -> list[str]:
    """题面泄漏（§14）：**答案原样出现在题干的提示/示例片段里** → 违规。

    只扫提示片段（（…） / 如…）：题干正文里的数字（比例 1:2、被减数…）是题目本身的一部分，
    不算泄漏；而「如 x=5」「如 3/5」这类示例等于答案，就是**直接漏答案**。
    """
    out: list[str] = []
    ans = str(answer or "").strip()
    if not ans:
        return out
    for seg in hint_segments(tpl):
        if re.search(rf"(?<![\\d.]){re.escape(ans)}(?![\\d.])", seg):
            out.append(f"题面泄漏（seed={seed}）：答案 {ans!r} 原样出现在题干示例/提示「{seg}」里"
                       "（示例不得等于任一 seed 的答案，请改成占位形式，如「如 x=…」）")
            break
    return out


def check_domain_rule(answer: str, domain: dict) -> list[str]:
    """通用层：单条答案是否违反声明的领域谓词（学科无关）。"""
    problems: list[str] = []
    if domain.get("ratio"):
        if ":" not in str(answer):
            problems.append(f"domain.ratio：答案应为「a:b」形式的比，实得 {answer!r}")
    val = _as_number(answer)
    if (domain.get("nonneg") or domain.get("integer")) and val is None:
        return problems + [f"通用层无法把答案 {answer!r} 解析为数值，无法验证 nonneg/integer"]
    if val is not None:
        if domain.get("nonneg") and val < 0:
            problems.append(f"结果为负（{val}），违反 domain.nonneg（题面已声明数量/金额非负）")
        if domain.get("integer") and abs(val - round(val)) > 1e-9:
            problems.append(f"结果非整数（{val}），违反 domain.integer（题面声明是个数/只数/元数等离散量）")
    return problems


# ---------------------------------------------------------------------------
# 闸门主流程
# ---------------------------------------------------------------------------
def check_template(node_id: str, doc: NodeDoc, ex: ExerciseDoc, *, seeds: int = 8) -> TemplateVerdict:
    tpl = ex.template
    subject = subject_of(node_id)
    verdict = TemplateVerdict(node_id=node_id, ex_id=ex.id, l1=(l1_for(subject).name if l1_for(subject) else None))
    if tpl is None:
        verdict.problems.append(f"{ex.id}: 模板缺失")
        verdict.ok = False
        return verdict
    domain, declared = effective_domain(doc, tpl)
    verdict.domain = domain
    semantics = tpl.semantics if isinstance(tpl.semantics, dict) else {}
    verifier = l1_for(subject)
    verdict.l1_available = verifier is not None
    verdict.verified = bool(verifier is not None and str(semantics.get("expect") or "").strip())

    # §14 步骤 3：**模板级依据**（规则句）——给了就必须逐字出自本节点讲解；数学模板建议声明
    if isinstance(getattr(tpl, "basis", None), dict):
        tpl.basis = BasisDoc(**tpl.basis)
    if getattr(tpl, "basis", None) is not None:
        from . import citations as _cit

        _q = str(getattr(tpl.basis, "quote", "") or "")
        _src = doc.explanation.body or doc.body_md or ""
        if not _q or not _cit.is_valid(_q, _src):
            verdict.problems.append(
                f"模板依据（basis.quote）不成立：{'未给出引文' if not _q else '引文不逐字出自本节点讲解'}"
                f"（须为支撑本模板的那句规则句，≥{_cit.MIN_QUOTE_CHARS} 字）")
    elif verdict.l1_available:
        verdict.findings.append("未声明模板级依据（basis.quote）——建议给出支撑本模板的规则句（R35 §14）")

    if verifier is None:
        # §13 裁决 4 后半：非数学学科**显式标注**"无独立验算"（如实分界，计入护栏统计）
        verdict.findings.append(NO_L1_MARKER)
    if not semantics:
        verdict.findings.append(
            "未声明 semantics（domain/expect）→ 通用层无谓词可验、L1 无独立算式可比（须显式声明，不猜）")
    if not declared and doc.level == PRIMARY_LEVEL:
        verdict.findings.append("未显式声明 domain：当前按小学学段政策取 nonneg（建议声明固化）")
    if not semantics.get("requires") and any(h in (tpl.prompt or "") for h in CONDITION_HINTS):
        verdict.findings.append("题面含条件性表述但未声明 requires → 无法验证「题面是否说出了未被 constraint 保证的话」")

    for seed in range(seeds):
        r = render_exercise(node_id, ex, seed)
        if r.broken:
            verdict.problems.append(f"seed={seed} 渲染失败：{r.detail}")
            continue
        verdict.seeds_checked += 1
        probs = check_domain_rule(r.canonical_answer, domain)
        if probs:
            verdict.problems.extend(f"seed={seed}（{r.prompt}）→ {p}" for p in probs)
        # §14：题面泄漏（答案原样出现在题干静态文本里）——直接漏答案，升为**违规**
        verdict.problems.extend(leak_problems(tpl, r.prompt, r.canonical_answer, seed=seed))
        if len(verdict.samples) < 3:
            verdict.samples.append({"seed": seed, "prompt": r.prompt, "answer": r.canonical_answer})
        if verifier is not None:
            vp, vf = verifier.verify(node_id=node_id, ex=ex, tpl=tpl, params=dict(r.params or {}),
                                     answer=r.canonical_answer, semantics=semantics)
            verdict.problems.extend(f"seed={seed}: {p}" for p in vp)
            verdict.findings.extend(vf)
    verdict.problems = list(dict.fromkeys(verdict.problems))
    verdict.findings = list(dict.fromkeys(verdict.findings))
    verdict.ok = not verdict.problems
    return verdict


def check_node(doc: NodeDoc, *, seeds: int = 8) -> list[TemplateVerdict]:
    """节点内**所有模板题**过闸门（固定题不适用：它们的答案是人写的，不产生参数化矛盾）。"""
    return [check_template(doc.id, doc, ex, seeds=seeds) for ex in doc.exercises if ex.kind == "template"]


def gate_errors(doc: NodeDoc, *, seeds: int = 8) -> list[str]:
    """生成端入口：返回**拒绝入库**的错误清单（空 = 过闸门）。"""
    errs: list[str] = []
    for v in check_node(doc, seeds=seeds):
        errs.extend(f"{v.ex_id}: {p}" for p in v.problems)
    return errs


def library_stats() -> dict:
    """全库模板题的**验证覆盖率统计**（供护栏/审计消费；§13 裁决 4 要求"计入护栏统计"）。

    返回 {templates, violations, verified, unverified, l1_subjects}：
    - `verified` = 有 L1 且声明了 expect（真被独立验算过）；
    - `unverified` = 其余（含"无 L1 学科的如实分界"与"未声明 expect"）。
    """
    from .loader import load_library

    templates = violations = verified = unverified = 0
    subjects: set[str] = set()
    for loaded in load_library().nodes:
        for v in check_node(loaded.doc, seeds=4):
            templates += 1
            violations += 1 if v.problems else 0
            verified += 1 if v.verified and not v.problems else 0
            unverified += 1 if not v.verified else 0
            if v.l1_available:
                subjects.add(subject_of(v.node_id))
    return {"templates": templates, "violations": violations, "verified": verified,
            "unverified": unverified, "l1_subjects": sorted(subjects)}


__all__ = [
    "PRIMARY_LEVEL",
    "CONDITION_HINTS",
    "NO_EXPECT_PROBLEM",
    "NO_L1_MARKER",
    "TemplateVerdict",
    "L1Verifier",
    "register_l1",
    "l1_for",
    "subject_of",
    "effective_domain",
    "check_domain_rule",
    "check_template",
    "check_node",
    "gate_errors",
    "library_stats",
]
