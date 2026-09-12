"""api.deps：共享依赖（DB 会话、AI 网关、SessionService）。"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai.gateway import gateway_factory
from ..db import SessionLocal
from ..service import model_config
from ..service.ai_sink import make_ai_log_sink
from ..service.session import SessionError, SessionService

# **R56 第 0 步**：网关按**生效配置**构建（页面设置 > .env > 默认），并按配置签名缓存
# ——设置页改了模型/Key → 下一次请求即用新的（不必重启）。
_GATEWAY_CACHE: dict[tuple, object] = {}


def _build_gateway(s) -> object:
    if not s.llm_api_key:
        return gateway_factory(api_key="")     # 无 Key → 离线兜底网关（照旧）
    sig = (s.llm_api_key, s.llm_base_url, s.llm_model_heavy, s.llm_model_light)
    gw = _GATEWAY_CACHE.get(sig)
    if gw is None:
        gw = gateway_factory(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            heavy_model=s.llm_model_heavy,
            light_model=s.llm_model_light,
            log_sink=make_ai_log_sink(),
        )
        _GATEWAY_CACHE.clear()                 # 只留当前这一份（Key 不驻留多份）
        _GATEWAY_CACHE[sig] = gw
    return gw


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


def get_gateway(db: Session = Depends(get_db)):
    """有可用 Key（页面或 .env）→ 真网关（带审计）；否则离线兜底网关。"""
    return _build_gateway(model_config.effective_settings(db))


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
