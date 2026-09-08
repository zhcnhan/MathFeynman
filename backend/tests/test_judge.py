"""domain.judge 单测（docs/04 §3）：四模式 + 边界/容差/等价 + notation 失败。

用例数 ≥ 30（docs/08 M1 判题用例 ≥30）。
"""
from __future__ import annotations

import pytest

from app.domain.judge import (
    NotationError,
    UnsupportedJudgeMode,
    judge,
    judge_boolean_judgment,
    judge_equation_solution,
    judge_numeric_value,
    judge_symbolic_equivalence,
)

# --------------------------------------------------------------------------
# numeric_value
# --------------------------------------------------------------------------
NUMERIC_CASES = [
    # (user, expected, tolerance, expect_correct)
    ("5", "5", None, True),
    ("5.0", "5", None, True),
    ("3/2", "1.5", None, True),
    ("0.3333333", "1/3", 1e-5, True),
    ("0.3333", "1/3", 1e-5, False),  # 容差外
    ("3.141592653589793", "pi", 1e-12, True),  # 容差内
    ("3.14", "pi", 1e-9, False),               # 明显不等于 π
    ("2.0000001", "2", 1e-3, True),
    ("2.01", "2", 1e-3, False),
    ("-4", "-4", None, True),
    ("-4", "4", None, False),
    ("0", "0", None, True),
    ("1.4142135623730951", "sqrt(2)", 1e-10, True),
    ("1.41", "sqrt(2)", 1e-10, False),
]


@pytest.mark.parametrize("user,expected,tol,want", NUMERIC_CASES)
def test_numeric_value(user, expected, tol, want):
    r = judge_numeric_value(user, expected=expected, tolerance=tol)
    assert r.correct is want, r


def test_numeric_result_shape():
    r = judge_numeric_value("7", expected="5")
    assert r.correct is False
    assert isinstance(r.feedback_hint, str) and isinstance(r.detail, str)
    assert r.expected is not None  # 仅审计/测试用；API 层不外泄


def test_numeric_notation_error():
    with pytest.raises(NotationError):
        judge_numeric_value("abc", expected="5")
    with pytest.raises(NotationError):
        judge_numeric_value("", expected="5")


# --------------------------------------------------------------------------
# symbolic_equivalence
# --------------------------------------------------------------------------
EQUIV_CASES = [
    # (user, expected, want)
    ("(x+1)*(x-1)", "x**2 - 1", True),
    ("x**2 - 1", "(x+1)*(x-1)", True),
    ("2*(x+1)", "2*x + 2", True),
    ("(x+1)**2", "x**2 + 2*x + 1", True),
    ("x**2 + 2*x + 2", "(x+1)**2", False),  # 差 1
    ("x + x", "2*x", True),
    ("x/2", "x*0.5", True),
    ("sin(x)**2 + cos(x)**2", "1", True),
    ("a*(b+c)", "a*b + a*c", True),
    ("x**3 - 1", "(x-1)*(x**2+x+1)", True),
    ("1/x + 1/y", "(x+y)/(x*y)", True),
    ("x+1", "x+2", False),
    ("- (x - 3)", "3 - x", True),
]


@pytest.mark.parametrize("user,expected,want", EQUIV_CASES)
def test_symbolic_equivalence(user, expected, want):
    r = judge_symbolic_equivalence(user, expected=expected)
    assert r.correct is want, r


def test_symbolic_equivalence_notation_error():
    with pytest.raises(NotationError):
        judge_symbolic_equivalence("x +", expected="x")


# --------------------------------------------------------------------------
# equation_solution
# --------------------------------------------------------------------------
EQUATION_CASES = [
    # (equation, user, want)
    ("3*x + 5 = 20", "x = 5", True),
    ("3*x + 5 = 20", "5", True),
    ("3*x + 5 = 20", "x = 4", False),
    ("3*x + 5 = 20", "x=5; x=5", True),  # 重复解集合等价
    ("2*x = 10", "x=5", True),
    ("2*x = 10", "x=-5", False),
    ("x + 3 = 3", "x=0", True),
    ("x**2 = 9", "x=3; x=-3", True),
    ("x**2 = 9", "x=-3, x=3", True),  # 无序
    ("x**2 = 9", "x=3", False),  # 缺根
    ("x**2 = 9", "x=3; x=3; x=3", False),  # 数量不符（3 个 3 ≠ 解集 {-3,3}）
    ("x**2 - 5*x + 6 = 0", "x=2; x=3", True),
    ("x**2 - 5*x + 6 = 0", "x=2", False),
    ("x**2 - 5*x + 6 = 0", "x=1; x=6", False),
    ("x/2 + 1 = 3", "x=4", True),
    ("x/2 + 1 = 3", "x=8", False),
    ("x**2 = 2", "x = sqrt(2), x = -sqrt(2)", True),
    ("x**2 = 2", "x=1.4142135623730951; x=-1.4142135623730951", True),  # 容差
    ("x**2 = 2", "x=1.41; x=-1.41", False),
    ("5 - x = 2", "x=3", True),
    ("-x = 4", "x=-4", True),
    ("x + 5 = x + 5", "x=0", False),  # 恒等式无唯一解 → 用户给 0 不正确
]


@pytest.mark.parametrize("equation,user,want", EQUATION_CASES)
def test_equation_solution(equation, user, want):
    r = judge_equation_solution(user, equation=equation)
    assert r.correct is want, (equation, user, r)


def test_equation_notation_error():
    with pytest.raises(NotationError):
        judge_equation_solution(user_answer="x=abc", equation="x+1=2")


# --------------------------------------------------------------------------
# boolean_judgment
# --------------------------------------------------------------------------
BOOLEAN_CASES = [
    ("对", True, True),
    ("正确", True, True),
    ("是", True, True),
    ("true", True, True),
    ("√", True, True),
    ("错", False, True),
    ("错误", False, True),
    ("不对", False, True),
    ("false", False, True),
    ("0", False, True),
    ("对", False, False),
    ("错", True, False),
]


@pytest.mark.parametrize("user,expected,want", BOOLEAN_CASES)
def test_boolean_judgment(user, expected, want):
    r = judge_boolean_judgment(user, expected=expected)
    assert r.correct is want, r


def test_boolean_notation_error():
    with pytest.raises(NotationError):
        judge_boolean_judgment("也许", expected=True)


# --------------------------------------------------------------------------
# 统一入口 judge() + 模式边界
# --------------------------------------------------------------------------
def test_judge_dispatch():
    assert judge("numeric_value", "5", expected="5").correct
    assert judge("symbolic_equivalence", "x+x", expected="2*x").correct
    assert judge("equation_solution", "x=5", equation="3*x+5=20").correct
    assert judge("boolean_judgment", "对", expected=True).correct


def test_unsupported_modes():
    for mode in ("ordering", "manual_review", "nonsense_mode"):
        with pytest.raises(UnsupportedJudgeMode):
            judge(mode, "1", expected="1")


def test_judge_argument_validation():
    with pytest.raises(Exception):
        judge("numeric_value", "5")  # 缺 expected
    with pytest.raises(Exception):
        judge("equation_solution", "x=1")  # 缺 equation


# 统计：本文件判题断言用例总数（含参数化条目）
def test_judge_case_count_ge_30():
    total = (
        len(NUMERIC_CASES)
        + len(EQUIV_CASES)
        + len(EQUATION_CASES)
        + len(BOOLEAN_CASES)
    )
    assert total >= 30, total
