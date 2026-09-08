"""app.ai.prompts：调用点 prompt 装配（docs/05 §4 ContextBlock 注入规范）。

每个生成类调用点 system prompt 统一含：
[角色][教学内容真源][概念白名单][禁令][风格][输出纪律]。
白名单由程序取 prereqs ∪ core_concepts，LLM 无权扩白。
"""
from __future__ import annotations

import json
from typing import Any


def context_block(
    *,
    level: str,
    explanation_body: str,
    worked_examples: list[str],
    whitelist: list[str],
    core_concepts: list[str],
    style: str = "",
    extra_bans: list[str] | None = None,
) -> str:
    """docs/05 §4 的统一 ContextBlock。"""
    examples = "\n".join(f"- {w}" for w in worked_examples) or "（无）"
    bans = [
        "禁止引入白名单之外的新名词/公式/方法；如果学生问题超出范围，"
        "回答'这属于后面的部分，我们先专注当前内容'并给出继续学习的建议。",
        *(extra_bans or []),
    ]
    return "\n".join(
        [
            "[角色] 你是本学习系统的数学导师，面向" + (level or "当前学段") + "学生。",
            "[教学内容真源] 以下是本节点官方讲解稿，只能在此基础上演绎，不得改动事实：",
            explanation_body.strip() or "（讲解稿为空，请仅围绕 core_concepts 基础事实讲解，不得自行发明内容。）",
            "[例题原文]",
            examples,
            f"[概念白名单] 允许涉及的概念：{'、'.join(whitelist) or '（仅讲解稿中已有概念）'}。",
            f"[禁令] {'；'.join(bans)}",
            f"[风格] {style or '解释清晰、循序渐进，面向初学者。'}",
            "[LaTeX 输出纪律] 数学公式必须满足："
            "① 显示公式用 $$...$$ 且**单独成行**（公式所在行除 $$ 外不得有其它文字）；"
            "② 行内公式用 $...$ 且**不得跨行**（单个 $...$ 内禁止包含换行符，公式不要折行书写）；"
            "③ 所有 $ 定界符必须成对闭合，禁止孤立/杂散的 $ 或 $$（如表示金钱时用文字'元'，不要写 '$5$' 之外的孤立 $）；"
            "④ 讲解文本不得夹带孤立 $$（前后无成对内容即视为孤立，必须删除）。",
            "[输出纪律] 只输出 JSON，字段严格符合给定 schema；讲解正文除 LaTeX 公式外的行内代码/符号用反引号包裹。",
        ]
    )


def task_json(**kw: Any) -> str:
    return "输出 JSON：\n" + json.dumps(kw, ensure_ascii=False)


__all__ = ["context_block", "task_json"]
