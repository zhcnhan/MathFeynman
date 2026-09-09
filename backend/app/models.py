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
    """学科注册（docs/14 §1 subject 命名空间 · Phase A A1）。

    kind: preset=预置学科（math，受代码治理）/ custom=用户自建。
    大纲文档持久于 content/subjects/<id>/outline.yaml（不在本表）。
    """

    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(16), default="custom")  # preset|custom
    description: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    kind: Mapped[str] = mapped_column(String(16), default="exercise")  # exercise|feynman
    exercise_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_input: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String(16), default="")  # correct|wrong|score|pass|fail|deferred
    error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    "Node",
    "Edge",
    "UserNode",
    "Session",
    "Attempt",
    "Review",
    "AiLog",
    "RelearnLog",
    "Feedback",
    "utcnow",
]
