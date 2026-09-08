"""app.api.feedback：内容纠错反馈端点（docs/10 §3、docs/11 子步 9）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..service import feedback as fb_svc
from .deps import get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])
USER = "local"


class FeedbackBody(BaseModel):
    node_id: str
    kind: str = "content"
    message: str = Field(min_length=1)
    exercise_id: str | None = None


@router.get("")
def list_feedback(status: str | None = None, node_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    """复核队列（pending 优先展示用途由前端按需筛）；可按节点过滤查处理结果。"""
    return {"items": fb_svc.list_feedback(db, USER, status=status, node_id=node_id)}


@router.post("")
def create_feedback(body: FeedbackBody, db: Session = Depends(get_db)) -> dict:
    try:
        row = fb_svc.record(
            db, USER, node_id=body.node_id, kind=body.kind, message=body.message, exercise_id=body.exercise_id
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"error": {"code": "validation_error", "message": str(e)}}) from e
    db.commit()
    # 工单 B 段：auto 节点反馈提交 → 后台自动重生成替换（先提交保证后台会话可见该行）
    regen = None
    if row["source"] == "auto":
        regen = fb_svc.spawn_auto_regen(row["node_id"], USER)
    return {"ok": True, "item": row, "regen": regen}


@router.post("/{feedback_id}/regen")
def regenerate_feedback(feedback_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        result = fb_svc.regenerate(db, USER, feedback_id)  # 默认 wait=False：后台执行，状态 regenerating
    except KeyError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": str(e)}}) from e
    db.commit()
    return result
