"""app.ai.gateway：AI 门面（service 唯一依赖面）。

- AiGateway（Protocol）：各调用点方法。两种实现：
  1. OpenAICompatibleGateway —— 真模型（默认 DeepSeek；ollama/Qwen 兼容），经
     ai.provider.chat_json（JSON 提取 + pydantic 校验 + 重试）产出，AiCallError 上抛；
  2. OfflineGateway —— 无 key/降级时的内容库兜底（docs/05 §6）与离线启发式（仅演示）。
- service 捕获 AiCallError 后按 docs/05 §6 降级，绝不脏状态。
"""
from __future__ import annotations

from typing import Protocol
from .calls import (
    AiCallError,
    AnswerQuestionIn,
    AnswerQuestionOut,
    CALL_ANSWER_QUESTION,
    CALL_CLASSIFY_ERROR,
    CALL_EXPLAIN_NODE,
    CALL_FEYNMAN_EVALUATE,
    CALL_FEYNMAN_FOLLOWUP,
    CALL_GENERATE_VARIANT,
    CALL_HINT_ON_ERROR,
    ClassifyErrorIn,
    ClassifyErrorOut,
    ExplainIn,
    ExplainOut,
    FeynmanDimScore,
    FeynmanEvaluateIn,
    FeynmanEvaluateOut,
    FeynmanFollowupIn,
    FeynmanFollowupOut,
    HintOnErrorIn,
    HintOnErrorOut,
    VariantIn,
    VariantOut,
)
from .provider import LogSink, OpenAICompatibleProvider
from .prompts import context_block, task_json

MIN_FEYNMAN_CHARS = 20  # docs/05 §5：口述 <20 字直接判敷衍，不进评分

_MODE_HINT = {
    "numeric_value": "先检查计算过程：代入、进位/借位、正负号，再核对题目要求。",
    "equation_solution": "检查三步：移项是否变号？同类项是否合并正确？系数除法是否算对？",
    "symbolic_equivalence": "检查代数变形：去括号每一项都乘到？合并同类项有没有漏项、错符号？",
    "boolean_judgment": "回到定义逐条核对：等式？含未知数？一元？一次？哪一条不满足？",
}


class AiGateway(Protocol):
    """service 只依赖此协议。所有方法要么返回校验过的输出，要么抛 AiCallError。

    strategy（R12）：fast|think|None —— 服务层经 ai/tier 决策后传入；None=按调用点默认档。
    """

    name: str

    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut: ...
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut: ...
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut: ...
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut: ...
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut: ...
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut: ...
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut: ...


class OfflineGateway:
    """确定性离线兜底实现（无 key 默认；真模型失败时 service 回落至此路径）。"""

    name = "offline"

    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        del strategy  # 离线实现忽略档位（决策层在 service 记账）
        header = "（离线模式：以下为官方讲解稿原文）\n\n"
        lecture = ctx.explanation_body.strip() or "（本节点暂无讲解稿）"
        asks: list[str] = []
        if ctx.core_concepts:
            asks.append(f"请确认：你能用自己的话说出「{ctx.core_concepts[0]}」是什么吗？")
        return ExplainOut(lecture_md=header + lecture, asked_to_confirm=asks)

    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        del strategy
        return AnswerQuestionOut(
            reply_md=(
                "（离线模式）我暂时无法针对你的具体问题自由作答。"
                "建议先重读本课讲解稿原文，再完成练习；如果仍卡住，请把卡住的那句话原样发给我，"
                "我会记录下来，联网后由老师为你详细解答。"
            ),
            needs_more_info=False,
            out_of_scope=False,
        )

    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        del strategy
        return HintOnErrorOut(hint_md=_MODE_HINT.get(ctx.mode, "再读一遍题目，检查每一步推导是否都有依据。"))

    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")

    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        del strategy
        text = ctx.transcript.strip()
        if len(text) < MIN_FEYNMAN_CHARS:
            raise AiCallError("feynman_evaluate", f"口述过短（{len(text)}<{MIN_FEYNMAN_CHARS}字），按敷衍处理")
        mentioned = [c for c in ctx.core_concepts if c in text]
        plausible = bool(mentioned)  # 提到核心概念 → 视为非胡言（离线启发式）
        score = 0.9 if plausible else 0.35
        quote = text[:40] + ("…" if len(text) > 40 else "")
        dims = [
            FeynmanDimScore(
                key=d["key"],
                score=score,
                evidence_quote=quote,
                comment=("提及核心概念，视为通过（离线启发式）" if plausible else "未涉及核心概念，需追问"),
            )
            for d in ctx.rubric_dimensions
        ]
        return FeynmanEvaluateOut(
            dimension_scores=dims,
            overall_note="离线启发式评分（未接 LLM），仅供参考。",
            misconceptions_found=[],
            recommend_action="pass" if plausible else "followup",
            confidence=1.0 if plausible else 0.3,  # 离线自评置信度（低=启发式）
        )

    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        del strategy
        if ctx.socratic_followups:
            return FeynmanFollowupOut(question_md=ctx.socratic_followups[0])
        return FeynmanFollowupOut(
            question_md="请用更具体的例子再讲一遍：这个概念解决什么问题？关键一步的依据是什么？"
        )

    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        return ClassifyErrorOut(error_type="unknown")


# --------------------------------------------------------------------------
# OpenAI 兼容网关（真模型）
# --------------------------------------------------------------------------
class OpenAICompatibleGateway:
    """经 provider.chat_json 调真模型；每个调用点 = schema 化（docs/05 §3/§6）。"""

    name = "openai-compatible"

    def __init__(self, provider: OpenAICompatibleProvider):
        self._p = provider

    # ---- prompt 装配通用 ----
    def _system(self, ctx, extra_bans: list[str] | None = None) -> str:
        return context_block(
            level=ctx.level if hasattr(ctx, "level") else "",
            explanation_body=getattr(ctx, "explanation_body", ""),
            worked_examples=getattr(ctx, "worked_examples", []) or [],
            whitelist=list(getattr(ctx, "whitelist", []) or []),
            core_concepts=list(getattr(ctx, "core_concepts", []) or []),
            style=getattr(ctx, "profile_style_block", ""),
            extra_bans=extra_bans,
        )

    # ---- 调用点 1：讲解 ----
    def explain_node(self, ctx: ExplainIn, *, strategy: str | None = None) -> ExplainOut:
        system = self._system(ctx)
        user = task_json(
            task="基于讲解稿为本节点写一份适合该生（考虑风格块）的演绎讲解（lecture_md，Markdown+LaTeX）。"
            "给出 1-3 个'引导确认/提问'出口（asked_to_confirm，学生应能自己回答的检查问题）。",
            node_title=ctx.node_title,
        )
        out = self._p.chat_json(CALL_EXPLAIN_NODE, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return ExplainOut(**out.parsed)

    # ---- 调用点 2：答疑 ----
    def answer_question(self, ctx: AnswerQuestionIn, *, strategy: str | None = None) -> AnswerQuestionOut:
        system = self._system(ctx)
        user = task_json(
            task="回答学生问题；若问题超出白名单/当前范围，回复应说明并置 out_of_scope=true。",
            question=ctx.student_question,
        )
        out = self._p.chat_json(CALL_ANSWER_QUESTION, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return AnswerQuestionOut(**out.parsed)

    # ---- 调用点 4：错题提示（禁令：禁止输出完整解答） ----
    def hint_on_error(self, ctx: HintOnErrorIn, *, strategy: str | None = None) -> HintOnErrorOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=[],
            core_concepts=[],
            extra_bans=[
                "这是提示生成：**绝对禁止给出完整解答或答案表达式**，只给方向性提示（哪一步可疑、检查什么）。",
            ],
        )
        user = task_json(
            task="给一条方向性提示（hint_md），帮助学生发现自己的错误。",
            prompt=ctx.prompt,
            mode=ctx.mode,
            student_answer=ctx.user_answer,
            judge_detail=ctx.judge_detail,
        )
        out = self._p.chat_json(CALL_HINT_ON_ERROR, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return HintOnErrorOut(**out.parsed)

    # ---- 调用点 6：费曼评分（逐字 evidence） ----
    def feynman_evaluate(self, ctx: FeynmanEvaluateIn, *, strategy: str | None = None) -> FeynmanEvaluateOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=list(getattr(ctx, "core_concepts", []) or []),
            core_concepts=list(getattr(ctx, "core_concepts", []) or []),
            extra_bans=[
                "评分必须可审计：每个维度必须给出 **evidence_quote —— 逐字引用学生原话片段**，禁止无据评分；"
                "misconceptions_found 也须附 evidence。",
            ],
        )
        user = task_json(
            task="按 rubric 逐维打分（score 0..1），给评语与逐字证据；给出 recommend_action；"
            "可附带评分置信度 confidence(0..1)（可选）。",
            task_prompt=ctx.task_prompt,
            rubric_dimensions=ctx.rubric_dimensions,
            transcript=ctx.transcript,
            previous_round=ctx.previous_round,
        )
        out = self._p.chat_json(CALL_FEYNMAN_EVALUATE, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return FeynmanEvaluateOut(**out.parsed)

    # ---- 调用点 7：Socratic 追问 ----
    def feynman_followup(self, ctx: FeynmanFollowupIn, *, strategy: str | None = None) -> FeynmanFollowupOut:
        system = context_block(
            level="",
            explanation_body="",
            worked_examples=[],
            whitelist=[],
            core_concepts=[],
            extra_bans=["追问应针对学生的薄弱点（misconceptions），一次只问一个问题，不用给出答案。"],
        )
        user = task_json(
            task="生成一条 Socratic 追问（question_md，可用 Markdown/LaTeX）。",
            socratic_topics=ctx.socratic_followups,
            previous_scores=ctx.previous_scores,
            student_transcript=ctx.student_transcript,
        )
        out = self._p.chat_json(CALL_FEYNMAN_FOLLOWUP, [{"role": "system", "content": system}, {"role": "user", "content": user}], strategy=strategy)
        return FeynmanFollowupOut(**out.parsed)

    # ---- 调用点 8：错误分类 ----
    def classify_error(self, ctx: ClassifyErrorIn) -> ClassifyErrorOut:
        system = (
            "[角色] 你是学习系统的错因分类器。\n"
            "[输出纪律] 只输出 JSON：{\"error_type\": \"<枚举>\"}。\n"
            f"枚举：arithmetic_slip | sign_error | concept_confusion | step_omission | "
            f"procedure_misuse | notation_error | unknown（无法归类时用 unknown）。"
        )
        user = task_json(task="分类学生的错答类型", prompt=ctx.prompt, correct_solution=ctx.correct_solution, student_answer=ctx.user_answer)
        out = self._p.chat_json(CALL_CLASSIFY_ERROR, [{"role": "system", "content": system}, {"role": "user", "content": user}])
        return ClassifyErrorOut(**out.parsed)

    # ---- 调用点 3：变体（MVP 不启用，docs/08 §1） ----
    def generate_practice_variant(self, ctx: VariantIn) -> VariantOut:
        raise AiCallError("generate_practice_variant", "MVP 不启用 AI 变体出题（docs/08 §1）")


# --------------------------------------------------------------------------
# 工厂
# --------------------------------------------------------------------------
def gateway_factory(
    *,
    api_key: str = "",
    base_url: str = "",
    heavy_model: str = "",
    light_model: str = "",
    log_sink: LogSink | None = None,
    transport=None,
) -> AiGateway:
    """有 key → OpenAI 兼容真网关；无 key → OfflineGateway（离线兜底）。"""
    if api_key:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            model_heavy=heavy_model,
            model_light=light_model,
            log_sink=log_sink,
            transport=transport,
        )
        return OpenAICompatibleGateway(provider)
    return OfflineGateway()


__all__ = ["AiGateway", "OfflineGateway", "OpenAICompatibleGateway", "gateway_factory", "MIN_FEYNMAN_CHARS"]
