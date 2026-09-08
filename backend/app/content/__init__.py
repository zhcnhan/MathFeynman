"""app.content：内容机代码（加载/模板/校验/渲染）。

数据目录（git 管理的结构化内容）在仓库根 `content/`，见 docs/04：
  content/stages/{primary,middle,high,college,ai}/...  —— 运行库只加载这里
  content/_drafts/                                     —— 未审核区，永不加载
  content/_meta/schemas + manifest.yaml                —— 索引/校验镜像

CLI（docs/04 §7）：`content validate` / `content render <node_id> <seed>`
（console script，见 backend/pyproject.toml）。
"""
from __future__ import annotations

import os
from pathlib import Path

from ..config import REPO_ROOT


def content_root() -> Path:
    """内容数据根目录：优先 MF_CONTENT_ROOT，缺省 <repo>/content。"""
    raw = os.getenv("MF_CONTENT_ROOT", "")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (REPO_ROOT / p)
    return REPO_ROOT / "content"


def stages_dir() -> Path:
    return content_root() / "stages"
