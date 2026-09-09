"""api.errors_zh：对外错误中文化工具（docs/13 §2 绝对要求 · 2026-09-09 起）。

规则：
- 任何对前端可见的错误 message 必须为**中文**（含原因 + 可操作提示）；英文原文/堆栈只进日志；
- RequestValidationError / pydantic ValidationError → 中文摘要（字段中文名映射 + 错误类型映射）；
- HTTPException：已结构化（{error:{code,message}} 且 message 含中文）直接透传；
  否则按状态给中文兜底文案（保留 log 原始 detail）；
- 未捕获 Exception → 500 中文"服务器内部错误（类别），详情见日志"，不暴露 traceback。
"""
from __future__ import annotations

import re
from typing import Any

# 常见字段 → 中文名（用户可读提示用；未知字段回显原名）
FIELD_ZH: dict[str, str] = {
    "label": "学科名称",
    "subject_id": "学科 id",
    "description": "学科简介",
    "node_id": "知识点",
    "session_id": "会话",
    "unit_id": "单元",
    "unit": "单元",
    "units": "单元列表",
    "user_answer": "你的答案",
    "answer": "答案",
    "exercise_id": "题目编号",
    "params_seed": "题目参数",
    "question": "提问内容",
    "transcript": "口述文本",
    "prompt": "题目/提示内容",
    "mode": "模式",
    "fields": "修改字段",
    "brief": "学科简介",
    "count": "单元数量",
    "group_hint": "分组提示",
    "status": "状态",
    "source": "来源",
    "body": "请求内容",
    "payload": "提交内容",
    "user_id": "用户",
    "model_mode": "模型模式",
    "concept_tags": "概念标签",
    "objectives": "学习目标",
    "prereqs": "前置单元",
    "title": "标题",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_zh(text: str | None) -> bool:
    return bool(text and _CJK_RE.search(text))


def field_zh(name: str) -> str:
    return FIELD_ZH.get(name, name)


def _type_zh(error: dict[str, Any]) -> str:
    """pydantic 单条错误 → 中文短语（type 规则映射，docs/13 §2）。"""
    typ = str(error.get("type") or "value_error")
    if typ == "missing" or "required" in typ:
        return "缺少字段"
    if typ == "extra_forbidden":
        return "包含未知字段"
    if "literal" in typ or "enum" in typ:
        return "取值不在允许范围内"
    if "string_type" in typ or "type" in typ:
        return "格式错误（应为文本/指定类型）"
    if "int" in typ or "float" in typ or "number" in typ:
        return "格式错误（应为数字）"
    if "bool" in typ:
        return "格式错误（应为是/否）"
    if "list" in typ or "array" in typ:
        return "格式错误（应为列表）"
    if "dict" in typ or "object" in typ:
        return "格式错误（应为对象）"
    if "value_error" in typ:
        return "内容不符合要求"
    return "格式或取值有误"


def pydantic_summary_zh(exc: Exception, *, limit: int = 4) -> str:
    """pydantic ValidationError/RequestValidationError → 中文摘要（供 message 使用）。"""
    raw = getattr(exc, "errors", None)
    if callable(raw):
        try:
            items = raw()
        except Exception:
            items = []
    else:
        items = []
    if not items:
        return "请求内容不符合要求，请检查后重试"
    parts: list[str] = []
    for it in items[:limit]:
        loc = [str(x) for x in (it.get("loc") or []) if str(x) not in ("body", "query", "path")]
        where = "、".join(field_zh(x) for x in loc) or "请求内容"
        parts.append(f"{where}：{_type_zh(it)}")
    more = f"（共 {len(items)} 处）" if len(items) > limit else ""
    return "参数校验失败：" + "；".join(parts) + more + "。请修正后重试。"


def http_zh_message(status_code: int, fallback_code: str = "", raw: Any = None) -> str:
    """按 HTTP 状态给出中文兜底文案（raw 为原始 detail/消息，仅用于日志语义参考）。"""
    _ = raw
    base = {
        400: "请求不合法，请检查输入内容。",
        401: "未授权访问，请确认配置后重试。",
        403: "没有权限执行此操作。",
        404: "请求的资源不存在，请检查地址或刷新后重试。",
        409: "操作与当前状态冲突，请按提示完成前置条件后重试。",
        422: "请求参数不合法，请检查输入后重试。",
        429: "请求过于频繁，请稍后重试。",
        500: "服务器内部错误，详情见日志。",
        502: "上游服务暂时不可用，请稍后重试。",
        503: "服务暂时不可用，请稍后重试。",
    }
    if status_code in base:
        return base[status_code]
    if fallback_code in base:  # code 与状态不一致时的兜底文案
        return base[status_code] if status_code in base else "请求处理失败，请稍后重试。"
    return "请求处理失败，请稍后重试。"


def ensure_zh_message(message: str, *, status_code: int = 422) -> str:
    """保证对外 message 含中文：已有中文 → 原样；纯英文/占位 → 中文兜底。"""
    if has_zh(message):
        return message
    return http_zh_message(status_code)


__all__ = [
    "FIELD_ZH",
    "has_zh",
    "field_zh",
    "pydantic_summary_zh",
    "http_zh_message",
    "ensure_zh_message",
]
