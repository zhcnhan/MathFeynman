"""app.outline.schemas：学科大纲数据模型（docs/14 §1 Outline 段、§2.1 单元规格）。

Schema v1（大纲文件 content/subjects/<sid>/outline.yaml 的 YAML 结构）：

    subject: math                 # 学科 id（preset=math；自定义=subjects 注册的 id）
    label: 数学                    # 学科显示名
    schema_version: 1             # 大纲 schema 版本（升级迁移用）
    revision: 3                   # 大纲版本号：整份重生成 +1（文件原子替换，历史留 git）
    status: draft|active          # 大纲状态：draft=草稿可审阅；active=当前采纳版本
    source: roadmap|ai|manual     # roadmap=由 roadmap 派生（math preset 治理载体）；
                                  # ai/manual=通用学科（AI 起草 / 手动采纳）
    generated_at / updated_at: ISO
    unit_id_scope: entry|subject  # entry=单元 id 复用既有命名（math：roadmap 条目 id）；
                                  # subject=单元 id 自动带 <subject>. 前缀（通用学科）
    units:
      - id: primary.s01
        title: …
        objectives: [≤4 条]
        concept_tags: [归一化概念标签（A2 起有效，v1 允许空）]
        group: primary            # 关卡组（math：学段 primary/middle/…；通用：主题组名）
        prereqs: [单元 id / 锚点内容节点 id（含 '.'）]
        difficulty: 1..3
        requires_thinking: false
        anchors: [已存在内容节点 id，可选]
        topic: 数与运算           # math 语义保留位（通用学科可空）
        status: draft|reviewed    # 单元级转正状态（math roadmap 如实标注）

语义要点（对齐 docs/14 与既有 roadmap 引擎）：
- 列表顺序 = 建议学习序列（roadmap 惯例："列表位置为真源"，R14）；
- 单元 id 大纲内唯一；prereq 引用同大纲单元 id 或真实内容节点 id（含 '.'）；
- 校验（validate_outline_doc）：结构/唯一性/自指/引用存在性/环（DFS）；
  分组名唯一（组内单元列表序即学习序）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

OUTLINE_SCHEMA_VERSION = 1
# 学科 id 命名空间（注册规则）：小写字母开头 + 小写字母/数字/连字符
SUBJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
# 单元本地号（id 的 <subject>. 之后部分）：字母数字/点/连字符/下划线
UNIT_LOCAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SUBJECT_KINDS = ("preset", "custom")
OUTLINE_STATUSES = ("draft", "active")
UNIT_STATUSES = ("draft", "reviewed")
OUTLINE_SOURCES = ("roadmap", "ai", "manual", "hybrid")


class OutlineError(ValueError):
    """大纲结构错误（含具体条目/字段，供 API 与校验报告透传）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OutlineUnit(BaseModel):
    """大纲单元条目（docs/14 §2.1：标题/目标≤3/概念标签集/前置/难度/分组/锚点可选）。"""

    id: str
    title: str = ""
    objectives: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)  # A2：概念标签集（归一化）
    group: str = ""  # 关卡组（学段 / 主题组）
    prereqs: list[str] = Field(default_factory=list)
    difficulty: int = Field(default=2, ge=1, le=3)
    requires_thinking: bool = False
    anchors: list[str] = Field(default_factory=list)  # 可选：已存在内容节点 id
    topic: str = ""  # math roadmap topic 保留位（通用学科可空）
    status: Literal["draft", "reviewed"] = "draft"  # 单元转正状态（roadmap 如实标注）
    meta: dict = Field(default_factory=dict)  # 附加元数据（生成器/AI 稿可携带，不改语义）

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not v or not UNIT_LOCAL_RE.match(v):
            raise ValueError(f"单元 id {v!r} 非法（须匹配 {UNIT_LOCAL_RE.pattern}）")
        return v

    @field_validator("objectives")
    @classmethod
    def _objectives_ok(cls, v: list[str]) -> list[str]:
        # docs/14 规格"目标≤3"；数学既有条目少量 ≤4（精核批 A2 曾扩至 4 条）→ 上限 4。
        # AI 起草提示词要求 ≤3；schema 宽松为 ≤4（见 NOTES 疑点，待架构定口径）。
        cleaned = [str(x).strip() for x in v if str(x).strip()]
        if len(cleaned) > 4:
            raise ValueError(f"objectives 过多（{len(cleaned)}>4）")
        return cleaned

    @field_validator("concept_tags")
    @classmethod
    def _tags_ok(cls, v: list[str]) -> list[str]:
        cleaned = []
        for x in v:
            s = str(x).strip()
            if not s:
                continue
            if len(s) > 64:
                raise ValueError(f"概念标签过长（>64）：{s!r}")
            cleaned.append(s)
        return cleaned

    @field_validator("title")
    @classmethod
    def _title_ok(cls, v: str) -> str:
        s = str(v).strip()
        if not s:
            raise ValueError("title 不能为空")
        return s


class OutlineDoc(BaseModel):
    """大纲文档（持久文件根对象）。"""

    subject: str
    label: str = ""
    schema_version: int = OUTLINE_SCHEMA_VERSION
    revision: int = 1
    status: Literal["draft", "active"] = "draft"
    source: Literal["roadmap", "ai", "manual", "hybrid"] = "manual"
    unit_id_scope: Literal["entry", "subject"] = "subject"
    generated_at: str = ""
    updated_at: str = ""
    note: str = ""
    units: list[OutlineUnit] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _schema_supported(cls, v: int) -> int:
        if v != OUTLINE_SCHEMA_VERSION:
            raise ValueError(
                f"大纲 schema 版本 {v} 不受支持（当前 {OUTLINE_SCHEMA_VERSION}；"
                f"跨版本升级迁移属 docs/14 §7 治理项）"
            )
        return v

    def by_id(self) -> dict[str, OutlineUnit]:
        return {u.id: u for u in self.units}

    def groups(self) -> list[str]:
        """按列表序去重后的关卡组（组内单元列表序 = 学习序）。"""
        out: list[str] = []
        for u in self.units:
            if u.group not in out:
                out.append(u.group)
        return out


def _split_ref(ref: str) -> tuple[str, str] | None:
    """`a.b` 形式的引用拆 (a, b)；用于区分"单元本地引用"与"内容节点/跨文件引用"。"""
    if "." not in ref:
        return None
    head, _, tail = ref.partition(".")
    return (head, tail) if head and tail else None


def validate_outline_doc(doc: OutlineDoc, *, known_content_ids: set[str] | None = None) -> list[str]:
    """大纲结构校验（不抛异常，返回问题清单；空 = 通过）。

    检查：单元 id 唯一 / 分组名去重合规 / prereq 存在性（同大纲单元或含 '.' 的内容节点引用
    需在 known_content_ids 内——不传则跳过内容存在性）/ 自指 / 同大纲引用环（DFS）。
    """
    problems: list[str] = []
    units = doc.units
    if not units:
        problems.append("大纲至少需要 1 个单元")
    ids = [u.id for u in units]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append(f"单元 id 重复: {dup}")
    groups = doc.groups()
    for g in groups:
        if not g or len(g) > 64:
            problems.append(f"分组名非法: {g!r}")
    index = {u.id: u for u in units}
    for u in units:
        for p in u.prereqs:
            if p == u.id:
                problems.append(f"{u.id}: prereq 自指 {p!r}")
                continue
            if p in index:
                continue  # 同大纲前置
            if "." in p:
                if known_content_ids is not None and p not in known_content_ids:
                    problems.append(f"{u.id}: prereq 引用的内容节点 {p!r} 不在内容库")
                continue  # 内容节点引用（跨单元边在内容生成时建）
            problems.append(f"{u.id}: prereq {p!r} 未指向大纲内单元或内容节点")
    # 同大纲引用环（DFS 三色；仅走大纲内引用边）
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {u.id: WHITE for u in units}
    stack: list[str] = []
    cyc: list[str] = []

    def dfs(nid: str) -> bool:
        color[nid] = GRAY
        stack.append(nid)
        for p in index[nid].prereqs:
            if p not in index:
                continue
            if color[p] == GRAY:
                i = stack.index(p)
                cyc.append("->".join(stack[i:] + [p]))
                return True
            if color[p] == WHITE and dfs(p):
                return True
        stack.pop()
        color[nid] = BLACK
        return False

    for u in units:
        if color[u.id] == WHITE and dfs(u.id):
            break
    if cyc:
        problems.append(f"大纲前置存在环: {'; '.join(cyc)}")
    return problems


def outline_to_yaml(doc: OutlineDoc) -> str:
    """大纲文档 → YAML 文本（UTF-8；保证可重载、可人工审阅）。"""
    return yaml.safe_dump(
        doc.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


def outline_from_dict(data: dict) -> OutlineDoc:
    try:
        return OutlineDoc(**data)
    except Exception as e:
        raise OutlineError(f"大纲结构校验失败: {e}") from e


def load_outline_yaml(text: str) -> OutlineDoc:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise OutlineError(f"大纲 YAML 解析失败: {e}") from e
    if not isinstance(raw, dict):
        raise OutlineError("大纲 YAML 顶层应为映射")
    return outline_from_dict(raw)


__all__ = [
    "OUTLINE_SCHEMA_VERSION",
    "SUBJECT_ID_RE",
    "UNIT_LOCAL_RE",
    "SUBJECT_KINDS",
    "OUTLINE_STATUSES",
    "UNIT_STATUSES",
    "OUTLINE_SOURCES",
    "OutlineDoc",
    "OutlineUnit",
    "OutlineError",
    "validate_outline_doc",
    "outline_to_yaml",
    "outline_from_dict",
    "load_outline_yaml",
]
