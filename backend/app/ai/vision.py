"""ai.vision：**把教材页/图交给模型读**（R56 第 1 步 · 全 AI 模式的第一步）。

口径（工单 §0.3 / §4-B2）：
- **方案 A**：不渲染、不拆解，**直接把图片交给模型**（模型自带读图能力）；
- 只做四件事：**装消息**（图片 → 多模态内容块）→ **调模型**（既有 `provider.chat_json`，
  于是这次调用**原样进既有 `ai_trace`**：发了什么、返回什么、token、耗时、成败）→
  **校验结构化输出**（`ReadPageOut`）→ **返回**；
- **诚实出口**：模型读不出来时返回 `readable=False` + 中文原因（不许编、不许硬猜）；
- 图片形态按**实测可行的 OpenAI 兼容格式**：`{"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}`
  ——实测 DeepSeek 收 webp/png/jpeg/gif 的 data URL；**PDF 文件本身它不收**（见 NOTES §79）。
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from . import prompt_runtime
from .calls import CALL_READ_PAGE, ReadPageIn, ReadPageOut
from .prompt_templates import UI_PLACEHOLDER_DEFAULTS, render

ALLOWED_IMAGE_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif")


def image_block(image: bytes | str | Path, *, mime: str = "") -> dict:
    """图片 → 多模态内容块（**data URL**，不依赖任何渲染/上传服务）。

    ``image`` 可以是字节、base64 字符串或文件路径；``mime`` 不传就按文件名猜、再退到 PNG。
    """
    if isinstance(image, Path):
        raw = image.read_bytes()
        mime = mime or (mimetypes.guess_type(image.name)[0] or "image/png")
        b64 = base64.b64encode(raw).decode()
    elif isinstance(image, (bytes, bytearray)):
        b64 = base64.b64encode(bytes(image)).decode()
    else:                                   # 已经是 base64 字符串
        b64 = str(image or "").strip()
    mime = (mime or "image/png").lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in ALLOWED_IMAGE_MIME:
        raise ValueError(f"图片格式只能是 {'/'.join(ALLOWED_IMAGE_MIME)}，收到 {mime}")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def read_page(provider, *, images: list[dict] | None = None, page_label: str = "",
              want: str = "", note: str = "", subject_id: str = "", unit_id: str = "",
              strategy: str | None = None) -> tuple[ReadPageOut, str]:
    """读一页/一张图 → ``(结构化结果, 提示词版本标签)``。

    调用**完整走既有审计链路**（`provider.chat_json` + `ai_trace`）；
    读不出来时 `ReadPageOut.readable=False` 且 `unreadable_reason` 给中文原因——
    调用方据此走"诚实出口"（告诉学生"这页我读不出来"），**不许**当成"读到了空内容"。
    """
    ctx = ReadPageIn(page_label=page_label, want=want, note=note)
    rt = prompt_runtime.PromptRuntime("read_page", subject_id=subject_id, unit_id=unit_id)
    vars_: dict[str, str] = dict(UI_PLACEHOLDER_DEFAULTS)
    vars_.update({
        "page_label": ctx.page_label or "（没有编号）",
        "want": ctx.want or "按上面的要求，把这一页真能看到的内容都记下来",
        "note": ctx.note or "（没有特别说明）",
    })
    system = render(rt.system_template, **vars_)
    user_text = render(rt.user_template, **vars_)
    content: list[dict] = [{"type": "text", "text": user_text}]
    content += list(images or [])
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": content}]
    outcome = provider.chat_json(
        CALL_READ_PAGE, messages, strategy=strategy,
        audit={"subject_id": subject_id, "unit_id": unit_id, "prompt_versions": rt.version},
    )
    parsed = dict(outcome.parsed or {})
    parsed.setdefault("page_label", ctx.page_label)
    return ReadPageOut(**parsed), rt.version


__all__ = ["ALLOWED_IMAGE_MIME", "image_block", "read_page"]
