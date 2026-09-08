"""app.api.content_admin：内容管理端点（docs/06 §1；MVP 以 CLI 为主，端点提供便捷面）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..content import content_root, stages_dir
from ..content.cli import validate_library
from ..service.library import sync_content
from .deps import get_db

router = APIRouter(prefix="/content", tags=["content"])


@router.post("/validate")
def content_validate(db: Session = Depends(get_db)) -> dict:
    """运行全库校验并返回报告；通过则同步进 DB（docs/06 §1）。"""
    report = validate_library()
    result = {
        "ok": report.ok,
        "nodes_loaded": report.nodes_loaded,
        "exercises_checked": report.exercises_checked,
        "errors": report.errors,
        "warnings": report.warnings,
        "detail": report.detail,
    }
    if report.ok:
        synced = sync_content(db)
        db.commit()
        result["sync"] = {
            "ok": synced.ok,
            "nodes_synced": synced.nodes_synced,
            "edges_synced": synced.edges_synced,
        }
    return result


@router.get("/drafts")
def list_drafts() -> dict:
    """列出未审核草稿（docs/04 §6：_drafts 永不加载进运行库）。"""
    drafts_dir = content_root() / "_drafts"
    files = sorted(drafts_dir.glob("*.md")) if drafts_dir.exists() else []
    return {"drafts": [f.name for f in files], "path": str(drafts_dir)}


class PromoteBody(BaseModel):
    filename: str
    stage: str  # primary/middle/high/college/ai
    topic_dir: str = "general"


@router.post("/drafts/{filename}/promote")
def promote_draft(filename: str, body: PromoteBody) -> dict:
    """审核通过 → 移入 stages（docs/04 §6 人工 gate；git 提交即记录）。"""
    if "/" in filename or "\\" in filename or not filename.endswith(".md"):
        raise HTTPException(status_code=422, detail={"error": {"code": "validation_error", "message": "非法文件名"}})
    src = content_root() / "_drafts" / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"草稿不存在: {filename}"}})
    if body.stage not in ("primary", "middle", "high", "college", "ai"):
        raise HTTPException(status_code=422, detail={"error": {"code": "validation_error", "message": "非法 stage"}})
    topic = "".join(ch for ch in body.topic_dir if ch.isalnum() or ch in "-_") or "general"
    dst_dir = stages_dir() / body.stage / f"topic_{topic}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / filename
    shutil.copy2(src, dst)
    return {"promoted": filename, "to": str(dst)}
