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
        default_factory=lambda: _env_path("MF_DB_PATH", "backend/data/yanhui.db")
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

    # --- 大纲起草的材料注入预算（R36 D4）---
    # 单次起草注入 prompt 的引用材料正文**总字符上限**（超出即分节摘要降级 + 截断留痕；
    # **禁止整本塞进一次调用**）。调用点：api/subjects._draft_materials → materials.draft_materials()。
    outline_material_max_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_OUTLINE_MATERIAL_MAX_CHARS", "6000") or "6000")
    )

    # --- 外部检索后端（docs/14 §8 · Phase C C1；默认未启用）---
    # 默认 "none"（未配置检索后端 → UI 标注 + 明确中文提示）；可配 "searxng"：
    # 自托管 SearXNG 实例（MF_SEARXNG_URL，如 http://127.0.0.1:8888，需开启 JSON 输出），
    # 免第三方 key（自托管=用户自有实例；外部公共实例需自行评估可用性/隐私）。
    search_provider: str = field(
        default_factory=lambda: (os.getenv("MF_SEARCH_PROVIDER", "") or "").strip().lower()
    )
    searxng_url: str = field(
        default_factory=lambda: (os.getenv("MF_SEARXNG_URL", "") or "").strip().rstrip("/")
    )
    search_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("MF_SEARCH_TIMEOUT_S", "20") or "20")
    )
    search_max_items: int = field(
        default_factory=lambda: int(os.getenv("MF_SEARCH_MAX_ITEMS", "8") or "8")
    )
    # 抓取用户勾选公开网页正文的大小上限（字符；防"整本下载/超大页"）
    fetch_page_max_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_FETCH_PAGE_MAX_CHARS", "200000") or "200000")
    )
    fetch_page_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("MF_FETCH_PAGE_TIMEOUT_S", "15") or "15")
    )

    # --- PDF/文档解析（Phase C C2：pypdf，BSD-3-Clause）---
    pdf_max_bytes: int = field(
        default_factory=lambda: int(os.getenv("MF_PDF_MAX_BYTES", str(20 * 1024 * 1024)) or "0")
    )
    pdf_max_pages: int = field(
        default_factory=lambda: int(os.getenv("MF_PDF_MAX_PAGES", "400") or "400")
    )
    pdf_per_page_max_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_PDF_PER_PAGE_MAX_CHARS", "8000") or "8000")
    )

    # --- 判题 ---
    judge_max_retry_samples: int = 20  # 模板自检失败重取样上限（docs/04 §4）

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent


def get_settings() -> Settings:
    return Settings()
