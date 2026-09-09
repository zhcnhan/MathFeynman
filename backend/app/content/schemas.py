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
    "ordering",
    "manual_review",
)
INTERACTIVE_MODES = ("workbench", "guided", "graph")


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
        "ordering",
        "manual_review",
    ]
    tolerance: Optional[float] = None
    equation: Optional[str] = None  # 简化冗余：允许在 check 层覆盖（优先级最高）


class ExerciseDoc(BaseModel):
    """一个练习条目：kind=template（默认）或 fixed。"""

    id: str
    kind: Literal["template", "fixed"] = "template"
    difficulty: int = Field(default=1, ge=1, le=3)
    prompt: str = ""  # fixed 题直接用；template 题被 template.prompt 覆盖
    template: Optional[TemplateDoc] = None
    answer_expr: Optional[str] = None  # fixed 题可选：判题用期望表达式
    answer_bool: Optional[bool] = None  # fixed + boolean_judgment 的期望真值
    equation: Optional[str] = None  # fixed + equation_solution 的方程
    check: CheckDoc
    interactive: list[Literal["workbench", "guided", "graph"]] = Field(
        default_factory=lambda: ["workbench"]
    )

    @field_validator("interactive")
    @classmethod
    def _interactive_ok(cls, v: list[str]) -> list[str]:
        bad = [i for i in v if i not in INTERACTIVE_MODES]
        if bad:
            raise ValueError(f"非法 interactive 模式: {bad}")
        return v


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
    "LEVELS",
    "CHECK_MODES",
    "INTERACTIVE_MODES",
]
