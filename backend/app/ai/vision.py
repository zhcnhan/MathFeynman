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
    # **页号以我们为准**（R57）：模型回什么都覆盖成"我们发出去的那个页号"——
    # 依据必须能追到"第 N 页"，不许由模型自己决定页号（它可能回错、回空或回成"这一页"）。
    if ctx.page_label:
        parsed["page_label"] = ctx.page_label
    else:
        parsed.setdefault("page_label", "")
    return ReadPageOut(**parsed), rt.version


def read_pages_batch(provider, *, pages: list[dict], want: str = "", note: str = "",
                     subject_id: str = "", unit_id: str = "",
                     strategy: str | None = None) -> list[tuple[str, dict, str]]:
    """**一次调用读 2–4 页**（R67 任务 F 的"批量"）→ ``[(页标签, 记录, 提示词版本), …]``。

    硬口径：**一页一条记录**——回来的是"每一页各自一条"，绝不是"几页糊成一条"。
    - 页号**以我们为准**：模型回的页号被覆盖成"我们发出去的那个"（它可能回错、回空）；
    - 模型漏页/页号对不上时按**顺序**补齐（数量对得上就按顺序认；对不上就只回它真给了的，
      由调用方把缺的页**单独重读一次**——**绝不允许**因此少一页记录）；
    - 记录字段与单页读**逐字相同**（`ReadPageOut` 的字段）。
    """
    from .calls import CALL_READ_PAGES, ReadPageOut

    labels = [str((p or {}).get("label") or "") for p in (pages or [])]
    if not labels:
        return []
    rt = prompt_runtime.PromptRuntime("read_pages", subject_id=subject_id, unit_id=unit_id)
    vars_: dict[str, str] = dict(UI_PLACEHOLDER_DEFAULTS)
    vars_.update({
        "page_labels": "、".join(labels),
        "want": want or "按上面的要求，把这几页真能看到的内容都记下来",
        "note": note or "（没有特别说明）",
    })
    system = render(rt.system_template, **vars_)
    user_text = render(rt.user_template, **vars_)
    content: list[dict] = [{"type": "text", "text": user_text}]
    for label, item in zip(labels, pages):
        content.append({"type": "text", "text": f"↓ 这一张是【{label}】的图片："})
        content.append(dict(item.get("image") or {}))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": content}]
    outcome = provider.chat_json(
        CALL_READ_PAGES, messages, strategy=strategy,
        audit={"subject_id": subject_id, "unit_id": unit_id, "prompt_versions": rt.version},
    )
    items = list((outcome.parsed or {}).get("pages") or [])
    out: list[tuple[str, dict, str]] = []
    used: set[int] = set()
    by_label: dict[str, int] = {}
    for i, raw in enumerate(items):
        lab = str((raw or {}).get("page_label") or "").strip()
        if lab and lab in labels and lab not in by_label:
            by_label[lab] = i
    for label in labels:
        idx = by_label.get(label)
        if idx is None:
            continue
        used.add(idx)
        rec = _clean_page_record(dict(items[idx] or {}), label)
        out.append((label, rec, rt.version))
    if not out and len(items) == len(labels):        # 模型完全没回页号但页数对得上 → 按顺序认
        for label, raw in zip(labels, items):
            rec = _clean_page_record(dict(raw or {}), label)
            out.append((label, rec, rt.version))
    elif len(out) < len(labels):
        rest = [i for i in range(len(items)) if i not in used]
        missing = [lb for lb in labels if lb not in {o[0] for o in out}]
        for label, idx in zip(missing, rest):        # 页号没对上但条数够 → 按顺序补位
            rec = _clean_page_record(dict(items[idx] or {}), label)
            out.append((label, rec, rt.version))
    return out


def _clean_page_record(raw: dict, label: str) -> dict:
    """一条批量记录 → 与单页读**同一种**结构（页号以我们为准；多余字段丢掉）。"""
    from .calls import ReadPageOut

    raw.pop("page_label", None)
    raw["page_label"] = label
    try:
        return ReadPageOut(**raw).model_dump()
    except Exception:
        keep = ("readable", "unreadable_reason", "key_points", "visible_text", "formulas",
                "figures", "uncertain", "confidence")
        out = {k: raw.get(k) for k in keep if k in raw}
        out["page_label"] = label
        try:
            return ReadPageOut(**out).model_dump()
        except Exception:
            return {"page_label": label, "readable": False,
                    "unreadable_reason": "这一页这次没读成（模型的返回格式不对），可以重读这一页",
                    "key_points": [], "visible_text": [], "formulas": [], "figures": [],
                    "uncertain": [], "confidence": 0.0}


__all__ = ["ALLOWED_IMAGE_MIME", "image_block", "read_page", "read_pages_batch"]
