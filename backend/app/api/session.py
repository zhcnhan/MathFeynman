"""app.api.session：学习会话端点（docs/06 §1）。薄层：只传参 + 错误映射。

R12-b 流式（docs/09 R12 §3）：`POST /session/step?stream=1` 返回 SSE——
- 事件 `start`：{session_id, action}；
- 处理期间每秒 `ping`：{seconds}（心跳/耗时提示）；
- 结束 `result`：与普通响应完全一致的完整 JSON（"渲染指令=状态机"契约不变）；
- 失败 `error`：{code, message}；流不可用（网络/非流内容）时前端自动回退普通 POST。
同步服务逻辑跑在工作线程，不阻塞事件循环。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..service.session import ExerciseBrokenError, SessionError, SessionService
from .deps import get_db, get_session_service, raise_session_error

router = APIRouter(prefix="/session", tags=["session"])

PING_INTERVAL_S = 1.0


class StartBody(BaseModel):
    node_id: str


class StepBody(BaseModel):
    session_id: str
    action: str
    payload: dict | None = Field(default_factory=dict)


class SessionStepOut(BaseModel):
    step: str
    payload: dict
    events: list[dict]
    session: dict


@router.post("/start")
def session_start(body: StartBody, db: Session = Depends(get_db), svc: SessionService = Depends(get_session_service)) -> dict:
    try:
        return svc.start(db, body.node_id)
    except SessionError as e:
        raise raise_session_error(e) from e


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_step_worker(svc: SessionService, session_id: str, action: str, payload: dict, holder: dict, done: threading.Event) -> None:
    """工作线程：自带事务（LLM 等待期间不占写锁——见 R7 commit 语义）。"""
    with SessionLocal() as db:
        try:
            result = svc.step(db, session_id, action, payload)
            db.commit()
            holder["result"] = result
        except SessionError as e:
            db.rollback()
            holder["error"] = {"code": e.code, "message": str(e)}
        except Exception as e:  # 兜底：不泄漏内部异常
            db.rollback()
            holder["error"] = {"code": "internal_error", "message": str(e)}
        finally:
            done.set()


def _stream_generator(svc: SessionService, body: StepBody) -> Iterator[str]:
    holder: dict = {}
    done = threading.Event()
    yield _sse("start", {"session_id": body.session_id, "action": body.action})
    threading.Thread(
        target=_run_step_worker,
        args=(svc, body.session_id, body.action, body.payload or {}, holder, done),
        daemon=True,
    ).start()
    t0 = time.monotonic()
    while not done.is_set():
        yield _sse("ping", {"seconds": int(time.monotonic() - t0)})
        done.wait(timeout=PING_INTERVAL_S)
    if "error" in holder:
        yield _sse("error", holder["error"])
        return
    yield _sse("result", holder.get("result") or {"ok": False, "detail": "no-result"})


@router.post("/step")
def session_step(
    body: StepBody,
    stream: bool = Query(default=False),  # R12-b：?stream=1 → SSE
    db: Session = Depends(get_db),
    svc: SessionService = Depends(get_session_service),
):
    if stream:
        return StreamingResponse(
            _stream_generator(svc, body),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        result = svc.step(db, body.session_id, body.action, body.payload or {})
        _trace_step("ok", body.session_id, body.action, result.get("step", ""))
        return result
    except SessionError as e:
        _trace_step("err", body.session_id, body.action, e.code, detail=str(e))
        raise raise_session_error(e) from e
    except Exception as e:
        _trace_step("unexpected", body.session_id, body.action, "500", detail=str(e))
        raise


@router.get("/{session_id}")
def session_get(session_id: str, db: Session = Depends(get_db), svc: SessionService = Depends(get_session_service)) -> dict:
    try:
        return svc.resume(db, session_id)
    except SessionError as e:
        raise raise_session_error(e) from e


def _trace_step(outcome: str, session_id: str, action: str, extra: str = "", detail: str = "") -> None:
    """B（R9 #6 排查）：轻量链路日志（stderr 直出，uvicorn 控制台可见）。"""
    import sys

    msg = f"[session.step] {outcome} session={session_id} action={action} extra={extra}"
    if detail:
        msg += f" detail={detail[:200]}"
    print(msg, file=sys.stderr, flush=True)
