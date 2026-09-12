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


class CiteBasis(BaseModel):
    """R35 S2/S6：一个问题的**依据**（引用的已述事实 id + 讲解原文引文；推理题另附前提与规则）。

    ⚠️ 必须在 schema 里声明（R36 §8 纪律）：pydantic 默认丢弃未声明字段 ——
    漏声明会让"模型给了依据、服务端收到空"，整条引文纪律**静默失效**。
    """

    fact_ids: list[str] = Field(default_factory=list)
    quote: str = ""
    premises: list[str] = Field(default_factory=list)  # 仅推理题
    rule: str = ""                                     # 仅推理题


# ---------- 输出 Schema（LLM 必须产出；pydantic 校验） ----------
class ExplainOut(BaseModel):
    lecture_md: str
    asked_to_confirm: list[str] = Field(default_factory=list)  # 引导确认/提问出口
    # R35 S6：与 asked_to_confirm **按下标对齐**的依据（无据的那条不下发——模板套话不再兜底）
    asks_basis: list[CiteBasis] = Field(default_factory=list)


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
    """R27 定向追问（R35 S4 补强）。

    S4 纪律：追问**必须逐字引用学生刚说过的话**（`student_quote`，服务端做逐字包含校验，
    与费曼 evidence / basis 同一把尺子），并指出"这句话缺了什么"（`missing`）。
    学生**没有可引用的实质内容**（如只写"我不知道"）→ 置 `reteach=true`，
    由服务端返回 `reteach`（退回讲解补讲），**禁止硬造发散题**。
    """

    question_md: str = ""
    student_quote: str = ""   # 逐字引用学生原话（服务端校验包含关系）
    missing: str = ""         # 这句话缺了什么（学生视角）
    reteach: bool = False     # 无可引用内容 → 退回讲解补讲（不发追问）


# ---------- R35 S3（挑战题池）：单独生成 / 单独判分 ----------
class ChallengeIn(BaseModel):
    """挑战题生成输入（**与核心题池刻意相反**：挑战题就是要超出讲解）。

    字段与 `ExplainIn` 对齐，以便**复用同一套 ContextBlock 注入范式**（ai/prompts.context_block）。
    """

    session_id: str = ""
    node_id: str = ""
    node_title: str = ""
    level: str = ""
    explanation_body: str = ""
    worked_examples: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)
    profile_style_block: str = ""
    asked: int = 0            # 本会话已生成次数（仅用于"换一道"去重，不限额）


class ChallengeOut(BaseModel):
    """一道挑战题（**永不进默认流程**、**完全不上算**：不进费曼账本/mastery/额度/掌握统计）。"""

    prompt_md: str
    answer_hint_md: str = ""   # 作答形式提示（如"只填数字"）
    why_hard_md: str = ""      # 为什么它需要讲解之外的知识（对学习者解释，非考点）
    difficulty: int = 3


class ChallengeCheckIn(BaseModel):
    session_id: str = ""
    node_id: str = ""
    node_title: str = ""
    prompt_md: str
    student_answer: str


class ChallengeCheckOut(BaseModel):
    """挑战题判分结果（**只记复盘**：不写任何账本）。"""

    correct: bool = False
    score: float = Field(default=0.0, ge=0, le=1)
    feedback_md: str = ""      # 对学习者说的话（鼓励 + 指出差在哪）
    better_md: str = ""        # 参考思路（挑战题可以给答案：它不上算，教比考重要）


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
    # R35 S1/S6：本节点已声明的事实句（旧内容为空）——S6 的小思考可以引用其 id，服务端据此校验
    taught_facts: list[dict] = Field(default_factory=list)


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
    # R9: 讲解 = 基于注入讲解稿的演绎，不依赖深度推理 → light 档（deepseek-flash）提速；
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
CALL_CHALLENGE_EXERCISE = CallSpec(
    # R35 S3：挑战题**单独调模型生成**（永不出现在默认流程）。light 档足够；
    # 温度高于核心题池（0.8）：挑战题要"发散"，这是用户拍板的特性，不是缺陷。
    "challenge_exercise", "light", ChallengeIn, ChallengeOut, temperature=0.8, max_retries=2
)
CALL_CHALLENGE_CHECK = CallSpec(
    # R35 S3：挑战题判分（无 rubric、无 L1 验算 → 如实分界，只能靠模型判）；
    # 结果**只记复盘**，绝不并入费曼账本/mastery/额度/掌握统计。
    "challenge_check", "light", ChallengeCheckIn, ChallengeCheckOut, temperature=0.2, max_retries=2
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
class UnitContentBasis(CiteBasis):
    """单元内容起草里的依据（与 `CiteBasis` 同结构；保留独立名字以标注调用点语义）。"""


class UnitContentFact(BaseModel):
    """R35 S1：本单元显式陈述的事实句（`text` 必须逐字取自讲解）。"""

    id: str = ""
    text: str = ""


class UnitContentDerivable(BaseModel):
    """R35 S1：允许的推理（结论 + 依据的事实 id + 规则）。"""

    conclusion: str = ""
    premises: list[str] = Field(default_factory=list)
    rule: str = ""


class UnitContentWorkedExample(BaseModel):
    """R35 A3：例题（示范"如何合法作答"）。"""

    prompt: str = ""
    solution_steps: list[str] = Field(default_factory=list)


class UnitContentAsk(BaseModel):
    """R35 S2/S6：运行时"🤔 小思考"，**必须带依据**（模板套话不再兜底）。"""

    ask: str = ""
    basis: UnitContentBasis | None = None


class UnitContentExercise(BaseModel):
    """AI 起草输出的单道练习题（kind ∈ boolean/choice/fill，服务器组装为 NodeDoc 并校验）。"""

    kind: Literal["boolean", "choice", "fill"]
    prompt: str
    answer_bool: bool = False          # boolean
    options: list[str] = Field(default_factory=list)
    answer_index: int = 0              # choice（0 起）
    expected: str = ""                 # fill
    aliases: list[str] = Field(default_factory=list)
    basis: UnitContentBasis | None = None  # R35 S2：无依据 → 服务端按"不可答"丢弃该题


class UnitContentDraftOut(BaseModel):
    lecture: str = ""
    feynman_task: str = ""
    taught_facts: list[UnitContentFact] = Field(default_factory=list)      # R35 S1
    derivable: list[UnitContentDerivable] = Field(default_factory=list)    # R35 S1
    worked_examples: list[UnitContentWorkedExample] = Field(default_factory=list)  # R35 A3
    asks: list[UnitContentAsk] = Field(default_factory=list)               # R35 S2/S6
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


# ---------------------------------------------------------------------------
# **R56 第 1 步**：读教材页/图（全 AI 模式的第一步——把"这一页/这张图里有什么"变成结构化记录）
# ---------------------------------------------------------------------------
class ReadPageIn(BaseModel):
    """要点：这次要读的是哪一页/哪张图，以及"想让它读出什么"。图片本身在消息里（多模态）。"""

    page_label: str = ""          # 页/图号（如"第 12 页"、"图 6.1"）——依据必须指到它
    want: str = ""                # 本次想读出来的东西（如"这一页的正文要点与公式"）
    note: str = ""                # 程序附注（如"整页扫描图，字可能很小"）


class ReadPageOut(BaseModel):
    """结构化"读到了什么"：**读不出来必须明说**（`readable=False` + 原因），不许编。"""

    page_label: str = ""
    readable: bool = True
    unreadable_reason: str = ""       # readable=False 时**必填**中文原因
    key_points: list[str] = Field(default_factory=list)      # 这一页讲了什么（要点）
    visible_text: list[str] = Field(default_factory=list)    # 图上/页面上真能看到的文字（逐条）
    formulas: list[str] = Field(default_factory=list)        # 公式（看不清就写在 unreadable_reason 里）
    figures: list[dict] = Field(default_factory=list)        # 图：[{label, kind, description}]（描述图里画了什么）
    uncertain: list[str] = Field(default_factory=list)       # 看不清/拿不准的地方（宁可少说）
    confidence: float = 0.0           # 0~1，自评"读得有多确定"


CALL_READ_PAGE = CallSpec(
    "read_page", "light", ReadPageIn, ReadPageOut, temperature=0.1, max_retries=1,
)


# ---------------------------------------------------------------------------
# **R67 任务 F（批量读）**：一次调用读 2–4 页 —— **仍然一页一条记录**
#
# 为什么要独立一个调用点：省的是"网络往返次数"，不是"读得粗"。口径必须是
# "一次发几张图，回来 N 条记录、每条各自带页号"，**绝不允许**把几页糊成一条。
# ---------------------------------------------------------------------------
class ReadPagesIn(BaseModel):
    """批量读：一次要读的页（按顺序）+ 想读出来的东西。图片本体在消息里（多模态）。"""

    page_labels: list[str] = Field(default_factory=list)   # 这一批要读的页号（一页一条记录）
    want: str = ""
    note: str = ""


class ReadPagesItem(BaseModel):
    """**每页一条**的读取记录（字段与单页读时逐字相同）。"""

    page_label: str = ""
    readable: bool = True
    unreadable_reason: str = ""
    key_points: list[str] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    figures: list[dict] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ReadPagesOut(BaseModel):
    pages: list[ReadPagesItem] = Field(default_factory=list)


CALL_READ_PAGES = CallSpec(
    "read_pages", "light", ReadPagesIn, ReadPagesOut, temperature=0.1, max_retries=1,
)


# ---------------------------------------------------------------------------
# **R56 第 2 步**：图示教材模式（全 AI 模式）的完整提示词调用点
#
# 为什么要**独立一套**（不与路径②共用）：路径②的提示词里写着"必须逐字出自教材段落"
# "服务端会丢弃找不到依据的题"——那套尺子在本模式**不成立**（本模式没有可检索原文，
# 依据只能指到"页/图号"）。共用会让两条路径的口径互相污染（工单 §1/§3-A 明确禁止）。
#
# **诚实出口**：凡是"判/评"的调用点都带 `uncertain` + `uncertain_reason`——
# 模型读不出来/拿不准时**必须**走这个出口，不许硬给对错（工单 §5-任务 C）。
# ---------------------------------------------------------------------------
class ModeOutlineIn(BaseModel):
    subject_label: str = ""
    brief: str = ""
    pages_digest: str = ""        # 各页"读到了什么"的结构化摘要（程序拼好给它）
    want_count: int = 0
    errors: list[str] = Field(default_factory=list)   # 上一轮不通过的原因（回灌）


class ModeUnit(BaseModel):
    title: str = ""
    objectives: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)   # 依据指到页/图号（本模式没有逐字原文）


class ModeOutlineOut(BaseModel):
    units: list[ModeUnit] = Field(default_factory=list)
    uncertain: bool = False
    uncertain_reason: str = ""


class ModeLessonIn(BaseModel):
    unit_title: str = ""
    objectives: list[str] = Field(default_factory=list)
    pages_digest: str = ""        # 本单元相关页的"读到了什么"
    errors: list[str] = Field(default_factory=list)


class ModeLessonOut(BaseModel):
    lecture_md: str = ""
    key_points: list[str] = Field(default_factory=list)
    worked_examples: list[dict] = Field(default_factory=list)   # [{prompt, solution_steps[]}]
    source_pages: list[str] = Field(default_factory=list)
    uncertain: bool = False
    uncertain_reason: str = ""


class ModeExerciseOutItem(BaseModel):
    prompt: str = ""
    kind: Literal["choice", "boolean", "short"] = "short"
    options: list[str] = Field(default_factory=list)
    answer: str = ""              # 标准答案（模型给的，本模式没有独立验算）
    explanation: str = ""         # 解析
    basis_pages: list[str] = Field(default_factory=list)        # 依据指到页/图号


class ModeExerciseIn(BaseModel):
    unit_title: str = ""
    key_points: list[str] = Field(default_factory=list)
    pages_digest: str = ""
    want_count: int = 3
    kind: Literal["practice", "challenge"] = "practice"
    asked_before: list[str] = Field(default_factory=list)


class ModeExerciseOut(BaseModel):
    exercises: list[ModeExerciseOutItem] = Field(default_factory=list)
    uncertain: bool = False
    uncertain_reason: str = ""


class ModeJudgeIn(BaseModel):
    prompt: str = ""
    kind: str = "short"
    options: list[str] = Field(default_factory=list)
    reference_answer: str = ""    # 出题时给的标准答案（仅供参考：本模式由模型自己判）
    explanation: str = ""
    student_answer: str = ""
    pages_digest: str = ""        # 相关页"读到了什么"（判题依据）


class ModeJudgeOut(BaseModel):
    """判对错的**诚实出口**：`verdict="uncertain"` 时**必须**给中文原因，且不打分。"""

    verdict: Literal["correct", "partial", "wrong", "uncertain"] = "uncertain"
    uncertain_reason: str = ""
    score_0_1: float = 0.0        # 部分对时给 0~1 的把握度/完成度
    feedback_md: str = ""         # 对学习者说人话
    better_md: str = ""           # 更对的思路/答案（只讲思路也行）
    basis_pages: list[str] = Field(default_factory=list)


class ModeFeynmanIn(BaseModel):
    task_prompt: str = ""
    dimensions: list[str] = Field(default_factory=list)
    transcript: str = ""
    pages_digest: str = ""


class ModeDimensionScore(BaseModel):
    key: str = ""
    score: float = 0.0
    evidence_quote: str = ""      # **逐字**引用学生原话（本模式唯一可逐字核对的东西）
    comment: str = ""


class ModeFeynmanOut(BaseModel):
    dimension_scores: list[ModeDimensionScore] = Field(default_factory=list)
    overall_note: str = ""
    verdict: Literal["pass", "followup", "uncertain"] = "followup"
    uncertain_reason: str = ""
    confidence: float = 0.0


class ModeFollowupIn(BaseModel):
    transcript: str = ""
    missing: list[str] = Field(default_factory=list)
    pages_digest: str = ""


class ModeFollowupOut(BaseModel):
    question_md: str = ""
    missing: str = ""
    student_quote: str = ""       # 逐字引用学生原话（引不出来 → reteach）
    reteach: bool = False         # 学生的话没有实质内容 → 让他回去看讲解（不硬造问题）
    uncertain: bool = False
    uncertain_reason: str = ""


class ModeGapCheckIn(BaseModel):
    followup_question: str = ""
    target_dimension: str = ""
    student_answer: str = ""
    pages_digest: str = ""


class ModeGapCheckOut(BaseModel):
    gap_filled: bool = False
    score_0_1: float = 0.0
    comment: str = ""
    uncertain: bool = False
    uncertain_reason: str = ""


class ModeQaIn(BaseModel):
    question: str = ""
    unit_title: str = ""
    pages_digest: str = ""


class ModeQaOut(BaseModel):
    reply_md: str = ""
    out_of_scope: bool = False    # 问的东西不在教材这些页里
    uncertain: bool = False
    uncertain_reason: str = ""


def _mode_call(name: str, inp: Type[BaseModel], outp: Type[BaseModel], *,
               tier: ModelTier = "light", temperature: float = 0.3) -> CallSpec:
    return CallSpec(name, tier, inp, outp, temperature=temperature, max_retries=1)


CALL_MODE_OUTLINE = _mode_call("mode_outline", ModeOutlineIn, ModeOutlineOut, temperature=0.4)
CALL_MODE_LESSON = _mode_call("mode_lesson", ModeLessonIn, ModeLessonOut, temperature=0.6)
CALL_MODE_EXERCISE = _mode_call("mode_exercise", ModeExerciseIn, ModeExerciseOut, temperature=0.6)
# 判对错给低温度：本模式没有独立验算，模型的判断要尽量稳定、别"越判越飘"
CALL_MODE_JUDGE = _mode_call("mode_judge", ModeJudgeIn, ModeJudgeOut, temperature=0.1)
CALL_MODE_FEYNMAN = _mode_call("mode_feynman", ModeFeynmanIn, ModeFeynmanOut, temperature=0.2)
CALL_MODE_FOLLOWUP = _mode_call("mode_followup", ModeFollowupIn, ModeFollowupOut, temperature=0.4)
CALL_MODE_GAP_CHECK = _mode_call("mode_gap_check", ModeGapCheckIn, ModeGapCheckOut, temperature=0.2)
CALL_MODE_QA = _mode_call("mode_qa", ModeQaIn, ModeQaOut, temperature=0.5)

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
        CALL_CHALLENGE_EXERCISE,
        CALL_CHALLENGE_CHECK,
        CALL_DRAFT_CONTENT,
        CALL_OUTLINE_DRAFT,
        CALL_UNIT_CONTENT,
        CALL_SEARCH_CANDIDATES,
        CALL_READ_PAGE,
        CALL_READ_PAGES,
        CALL_MODE_OUTLINE,
        CALL_MODE_LESSON,
        CALL_MODE_EXERCISE,
        CALL_MODE_JUDGE,
        CALL_MODE_FEYNMAN,
        CALL_MODE_FOLLOWUP,
        CALL_MODE_GAP_CHECK,
        CALL_MODE_QA,
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
    "ChallengeIn",
    "ChallengeOut",
    "ChallengeCheckIn",
    "ChallengeCheckOut",
    "GapCheckIn",
    "GapCheckOut",
    "ClassifyErrorIn",
    "ClassifyErrorOut",
    "ErrorType",
]
