"""api.settings_api：运行时设置（**开发者/调试模式**开关）＋ **AI 对话审计/提示词监听**（docs/09 R39 §3）。

红线：审计全文里**不得**出现 API Key；记录**不得阻塞**主流程；写文件失败要**记账**。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..service import ai_trace, app_settings
from .deps import get_db

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)) -> dict:
    """应用设置（含调试模式开关状态与审计存储信息）。"""
    return {
        **app_settings.view(db),
        "ai_trace": {"dir": str(ai_trace.trace_dir()), "keep_days": ai_trace.keep_days()},
    }


class SettingsBody(BaseModel):
    developer_mode: bool | None = None


@router.put("/settings")
def put_settings(body: SettingsBody, db: Session = Depends(get_db)) -> dict:
    if body.developer_mode is not None:
        app_settings.set_flag(db, app_settings.DEV_MODE, bool(body.developer_mode))
    return {**app_settings.view(db),
            "ai_trace": {"dir": str(ai_trace.trace_dir()), "keep_days": ai_trace.keep_days()}}


# ---------------------------------------------------------------------------
# AI 对话审计 / 提示词监听
# ---------------------------------------------------------------------------
@router.get("/ai-traces")
def list_traces(subject_id: str = "", call_name: str = "", outcome: str = "",
                only_failed: bool = False, limit: int = 50, offset: int = 0,
                db: Session = Depends(get_db)) -> dict:
    """审计列表：时间倒序，**失败与丢弃置顶**（前端另加红色标记）。"""
    out = ai_trace.query(db, subject_id=subject_id, call_name=call_name, outcome=outcome,
                         only_failed=only_failed, limit=limit, offset=offset)
    out["trace_dir"] = str(ai_trace.trace_dir())
    out["keep_days"] = ai_trace.keep_days()
    return out


@router.get("/ai-traces/{log_id}")
def get_trace(log_id: int, db: Session = Depends(get_db)) -> dict:
    """一条记录：**上＝发给 AI 的完整内容，下＝AI 返回的完整内容**（读全文文件，非流式）。"""
    try:
        return ai_trace.get_detail(db, log_id)
    except ValueError as e:
        from .subjects import _err

        raise _err(404, "not_found", str(e)) from e


class CleanupBody(BaseModel):
    keep_days: int | None = None


@router.post("/ai-traces/cleanup")
def cleanup_traces(body: CleanupBody | None = None, db: Session = Depends(get_db)) -> dict:
    """按保留期清理审计全文文件：**先记账（清理了哪几条），再删除**（不静默消失）。

    **R48 B**：手动入口也走 `cleanup_once`（与启动/定时**同一实现**），账目 `detail.trigger="手动"`。
    """
    del db
    return ai_trace.cleanup_once("手动", keep_days_override=(body.keep_days if body else None))
