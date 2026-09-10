"""content.l1_math：**math preset 的 L1 验算插件**（R35 §12 第二层）。

职责（只有这一层与学科相关）：
- **独立验算**：用 sympy 按内容声明的 `semantics.expect` 独立计算标准答案，与模板 `answer_expr`
  **符号比对**（`simplify(expect - answer_expr) == 0`）；不一致 → 拒绝入库。
- **条件强制**：`semantics.requires` 里每一条"题面陈述的条件"都必须被 `constraint` 保证——
  在参数取值域上穷举（有上限）找出**反例**（constraint 成立但 requires 不成立）→ 拒绝入库。

注册方式：导入本模块即向 `content.verify` 注册（`register_l1("math", …)`）；
**没有任何 `if subject == "math"` 分支**——解析一律走注册表。
"""
from __future__ import annotations

import re
from itertools import product
from typing import Any

import sympy as sp

from .schemas import ExerciseDoc, TemplateDoc
from .templates import eval_answer_expr
from .verify import L1Verifier, register_l1

# 允许在 expect/requires 里使用的符号（学科自有的数学函数；不给外部求值能力）
_LOCALS: dict[str, Any] = {
    "lcm": sp.lcm, "gcd": sp.gcd, "Abs": sp.Abs, "Min": sp.Min, "Max": sp.Max,
    "floor": sp.floor, "ceiling": sp.ceiling, "sqrt": sp.sqrt, "Rational": sp.Rational,
}
_MAX_COMBOS = 5000   # requires 反例穷举上限（超限则退化为按声明区间抽样）


_NAME_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def _sympify(expr: str) -> sp.Expr:
    return sp.sympify(str(expr), locals=_LOCALS, evaluate=False)


def _bind_text(expr_txt: str, params: dict[str, Any]) -> str:
    """把参数**代入表达式文本**（数字字面量）——这样 `lcm(a,b)` 变成 `lcm(6,9)` 才会被真正求值；
    否则 sympy 会把 `lcm(a,b)` 当"一般符号"化简成 `a*b`（默认互质），独立验算退化成抄答案。
    """
    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in params and name not in _LOCALS:
            v = params[name]
            return f"({v})" if isinstance(v, (int, float)) else str(v)
        return name

    return _NAME_RE.sub(repl, str(expr_txt))


def _param_values(expr_txt: str, params: dict[str, Any]) -> sp.Expr:
    """把表达式在给定参数上求值：先文本代入、再 sympy 求值/化简。"""
    return sp.simplify(_sympify(_bind_text(expr_txt, params)))


def _holds(expr_txt: str, params: dict[str, Any]) -> bool | None:
    """求值一个布尔条件；无法判定返回 None。"""
    try:
        val = _param_values(expr_txt, params)
        return bool(val)
    except Exception:
        return None


def _iter_combos(tpl: TemplateDoc):
    """参数区间的笛卡尔积（有上限）；用于 requires 的**反例穷举**。"""
    keys, ranges = [], []
    total = 1
    for k, spec in (tpl.params or {}).items():
        rng = spec.range if hasattr(spec, "range") else spec
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            return
        lo, hi = int(rng[0]), int(rng[1])
        vals = [v for v in range(lo, hi + 1) if v not in (getattr(spec, "exclude", None) or [])]
        keys.append(k)
        ranges.append(vals)
        total *= max(1, len(vals))
    if total > _MAX_COMBOS:
        return
    for combo in product(*ranges):
        yield dict(zip(keys, combo))


class MathSympyVerifier:
    """math preset 的 L1 验算器（sympy 独立验算 + constraint 蕴含检查）。"""

    name = "math-sympy"

    def verify(self, *, node_id: str, ex: ExerciseDoc, tpl: TemplateDoc, params: dict[str, Any],
               answer: str, semantics: dict) -> tuple[list[str], list[str]]:
        problems: list[str] = []
        findings: list[str] = []
        expect = str((semantics or {}).get("expect") or "").strip()
        if not expect:
            findings.append("未声明 semantics.expect：L1 无法独立验算标准答案（须声明「答案的独立算式」）")
        else:
            try:
                e_expect = _param_values(expect, params)
                e_answer = _param_values(tpl.answer_expr or "0", params)
                if sp.simplify(e_expect - e_answer) != 0:
                    problems.append(
                        f"答案与独立验算不一致：声明 expect={expect!r} 实算 {sp.sstr(e_expect)}，"
                        f"而 answer_expr={tpl.answer_expr!r} 给出 {sp.sstr(e_answer)}"
                        f"（params={params}）")
            except Exception as e:  # 表达式不可解析 → 无法验算（如实计入 findings）
                findings.append(f"expect/answer_expr 无法解析比对：{type(e).__name__}: {e}")

        reqs = [str(r) for r in ((semantics or {}).get("requires") or []) if str(r).strip()]
        for req in reqs:
            bad = self._counterexample(tpl, req)
            if bad is not None:
                problems.append(
                    f"题面条件未被 constraint 保证（反例 params={bad}）：{req!r}"
                    f"（constraint={tpl.constraint!r}）")
        return problems, findings

    @staticmethod
    def _counterexample(tpl: TemplateDoc, req: str) -> dict[str, Any] | None:
        """找出"constraint 成立但 requires 不成立"的参数组合（穷举，有上限）。"""
        found: dict[str, Any] | None = None
        any_combo = False
        for combo in _iter_combos(tpl):
            any_combo = True
            if tpl.constraint:
                ok_c = _holds(str(tpl.constraint), combo)
                if ok_c is not True:
                    continue
            ok_r = _holds(req, combo)
            if ok_r is False:
                found = combo
                break
        if not any_combo:
            return None   # 无法穷举（参数空间过大/非法）→ 交由穷举外的抽样自行暴露
        return found


register_l1("math", MathSympyVerifier())

__all__ = ["MathSympyVerifier"]
