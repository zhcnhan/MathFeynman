"""app.api.exercises：练习判题/抽题端点（docs/06 §1）。判题只走 sympy（红线）。"""
from __future__ import annotations

import datetime as dt
import random
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..ai.gateway import OfflineGateway
from ..ai.calls import AiCallError, HintOnErrorIn
from ..content.templates import render_exercise
from ..domain.judge import JudgeError, NotationError, judge
from ..service.library import get_library
from .deps import get_db

router = APIRouter(prefix="/exercises", tags=["exercises"])

USER = "local"


class CheckBody(BaseModel):
    node_id: str
    exercise_id: str
    params_seed: int = 0
    user_answer: str
    session_id: str | None = None


class NextBody(BaseModel):
    node_id: str
    exclude_ids: list[str] = Field(default_factory=list)


def _exercise_of(node_id: str, exercise_id: str):
    lib = get_library()
    loaded = lib.by_id.get(node_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"节点不存在: {node_id}"}})
    ex = next((e for e in loaded.doc.exercises if e.id == exercise_id), None)
    if ex is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"练习不存在: {exercise_id}"}})
    return loaded, ex


@router.post("/check")
def check_exercise(body: CheckBody, db: Session = Depends(get_db)) -> dict:
    """幂等判题（docs/06 §1）。返回正确性 + 安全 hint，**永不返回答案**。"""
    loaded, ex = _exercise_of(body.node_id, body.exercise_id)
    rendered = render_exercise(loaded.doc.id, ex, body.params_seed)
    if rendered.broken:
        raise HTTPException(status_code=500, detail={"error": {"code": "exercise_broken", "message": rendered.detail}})
    try:
        result = judge(user_answer=body.user_answer.strip(), **rendered.judge_payload())
    except NotationError as e:
        return {
            "correct": False,
            "verdict": "notation",
            "message": str(e).split(":")[-1].strip(),
            "hint": None,
            "degraded": False,
        }
    except JudgeError as e:
        raise HTTPException(status_code=500, detail={"error": {"code": "exercise_broken", "message": str(e)}}) from e

    # 尝试留痕（无会话也可；kind=exercise，verdict 只由 sympy 裁决）
    db.add(
        models.Attempt(
            session_id=body.session_id,
            node_id=body.node_id,
            kind="exercise",
            exercise_id=body.exercise_id,
            params_json={"seed": body.params_seed},
            user_input=body.user_answer,
            verdict="correct" if result.correct else "wrong",
            meta_json={"mode": rendered.mode, "difficulty": ex.difficulty, "detail": result.detail, "source": "check"},
        )
    )
    db.commit()

    hint_md = None
    degraded = False
    if not result.correct:
        try:
            out = OfflineGateway().hint_on_error(
                HintOnErrorIn(
                    node_id=body.node_id,
                    prompt=rendered.prompt,
                    mode=rendered.mode,
                    user_answer=body.user_answer,
                    judge_detail=result.detail,
                )
            )
            hint_md = out.hint_md
            degraded = True
        except AiCallError:
            hint_md = "请再检查一遍计算与符号。"  # 防御兜底
    return {
        "correct": result.correct,
        "verdict": "correct" if result.correct else "wrong",
        "hint": hint_md,
        "degraded": degraded,
        "detail": result.detail if not result.correct else None,
    }


@router.post("/next")
def next_exercise(body: NextBody, db: Session = Depends(get_db)) -> dict:
    """下一道题（模板渲染或 AI 变体——MVP 只用模板，docs/08 §1）。"""
    loaded = get_library().by_id.get(body.node_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"节点不存在: {body.node_id}"}})
    pool = [e for e in loaded.doc.exercises if e.id not in set(body.exclude_ids)] or loaded.doc.exercises
    rng = random.Random(int(time.time() * 1000) ^ hash(body.node_id))
    ex = rng.choice(pool)
    seed = rng.randint(0, 2**31 - 1)
    rendered = render_exercise(loaded.doc.id, ex, seed)
    if rendered.broken:
        raise HTTPException(status_code=500, detail={"error": {"code": "exercise_broken", "message": rendered.detail}})
    return {
        "node_id": body.node_id,
        "exercise": {
            "exercise_id": rendered.exercise_id,
            "prompt": rendered.prompt,
            "mode": rendered.mode,
            "difficulty": rendered.difficulty,
            "interactive": rendered.interactive,
            "seed": rendered.seed,
        },
    }
