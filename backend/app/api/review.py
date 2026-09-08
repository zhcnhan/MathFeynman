"""app.api.review：复习端点（docs/06 §1）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..service import review as review_svc
from ..service.library import ensure_user, get_graph
from ..service import progress
from .deps import get_db

router = APIRouter(prefix="/review", tags=["review"])
USER = "local"


@router.get("/queue")
def review_queue(db: Session = Depends(get_db)) -> dict:
    """到期复习列表（含堆积警示，docs/03 §3）。"""
    ensure_user(db, USER)
    queue = review_svc.due_queue(db, USER)
    return {
        "due": queue,
        "stacked_count": sum(1 for q in queue if q["stacked"]),
        "total_due": len(queue),
    }


class SubmitBody(BaseModel):
    node_id: str
    rating: int = Field(ge=1, le=4)  # again/hard/good/easy = 1..4（docs/03 §3）
    answers: list[dict] = Field(default_factory=list)  # 审计用；判题已在 check 端点完成


@router.post("/submit")
def review_submit(body: SubmitBody, db: Session = Depends(get_db)) -> dict:
    """提交复习 rating：更新 FSRS 状态，返回下个到期日（docs/06 §1）。"""
    ensure_user(db, USER)
    try:
        result = review_svc.submit_review(db, USER, body.node_id, body.rating, body.answers)
    except KeyError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": str(e)}}) from e
    db.commit()
    return result
