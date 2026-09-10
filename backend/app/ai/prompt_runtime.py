"""ai.prompt_runtime：调用点**取生效模板**的唯一入口（R39 §2）。

为什么单独一层：调用点既可能在网关里（有 DB 会话），也可能在 ``outline/draft.py`` /
``outline/generate.py`` 这类"自己建 provider"的地方。两边都必须读到**用户改过的**模板
（否则"改了提示词却不生效"＝静默失效，正是铁则要防的）。

读库失败 / 模板被改坏（渲染不出）→ **记账 + 回退默认**，绝不静默失效。
"""
from __future__ import annotations

from . import prompt_templates as reg


class PromptRuntime:
    """一次调用点渲染（模板 + 版本标签 + 变量）。"""

    def __init__(self, call_name: str, *, subject_id: str = "", unit_id: str = ""):
        self.call_name = call_name
        self.subject_id = subject_id
        self.unit_id = unit_id
        self.system_template, self.user_template, self.version = _effective(
            call_name, subject_id=subject_id, unit_id=unit_id)

    def render_system(self, **vars) -> str:
        return self.render(self.system_template, self.system_ok(vars), **vars)

    def render_user(self, **vars) -> str:
        return self.render(self.user_template, vars, **vars)

    @staticmethod
    def render(template: str, given: dict, **vars) -> str:
        """渲染（缺占位符 → PromptError；由调用方转中文 422 或回退默认）。"""
        return reg.render(template, **vars)

    def system_ok(self, vars: dict) -> dict:
        """system 渲染时的兜底变量（material_discipline 等）。"""
        out = dict(vars)
        out.setdefault("material_discipline", "")
        return out


def _effective(call_name: str, *, subject_id: str = "", unit_id: str = "") -> tuple[str, str, str]:
    spec = reg.PROMPTS.get(call_name)
    if spec is None:
        raise reg.PromptError(f"未知调用点「{call_name}」：提示词模板注册表未收录")
    try:
        from ..db import SessionLocal

        with SessionLocal() as db:
            from ..service import prompt_store

            eff = prompt_store.effective(db, call_name)
        return eff["system"], eff["user"], f"{eff['system_version']}|{eff['user_version']}"
    except Exception as e:  # 读库失败 → 记账 + 回退默认（不静默失效）
        try:
            from ..service import ledger

            ledger.note(
                ledger.CAT_OTHER, f"提示词（{call_name}）",
                f"读取自定义提示词失败，本次已回退默认模板：{e}",
                impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
                subject_id=subject_id, unit_id=unit_id,
                detail={"call_name": call_name, "error": str(e)[:200]},
            )
        except Exception:
            pass
        return spec.system, spec.user, f"fallback-default:{call_name}"


def render_pair(call_name: str, *, system_vars: dict | None = None, user_vars: dict | None = None,
                subject_id: str = "", unit_id: str = "") -> tuple[str, str, str]:
    """便捷入口：一次拿到渲染后的 ``(system, user, 版本标签)``。

    渲染失败（模板被改坏）→ **记账 + 回退默认模板**（默认模板一定渲染得出）。
    """
    rt = PromptRuntime(call_name, subject_id=subject_id, unit_id=unit_id)
    sv = dict(system_vars or {})
    sv.setdefault("material_discipline", "")
    uv = dict(user_vars or {})
    try:
        return reg.render(rt.system_template, **sv), reg.render(rt.user_template, **uv), rt.version
    except reg.PromptError as e:
        from ..service import ledger

        ledger.note(
            ledger.CAT_OTHER, f"提示词（{call_name}）",
            f"提示词渲染失败，本次已回退默认模板：{e}",
            impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
            subject_id=subject_id, unit_id=unit_id,
            detail={"call_name": call_name, "error": str(e)[:200]},
        )
        spec = reg.PROMPTS[call_name]
        dv = reg.default_vars(spec)
        dv.update({k: str(v) for k, v in {**sv, **uv}.items()})
        return (reg.render(spec.system, **dv) if spec.system else "",
                reg.render(spec.user, **dv) if spec.user else "",
                f"fallback-default:{call_name}")


__all__ = ["PromptRuntime", "render_pair"]
