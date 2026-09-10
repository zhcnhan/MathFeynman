"""app.content.schemas：节点文件 pydantic 模型（docs/04 §2 结构镜像）。

一个 .md 文件 = 一个知识点节点；front-matter(YAML) = 节点定义，正文(Markdown) 为讲解全文。
字段约束对齐 docs/04：exercise 模板参数化、check.mode 枚举、feynman rubric 结构等。
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

LEVELS = ("primary", "middle", "high", "college", "ai")
CHECK_MODES = (
    "equation_solution",
    "symbolic_equivalence",
    "numeric_value",
    "boolean_judgment",
    "single_choice",
    "fill_text",
    "ordering",
    "manual_review",
)
INTERACTIVE_MODES = ("workbench", "guided", "graph")


# ---------- R35 可答性：声明式知识包 + 出题引文纪律 ----------
class TaughtFact(BaseModel):
    """本单元**显式陈述**的一条事实/关系句（封闭集合）。

    `text` 必须**逐字出自讲解正文**（服务端用 `content/citations.py` 的同一把尺子校验）。
    `concept_id`（可选，R35 §11 裁定）：指向**既有概念注册表**（`concepts` 表 / 大纲 concept_tags）的 id，
    使"讲过的概念"与"考的概念"共用同一套 id；**事实句本身仍留在节点内**（不落 concepts 表）。
    """

    id: str
    text: str
    concept_id: str = ""


class Derivable(BaseModel):
    """本单元允许的**推理**：结论 + 所依据的事实 id + 明确规则（普适逻辑或本单元教过的规则）。"""

    conclusion: str
    premises: list[str] = Field(default_factory=list)
    rule: str = ""


class BasisDoc(BaseModel):
    """一个问题的**依据**（R35 S2）：引用的已述事实 + 讲解原文引文；推理题另附前提与规则。"""

    fact_ids: list[str] = Field(default_factory=list)
    quote: str = ""
    premises: list[str] = Field(default_factory=list)  # 仅推理题
    rule: str = ""                                     # 仅推理题


# ---------- 讲解/例题 ----------
class ExplanationDoc(BaseModel):
    role: str = "教师讲解稿"
    body: str = ""


class WorkedExampleDoc(BaseModel):
    prompt: str
    solution_steps: list[str] = Field(default_factory=list)
    verification: Optional[str] = None  # sympy 验算（可选，示例注解）


# ---------- 练习 ----------
class ParamRange(BaseModel):
    range: list[int | float] = Field(min_length=2, max_length=2)
    exclude: list[int | float] = Field(default_factory=list)


class TemplateDoc(BaseModel):
    prompt: str  # 支持 {param} 占位
    params: dict[str, ParamRange | list[int | float]] = Field(default_factory=dict)
    constraint: Optional[str] = None  # python 表达式，params 全部可用
    answer_expr: str = ""  # 答案表达式模板（代入 params 后应可 sympy 解析）
    equation: Optional[str] = None  # [实现扩展] equation_solution 用的机器方程模板（见 NOTES）
    # R35 §12 语义自检闸门（**内容显式声明**；不猜题面关键词）：
    #   expect:   标准答案的**独立算式**（L1 验算插件据此独立算一遍并与 answer_expr 比对）
    #   requires: 题面里陈述的条件（*必须*被 constraint 强制保证；否则题面在说没保证的话）
    #   domain:   领域谓词 {nonneg/integer/ratio: bool}（通用层按学科无关的谓词表校验渲染结果）
    semantics: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _lift_constraint(cls, data: dict) -> dict:
        """docs/04 §2 格式：constraint 写在 params 内层 → 提升到模板层。"""
        if isinstance(data, dict):
            params = data.get("params")
            if isinstance(params, dict) and isinstance(params.get("constraint"), str):
                data["constraint"] = params.pop("constraint")
        return data


class CheckDoc(BaseModel):
    mode: Literal[
        "equation_solution",
        "symbolic_equivalence",
        "numeric_value",
        "boolean_judgment",
        "single_choice",   # B2：选择题（fixed；options+answer_index）
        "fill_text",       # B2：填空（fixed；expected+aliases）
        "ordering",
        "manual_review",
    ]
    tolerance: Optional[float] = None
    equation: Optional[str] = None  # 简化冗余：允许在 check 层覆盖（优先级最高）


class ExerciseDoc(BaseModel):
    """一个练习条目：kind=template（默认）或 fixed。

    B2 题型扩展（docs/14 §2.5/Phase B·docs/04 §2 同步）：
    - single_choice：options（选项列表）+ answer_index（0 起正确项下标）；
    - fill_text：expected（标准答案）+ aliases（可接受同义答法）。
    fixed 的判题/自检语义见 content/templates `_render_fixed` 与 domain/judge。
    """

    id: str
    kind: Literal["template", "fixed"] = "template"
    difficulty: int = Field(default=1, ge=1, le=3)
    prompt: str = ""  # fixed 题直接用；template 题被 template.prompt 覆盖
    template: Optional[TemplateDoc] = None
    answer_expr: Optional[str] = None  # fixed + 数值/等价类 判题用期望表达式
    answer_bool: Optional[bool] = None  # fixed + boolean_judgment 的期望真值
    equation: Optional[str] = None  # fixed + equation_solution 的方程
    options: list[str] = Field(default_factory=list)  # single_choice 选项
    answer_index: Optional[int] = None  # single_choice 正确项下标（0 起）
    expected: str = ""  # fill_text 标准答案
    aliases: list[str] = Field(default_factory=list)  # fill_text 可接受同义答法
    check: CheckDoc
    interactive: list[Literal["workbench", "guided", "graph"]] = Field(
        default_factory=lambda: ["workbench"]
    )
    # R35 S2：核心题的依据（引文纪律）。缺失/不成立 → 该题按"不可答"处理（生成端丢弃）。
    basis: Optional[BasisDoc] = None

    @field_validator("interactive")
    @classmethod
    def _interactive_ok(cls, v: list[str]) -> list[str]:
        bad = [i for i in v if i not in INTERACTIVE_MODES]
        if bad:
            raise ValueError(f"非法 interactive 模式: {bad}")
        return v

    @model_validator(mode="after")
    def _mode_fields_ok(self) -> "ExerciseDoc":
        """题型一致性（B2）：single_choice 需 options+answer_index；fill_text 需 expected。"""
        mode = self.check.mode
        if self.kind != "fixed":
            return self
        if mode == "single_choice":
            if len(self.options) < 2:
                raise ValueError(f"练习 {self.id}: single_choice 至少 2 个选项")
            if self.answer_index is None or not (0 <= self.answer_index < len(self.options)):
                raise ValueError(f"练习 {self.id}: single_choice 的 answer_index 越界或缺失")
            if not self.options[self.answer_index].strip():
                raise ValueError(f"练习 {self.id}: single_choice 正确选项不能为空")
        elif mode == "fill_text":
            if not self.expected.strip():
                raise ValueError(f"练习 {self.id}: fill_text 需要 expected 标准答案")
        return self


# ---------- 费曼 ----------
class RubricDimension(BaseModel):
    key: str
    weight: float = Field(gt=0, le=1)
    description: str = ""


class RubricDoc(BaseModel):
    dimensions: list[RubricDimension] = Field(min_length=1)
    pass_threshold: float = Field(default=0.7, ge=0, le=1)


class FeynmanDoc(BaseModel):
    task_prompt: str
    rubric: RubricDoc
    socratic_followups: list[str] = Field(default_factory=list)
    # R35 S2：与 socratic_followups **按下标对齐**的依据；缺失/不成立的那条不下发（S4：模板套话不得兜底）
    socratic_basis: list[BasisDoc] = Field(default_factory=list)
    thinking: bool = False  # R12：内容标记 → 基础档 think（覆盖按学段的 fast 默认）


# ---------- 节点 ----------
class NodeDoc(BaseModel):
    """节点文件完整结构（front-matter + 正文）。"""

    id: str
    title: str
    # level：math 学段 ∈ LEVELS（primary/middle/high/college/ai）；通用学科（docs/14 Phase A）
    # 内容节点为其大纲关卡组标识（任意非空字符串）——数学引擎只认 LEVELS，其余由 subject 大纲门禁
    level: str
    topic: str
    prereqs: list[str] = Field(default_factory=list)
    kind: Literal["normal", "boss"] = "normal"  # 关卡首领（综合+费曼综述，docs/10 §2.1）
    objectives: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    explanation: ExplanationDoc = Field(default_factory=ExplanationDoc)
    worked_examples: list[WorkedExampleDoc] = Field(default_factory=list)
    exercises: list[ExerciseDoc] = Field(default_factory=list)
    feynman: FeynmanDoc
    exercises: list[ExerciseDoc] = Field(default_factory=list)
    # R35 S1：声明式知识包（旧内容可缺省；缺省者**不阻塞加载**，但不得通过可答性校验）
    taught_facts: list[TaughtFact] = Field(default_factory=list)
    derivable: list[Derivable] = Field(default_factory=list)
    # 正文（front-matter 之后的全部 Markdown）
    body_md: str = ""

    @field_validator("exercises")
    @classmethod
    def _need_exercises(cls, v: list[ExerciseDoc]) -> list[ExerciseDoc]:
        if not v:
            raise ValueError("每个节点至少 1 道练习（学习闭环需自动判题环节）")
        return v

    def explain_prompt(self) -> str:
        return self.explanation.body


__all__ = [
    "NodeDoc",
    "ExerciseDoc",
    "TemplateDoc",
    "CheckDoc",
    "ExplanationDoc",
    "WorkedExampleDoc",
    "RubricDoc",
    "RubricDimension",
    "FeynmanDoc",
    # R35
    "TaughtFact",
    "Derivable",
    "BasisDoc",
    "LEVELS",
    "CHECK_MODES",
    "INTERACTIVE_MODES",
]
