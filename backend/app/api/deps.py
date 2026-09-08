"""api.deps：共享依赖（DB 会话、AI 网关、SessionService）。"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai.gateway import gateway_factory
from ..config import get_settings
from ..db import SessionLocal
from ..service.ai_sink import make_ai_log_sink
from ..service.session import SessionError, SessionService

_settings = get_settings()

# 有 LLM_API_KEY → OpenAI 兼容真网关（ai_logs 审计）；无 key → 离线兜底网关
_gateway = gateway_factory(
    api_key=_settings.llm_api_key,
    base_url=_settings.llm_base_url,
    heavy_model=_settings.llm_model_heavy,
    light_model=_settings.llm_model_light,
    log_sink=make_ai_log_sink(),
)


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()  # 请求成功即持久化（本地单机；异常路径 rollback）
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_gateway():
    return _gateway


def get_session_service(gateway=Depends(get_gateway)) -> SessionService:
    return SessionService(gateway)


def raise_session_error(e: SessionError) -> HTTPException:
    status = {
        "not_found": 404,
        "validation_error": 422,
        "invalid_state": 409,
        "exercise_broken": 500,
    }.get(e.code, 400)
    return HTTPException(status_code=status, detail={"error": {"code": e.code, "message": str(e)}})


def http_404(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": code, "message": message}})


__all__ = ["get_db", "get_gateway", "get_session_service", "raise_session_error", "http_404", "Session"]
