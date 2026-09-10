"""ORM 模型：对应 docs/06 §3 SQLite 表结构草案。

约定：所有表带 user_id（ADR A10，MVP 恒为 'local'）；
时间统一 UTC；JSON 字段用 SQLAlchemy JSON（SQLite 下序列化为 TEXT）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Subject(Base):
    """学科注册（docs/14 §1 subject 命名空间 · Phase A A1 / B4 生命周期）。

    kind: preset=预置学科（math）/ custom=用户自建；
    enabled: 停用标记（docs/14 §9"移除可恢复"）——停用=列表隐藏+不可学+进度已清；
     大纲/内容文件留盘，可随时重新启用；preset 与 custom 语义一致（不再特殊）。
    大纲文档持久于 content/subjects/<id>/outline.yaml（不在本表）。
    """

    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(16), default="custom")  # preset|custom
    description: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # B4：停用（移除）标记
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Concept(Base):
    """概念标签注册表（docs/14 §1 Concept Layer · Phase A A2）。

    概念 = 学科内可移植的掌握证据挂载点：单元完成 → 归一化概念标签 → 挂 (subject, concept)。
    concept_id = 归一化后的规范标签（A2 归一规则：去空白 + ASCII 小写 + 全半角统一）；
    label 保留原始书写；aliases 保留同义合并（docs/14 §7 #3 归一化策略 MVP：精确归一匹配）。
    """

    __tablename__ = "concepts"
    __table_args__ = (Index("ix_concepts_label", "subject_id", "label"),)

    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    concept_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    aliases_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserConcept(Base):
    """用户概念掌握证据（docs/14 §2.2）：掌握证据挂 (subject, concept)。

    evidence_json = 提供证据的内容节点 id 列表（派生自 user_nodes mastered + 大纲单元标签映射，
    幂等重算，非人工录入）；mastered_at = 最近一次证据成立时间。
    """

    __tablename__ = "user_concepts"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    concept_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 如 middle.0102
    yaml_path: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(32), default="")  # primary/middle/high/college/ai
    topic: Mapped[str] = mapped_column(Text, default="")
    objectives_json: Mapped[list] = mapped_column(JSON, default=list)
    core_concepts_json: Mapped[list] = mapped_column(JSON, default=list)
    feynman_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (Index("ix_edges_prereq", "prereq_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    prereq_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"))


class UserNode(Base):
    """节点状态机（docs/03 §1）：locked/available/learning/mastered/reviewing。"""

    __tablename__ = "user_nodes"
    __table_args__ = (Index("ix_user_nodes_state", "user_id", "state"),)

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="locked")
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0)
    attempts_total: Mapped[int] = mapped_column(Integer, default=0)
    last_error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), index=True)
    state: Mapped[str] = mapped_column(String(16), default="learning")  # 状态机当前阶段
    flow_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 会话内累积数据
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    node_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="exercise")  # exercise|feynman|challenge
    exercise_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_input: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String(16), default="")  # correct|wrong|score|pass|fail|deferred|abandoned
    error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# 计入"进度统计"的 attempts 种类（R35 S3 红线）：**挑战题（kind="challenge"）永远不在其中**——
# 它只进复盘。任何按 attempts 汇总的"今日完成/学习量"都必须用本常量过滤，不得直接 count 全表。
PROGRESS_KINDS = ("exercise", "feynman")


class Review(Base):
    """FSRS 复习状态（docs/03 §3）。"""

    __tablename__ = "reviews"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-4
    lapse_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AiLog(Base):
    """AI 调用元数据（docs/05 §6）＋ **R39 §3 提示词监听 / AI 对话审计**。

    R39 起本表是"每次调用一条"的**审计索引**：全文（渲染后 system/user + 原始返回 +
    解析结果）落文件 ``.runtime/ai_trace/<时间>-<调用点>-<id>.txt``，本表只存
    **路径 + 预览 + 字符数**（防库爆；界面展开即完整——用户明确不要流式）。
    """

    __tablename__ = "ai_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_name: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str] = mapped_column(String(16), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # --- R39 §3：审计扩字段（旧库由 db._migrate_columns 幂等补列）---
    subject_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    unit_id: Mapped[str] = mapped_column(String(64), default="")
    retries: Mapped[int] = mapped_column(Integer, default=0)
    # 最终结局：adopted 采纳 / degraded 降级 / dropped 丢弃 / failed 失败
    outcome: Mapped[str] = mapped_column(String(16), default="adopted")
    # 本次生成用的**提示词版本**（"哪次生成用的哪版提示词"，R39 §2 可回溯）
    prompt_versions: Mapped[str] = mapped_column(Text, default="")
    trace_path: Mapped[str] = mapped_column(Text, default="")
    trace_chars: Mapped[int] = mapped_column(Integer, default=0)
    system_preview: Mapped[str] = mapped_column(Text, default="")
    user_preview: Mapped[str] = mapped_column(Text, default="")
    response_preview: Mapped[str] = mapped_column(Text, default="")
    parse_result: Mapped[str] = mapped_column(Text, default="")


class ContentLedger(Base):
    """**「一切显性」账本**（docs/09 R39 §1）：所有丢弃/截断/跳过/降级/失败/重试的唯一落库点。

    写入必须经 ``service.ledger``（禁止各处自行 print / 只在 prompt 尾部提一句）。
    """

    __tablename__ = "content_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    unit_id: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(24), default="other", index=True)
    object: Mapped[str] = mapped_column(Text, default="")       # 对象（材料/单元/题号…）
    reason: Mapped[str] = mapped_column(Text, default="")       # 原因（中文）
    impact: Mapped[str] = mapped_column(Text, default="")       # 影响面
    remedy: Mapped[str] = mapped_column(Text, default="")       # 可否补救
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PromptOverride(Base):
    """**提示词改动**（docs/09 R39 §2）：新数据建表正当——**不塞** ``subjects.meta_json``。

    ``call_name`` = 调用点（= ``ai.calls.CALLS`` 的键）；库里没有行 = **用默认**（删行即恢复默认）。
    ``system_text`` / ``user_text`` 各自为空串 = 该字段仍用默认（可只改一半——
    "改了一条 → 生成确实用了新版"能逐字段对照）。
    """

    __tablename__ = "prompt_overrides"

    call_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    system_text: Mapped[str] = mapped_column(Text, default="")
    user_text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """运行时应用设置（键值）。R39 §3：调试模式开关（**不靠开关决定"要不要留证据"**，
    开关只决定界面入口是否出现）。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RelearnLog(Base):
    """mastered→learning 降级留痕（docs/03 §3 行为规则）。"""

    __tablename__ = "relearn_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Feedback(Base):
    """内容纠错反馈（docs/10 §3、docs/11 子步 9、工单 B 段）：讲解/题目 → auto 自动重生成替换 / 人工仅复核。"""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="content")  # lecture|exercise|content
    exercise_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    # pending(待处理/复核) | regenerating(auto 重生成中) | regenerated(已重生成替换) |
    # reviewed(人工仅复核) | failed(重生成失败，保留原内容待人工)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[str] = mapped_column(Text, default="")  # 处理结果/失败原因（UI 可见）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, onupdate=utcnow)


__all__ = [
    "Base",
    "User",
    "Subject",
    "Concept",
    "UserConcept",
    "Node",
    "Edge",
    "UserNode",
    "Session",
    "Attempt",
    "PROGRESS_KINDS",
    "Review",
    "AiLog",
    "RelearnLog",
    "Feedback",
    "ContentLedger",
    "PromptOverride",
    "AppSetting",
    "utcnow",
]
