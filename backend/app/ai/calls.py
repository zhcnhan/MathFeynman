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


# ---------- R27：缺口补答评估（轻量，非整体重评） ----------
class GapCheckIn(BaseModel):
    """补答评估输入（docs/09 R27 §2）：只针对当前追问与目标缺口，不做整体重评。

    - ``target_gap``：{key, description, evidence_quote, comment} —— 维度 key + 学生视角
      缺口描述 + 上轮 evidence/comment；
    - ``student_answer``：本轮**只**是补答文本（不含历史合并稿——R27 治锚定的关键）。
    """

    session_id: str
    node_id: str
    task_prompt: str = ""
    rubric_dimensions: list[dict] = Field(default_factory=list)  # [{key, weight, description}]
    core_concepts: list[str] = Field(default_factory=list)
    followup_question: str
    student_answer: str
    target_gap: dict


class GapCheckOut(BaseModel):
    """补答评估输出：gap_filled + 只更新缺口所属维度的 dimension_updates。"""

    gap_filled: bool = False
    dimension_updates: list[FeynmanDimScore] = Field(default_factory=list)
    comment: str = ""  # 面向学生的缺口说明/是否补上（展示用）


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
    # R27：账本已认可内容摘要（维度 key → 学生已被认可的原话/说明）。
    # 学生没把已认可点重抄一遍不扣分（治"整体稿越写越薄被旧分拖累"）。
    previously_acknowledged: list[dict] = Field(default_factory=list)


class FeynmanFollowupIn(BaseModel):
    session_id: str
    node_id: str
    student_transcript: str
    previous_scores: list[dict] = Field(default_factory=list)
    socratic_followups: list[str] = Field(default_factory=list)
    # R27：未达标缺口清单（定向追问；一次一个 —— 不再自由发问）
    unmet_gaps: list[dict] = Field(default_factory=list)


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
CALL_FEYNMAN_GAP_CHECK = CallSpec(
    # R27：补答 = 轻量缺口评估（只判"缺口是否补上 + 该维度新分"），不整体重评
    # → light 档足够且快（学生答完立刻看到涨分）；真模型可用时仍受 tier 决策链约束。
    "feynman_gap_check", "light", GapCheckIn, GapCheckOut, temperature=0.2, max_retries=2
)
CALL_CLASSIFY_ERROR = CallSpec(
    "classify_error", "light", ClassifyErrorIn, ClassifyErrorOut, temperature=0.0, max_retries=2
)
CALL_DRAFT_CONTENT = CallSpec(
    "draft_content", "light", DraftContentIn, DraftContentOut, temperature=0.6, max_retries=2
)


# ---------- 调用点 10：通用学科大纲起草（docs/14 Phase A A4） ----------
class OutlineDraftIn(BaseModel):
    brief: str = ""


class OutlineDraftMaterial(BaseModel):
    """起草输出的单条材料溯源（R36 D2）：材料标题 + 该材料的章节名/逐字引文。

    服务端在 ``outline.materials.check_unit_material`` 里校验（title 必须属于该学科引用库；
    section 必须是真实章节名或逐字出自材料正文的引文）。
    """

    title: str = ""
    section: str = ""


class OutlineDraftUnit(BaseModel):
    """AI 起草输出的单个大纲单元（终稿由 outline.finalize 收尾：id 化/修剪/校验）。"""

    title: str
    objectives: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    group: str = ""
    prereqs: list[str] = Field(default_factory=list)  # 更早单元本地序（u01…）或既有单元 id
    difficulty: int = 2
    requires_thinking: bool = False
    # R36 D2：逐单元材料溯源。**必须在此声明**——pydantic 默认丢弃未声明字段，
    # 漏声明会让"模型给了引用、服务端却收到空数组"（活体冒烟 2026-09-10 实测踩到，已加固用例）。
    materials: list[OutlineDraftMaterial] = Field(default_factory=list)


class OutlineDraftOut(BaseModel):
    units: list[OutlineDraftUnit] = Field(default_factory=list)


CALL_OUTLINE_DRAFT = CallSpec(
    "outline_draft", "light", OutlineDraftIn, OutlineDraftOut, temperature=0.7, max_retries=2
)


# ---------- 调用点 11：通用学科单元内容起草（docs/14 Phase B · B1） ----------
class UnitContentExercise(BaseModel):
    """AI 起草输出的单道练习题（kind ∈ boolean/choice/fill，服务器组装为 NodeDoc 并校验）。"""

    kind: Literal["boolean", "choice", "fill"]
    prompt: str
    answer_bool: bool = False          # boolean
    options: list[str] = Field(default_factory=list)
    answer_index: int = 0              # choice（0 起）
    expected: str = ""                 # fill
    aliases: list[str] = Field(default_factory=list)


class UnitContentDraftOut(BaseModel):
    lecture: str = ""
    feynman_task: str = ""
    exercises: list[UnitContentExercise] = Field(default_factory=list)


CALL_UNIT_CONTENT = CallSpec(
    "unit_content_draft", "light", OutlineDraftIn, UnitContentDraftOut,
    temperature=0.5, max_retries=2,
)


# ---------- 调用点 12：联网候选清单整理（docs/14 §8 · Phase C C1） ----------
class SearchCandidateItem(BaseModel):
    """整理后的单个候选（url 必须取自检索原始结果——服务端回滤防杜撰）。"""

    title: str
    url: str = ""
    source: str = ""
    summary: str = ""
    reason: str = ""


class SearchCandidatesIn(BaseModel):
    query: str = ""
    subject_label: str = ""
    subject_brief: str = ""
    results: list[dict] = Field(default_factory=list)  # 检索原始结果（供 LLM 挑选）


class SearchCandidatesOut(BaseModel):
    items: list[SearchCandidateItem] = Field(default_factory=list)


CALL_SEARCH_CANDIDATES = CallSpec(
    "search_candidates", "light", SearchCandidatesIn, SearchCandidatesOut,
    temperature=0.2, max_retries=1,
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
        CALL_FEYNMAN_GAP_CHECK,
        CALL_CLASSIFY_ERROR,
        CALL_DRAFT_CONTENT,
        CALL_OUTLINE_DRAFT,
        CALL_UNIT_CONTENT,
        CALL_SEARCH_CANDIDATES,
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
    "GapCheckIn",
    "GapCheckOut",
    "ClassifyErrorIn",
    "ClassifyErrorOut",
    "ErrorType",
]
