"""app.api.profile：用户画像与配置端点（docs/06 §1、03 §4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm import Session

from ..domain.profile import DEPTH_MAX, DEPTH_MIN, Profile
from ..service.library import ensure_user
from .deps import get_db

router = APIRouter(tags=["profile"])
USER = "local"


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)) -> dict:
    user = ensure_user(db, USER)
    profile = Profile.from_dict(user.profile_json or {})
    return profile.to_dict()


class PatchProfileBody(BaseModel):
    preferred_explanation_depth: int | None = Field(default=None, ge=DEPTH_MIN, le=DEPTH_MAX)
    preferred_examples: list[str] | None = None
    model_mode: Literal["smart", "light", "deep"] | None = None  # R12：⚡快/自动/🧠深度
    styling_notes: list[str] | None = None  # MVP：仅回读；AI 观察入列须人工确认（docs/03 §4）


@router.patch("/profile")
def patch_profile(body: PatchProfileBody, db: Session = Depends(get_db)) -> dict:
    user = ensure_user(db, USER)
    profile = Profile.from_dict(user.profile_json or {})
    if body.preferred_explanation_depth is not None:
        profile.preferred_explanation_depth = body.preferred_explanation_depth
    if body.preferred_examples is not None:
        profile.preferred_examples = body.preferred_examples
    if body.model_mode is not None:
        profile.model_mode = body.model_mode
    user.profile_json = profile.to_dict()
    db.commit()
    return profile.to_dict()


@router.get("/config/models")
def config_models(db: Session = Depends(get_db)) -> dict:
    """当前模型分级配置（docs/02 §4；显示用，**不含密钥**）。

    **R56**：改成读**生效配置**（页面设置 > .env > 默认）——设置页改了模型这里立刻同步。
    """
    from ..service import model_config

    v = model_config.view(db)
    return {
        "provider": v["provider"],
        "provider_label": v["provider_label"],
        "base_url": v["base_url"],
        "tiers": {
            "heavy": {"model": v["heavy"]},
            "light": {"model": v["light"]},
        },
        "configured": bool(v["configured"]),
        "api_key_masked": v["api_key_masked"],
        "settings_path_zh": "去「设置 · 模型」里填 Key",
    }
