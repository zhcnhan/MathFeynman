"""content.exprs：**模板表达式求值的单一实现**（R35 §13 裁决 1）。

背景（s23 事故）：`templates.eval_answer_expr` 曾用 `sympify(expr, locals=<仅参数名>)`——
`sympify("gcd(m,n)")` 在**没有 gcd 的环境**里把未知函数**静默当成 1**（`strict` 默认 False），
于是「16:20 化简后前项与后项之和」被算成 `16/1 + 20/1 = 36`（正确 9）。
而 L1 验算那套 `_LOCALS` 注册了 `gcd` → 算出 9 → 两边"一致"→ 闸门放行。
**根因不是数学错，而是"求值器解析不了却被静默吞掉"+ 求值有两份实现。**

本模块把这件事收敛成**一份**：
- `MATH_LOCALS`：唯一函数表（判题求值 / L1 独立验算 / 语义闸门**三方共用**）；
- `parse(expr_txt, params)` / `eval_expr(expr_txt, params)` / `eval_number(...)`：
  `sympify(..., locals=MATH_LOCALS, strict=True)`，**未知名/无法解析 → 抛中文 `ExprError`，禁止静默当 1**。
"""
from __future__ import annotations

import re
from typing import Any

import sympy as sp


class ExprError(ValueError):
    """表达式无法解析/求值（message 中文，直接面向用户可见的错误口径）。"""


# 唯一数学函数表（新增函数只改这里；判题与验算共用，避免"两把尺子"）
MATH_LOCALS: dict[str, Any] = {
    "lcm": sp.lcm,
    "gcd": sp.gcd,
    "igcd": sp.igcd,
    "ilcm": sp.ilcm,
    "Abs": sp.Abs,
    "abs": sp.Abs,
    "Min": sp.Min,
    "Max": sp.Max,
    "floor": sp.floor,
    "ceiling": sp.ceiling,
    "sqrt": sp.sqrt,
    "Rational": sp.Rational,
    "Integer": sp.Integer,
    "pi": sp.pi,
    "E": sp.E,
}

_NAME_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def bind_text(expr_txt: str, params: dict[str, Any]) -> str:
    """把参数**代入表达式文本**（数字字面量）：`lcm(a,b)` → `lcm(6,9)`。

    必须先代入再解析：否则 `sympify("lcm(a,b)")` 会把 `lcm` 当"一般符号"化简成 `a*b`
    （sympy 对一般符号默认互质），独立验算就退化成抄答案。
    """
    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in params and name not in MATH_LOCALS:
            v = params[name]
            return f"({v})" if isinstance(v, (int, float)) else str(v)
        return name

    return _NAME_RE.sub(repl, str(expr_txt))


def parse(expr_txt: str, *, names: "list[str] | None" = None) -> sp.Expr:
    """解析表达式 —— **未知名/未支持函数一律报错，不得静默当 1**。

    实现说明：先**逐词白名单校验**（参数名 ∪ `MATH_LOCALS`），再交给 sympy 解析。
    这样既拿到确定的中文错误（`gcd` 未注册时不会退化成 1），又不会因 `sympify(strict=True)`
    连数字字面量都拒掉（实测其 strict 语义会误伤纯算术文本）。
    """
    text = str(expr_txt)
    allowed = set(MATH_LOCALS) | {str(n) for n in (names or [])}
    for m in _NAME_RE.finditer(text):
        name = m.group(1)
        if name in allowed:
            continue
        raise ExprError(
            f"表达式含未知名 {name!r}（{text!r}）：只能用已声明的参数名与支持函数"
            "（加减乘除/括号/lcm/gcd/abs/min/max/floor/ceiling/sqrt）"
        )
    try:
        return sp.sympify(text, locals={n: MATH_LOCALS.get(n, sp.Symbol(n)) for n in allowed})
    except Exception as e:  # sp.SympifyError / SyntaxError / TypeError …
        raise ExprError(
            f"表达式无法解析（{text!r}）：{type(e).__name__}: {e}；"
            "请只使用已声明的参数名与已支持函数（加减乘除/括号/lcm/gcd/abs/min/max/floor/ceiling/sqrt）"
        ) from e


def eval_expr(expr_txt: str, params: dict[str, Any] | None = None) -> sp.Expr:
    """解析 + 代入 + 化简（求值的**唯一入口**）。

    有参数时**先把参数代入表达式文本**（`lcm(a,b)` → `lcm(6,9)`）再解析：
    否则 `lcm` 会被当成一般符号化简成 `a*b`（sympy 默认互质），独立验算退化成抄答案。
    """
    if params:
        expr = parse(bind_text(expr_txt, params))
    else:
        expr = parse(expr_txt)
    try:
        return sp.simplify(expr)
    except Exception as e:  # 化简失败也算无法求值（不得静默）
        raise ExprError(f"表达式无法化简（{expr_txt!r}）：{type(e).__name__}: {e}") from e


def eval_text(expr_txt: str, params: dict[str, Any] | None = None) -> str:
    """求值并转 sympy 字符串（判题/展示用，等价于旧的 `eval_answer_expr`）。"""
    return sp.sstr(eval_expr(expr_txt, params))


def eval_number(expr_txt: str, params: dict[str, Any] | None = None) -> float | None:
    """求值为 float（验算比对用）；非数值表达式返回 None。"""
    val = eval_expr(expr_txt, params)
    return float(val) if getattr(val, "is_number", False) else None


def holds(expr_txt: str, params: dict[str, Any]) -> bool | None:
    """求值一个布尔条件（requires/constraint 用）；无法判定返回 None。"""
    try:
        return bool(eval_expr(expr_txt, params))
    except ExprError:
        return None


__all__ = [
    "ExprError",
    "MATH_LOCALS",
    "bind_text",
    "parse",
    "eval_expr",
    "eval_text",
    "eval_number",
    "holds",
]
