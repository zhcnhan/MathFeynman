"""app.ai.prompts：调用点 prompt 装配（docs/05 §4 ContextBlock 注入规范）。

R39 §2 起：**所有**模板文本住在 ``ai.prompt_templates``（可在程序内修改、可恢复默认）；
本模块只负责把 ContextBlock 的**各部分**算出来（占位符取值），由注册表渲染成最终文本。
白名单由程序取 prereqs ∪ core_concepts，LLM 无权扩白。

历史接口 ``context_block(**kw)`` 保留（返回渲染后的完整字符串），供测试与离线路径复用。
"""
from __future__ import annotations

import json
from typing import Any

# 默认禁令（注册表的 {bans} 占位符取值；调用点可追加 extra_bans）
BASE_BANS = [
    "禁止引入白名单之外的新名词/公式/方法；如果学生问题超出范围，"
    "回答'这属于后面的部分，我们先专注当前内容'并给出继续学习的建议。",
]


def context_parts(
    *,
    level: str,
    explanation_body: str,
    worked_examples: list[str],
    whitelist: list[str],
    core_concepts: list[str],
    style: str = "",
    extra_bans: list[str] | None = None,
) -> dict[str, str]:
    """ContextBlock 的逐项取值（R39 §2：模板可改，取值由程序算）。"""
    del core_concepts  # 白名单已由调用方算好（prereqs ∪ core_concepts）
    examples = "\n".join(f"- {w}" for w in worked_examples) or "（无）"
    bans = [*BASE_BANS, *(extra_bans or [])]
    return {
        "level": level or "当前学段",
        "explanation_body": explanation_body.strip()
        or "（讲解稿为空，请仅围绕 core_concepts 基础事实讲解，不得自行发明内容。）",
        "worked_examples": examples,
        "whitelist": "、".join(whitelist) or "（仅讲解稿中已有概念）",
        "bans": "；".join(bans),
        "style": style or "解释清晰、循序渐进，面向初学者。",
    }


def context_block(**kw: Any) -> str:
    """docs/05 §4 的统一 ContextBlock（= 注册表 ``explain_node`` 的 system 默认模板渲染）。

    保留为函数：离线路径/既有测试/工具脚本仍按"传取值、拿文本"使用。
    """
    from .prompt_templates import PROMPTS, render

    return render(PROMPTS["explain_node"].system, **context_parts(**kw))


def task_json(**kw: Any) -> str:
    """（历史接口）把任务 JSON 序列化；R39 起各调用点改用注册表的 user 模板。"""
    return "输出 JSON：\n" + json.dumps(kw, ensure_ascii=False)


__all__ = ["context_block", "context_parts", "task_json", "BASE_BANS"]
