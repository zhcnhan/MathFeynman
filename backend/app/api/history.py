"""app.api.history：复盘记录（docs/07 §2.3 历史复盘入口；费曼与挑战题 attempts 回看）。

R35 S3：挑战题**唯一**的落库点就是 `attempts.kind="challenge"`（不进费曼账本/mastery/额度/
掌握统计）。"记入复盘"= 本路由；**不新建表、不新建存储**（与费曼复盘同一张表、同一套读法）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from .deps import get_db

router = APIRouter(prefix="/history", tags=["history"])


def _rows(db: Session, kind: str, limit: int = 100) -> list[dict]:
    rows = (
        db.query(models.Attempt)
        .filter(models.Attempt.kind == kind)
        .order_by(models.Attempt.id.desc())
        .limit(limit)
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
    return out


@router.get("/feynman")
def feynman_history(db: Session = Depends(get_db)) -> dict:
    """费曼口述历史（'我当时哪里讲岔了'复盘，docs/07 §2.3）。"""
    return {"items": _rows(db, "feynman")}


@router.get("/challenge")
def challenge_history(db: Session = Depends(get_db)) -> dict:
    """挑战题复盘（R35 S3：**只在这里**留有痕迹；不上算、不影响任何进度）。"""
    return {"items": _rows(db, "challenge"), "notice": "挑战题记录：仅复盘用，不计入任何进度"}

