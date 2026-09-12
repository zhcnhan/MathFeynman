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
    # **R56 裁定（用户 2026-09-12）**：模型就用 **DeepSeek V4.1 Flash**（规范名 `deepseek-flash`），
    # **不用** `deepseek-v4-pro`（贵一档，且不支持读图）。旧名 `deepseek-chat`/`deepseek-reasoner`
    # 实测都被静默转成 flash，所以这里直接写规范名（两档同一模型：快档够用、读图也只有它支持）。
    llm_model_heavy: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_HEAVY", "deepseek-flash")
    )
    llm_model_light: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL_LIGHT", "deepseek-flash")
    )
    llm_max_tokens_per_day: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS_PER_DAY", "0") or "0")
    )

    # --- 大纲起草的材料注入预算（R36 D4 → R37 S1 改造）---
    # **R37 起默认 0 = 不限**：教材＝权威真源，不再用"前 N 字摘要/总预算"糊弄（用户明示不省成本）。
    # 该变量是 R36 的旧名，保留兼容（显式设置时仍生效）；新名优先：
    # MF_MATERIAL_INJECT_MAX_CHARS（0=不限，>0=单次注入的硬上限，超限按结构截断并留痕）。
    outline_material_max_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_OUTLINE_MATERIAL_MAX_CHARS", "0") or "0")
    )
    material_inject_max_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_MATERIAL_INJECT_MAX_CHARS", "0") or "0")
    )
    # R37 S1：书太大时的**结构化分段**阈值（单次调用注入正文的物理上限，按章/页边界切，
    # **绝不**在句中截断）。0 = 不分段（整本一次调用，仅供小材料/测试）。
    material_batch_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_MATERIAL_BATCH_CHARS", "60000") or "0")
    )
    # R37 S7：扫描/图片版 PDF 的文本层健康度门槛（每页平均字符数 / 有文字的页占比）
    material_min_chars_per_page: int = field(
        default_factory=lambda: int(os.getenv("MF_MATERIAL_MIN_CHARS_PER_PAGE", "40") or "40")
    )
    material_min_text_page_ratio: float = field(
        default_factory=lambda: float(os.getenv("MF_MATERIAL_MIN_TEXT_PAGE_RATIO", "0.5") or "0.5")
    )
    # R38 S1b：**节粒度适配整本书**——PDF 无标题时把页合并成"章级"单元的目标大小（字符）。
    # 0 = 关闭合并（退回固定 4 页窗口，仅供测试/回退）。
    page_unit_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_PAGE_UNIT_CHARS", "8000") or "0")
    )
    # R38 S4：无上限时的**安全阀**——单次请求"字符数 ≈ token"粗估的上下文硬上限。
    # 超过就**不发请求**，改为自动分批 + 中文说明（"本书较大，已分 N 批处理"）。
    context_token_limit: int = field(
        default_factory=lambda: int(os.getenv("MF_CONTEXT_TOKEN_LIMIT", "120000") or "0")
    )
    # R42 B1：教材**过短条目**阈值（字符；默认 200）。低于它的条目（标题/目录类）
    # **并入相邻单元**或**标为跳过**，两种处理都进账本（不许静默吞掉）。
    min_entry_chars: int = field(
        default_factory=lambda: int(os.getenv("MF_MIN_ENTRY_CHARS", "200") or "0")
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

    # --- **R57 任务 A**：PDF → 页图渲染（图示教材模式 · 方案 a；可选依赖 pypdfium2+Pillow）---
    # 目标宽度（px）：**成本实测** 1024 px 宽 JPEG 一页 ≈ 960 prompt token；1457 px ≈ 1049。
    page_image_width: int = field(
        default_factory=lambda: int(os.getenv("MF_PAGE_IMAGE_WIDTH", "1024") or "1024")
    )
    # 输出格式（jpeg|png）与 JPEG 质量
    page_image_format: str = field(
        default_factory=lambda: (os.getenv("MF_PAGE_IMAGE_FORMAT", "jpeg") or "jpeg").lower()
    )
    page_image_quality: int = field(
        default_factory=lambda: int(os.getenv("MF_PAGE_IMAGE_QUALITY", "85") or "85")
    )
    # DPI 上限（防止"小页面被目标宽放大"到过大；实际 dpi = min(目标宽隐含 dpi, 本上限)）
    page_image_dpi_cap: int = field(
        default_factory=lambda: int(os.getenv("MF_PAGE_IMAGE_DPI_CAP", "200") or "200")
    )
    # 单页图片字节上限（防畸形页/超大页；超限 → 降质量重出一次，仍超 → 中文报错）
    page_image_max_bytes: int = field(
        default_factory=lambda: int(os.getenv("MF_PAGE_IMAGE_MAX_BYTES", str(4 * 1024 * 1024)) or "0")
    )
    # 渲染后的 PDF 缓存目录（**不进 content/**；进 .gitignore；按保留期清理）
    pdf_cache_dir: Path = field(
        default_factory=lambda: _env_path("MF_PDF_CACHE_DIR", ".runtime/pdf_cache")
    )
    pdf_cache_keep_days: int = field(
        default_factory=lambda: int(os.getenv("MF_PDF_CACHE_KEEP_DAYS", "7") or "7")
    )

    # --- 判题 ---
    judge_max_retry_samples: int = 20  # 模板自检失败重取样上限（docs/04 §4）

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent


def get_settings() -> Settings:
    return Settings()


def material_inject_budget(s: Settings | None = None) -> int:
    """R37 S1：**生效的**材料注入上限（0 = 不限）。

    优先级：``MF_MATERIAL_INJECT_MAX_CHARS``（R37 新名）> ``MF_OUTLINE_MATERIAL_MAX_CHARS``
    （R36 旧名，显式设置时仍生效）> 默认 0（不限）。
    """
    s = s or get_settings()
    raw = os.getenv("MF_MATERIAL_INJECT_MAX_CHARS")
    if raw not in (None, ""):
        return max(0, s.material_inject_max_chars)
    return max(0, s.outline_material_max_chars)
