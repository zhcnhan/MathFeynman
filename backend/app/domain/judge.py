"""domain.judge：确定性判题器（docs/04 §3、ADR A4）。唯一判题器 = sympy，永不调用 LLM。

MVP 四模式（docs/08 §1）：equation_solution / symbolic_equivalence / numeric_value /
boolean_judgment。ordering/manual_review 属扩展枚举，本里程碑不支持（manual_review
应走人工复核队列，非自动判题）。

统一返回 docs/04 §3 的结果结构：
    {correct: bool, feedback_hint: str|null, expected: str|null, detail: str}

解析失败（用户输入不合法）抛 NotationError（docs/07 §3：不判错，返回 notation_error 提示改法）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sympy as sp

SUPPORTED_MODES = (
    "equation_solution",
    "symbolic_equivalence",
    "numeric_value",
    "boolean_judgment",
)
ALL_MODES = SUPPORTED_MODES + ("ordering", "manual_review")

# 数值容差缺省（content 未指定 tolerance 时视作精确等价）
DEFAULT_TOLERANCE = 1e-9

_TRUE_WORDS = {"对", "正确", "是", "true", "t", "yes", "y", "1", "✓", "√", "对呀", "对的", "正确。"}
_FALSE_WORDS = {"错", "错误", "否", "不是", "false", "f", "no", "n", "0", "×", "不对", "错的"}


class JudgeError(ValueError):
    """判题配置/输入错误。"""


class NotationError(JudgeError):
    """用户作答无法解析为数学表达式（docs/07 §3：返回 notation_error，不判错）。"""


class UnsupportedJudgeMode(JudgeError):
    """当前未支持的判题模式（ordering/manual_review 等）。"""


@dataclass(frozen=True)
class JudgeResult:
    correct: bool
    feedback_hint: str | None = None
    expected: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "correct": self.correct,
            "feedback_hint": self.feedback_hint,
            "expected": self.expected,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------
# 解析辅助
# --------------------------------------------------------------------------
def _sympify(text: str, *, variables: str = "") -> sp.Expr:
    """安全 sympify：拒绝 eval 风格构造；支持 x, y, pi, sqrt 等。

    若 variables 提供（如 "x"），则把出现的符号显式声明，避免与常量冲突。
    """
    text = text.strip()
    if not text:
        raise NotationError("作答为空")
    local: dict[str, Any] = {}
    if variables:
        for v in variables.split(","):
            v = v.strip()
            if v:
                local[v] = sp.Symbol(v)
    try:
        expr = sp.sympify(text, locals=local, evaluate=True)
    except (sp.SympifyError, SyntaxError, TypeError, ValueError) as e:
        raise NotationError(f"无法解析表达式 {text!r}: {e}") from e
    if not isinstance(expr, sp.Basic):
        # 字面量（如 "3"）sympify 会返回 Integer，属 Basic；这里兜底
        raise NotationError(f"无法解析表达式 {text!r}")
    return expr


def _format_roots(roots: list[sp.Expr], symbol: sp.Symbol) -> str:
    """把解集格式化为展示文本（tests 与 expected 字段用）。"""
    items = []
    for r in sorted(roots, key=lambda z: (float(sp.re(z)) if z.is_real is not False else 0.0, 0)):
        items.append(f"{symbol} = {sp.sstr(r)}")
    return "；".join(items) if items else "无解"


# --------------------------------------------------------------------------
# 模式实现
# --------------------------------------------------------------------------
def judge_numeric_value(
    user_answer: str,
    *,
    expected: str,
    tolerance: float | None = DEFAULT_TOLERANCE,
) -> JudgeResult:
    """numeric_value：代入后 |a-b| < tol（tolerance 为空则精确相等）。"""
    expected_expr = _sympify(expected)
    user_expr = _sympify(user_answer)
    if user_expr.free_symbols:
        raise NotationError("数值作答不应包含未知符号，请直接给数值（如 5 或 3/2）。")
    delta = sp.simplify(expected_expr - user_expr)
    tol = DEFAULT_TOLERANCE if tolerance is None else tolerance
    if delta == 0:
        correct = True
    elif delta.is_number:
        correct = bool(abs(complex(delta)) <= tol) if delta.is_complex else bool(abs(float(delta)) <= tol)
    else:  # 非纯数值（如含符号）→ 等价化简
        correct = delta == 0
    return JudgeResult(
        correct=bool(correct),
        feedback_hint=None if correct else "数值不对，请再检查计算。",
        expected=sp.sstr(expected_expr) if not correct else None,
        detail=f"容差 {tol:g}" if not correct else "数值一致",
    )


def judge_symbolic_equivalence(
    user_answer: str,
    *,
    expected: str,
    tolerance: float | None = None,
) -> JudgeResult:
    """symbolic_equivalence：simplify(a - b) == 0。"""
    expected_expr = _sympify(expected)
    user_expr = _sympify(user_answer)
    equivalent = sp.simplify(expected_expr - user_expr) == 0
    return JudgeResult(
        correct=equivalent,
        feedback_hint=None if equivalent else "两个表达式不等价，请检查变形过程。",
        expected=None if equivalent else sp.sstr(expected_expr),
        detail="化简差为 0" if equivalent else "化简差非 0",
    )


def judge_equation_solution(
    user_answer: str,
    *,
    equation: str,
    symbol: str = "x",
    tolerance: float | None = DEFAULT_TOLERANCE,
) -> JudgeResult:
    """equation_solution：对 equation（如 "3*x + 5 = 20"）求解，与用户解集比对（无序、容差）。

    用户作答支持形态：x=5 / 5 / x=5; x=-1 / 5,-1 / {5,-1} 等。
    """
    sym = sp.Symbol(symbol)
    if "=" not in equation:
        raise JudgeError(f"equation_solution 需要含 '=' 的方程，得到: {equation!r}")
    lhs_txt, rhs_txt = equation.split("=", 1)
    lhs = _sympify(lhs_txt, variables=symbol)
    rhs = _sympify(rhs_txt, variables=symbol)

    solutions = sp.solve(sp.Eq(lhs, rhs), sym)
    if not isinstance(solutions, list):
        solutions = [solutions]
    # 处理 solve 返回的不等式/条件等非常规结果
    expected_roots: list[sp.Expr] = []
    for s in solutions:
        if isinstance(s, sp.Basic) and s.free_symbols == set():
            expected_roots.append(s)

    user_roots = _parse_solution_answer(user_answer, sym, tolerance)

    def same(a: sp.Expr, b: sp.Expr) -> bool:
        if sp.simplify(a - b) == 0:
            return True
        try:
            tol = DEFAULT_TOLERANCE if tolerance is None else tolerance
            return bool(abs(complex(sp.N(a - b))) <= tol)
        except Exception:
            return False

    def dedupe(roots: list[sp.Expr]) -> list[sp.Expr]:
        kept: list[sp.Expr] = []
        for r in roots:
            if not any(same(r, k) for k in kept):
                kept.append(r)
        return kept

    # 集合语义比对：先按等价去重（重复书写同根不算错），再双向子集检查
    expected_roots = dedupe(expected_roots)
    user_roots = dedupe(user_roots)

    def covered(roots: list[sp.Expr], others: list[sp.Expr]) -> bool:
        unmatched = list(others)
        for r in roots:
            for i, o in enumerate(unmatched):
                if same(o, r):
                    del unmatched[i]
                    break
        return not unmatched

    matched = covered(user_roots, expected_roots) and covered(expected_roots, user_roots)

    return JudgeResult(
        correct=matched,
        feedback_hint=None if matched else "解集不一致：可能漏解、多解或解错，请把方程变形成 x=… 再核对。",
        expected=None if matched else _format_roots(expected_roots, sym),
        detail=f"方程解集大小 {len(expected_roots)}，用户解集大小 {len(user_roots)}" if not matched else "解集一致",
    )


def _parse_solution_answer(text: str, sym: sp.Symbol, tolerance: float | None) -> list[sp.Expr]:
    """解析用户解集文本 → 根列表（无序）。"""
    t = text.strip()
    if not t:
        raise NotationError("作答为空")
    # 去包裹花括号/方括号
    if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
        t = t[1:-1]
    # 统一分隔符
    for sep in ("；", ";"):
        t = t.replace(sep, ",")
    parts = [p.strip() for p in t.split(",") if p.strip()]
    if not parts:
        # 无逗号则整体解析（可能 "x=5" 或 "5"）
        parts = [t]
    roots: list[sp.Expr] = []
    for part in parts:
        roots.append(_parse_single_solution(part, sym))
    return roots


def _parse_single_solution(part: str, sym: sp.Symbol) -> sp.Expr:
    """解析单个解写法：'x=5' / 'x = 5' / '5' / 'x=sqrt(2)'。"""
    p = part.strip()
    if "=" in p:
        _, rhs = p.split("=", 1)
        p = rhs.strip()
    expr = _sympify(p, variables="x,y,z,a,b,c")
    if expr.free_symbols:
        raise NotationError(f"解应为具体数值/常数表达式，无法解析 {part!r} 为解。")
    return expr


def judge_boolean_judgment(
    user_answer: str,
    *,
    expected: bool,
    tolerance: float | None = None,
) -> JudgeResult:
    """boolean_judgment：对错为真值判断（docs/04 §3）；理由由 rubric 评估，不在此判。"""
    u = user_answer.strip().rstrip("。.!！").lower()
    if u in _TRUE_WORDS:
        user_bool = True
    elif u in _FALSE_WORDS:
        user_bool = False
    else:
        raise NotationError(f"无法识别判断词：{user_answer!r}（请输入 对/错）")
    exp_word = "对" if expected else "错"
    return JudgeResult(
        correct=user_bool == expected,
        feedback_hint=None if user_bool == expected else f"判断结果应为「{exp_word}」。理由部分请说清依据。",
        expected=None if user_bool == expected else exp_word,
        detail="真值一致" if user_bool == expected else "真值不一致",
    )


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def judge(
    mode: str,
    user_answer: str,
    *,
    expected: str | bool | None = None,
    equation: str | None = None,
    symbol: str = "x",
    tolerance: float | None = None,
) -> JudgeResult:
    """按 mode 分发判题。mode ∈ MVP 四模式；ordering/manual_review 抛 UnsupportedJudgeMode。"""
    if mode == "numeric_value":
        if expected is None or not isinstance(expected, str):
            raise JudgeError("numeric_value 需要 expected(字符串表达式)")
        return judge_numeric_value(user_answer, expected=expected, tolerance=tolerance)
    if mode == "symbolic_equivalence":
        if expected is None or not isinstance(expected, str):
            raise JudgeError("symbolic_equivalence 需要 expected(字符串表达式)")
        return judge_symbolic_equivalence(user_answer, expected=expected, tolerance=tolerance)
    if mode == "equation_solution":
        if not equation:
            raise JudgeError("equation_solution 需要 equation 参数")
        return judge_equation_solution(user_answer, equation=equation, symbol=symbol, tolerance=tolerance)
    if mode == "boolean_judgment":
        if expected is None or not isinstance(expected, bool):
            raise JudgeError("boolean_judgment 需要 expected(bool)")
        return judge_boolean_judgment(user_answer, expected=expected)
    if mode in ("ordering", "manual_review"):
        raise UnsupportedJudgeMode(
            f"模式 {mode} 非 MVP 自动判题范围（manual_review 应进人工复核队列）"
        )
    raise UnsupportedJudgeMode(f"未知判题模式: {mode!r}")


__all__ = [
    "JudgeResult",
    "JudgeError",
    "NotationError",
    "UnsupportedJudgeMode",
    "SUPPORTED_MODES",
    "ALL_MODES",
    "judge",
]
