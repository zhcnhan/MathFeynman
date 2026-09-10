"""FastAPI 入口（docs/02 §3）。启动时建表 + 同步内容库；挂载 /api 路由。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    campaign,
    content_admin,
    dashboard,
    exercises,
    feedback,
    graph,
    history,
    ledger_api,
    profile,
    prompts_api,
    review,
    selfextend,
    session as session_api,
    settings_api,
    subjects,
)
from .api.errors_zh import (
    ensure_zh_message,
    has_zh,
    http_zh_message,
    pydantic_summary_zh,
)
from .config import get_settings
from .db import SessionLocal, init_db
from .outline import store as outline_store
from .outline.store import ensure_math_preset
from .service.library import ensure_user, sync_content

logger = logging.getLogger("yanhui")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        try:
            ensure_user(db)
            ensure_math_preset(db)  # Phase A A1：预置学科注册（幂等）
            report = sync_content(db)
            # Phase A A3：数学总 Outline 缺失时由 roadmap 自动派生一次（版本治理见 math_preset）
            if outline_store.get_outline("math") is None:
                try:
                    from .outline.math_preset import derive_math_outline

                    derive_math_outline(db)
                    logger.info("数学总 Outline 已由 roadmap 自动派生（首启）")
                except Exception as e:  # roadmap/内容异常不阻塞启动
                    logger.warning("数学总 Outline 自动派生失败（服务仍可启动）: %s", e)
            db.commit()
            logger.info(
                "内容库同步完成: nodes=%s edges=%s disabled=%s errors=%s",
                report.nodes_synced, report.edges_synced, report.disabled, len(report.errors),
            )
        except Exception as e:  # 内容库异常不阻塞启动（可后续 POST /content/validate 排查）
            logger.warning("内容库同步失败（服务仍可启动）: %s", e)
    # **R42 C3 + R46 B：审计全文文件按保留期自动清理**（架构侧 R41 §3-⑤ 裁决 / R45 §3-1 延伸）——
    # **启动清一次 + 之后每 N 小时清一次**（N 见 `ai_trace.clean_interval_hours()`，默认 6 小时）；
    # 清理**必须记账**（"已清理哪几条"），不得静默删；一切失败只 warning（不退服务、不阻塞主流程）。
    cleanup_handle = None
    try:
        from .service import ai_trace

        cleaned = ai_trace.cleanup_once("启动")
        if cleaned.get("count"):
            logger.info("审计保留期清理完成: 删除 %s 个文件（保留期 %s 天，已记入总账）",
                        cleaned["count"], cleaned.get("keep_days"))
        cleanup_handle = ai_trace.start_periodic_cleanup()
        logger.info("审计定时清理已启动：每 %s 小时一次（守护线程，关闭时干净退出）",
                    ai_trace.clean_interval_hours())
    except Exception as e:
        logger.warning("审计保留期清理启动失败（服务仍可启动）: %s", e)
    app.state.ai_trace_cleanup = cleanup_handle
    try:
        yield
    finally:
        # **R46 B：应用关闭时干净退出**（守护线程 + 显式 stop；即便 stop 失败也不会挂住进程）
        if cleanup_handle is not None:
            try:
                cleanup_handle.stop()
                logger.info("审计定时清理已停止（干净退出）")
            except Exception as e:
                logger.warning("审计定时清理停止异常（不影响退出）: %s", e)


app = FastAPI(title="YanHui", version="0.1.0", lifespan=lifespan)

# 本地单机 + vite dev(5173) 跨端口访问后端(8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{settings.host}:{settings.front_port}",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 对外错误中文化（docs/13 §2 绝对要求 2026-09-09 起）：
# 任何对前端可见的错误 message 必须为中文（含原因+提示）；英文原文/堆栈只进日志。
# ---------------------------------------------------------------------------
_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}
_ZH_CATEGORY = {
    "KeyError": "数据缺失",
    "IndexError": "数据越界",
    "TypeError": "类型异常",
    "ValueError": "值异常",
    "AttributeError": "状态异常",
    "sqlite3.OperationalError": "数据库繁忙",
    "IntegrityError": "数据冲突",
    "sqlalchemy.exc.OperationalError": "数据库繁忙",
    "AiCallError": "AI 服务异常",
    "OSError": "文件或读写异常",
    "PermissionError": "权限异常",
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """仓库错误契约（docs/06 §4 / 前端 api.ts）：body = {"detail": {"error": {code,message}}}。"""
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"error": {"code": code, "message": message}}},
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_zh(request, exc: RequestValidationError) -> JSONResponse:
    """入参校验失败（FastAPI 自动 422）→ 中文提示（字段中文名映射，docs/13 §2）。"""
    del request
    return _error_response(422, "validation_error", pydantic_summary_zh(exc))


@app.exception_handler(StarletteHTTPException)
@app.exception_handler(HTTPException)
async def _http_error_zh(request, exc: HTTPException) -> JSONResponse:
    """统一 HTTPException 出口：已结构化（{detail:{error:{code,message}}} 且 message 中文）直接
    透传；否则（Starlette 默认/未中文化 detail）按状态给中文兜底，原始 detail 只进日志。"""
    del request
    detail = exc.detail
    if isinstance(detail, dict):
        err = detail.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or _CODE_BY_STATUS.get(exc.status_code, "error"))
            message = str(err.get("message") or "")
            if has_zh(message):
                return _error_response(exc.status_code, code, message)
            logger.warning("HTTP %s（detail 非中文，已按兜底文案响应）: %s", exc.status_code, message)
            return _error_response(exc.status_code, code,
                                   ensure_zh_message(message, status_code=exc.status_code))
        raw = str(detail)
    else:
        raw = str(detail) if detail else ""
    if has_zh(raw):
        # 语义已中文但未走 error 结构的响应 → 归一为约定结构
        return _error_response(exc.status_code, _CODE_BY_STATUS.get(exc.status_code, "error"), raw)
    if raw:
        logger.warning("HTTP %s（detail 英文/缺失，已中文化）: %s", exc.status_code, raw)
    return _error_response(exc.status_code, _CODE_BY_STATUS.get(exc.status_code, "error"),
                           http_zh_message(exc.status_code, raw=raw))


@app.exception_handler(Exception)
async def _unhandled_error_zh(request, exc: Exception) -> JSONResponse:
    """未捕获异常 → 500 中文（类别 + 查日志提示）；完整 traceback 只进服务端日志。"""
    logger.exception("Unhandled %s at %s %s", type(exc).__name__, request.method, request.url.path)
    name = type(exc).__name__
    category = _ZH_CATEGORY.get(name, "系统处理")
    return _error_response(
        500, "internal_error", f"服务器内部错误（{category}），详情见日志，请稍后重试。"
    )


api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True, "app": "YanHui", "version": "0.1.0"}


api.include_router(dashboard.router)
api.include_router(graph.router)
api.include_router(campaign.router)
api.include_router(session_api.router)
api.include_router(exercises.router)
api.include_router(review.router)
api.include_router(profile.router)
api.include_router(history.router)
api.include_router(selfextend.router)
api.include_router(feedback.router)
api.include_router(content_admin.router)
api.include_router(subjects.router)
# R39：一切显性（总账）+ 提示词可改 + AI 对话审计/调试模式
api.include_router(ledger_api.router)
api.include_router(prompts_api.router)
api.include_router(settings_api.router)
app.include_router(api)
