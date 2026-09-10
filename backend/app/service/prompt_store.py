"""service.prompt_store：提示词的改 / 读 / 恢复默认（docs/09 R39 §2）。

- 存储：``prompt_overrides`` 表（**新数据建表正当**；不塞 ``subjects.meta_json``）；
- **可恢复**：单条恢复默认（可按字段：system / user）+ 全部恢复默认（前端恢复前确认）；
- **可回溯**：每次都记入 R39 §1 账本；"哪次生成用的哪版提示词"由 ``service.ai_trace`` 的
  ``prompt_versions`` 落档（审计页可对照）；
- **安全**：必填占位符/硬约束缺失 → **中文报错并拒绝保存**（``prompt_templates.validate_text``）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .. import models
from ..ai import prompt_templates as reg
from . import ledger


def _iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _row(db, call_name: str) -> models.PromptOverride | None:
    return db.get(models.PromptOverride, call_name)


def _view(db, call_name: str) -> dict:
    spec = reg.PROMPTS.get(call_name)
    if spec is None:
        raise reg.PromptError(f"未知调用点「{call_name}」：提示词模板注册表未收录")
    row = _row(db, call_name)
    default_system = reg.render(spec.system, **reg.default_vars(spec))
    default_user = reg.render(spec.user, **reg.default_vars(spec)) if spec.user else ""
    sys_custom = bool(row is not None and (row.system_text or "").strip())
    usr_custom = bool(row is not None and (row.user_text or "").strip())
    cur_system = row.system_text if sys_custom else default_system
    cur_user = row.user_text if usr_custom else default_user
    return {
        "call_name": call_name,
        "label": spec.label,
        "purpose": spec.purpose,
        "notes": spec.notes,
        "editable_fields": ["system"] + (["user"] if spec.user else []),
        # system
        "system": cur_system,
        "default_system": default_system,
        # **可编辑的模板原文**（含 {占位符}）——界面编辑器用这个（改占位符不能被渲染值吃掉）
        "raw_template": (row.system_text if sys_custom else spec.system),
        "default_raw_template": spec.system,
        "system_is_default": not sys_custom,
        "system_diff": reg.diff_lines(default_system, cur_system),
        # user（本批界面只读对照）
        "user": cur_user,
        "default_user": default_user,
        "user_is_default": not usr_custom,
        "user_diff": reg.diff_lines(default_user, cur_user),
        # 兼容/汇总字段：整条是否全默认 = 界面"是否默认"列
        "is_default": (not sys_custom) and (not usr_custom),
        "updated_at": _iso(row.updated_at) if row is not None else "",
        "required_placeholders": list(spec.system_required_placeholders),
        "required_tokens": list(spec.system_required_tokens),
        "placeholders": spec.placeholders,
    }


def spec_list(db, *, subject_id: str = "") -> dict:
    """提示词页左列 + 每条状态（当前值 / 是否默认 / 上次修改时间 / 与默认的差异）。"""
    items = [_view(db, name) for name in reg.PROMPTS]
    return {
        "prompts": items,
        "count": len(items),
        "changed": [i["call_name"] for i in items if not i["is_default"]],
    }


def get_one(db, call_name: str) -> dict:
    return _view(db, call_name)


def save(db, call_name: str, *, system_text: str | None = None,
         user_text: str | None = None, subject_id: str = "") -> dict:
    """保存提示词（改后**立即生效**）。硬约束缺失/模板语法错误 → ``reg.PromptError``（中文 422）。

    至少给一个字段；另一字段保持原样（未给 = 不动）。
    """
    spec = reg.PROMPTS.get(call_name)
    if spec is None:
        raise reg.PromptError(f"未知调用点「{call_name}」：提示词模板注册表未收录，拒绝保存")
    if system_text is None and user_text is None:
        raise reg.PromptError("没有要保存的内容（system/user 至少要给一个）")
    problems: list[str] = []
    if system_text is not None:
        problems += [f"system 模板：{p}" for p in reg.validate_text(call_name, system_text, field="system")]
    if user_text is not None:
        if not spec.user:
            problems.append("user 模板：该调用点没有 user 模板可改")
        else:
            problems += [f"user 模板：{p}" for p in reg.validate_text(call_name, user_text, field="user")]
    if problems:
        raise reg.PromptError("提示词未通过校验，已拒绝保存：" + "；".join(problems))

    row = _row(db, call_name)
    before_default = row is None or not (
        (row.system_text or "").strip() or (row.user_text or "").strip())
    if row is None:
        row = models.PromptOverride(call_name=call_name, system_text="", user_text="")
        db.add(row)
    if system_text is not None:
        row.system_text = system_text
    if user_text is not None:
        row.user_text = user_text
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    changed = []
    if system_text is not None:
        changed.append("system")
    if user_text is not None:
        changed.append("user")
    ledger.note(
        ledger.CAT_OTHER, f"提示词「{spec.label}」（{call_name}）",
        "用户修改了发往模型的提示词（" + "/".join(changed) + "），之后的生成会使用改后的版本"
        + ("（此前为默认版本）" if before_default else "（此前已是自定义版本）"),
        impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"call_name": call_name, "fields": changed,
                "chars": len(system_text or "") + len(user_text or "")},
    )
    out = _view(db, call_name)
    out["saved_fields"] = changed
    return out


def reset_one(db, call_name: str, *, field: str = "", subject_id: str = "") -> dict:
    """单条恢复默认（``field`` 空 = 该调用点整条；或仅 ``system`` / ``user``）。"""
    spec = reg.PROMPTS.get(call_name)
    if spec is None:
        raise reg.PromptError(f"未知调用点「{call_name}」：提示词模板注册表未收录")
    if field not in ("", "system", "user"):
        raise reg.PromptError(f"字段非法：{field!r}（只能是 system / user / 空）")
    row = _row(db, call_name)
    if row is not None:
        if field in ("", "system"):
            row.system_text = ""
        if field in ("", "user"):
            row.user_text = ""
        if not (row.system_text or "").strip() and not (row.user_text or "").strip():
            db.delete(row)
        db.commit()
        ledger.note(ledger.CAT_OTHER, f"提示词「{spec.label}」（{call_name}）",
                    "用户把该提示词恢复为默认版本"
                    + (f"（字段：{field}）" if field else "（整条）")
                    + "（自定义内容已删除）",
                    impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                    detail={"call_name": call_name, "field": field or "all"})
    return _view(db, call_name)


def reset_all(db, *, subject_id: str = "") -> dict:
    """全部恢复默认（前端恢复前确认）。"""
    rows = list(db.execute(select(models.PromptOverride)).scalars())
    names = [r.call_name for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()
    if names:
        ledger.note(ledger.CAT_OTHER, f"提示词（共 {len(names)} 条）",
                    "用户把全部提示词恢复为默认版本：" + "、".join(names),
                    impact=ledger.SCOPE_GLOBAL, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                    detail={"call_names": names})
    return {"reset": names, "count": len(names)}


def effective(db, call_name: str) -> dict:
    """**生成链路使用**：返回生效模板 + 版本标签（供审计"哪次生成用哪版提示词"）。

    ``{"system","user","system_version","user_version"}``；
    版本标签：``default:<call>`` 或 ``custom:<call>@<updated_at>``。
    """
    spec = reg.PROMPTS.get(call_name)
    if spec is None:
        raise reg.PromptError(f"未知调用点「{call_name}」：提示词模板注册表未收录")
    row = _row(db, call_name)
    sys_txt = row.system_text if (row is not None and (row.system_text or "").strip()) else spec.system
    usr_txt = row.user_text if (row is not None and (row.user_text or "").strip()) else spec.user
    tag = f"custom:{call_name}@{_iso(row.updated_at)}" if row is not None else f"default:{call_name}"
    usr_tag = (f"custom:{call_name}@{_iso(row.updated_at)}"
               if (row is not None and (row.user_text or "").strip()) else f"default:{call_name}")
    return {"system": sys_txt, "user": usr_txt,
            "system_version": tag, "user_version": usr_tag}


__all__ = ["spec_list", "get_one", "save", "reset_one", "reset_all", "effective"]
