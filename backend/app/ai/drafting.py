"""AI 内容出稿 drafter（R13：服务侧在线生成接入）。

背景：原 AI 出稿器只存在于 scripts/gen_content.py（CLI），服务端 /api/selfextend/run
在配置了 LLM_API_KEY 时把 drafter 置 None → "继续下一关"直接 500（TypeError）。
本模块收编同一逻辑：scripts 与在线端点共用一套 schema 化出稿，避免双份漂移。

原则（docs/04 §6 / docs/05）：出稿 = 受控生成。draft_content 调用点已有 schema
（CALL_DRAFT_CONTENT，light 档），输出经 provider 层 JSON 校验；内容质量护栏 =
pipeline 自动校验（结构/无环/渲染/每题 sympy 验算 broken=0）与入库策略。
"""
from __future__ import annotations

import json

from ..config import get_settings


class DraftingError(RuntimeError):
    """AI 出稿不可用（无 key / provider 异常 / 输出非法）。"""


def _draft_messages(spec: dict) -> list[dict]:
    """构造 draft_content 调用消息。

    注意：draft_content 走 provider.chat_json 的 response_format=json_object，
    DeepSeek 要求 prompt 必须包含 'json' 字样，且模型输出必须是与 DraftContentOut
    匹配的 JSON（draft_md 字段承载完整节点 .md 文本）——此前提示词让模型"直接输出 md"
    与 JSON 模式冲突 → 400（R13 补记）。
    """
    system = (
        "你是学科教学内容编辑（数学 / 科学 / 人文同一套纪律）。本次必须输出 JSON（不要输出 JSON 以外的任何文字），"
        "格式：{\"draft_md\": \"<完整节点 .md 文件内容，作为单个 JSON 字符串>\"}。"
        "draft_md 内的换行请用 \\n 转义。draft_md 是 YanHui content 节点文件，"
        "**必须包含全部必填字段且 key 拼写与本骨架一致**：\n"
        "---\n"
        "id: <蓝图 id>\n"
        "title: <标题>\n"
        "level: primary\n"
        "topic: <主题>\n"
        "prereqs: [<前置 id>]\n"
        "objectives:\n"
        "  - <学习目标>\n"
        "core_concepts: [<核心概念>]\n"
        "explanation:\n"
        "  role: 教师讲解稿\n"
        "  body: |\n"
        "    <正文；LaTeX 显示公式 $$...$$ 单独成行，行内 $...$ 不跨行>\n"
        "worked_examples:\n"
        "  - prompt: <例题题干>\n"
        "    solution_steps:\n"
        "      - <步骤>\n"
        "exercises:\n"
        "  - id: ex1\n"
        "    kind: template\n"
        "    difficulty: 1\n"
        "    template:\n"
        "      prompt: \"<题干，参数占位如 {a}、{b}>\"\n"
        "      params:\n"
        "        a: {range: [1, 9], exclude: [0]}\n"
        "        b: {range: [1, 9], exclude: [0]}\n"
        "      answer_expr: \"<参数符号表达式，如 a+b>\"\n"
        "    check:\n"
        "      mode: numeric_value\n"
        "feynman:\n"
        "  task_prompt: <费曼任务：让学生用自己的话讲解什么>\n"
        "  rubric:\n"
        "    dimensions:\n"
        "      - {key: correctness, weight: 0.4}\n"
        "      - {key: own_words, weight: 0.2}\n"
        "      - {key: example_and_edge, weight: 0.2}\n"
        "      - {key: self_correction, weight: 0.2}\n"
        "    pass_threshold: 0.7\n"
        "  socratic_followups:\n"
        "    - <追问问题>\n"
        "---\n"
        "（正文可精简，但**结尾的 --- 行不可省略**）\n"
        "模板题纪律（违反即 sympy 自检失败）：params 只出整数；answer_expr 只允许 + - * / 、括号与参数，"
        "**禁止 round/floor/ceil/abs/mod 及对符号取整**；需要整除时用 constraint 保证（如 (c-b)%a==0）；"
        "目标含\"四舍五入/估算/约等于\"的题改出 fixed 题（题干写具体数字、check 配数值答案），"
        "不要用模板+取整实现。\n"
        "铁律：draft_md 必须以 --- 行开始、以 --- 行结束（无前导/尾随空行，不要代码围栏），"
        "front-matter 字段完整。教学事实简洁正确，适合目标学段。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"生成以下蓝图条目的内容节点文件（放进 JSON 的 draft_md 字段）：\n{json.dumps(spec, ensure_ascii=False)}"},
    ]


def make_ai_drafter(settings=None):
    """构建 AI 出稿 drafter(entry) -> .md 文本。无 LLM_API_KEY → None。"""
    settings = settings or get_settings()
    if not settings.llm_api_key:
        return None
    from .calls import CALL_DRAFT_CONTENT, DraftContentIn
    from .gateway import gateway_factory

    gw = gateway_factory(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        heavy_model=settings.llm_model_heavy,
        light_model=settings.llm_model_light,
    )
    provider = getattr(gw, "_p", None)
    if provider is None:
        return None

    def drafter(entry, errors: list[str] | None = None):
        spec = DraftContentIn(
            spec={
                "level": entry.level,
                "topic": entry.topic,
                "id_hint": entry.id,
                "title": entry.title,
                "objectives": entry.objectives,
                "prereqs": entry.prereqs,
                "difficulty": entry.difficulty,
                "requires_thinking": entry.requires_thinking,
                "format_note": (
                    "请严格按 YanHui content 节点 .md 格式（YAML front-matter + 正文），"
                    "含 ≥1 道模板题（check.mode 用 numeric_value 且 answer_expr 可 sympy 验算）"
                    "与 feynman(rubric 四维)。"
                ),
            }
        )
        messages = _draft_messages(spec.spec)
        if errors:  # R13/A2：校验失败自动修复——携带错误信息要求修正
            messages[-1] = {
                "role": "user",
                "content": messages[-1]["content"]
                + "\n\n[上一轮输出未通过自动校验，请修正后重新生成] 校验错误：\n"
                + "\n".join(f"- {e}" for e in errors[:6]),
            }
        out = provider.chat_json(CALL_DRAFT_CONTENT, messages)
        parsed = getattr(out, "parsed", None)
        md = parsed.get("draft_md") if isinstance(parsed, dict) else None
        if not md:
            raise DraftingError("AI 出稿返回为空或格式非法")
        return md

    return drafter


__all__ = ["make_ai_drafter", "DraftingError", "_draft_messages"]
