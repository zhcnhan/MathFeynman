"""app.api.history：费曼复盘记录（docs/07 §2.3 历史复盘入口；Feynman attempts 回看）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from .deps import get_db

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/feynman")
def feynman_history(db: Session = Depends(get_db)) -> dict:
    """费曼口述历史（'我当时哪里讲岔了'复盘，docs/07 §2.3）。"""
    rows = (
        db.query(models.Attempt)
        .filter(models.Attempt.kind == "feynman")
        .order_by(models.Attempt.id.desc())
        .limit(100)
        .all()
    )
    out = []
    for a in rows:
        node = db.get(models.Node, a.node_id)
        meta = a.meta_json or {}
        out.append(
            {
                "id": a.id,
                "node_id": a.node_id,
                "node_title": node.title if node else a.node_id,
                "transcript": a.user_input,
                "verdict": a.verdict,
                "score": meta.get("score"),
                "meta": meta,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        )
    return {"items": out}
