"""api.prompts：**提示词可在程序内修改** + 一键恢复默认（docs/09 R39 §2）。

- ``GET  /prompts``                     全部调用点（中文名 + 用途 + 当前值/是否默认/上次修改 + 与默认的差异）
- ``GET  /prompts/{call_name}``         单条
- ``PUT  /prompts/{call_name}``         保存（必填占位符/硬约束缺失 → **中文 422 拒绝保存**）
- ``POST /prompts/{call_name}/reset``   单条恢复默认
- ``POST /prompts/reset-all``           全部恢复默认（前端恢复前确认）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai.prompt_templates import PromptError
from ..service import prompt_store
from .deps import get_db

router = APIRouter(tags=["prompts"])


def _zh_422(e: PromptError) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": {
        "code": "validation_error", "message": str(e)}})


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db)) -> dict:
    """调用点清单（"一处不漏"由注册表与 ``ai.calls.CALLS`` 的一致性用例保证）。"""
    return prompt_store.spec_list(db)


@router.get("/prompts/{call_name}")
def get_prompt(call_name: str, db: Session = Depends(get_db)) -> dict:
    try:
        return prompt_store.get_one(db, call_name)
    except PromptError as e:
        raise _zh_422(e) from e


class SavePromptBody(BaseModel):
    system: str | None = None
    user: str | None = None


@router.put("/prompts/{call_name}")
def save_prompt(call_name: str, body: SavePromptBody, db: Session = Depends(get_db)) -> dict:
    """保存提示词（改动**立即生效**；会记入账本，可回溯"哪次生成用哪版提示词"）。"""
    try:
        return prompt_store.save(db, call_name, system_text=body.system, user_text=body.user)
    except PromptError as e:
        raise _zh_422(e) from e


class ResetBody(BaseModel):
    field: str = ""   # "" = 整条；或 "system" / "user"


@router.post("/prompts/{call_name}/reset")
def reset_prompt(call_name: str, body: ResetBody | None = None,
                 db: Session = Depends(get_db)) -> dict:
    try:
        return prompt_store.reset_one(db, call_name, field=(body.field if body else ""))
    except PromptError as e:
        raise _zh_422(e) from e


@router.post("/prompts/reset-all")
def reset_all_prompts(db: Session = Depends(get_db)) -> dict:
    """全部恢复默认（前端已确认）。"""
    return prompt_store.reset_all(db)
