"""FastAPI 入口（docs/02 §3）。启动时建表 + 同步内容库；挂载 /api 路由。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    campaign,
    content_admin,
    dashboard,
    exercises,
    feedback,
    graph,
    history,
    profile,
    review,
    selfextend,
    session as session_api,
    subjects,
)
from .config import get_settings
from .db import SessionLocal, init_db
from .outline import store as outline_store
from .outline.store import ensure_math_preset
from .service.library import ensure_user, sync_content

logger = logging.getLogger("mathfeynman")
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
    yield


app = FastAPI(title="MathFeynman", version="0.1.0", lifespan=lifespan)

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

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True, "app": "MathFeynman", "version": "0.1.0"}


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
app.include_router(api)
