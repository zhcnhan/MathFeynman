"""app.content.templates：参数化题目渲染/取样（docs/04 §4）。

- 在 params 约束下**确定性随机**取样（seed 可复现：hash(node_id, ex_id, seed)）。
- 渲染后必须自检三步：① sympy 能解析答案表达式；② 约束成立；③ 代入答案后判题器返回 correct。
  失败则重取样（上限 N 次），全部失败 → broken 标记（不允许入库，content validate 报错）。
- LLM 变体（generate_practice_variant）MVP 不启用（docs/08 §1），本模块只服务模板题。
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

import sympy as sp

from ..domain.judge import judge
from .schemas import CheckDoc, ExerciseDoc, ParamRange

MAX_SAMPLE_ATTEMPTS = 200  # 单次取样尝试上限


@dataclass
class RenderedExercise:
    """一次渲染出的具体题目（全部字段学生可见或判题必需；canonical_answer 不外泄）。"""

    exercise_id: str
    prompt: str
    mode: str
    tolerance: float | None
    difficulty: int
    interactive: list[str]
    seed: int
    params: dict[str, Any] = field(default_factory=dict)
    equation: str | None = None          # equation_solution 机器方程
    expected: str | bool | None = None   # 判题期望（numeric/equivalence/boolean/fill_text）
    canonical_answer: str = ""           # 正确答案文本（自检/测试用，严禁直接返回前端）
    broken: bool = False
    detail: str = ""
    # B2（docs/04 §2 同步）：选择/填空附加判题数据
    options: list[str] = field(default_factory=list)
    answer_index: int | None = None
    aliases: list[str] = field(default_factory=list)
    # **R56 mode="ai"**：模型给的标准答案 / 解析 / 依据页（判对错由模型做，程序只搬运）
    ai_answer: str = ""
    ai_explanation: str = ""
    ai_basis_pages: list[str] = field(default_factory=list)
    ai_answer_kind: str = ""

    def judge_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.mode == "ai":
            # 本模式**不走** sympy：本载荷只用于界面/审计展示（判题在 mode_ai 分支）
            return payload
        if self.mode == "equation_solution":
            payload["equation"] = self.equation
        elif self.mode == "single_choice":
            payload["expected"] = str(self.answer_index if self.answer_index is not None else 0)
            payload["options"] = list(self.options)
        else:
            payload["expected"] = self.expected
            if self.mode == "fill_text" and self.aliases:
                payload["aliases"] = list(self.aliases)
        if self.tolerance is not None:
            payload["tolerance"] = self.tolerance
        return payload


# --------------------------------------------------------------------------
# 参数取样
# --------------------------------------------------------------------------
def sample_params(
    spec: dict[str, ParamRange | list[int | float]],
    constraint: str | None,
    rng: random.Random,
) -> dict[str, Any] | None:
    """在约束下取样 params；达到尝试上限返回 None。"""
    for _ in range(MAX_SAMPLE_ATTEMPTS):
        values: dict[str, Any] = {}
        ok = True
        for key, s in spec.items():
            if isinstance(s, ParamRange):
                lo, hi = int(s.range[0]), int(s.range[1])
                lo, hi = (hi, lo) if lo > hi else (lo, hi)
                excluded = {int(e) for e in s.exclude}
                pool = [v for v in range(lo, hi + 1) if v not in excluded]
                if not pool:
                    ok = False
                    break
                values[key] = rng.choice(pool)
            elif isinstance(s, (list, tuple)):
                values[key] = rng.choice(list(s))
            else:
                ok = False
                break
        if not ok:
            return None
        if constraint:
            try:
                ok = bool(eval(constraint, {"__builtins__": {}}, dict(values)))  # noqa: S307
            except Exception:
                ok = False
        if ok:
            return values
    return None


def _substitute(tpl: str, params: dict[str, Any]) -> str:
    try:
        return tpl.format(**params)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"模板占位符替换失败 {tpl!r}: {e}") from e


def eval_answer_expr(expr_txt: str, params: dict[str, Any]) -> str:
    """answer_expr 语义（docs/04 §2 样例）：参数名作为符号的表达式，代入取值后化简。

    R35 §13 裁决 1：**统一走 `content.exprs`**（唯一函数表 + `strict=True`）——
    禁止再用"只认参数名的 locals"解析（那会把未知函数静默当 1：`gcd(16,20)` → `1`，
    算出 36 而不是 9，见 s23 事故）。无法解析 → **中文错误**，不吞。
    """
    from . import exprs

    return exprs.eval_text(expr_txt, params)


# --------------------------------------------------------------------------
# 渲染 + 自检
# --------------------------------------------------------------------------
def render_exercise(
    node_id: str,
    ex: ExerciseDoc,
    seed: int,
) -> RenderedExercise:
    """渲染一个具体题目并自检；自检不通过 → broken=True（detail 说明）。"""
    rng = random.Random(hashlib.sha1(f"{node_id}:{ex.id}:{seed}".encode()).hexdigest())
    check = ex.check
    out = RenderedExercise(
        exercise_id=ex.id,
        prompt="",
        mode=check.mode,
        tolerance=check.tolerance,
        difficulty=ex.difficulty,
        interactive=list(ex.interactive),
        seed=seed,
    )
    try:
        if ex.kind == "fixed":
            return _render_fixed(ex, out)
        return _render_template(ex, check, rng, out)
    except Exception as e:  # 渲染/解析/判题任何一步失败 → broken
        out.broken = True
        out.detail = str(e)
        return out


def _render_fixed(ex: ExerciseDoc, out: RenderedExercise) -> RenderedExercise:
    out.prompt = ex.prompt
    mode = ex.check.mode
    if mode == "boolean_judgment":
        if ex.answer_bool is None:
            raise ValueError("fixed + boolean_judgment 需要 answer_bool")
        out.expected = ex.answer_bool
        out.canonical_answer = "对" if ex.answer_bool else "错"
    elif mode in ("numeric_value", "symbolic_equivalence"):
        if not ex.answer_expr:
            raise ValueError(f"fixed + {mode} 需要 answer_expr")
        expr = sp.sympify(ex.answer_expr)
        out.expected = sp.sstr(expr)
        out.canonical_answer = sp.sstr(expr)
    elif mode == "equation_solution":
        if not ex.equation:
            raise ValueError("fixed + equation_solution 需要 equation")
        out.equation = ex.equation
        out.canonical_answer = _canonical_solution_text(ex.equation)
    elif mode == "single_choice":  # B2
        out.options = list(ex.options)
        out.answer_index = ex.answer_index
        out.canonical_answer = str((ex.answer_index or 0) + 1)  # 作答=1..n 编号
    elif mode == "fill_text":  # B2
        out.expected = ex.expected
        out.aliases = list(ex.aliases)
        out.canonical_answer = ex.expected
    elif mode == "ai":
        # **R56**：图示教材模式——标准答案/解析由模型给；**不做自检**（没有独立验算就是本模式的定义）
        if not (ex.check.answer or "").strip():
            raise ValueError("图示教材模式的题需要 check.answer")
        out.options = list(ex.options)
        out.ai_answer = ex.check.answer
        out.ai_explanation = ex.check.explanation
        out.ai_basis_pages = list(ex.check.basis_pages or [])
        out.ai_answer_kind = ex.check.answer_kind or ("choice" if ex.options else "short")
        out.canonical_answer = ex.check.answer      # 仅供测试/审计，不参与判题
        out.detail = "ok（图示教材模式：判对错由模型做）"
        return out
    else:
        raise ValueError(f"fixed 不支持判题模式 {mode}")
    _selfcheck(out)
    return out


def _render_template(ex: ExerciseDoc, check: CheckDoc, rng: random.Random, out: RenderedExercise) -> RenderedExercise:
    tpl = ex.template
    if tpl is None:
        raise ValueError(f"kind=template 的练习 {ex.id} 缺少 template 段")
    params = sample_params(tpl.params, tpl.constraint, rng)
    if params is None:
        raise ValueError(f"练习 {ex.id}: 在约束下无法取样（检查 params/constraint）")
    out.params = params
    out.prompt = _substitute(tpl.prompt, params)
    mode = check.mode
    if mode == "equation_solution":
        eq_tpl = check.equation or tpl.equation
        if not eq_tpl:
            raise ValueError(
                f"练习 {ex.id}: equation_solution 需要 check.equation（机器方程模板）"
            )
        out.equation = _substitute(eq_tpl, params)
        out.canonical_answer = _canonical_solution_text(out.equation)
        if tpl.answer_expr:  # 交叉验证：answer_expr 代参求值后应为方程的解
            cross = eval_answer_expr(tpl.answer_expr, params)
            _crosscheck_root(out.equation, cross)
    elif mode in ("numeric_value", "symbolic_equivalence"):
        if not tpl.answer_expr:
            raise ValueError(f"练习 {ex.id}: {mode} 需要 answer_expr")
        expected_str = eval_answer_expr(tpl.answer_expr, params)
        expr = sp.sympify(expected_str)
        if mode == "numeric_value" and expr.free_symbols:
            raise ValueError(f"练习 {ex.id}: numeric_value 的 answer_expr 不应含符号")
        out.expected = expected_str
        out.canonical_answer = expected_str
    else:
        raise ValueError(f"template 不支持判题模式 {mode}")
    _selfcheck(out)
    return out


def _selfcheck(out: RenderedExercise) -> None:
    """自检 ③：用 canonical_answer 作答应判 correct（docs/04 §4）。"""
    payload = out.judge_payload()
    res = judge(user_answer=out.canonical_answer, **payload)
    if not res.correct:
        raise ValueError(
            f"自检失败（canonical 答案被判错）: mode={out.mode} answer={out.canonical_answer!r} detail={res.detail}"
        )
    out.detail = "ok"


def _crosscheck_root(equation: str, root_expr: str) -> None:
    """交叉验证 answer_expr 代入后确为方程解（模板作者防手误）。"""
    lhs_txt, rhs_txt = equation.split("=", 1)
    syms = sorted({str(s) for s in sp.sympify(lhs_txt).free_symbols} | {str(s) for s in sp.sympify(rhs_txt).free_symbols})
    if len(syms) != 1:
        raise ValueError(f"方程 {equation} 需单一未知数，实际 {syms}")
    sym = sp.Symbol(syms[0])
    sols = sp.solve(sp.Eq(sp.sympify(lhs_txt), sp.sympify(rhs_txt)), sym)
    root = sp.sympify(root_expr)
    if not any(sp.simplify(s - root) == 0 for s in sols):
        raise ValueError(f"answer_expr 结果 {root_expr} 不是方程 {equation} 的解（解: {sols}）")


def _canonical_solution_text(equation: str) -> str:
    """求方程解 → 学生"正确答案"文本（供自检/测试）。"""
    lhs_txt, rhs_txt = equation.split("=", 1)
    syms = sorted({str(s) for s in sp.sympify(lhs_txt).free_symbols} | {str(s) for s in sp.sympify(rhs_txt).free_symbols})
    if len(syms) != 1:
        raise ValueError(f"方程需单一未知数: {equation}")
    sym = sp.Symbol(syms[0])
    sols = sp.solve(sp.Eq(sp.sympify(lhs_txt), sp.sympify(rhs_txt)), sym)
    return "; ".join(f"{sym} = {sp.sstr(s)}" for s in sols) if sols else "无解"


__all__ = ["RenderedExercise", "render_exercise", "sample_params", "MAX_SAMPLE_ATTEMPTS"]
