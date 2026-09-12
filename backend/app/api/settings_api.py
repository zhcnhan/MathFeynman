"""api.settings_api：运行时设置（**开发者/调试模式**开关 ＋ **模型与 Key**）＋ AI 对话审计/提示词监听。

红线：审计全文里**不得**出现 API Key；记录**不得阻塞**主流程；写文件失败要**记账**。
R56 第 0 步：模型与 Key 的设置在**这里可改**（页面 > .env > 默认）；接口**永不回显完整 Key**。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..service import ai_trace, app_settings, model_config
from .deps import get_db

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)) -> dict:
    """应用设置（含调试模式开关状态、模型与 Key、审计存储信息）。"""
    return {
        **app_settings.view(db),
        "model": model_config.view(db),
        "ai_trace": {"dir": str(ai_trace.trace_dir()), "keep_days": ai_trace.keep_days()},
    }


class SettingsBody(BaseModel):
    developer_mode: bool | None = None


@router.put("/settings")
def put_settings(body: SettingsBody, db: Session = Depends(get_db)) -> dict:
    if body.developer_mode is not None:
        app_settings.set_flag(db, app_settings.DEV_MODE, bool(body.developer_mode))
    return {**app_settings.view(db),
            "model": model_config.view(db),
            "ai_trace": {"dir": str(ai_trace.trace_dir()), "keep_days": ai_trace.keep_days()}}


# ---------------------------------------------------------------------------
# **R56 第 0 步**：模型与 Key（复用 app_settings 键值表；不新建表、不新建配置机制）
# ---------------------------------------------------------------------------
@router.get("/settings/model")
def get_model_settings(db: Session = Depends(get_db)) -> dict:
    """模型与 Key 的当前状态：**只回掩码 + 是否已配**，永不回显完整 Key。"""
    return model_config.view(db)


class ModelSettingsBody(BaseModel):
    provider: str | None = None
    api_key: str | None = None          # 空串 = 清除
    base_url: str | None = None
    heavy: str | None = None
    light: str | None = None
    max_tokens_per_day: int | None = None
    memory_only: bool | None = None


@router.put("/settings/model")
def put_model_settings(body: ModelSettingsBody, db: Session = Depends(get_db)) -> dict:
    """保存模型设置（只改传进来的项）；变更进账本（中文，**不含 Key 明文**）。"""
    from ..outline.schemas import OutlineError

    from .subjects import _outline_err

    patch = body.model_dump(exclude_unset=True)
    try:
        return model_config.save(
            db,
            provider=patch.get("provider", model_config.UNSET),
            api_key=patch.get("api_key", model_config.UNSET),
            base_url=patch.get("base_url", model_config.UNSET),
            heavy=patch.get("heavy", model_config.UNSET),
            light=patch.get("light", model_config.UNSET),
            max_tokens_per_day=patch.get("max_tokens_per_day", model_config.UNSET),
            memory_only=patch.get("memory_only", model_config.UNSET),
        )
    except OutlineError as e:
        raise _outline_err(e) from e


@router.post("/settings/model/test")
def test_model_connection(db: Session = Depends(get_db)) -> dict:
    """「测试连接」：发一次最小请求，中文报告成功或失败原因（不含 Key）。"""
    return model_config.test_connection(db)


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
