"""content.l1_math：**math preset 的 L1 验算插件**（R35 §12/§13）。

职责（只有这一层与学科相关）：
1. **独立验算**：按内容声明的 `semantics.expect` 独立计算标准答案；
2. **必须校验"实际求值路径"**（§13 裁决 2）：`templates.eval_answer_expr(answer_expr)` 的结果
   与 L1 独立验算结果**必须一致** —— 这正是漏过 s23 的缺口（当时两侧都走 L1 的函数表，
   而判题实际走的是另一套、把 `gcd` 静默当 1）；
3. **`expect` 不得自证**（§13 裁决 3）：`semantics.expect` 与 `answer_expr` **文本相同 → 违规**；
4. **条件强制**：`requires` 必须被 `constraint` 保证（穷举反例）；
5. **未声明 expect → 违规**（§13 裁决 4，数学模板必须可独立验算）。

求值/函数表统一来自 `content.exprs`（**单一实现**，与判题路径同一份）。
注册方式：导入本模块即向 `content.verify` 注册（`register_l1("math", …)`）；**无学科分支**。
"""
from __future__ import annotations

from itertools import product
from typing import Any

from . import exprs
from .schemas import ExerciseDoc, TemplateDoc
from .templates import eval_answer_expr
from .verify import NO_EXPECT_PROBLEM, L1Verifier, register_l1

_MAX_COMBOS = 5000   # requires 反例穷举上限（超限则退化为按 seed 抽样）


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
    """math preset 的 L1 验算器（独立验算 + 实际路径比对 + constraint 蕴含检查）。"""

    name = "math-sympy"

    def verify(self, *, node_id: str, ex: ExerciseDoc, tpl: TemplateDoc, params: dict[str, Any],
               answer: str, semantics: dict) -> tuple[list[str], list[str]]:
        problems: list[str] = []
        findings: list[str] = []
        answer_expr = str(tpl.answer_expr or "").strip()
        expect = str((semantics or {}).get("expect") or "").strip()
        same_text = bool(expect and answer_expr) and expect.replace(" ", "") == answer_expr.replace(" ", "")

        # §13 裁决 3：expect 不得是 answer_expr 的复制（否则等于没验）
        if same_text:
            problems.append(
                f"semantics.expect 与 answer_expr 文本完全相同（{expect!r}）——等于自证，"
                "必须写成**独立表述**（如 lcm(a, b) / gcd(a, b) / a*b/100）")
        # §13 裁决 4：数学模板必须能独立验算（未声明 expect = 违规，不再只是 finding）
        if not expect:
            problems.append(NO_EXPECT_PROBLEM)

        if expect and not same_text:
            try:
                e_expect = exprs.eval_number(expect, params)
            except exprs.ExprError as e:
                problems.append(f"expect 无法求值：{e}")
                e_expect = None
            if e_expect is not None:
                try:
                    e_answer = exprs.eval_number(answer_expr, params)
                except exprs.ExprError as e:
                    problems.append(f"answer_expr 无法求值：{e}")
                    e_answer = None
                if e_answer is not None and abs(e_expect - e_answer) > 1e-9:
                    problems.append(
                        f"答案与独立验算不一致：expect={expect!r} 实算 {e_expect}，"
                        f"answer_expr={answer_expr!r} 给出 {e_answer}（params={params}）")

        # §13 裁决 2：**判题实际求值路径**必须与独立验算一致（这条才防住 s23 那一类）
        if answer_expr:
            try:
                actual_text = eval_answer_expr(answer_expr, params)
                actual_val = exprs.eval_number(actual_text)
            except Exception as e:  # 判题路径解析失败 → 用户会碰到坏题，必须报
                problems.append(f"判题求值路径无法解析 answer_expr（{answer_expr!r}）：{e}")
                actual_val = None
            if actual_val is not None and expect and not same_text:
                try:
                    e_expect = exprs.eval_number(expect, params)
                except exprs.ExprError:
                    e_expect = None
                if e_expect is not None and abs(e_expect - actual_val) > 1e-9:
                    problems.append(
                        f"判题实际求值与独立验算不一致：判题路径给出 {actual_text}，独立验算为 {e_expect}"
                        f"（params={params}，answer_expr={answer_expr!r}）")

        # 条件强制（题面不得说出未被 constraint 保证的话）
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
        for combo in _iter_combos(tpl):
            if tpl.constraint and exprs.holds(str(tpl.constraint), combo) is not True:
                continue
            if exprs.holds(req, combo) is False:
                return combo
        return None


register_l1("math", MathSympyVerifier())

__all__ = ["MathSympyVerifier"]
