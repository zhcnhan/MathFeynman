"""app.api.campaign：关卡地图数据（docs/10 §2.1，docs/11 阶段 2）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..service.campaign import snapshot
from .deps import get_db

router = APIRouter(tags=["campaign"])
USER = "local"


@router.get("/campaign")
def get_campaign(db: Session = Depends(get_db)) -> dict:
    """关卡地图：学段→主题组→节点/首领 + 进度/通关 + 自续提示。"""
    import os

    if os.getenv("MF_AUTO_EXTEND") == "1":
        from ..service import selfextend as se

        se.run_auto(db, USER)
    return snapshot(db, USER)
