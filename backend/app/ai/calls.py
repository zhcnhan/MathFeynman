"""app.ai.calls：LLM 调用点清单（docs/05 §3）。每个调用点 = 一个 CallSpec。

MVP 调用点（docs/08 §1：variant/draft 保留接口不启用）：
  1 explain_node · 2 answer_question · 3 generate_practice_variant(不启用)
  4 hint_on_error · 5 explain_solution_step(轻，未列入 M3 必须？docs M3 列 1/2/4/6/7/8)
  6 feynman_evaluate · 7 feynman_followup · 8 classify_error · 9 draft_content(P1)

输入/输出全部 pydantic（输出先校验再生效，docs/05 §6/§7）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Type

from pydantic import BaseModel, Field

# ---------- 公共概念 ----------
ErrorType = Literal[
    "arithmetic_slip",
    "sign_error",
    "concept_confusion",
    "step_omission",
    "procedure_misuse",
    "notation_error",
    "unknown",
]

ModelTier = Literal["heavy", "light"]


# ---------- 输出 Schema（LLM 必须产出；pydantic 校验） ----------
class ExplainOut(BaseModel):
    lecture_md: str
    asked_to_confirm: list[str] = Field(default_factory=list)  # 引导确认/提问出口


class AnswerQuestionOut(BaseModel):
    reply_md: str
    needs_more_info: bool = False
    out_of_scope: bool = False  # R12：问题超出白名单/当前范围（触发 think 重生成）


class HintOnErrorOut(BaseModel):
    hint_md: str


class VariantOut(BaseModel):
    param_values: dict = Field(default_factory=dict)
    prompt_md: str


class SolutionStepOut(BaseModel):
    step_explanation_md: str


class FeynmanDimScore(BaseModel):
    key: str
    score: float = Field(ge=0, le=1)
    evidence_quote: str  # 必须逐字引用学生原话（docs/05 §5 防无据评分）
    comment: str


class FeynmanMisconception(BaseModel):
    concept: str
    evidence: str


class FeynmanEvaluateOut(BaseModel):
    dimension_scores: list[FeynmanDimScore]
    overall_note: str = ""
    misconceptions_found: list[FeynmanMisconception] = Field(default_factory=list)
    recommend_action: Literal["pass", "followup", "relearn"] = "followup"
    confidence: float | None = None  # R12：可选评分置信度（0..1），供边缘区间决策参考


class FeynmanFollowupOut(BaseModel):
    question_md: str


class ClassifyErrorOut(BaseModel):
    error_type: ErrorType = "unknown"


class DraftContentOut(BaseModel):
    draft_md: str


# ---------- 输入 Schema（含注入片段；内容全部来自程序） ----------
class ExplainIn(BaseModel):
    session_id: str
    node_id: str
    node_title: str
    level: str
    explanation_body: str
    worked_examples: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    prereq_titles: list[str] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)  # = core_concepts ∪ prereq titles
    profile_style_block: str = ""


class AnswerQuestionIn(BaseModel):
    session_id: str
    node_id: str
    node_title: str
    level: str
    explanation_body: str
    whitelist: list[str] = Field(default_factory=list)
    profile_style_block: str = ""
    student_question: str


class HintOnErrorIn(BaseModel):
    node_id: str
    prompt: str
    mode: str
    user_answer: str
    judge_detail: str = ""


class VariantIn(BaseModel):
    node_id: str
    exercise_prompt_tpl: str
    given_params: list[dict] = Field(default_factory=list)  # 已出题列表（防重复）


class SolutionStepIn(BaseModel):
    step_text: str


class FeynmanEvaluateIn(BaseModel):
    session_id: str
    node_id: str
    task_prompt: str
    rubric_dimensions: list[dict]  # [{key, weight, description}]
    core_concepts: list[str] = Field(default_factory=list)  # 评分语境（程序注入）
    transcript: str
    previous_round: dict | None = None  # 二轮起：首轮评分摘要


class FeynmanFollowupIn(BaseModel):
    session_id: str
    node_id: str
    student_transcript: str
    previous_scores: list[dict] = Field(default_factory=list)
    socratic_followups: list[str] = Field(default_factory=list)


class ClassifyErrorIn(BaseModel):
    node_id: str
    prompt: str
    correct_solution: str
    user_answer: str


class DraftContentIn(BaseModel):
    spec: dict  # level/topic/objectives/prereqs 等（P1）


# ---------- CallSpec ----------
@dataclass(frozen=True)
class CallSpec:
    name: str
    model_tier: ModelTier
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    temperature: float = 0.6
    max_retries: int = 2


CALL_EXPLAIN_NODE = CallSpec(
    "explain_node", "light", ExplainIn, ExplainOut, temperature=0.6, max_retries=2
    # R9: 讲解 = 基于注入讲解稿的演绎，不依赖深度推理 → light 档（deepseek-chat）提速；
    # 重新生成讲解走同一调用点，同样为 light。质量回退可回滚并留痕于 docs/09 R9。
)
CALL_ANSWER_QUESTION = CallSpec(
    "answer_question", "heavy", AnswerQuestionIn, AnswerQuestionOut, temperature=0.6, max_retries=2
)
CALL_GENERATE_VARIANT = CallSpec(
    "generate_practice_variant", "light", VariantIn, VariantOut, temperature=0.8, max_retries=2
)
CALL_HINT_ON_ERROR = CallSpec(
    "hint_on_error", "light", HintOnErrorIn, HintOnErrorOut, temperature=0.3, max_retries=2
)
CALL_EXPLAIN_SOLUTION_STEP = CallSpec(
    "explain_solution_step", "light", SolutionStepIn, SolutionStepOut, temperature=0.4, max_retries=2
)
CALL_FEYNMAN_EVALUATE = CallSpec(
    "feynman_evaluate", "heavy", FeynmanEvaluateIn, FeynmanEvaluateOut, temperature=0.2, max_retries=2
)
CALL_FEYNMAN_FOLLOWUP = CallSpec(
    "feynman_followup", "heavy", FeynmanFollowupIn, FeynmanFollowupOut, temperature=0.6, max_retries=2
)
CALL_CLASSIFY_ERROR = CallSpec(
    "classify_error", "light", ClassifyErrorIn, ClassifyErrorOut, temperature=0.0, max_retries=2
)
CALL_DRAFT_CONTENT = CallSpec(
    "draft_content", "light", DraftContentIn, DraftContentOut, temperature=0.6, max_retries=2
)

CALLS: dict[str, CallSpec] = {
    c.name: c for c in (
        CALL_EXPLAIN_NODE,
        CALL_ANSWER_QUESTION,
        CALL_GENERATE_VARIANT,
        CALL_HINT_ON_ERROR,
        CALL_EXPLAIN_SOLUTION_STEP,
        CALL_FEYNMAN_EVALUATE,
        CALL_FEYNMAN_FOLLOWUP,
        CALL_CLASSIFY_ERROR,
        CALL_DRAFT_CONTENT,
    )
}


class AiCallError(Exception):
    """AI 调用失败（重试耗尽/校验失败/断网）。service 捕获后降级（docs/05 §6）。"""

    def __init__(self, call_name: str, reason: str = ""):
        self.call_name = call_name
        self.reason = reason
        super().__init__(f"AI 调用失败 [{call_name}]: {reason}")


__all__ = [
    "CallSpec",
    "CALLS",
    "AiCallError",
    "ExplainIn",
    "ExplainOut",
    "AnswerQuestionIn",
    "AnswerQuestionOut",
    "HintOnErrorIn",
    "HintOnErrorOut",
    "VariantIn",
    "VariantOut",
    "SolutionStepIn",
    "SolutionStepOut",
    "FeynmanEvaluateIn",
    "FeynmanEvaluateOut",
    "FeynmanDimScore",
    "FeynmanFollowupIn",
    "FeynmanFollowupOut",
    "FeynmanMisconception",
    "ClassifyErrorIn",
    "ClassifyErrorOut",
    "ErrorType",
]
