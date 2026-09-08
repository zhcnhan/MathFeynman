"""app.api.selfextend：内容自续端点（docs/10 §2.3，docs/11 子步 8）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..service import selfextend
from .deps import get_db

router = APIRouter(prefix="/selfextend", tags=["selfextend"])
USER = "local"


@router.get("/status")
def selfextend_status(db: Session = Depends(get_db)) -> dict:
    """状态：是否可自续、下一待生成主题、预算、最近一次运行。"""
    st = selfextend.status()
    levels = selfextend.roadmap_levels()
    active_level = levels[0] if levels else None
    pending = selfextend.next_pending_topics(active_level) if active_level else []
    return {
        "levels": levels,
        "active_level": active_level,
        "ratio": selfextend.mastered_ratio(db, USER, active_level) if active_level else None,
        "pending_topics": pending,
        "running": st.get("running", False),
        "last_status": st.get("last_status", "idle"),
        "last_summary": st.get("last_summary", ""),
        "last_at": st.get("last_at"),
    }


@router.post("/run")
def selfextend_run(
    level: str | None = None,
    wait: bool = Query(default=True),  # wait=0 → 后台执行（非阻塞）
    db: Session = Depends(get_db),
) -> dict:
    """手动触发"继续下一关"。默认同步等待（离线 stub 快）；?wait=0 后台执行。"""
    result = selfextend.extend(db, USER, level=level, wait=wait)
    return result
