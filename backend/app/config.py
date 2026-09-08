"""应用配置：环境变量 → 配置对象（docs/02 §4：LLM 分级、路径等）。

MVP 阶段配置极简：读环境变量 + 可选 .env（仓库根或当前目录）。
LLM 分级模型在 M3 接入 ai/provider 时使用；此处先定义缺省值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv 可选：.env 不存在时静默跳过
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - 无 dotenv 也不阻塞
    pass

# 仓库根 = 本文件 ../..（backend/app/config.py -> backend -> repo root）
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: str) -> Path:
    raw = os.getenv(name) or default
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p)


@dataclass(frozen=True)
class Settings:
    """应用配置。"""

    # --- 服务 ---
    host: str = field(default_factory=lambda: os.getenv("MF_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("MF_PORT", "8000")))
    front_port: int = field(default_factory=lambda: int(os.getenv("MF_FRONT_PORT", "5173")))
    single_user_id: str = "local"  # ADR A10：MVP 固定单用户

    # --- 路径 ---
    db_path: Path = field(
        default_factory=lambda: _env_path("MF_DB_PATH", "backend/data/mathfeynman.db")
    )
    content_root: Path = field(
        default_factory=lambda: _env_path("MF_CONTENT_ROOT", "content")
    )

    # --- LLM（docs/02 §4 分级；M3 起生效）---
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    )
    llm_model_heavy: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_HEAVY", "deepseek-reasoner")
    )
    llm_model_light: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_LIGHT", "deepseek-chat")
    )
    llm_max_tokens_per_day: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS_PER_DAY", "0") or "0")
    )

    # --- 判题 ---
    judge_max_retry_samples: int = 20  # 模板自检失败重取样上限（docs/04 §4）

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent


def get_settings() -> Settings:
    return Settings()
