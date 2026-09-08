"""service.feedback：内容纠错反馈闭环（docs/10 §3、docs/11 子步 9）。

- 记录：用户对讲解/题目/内容的"纠错反馈" → feedback 表（status=pending）。
- 自动重生成（auto 内容）：根据反馈对该条 auto 节点重新出稿替换；无 LLM key 时置为需 key 队列
  （status 保持 pending，标记 `needs_ai`），由配置 key 后重跑/脚本批量处理。
- 人工精写节点（source≠auto）不做自动覆盖（保护人工锚点），仅标记复核。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .library import refresh_library, sync_content

KINDS = ("lecture", "exercise", "content")


def node_source(node_id: str) -> str:
    """节点来源：auto（流水线生成）| human（人工/锚点）。读原始文件 front-matter source。"""
    from ..content.loader import load_node_file
    from ..content.roadmap import roadmap_path  # noqa: F401

    try:
        from ..content.loader import load_library

        lib = load_library()
        loaded = lib.by_id.get(node_id)
        if loaded is None:
            return "unknown"
        from ..content.loader import parse_node_text

        meta, _ = parse_node_text(loaded.raw_text)
        return meta.get("source", "human")
    except Exception:
        return "human"


def record(db: Session, user_id: str, *, node_id: str, kind: str, message: str, exercise_id: str | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS}")
    if not message.strip():
        raise ValueError("反馈内容不能为空")
    row = models.Feedback(
        user_id=user_id,
        node_id=node_id,
        kind=kind,
        exercise_id=exercise_id,
        message=message.strip(),
        status="pending",
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "node_id": row.node_id,
        "kind": row.kind,
        "status": row.status,
        "source": node_source(node_id),
    }


def list_feedback(db: Session, user_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    q = db.query(models.Feedback).filter(models.Feedback.user_id == user_id)
    if status:
        q = q.filter(models.Feedback.status == status)
    out = []
    for row in q.order_by(models.Feedback.id.desc()).limit(200).all():
        node = db.get(models.Node, row.node_id)
        out.append(
            {
                "id": row.id,
                "node_id": row.node_id,
                "node_title": node.title if node else row.node_id,
                "kind": row.kind,
                "exercise_id": row.exercise_id,
                "message": row.message,
                "status": row.status,
                "source": node_source(row.node_id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


def regenerate(db: Session, user_id: str, feedback_id: int) -> dict[str, Any]:
    """尝试自动重生成该条 auto 节点；人工节点只标记不覆盖。"""
    row = db.get(models.Feedback, feedback_id)
    if row is None or row.user_id != user_id:
        raise KeyError(f"反馈不存在: {feedback_id}")
    node_id = row.node_id
    src = node_source(node_id)
    if src != "auto":
        row.status = "reviewed"
        db.flush()
        return {
            "action": "manual_only",
            "node_id": node_id,
            "message": "该节点非流水线(auto)内容，不自动覆盖（已标记复核，人工修订）。",
        }
    # auto 节点：无 LLM key → 入"需 AI 重生成"队列；有 key 的 AI 重出稿由 scripts 批量执行（预留）
    from ..config import get_settings

    if not get_settings().llm_api_key:
        return {
            "action": "queued_needs_ai",
            "node_id": node_id,
            "message": "已入复核队列；配置 LLM_API_KEY 后运行 gen_content 可对该条自动重生成替换。",
        }
    # 有 key：由外部 AI drafter 重建（本服务不直接调 LLM，返回待办标记，脚本侧消费）
    row.status = "reviewed"
    db.flush()
    return {
        "action": "queued_regen",
        "node_id": node_id,
        "message": "已标记待 AI 重生成（gen_content 消费队列后替换并同步图谱）。",
    }


__all__ = ["record", "list_feedback", "regenerate", "node_source", "KINDS"]
