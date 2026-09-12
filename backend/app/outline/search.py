"""outline.search：外部检索后端 provider 抽象（docs/14 §8 · Phase C C1）。

设计（docs/14 §8"联网候选清单 → 勾选 → 本地化引用"，不整本下载）：
- **默认未启用**：无 provider 时 materials.search_candidates 返回明确中文提示，
  UI 标注"未配置检索后端"（离线仍可用「本地导入」）。
- **可配 provider：自托管 SearXNG**（`MF_SEARCH_PROVIDER=searxng` +
  `MF_SEARXNG_URL=<实例>/search`，如 http://127.0.0.1:8888；实例需开启 `format=json`）。
  SearXNG = 无第三方 key 的元搜索聚合器，自托管时隐私可控；**依赖**：一个运行中的
  SearXNG 实例（docker/本地，不在本仓库代码内）。
- 流程：真实检索 →（配 LLM_API_KEY 时）LLM 整理候选清单（CALL_SEARCH_CANDIDATES，
  输出 url 只允许取自原始结果，防杜撰）→ 用户 select 时抓**勾选**的公开网页正文入库
  （http(s)、text/html、大小上限）→ 本地引用库。
- 版权/robots 边界：仅抓取用户勾选的公开网页正文；不整本下载书籍/不抓 PDF 二进制
  （PDF 走 C2 的用户上传解析路径，上传者须为自有/授权资料）。

传输可注入 httpx transport（测试）；错误一律中文（docs/13 §2）。
"""
from __future__ import annotations

import html
import re
from typing import Any

import httpx

from ..config import Settings, get_settings

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YanHui-Coach/0.1 "
    "(material-citation-fetcher; +local-only)"
)
KNOWN_PROVIDERS = ("searxng",)


class SearchBackendError(RuntimeError):
    """检索后端不可用/配置非法（message 中文）。"""


def provider_status(settings: Settings | None = None) -> dict:
    """当前检索后端状态（供 search 响应与 UI 标注）。"""
    s = settings or get_settings()
    provider = s.search_provider
    if not provider:
        provider = "none"
    if provider not in KNOWN_PROVIDERS:
        return {
            "configured": False,
            "provider": "none" if provider in ("none", "") else provider,
            "url": "",
            "note": ("" if provider == "none" else f"未知检索后端: {provider!r}（支持: searxng）"),
        }
    if provider == "searxng" and not s.searxng_url:
        return {
            "configured": False,
            "provider": "searxng",
            "url": "",
            # **R61 任务 B**：这段 note 会随检索响应回给界面——不许出现内部变量名。
            "note": "SearXNG 未配置实例地址（要在这台机器的程序配置文件里填自托管实例地址）",
        }
    return {"configured": True, "provider": provider, "url": s.searxng_url, "note": ""}


def _settings_or(settings: Settings | None) -> Settings:
    return settings or get_settings()


def _searxng_search(query: str, *, settings: Settings, transport=None) -> list[dict[str, str]]:
    """SearXNG JSON API：GET <url>/search?q=..&format=json。"""
    url = settings.searxng_url
    headers = {"User-Agent": UA}
    try:
        with httpx.Client(headers=headers, timeout=settings.search_timeout_s,
                          transport=transport, follow_redirects=True) as client:
            resp = client.get(
                url if url.endswith("/search") else f"{url}/search",
                params={"q": query, "format": "json"},
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        raise SearchBackendError(f"检索后端返回错误状态 {e.response.status_code}（请检查 SearXNG 实例）") from e
    except httpx.RequestError as e:
        raise SearchBackendError(f"无法连接检索后端：{e}") from e
    except ValueError as e:  # JSON 解析失败
        raise SearchBackendError("检索后端返回了无法解析的内容（确认 SearXNG 已开启 JSON 输出）") from e
    raw = body.get("results") or []
    items: list[dict[str, str]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        link = str(r.get("url") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        summary = str(r.get("content") or r.get("snippet") or "").strip()
        items.append({
            "title": title,
            "url": link,
            "source": str(r.get("engine") or "SearXNG"),
            "summary": summary or title,
        })
    return items


def search_web(query: str, *, settings: Settings | None = None,
               transport=None) -> list[dict[str, str]]:
    """真实检索（provider 已配置前提；配置缺失抛 SearchBackendError 中文）。

    返回候选原始条目 [{title,url,source,summary}]（上限 search_max_items）。
    """
    s = _settings_or(settings)
    status = provider_status(s)
    if not status["configured"]:
        note = status.get("note") or ""
        # **R61 任务 B**：这条中文报错会被材料层拼进界面上的 note（`联网检索失败：…`）——
        # 不出现内部变量名，只说"在这台机器的程序配置文件里配"。
        raise SearchBackendError(f"联网检索后端未配置（{note}）。可选方案：在这台机器的程序配置文件里"
                                 "启用自托管 SearXNG 并填实例地址。")
    if s.search_provider == "searxng":
        items = _searxng_search(query, settings=s, transport=transport)
    else:  # pragma: no cover - provider_status 已拦截未知值
        raise SearchBackendError(f"未知检索后端: {s.search_provider!r}")
    # 去重（同 url 取先）+ 截断
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
        if len(out) >= max(1, s.search_max_items):
            break
    return out


# ---------------------------------------------------------------------------
# 抓取用户勾选的公开网页正文（select 阶段；本地化引用；robots/版权边界见模块 docstring）
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"(</(?:p|div|h[1-6]|li|tr|section|article)>|<br\s*/?>)", re.I)
_SKIP_RE = re.compile(r"<(script|style|noscript|template|svg|head)[^>]*>.*?</\1>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _html_to_text(raw: str, *, max_chars: int) -> str:
    raw = _COMMENT_RE.sub("", raw)
    raw = _SKIP_RE.sub(" ", raw)
    raw = _BLOCK_RE.sub("\n", raw)
    text = _TAG_RE.sub("", raw)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    text = re.sub(r"[ \t]+(?=\n)", "", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（页面正文过长，已按上限截取）"
    return text


def fetch_page_text(url: str, *, settings: Settings | None = None,
                    transport=None) -> str | None:
    """抓取单页公开网页正文（http(s)/text/html；大小上限）。

    返回清理后的纯文本；不可抓取（非 http(s)/非 html/网络失败/超上限）返回 None，
    调用方回落"仅摘要"——保证 select 永不因抓取失败而崩（错误只进日志/摘要回落）。
    """
    s = _settings_or(settings)
    if not url.startswith(("http://", "https://")):
        return None
    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
    try:
        with httpx.Client(headers=headers, timeout=s.fetch_page_timeout_s,
                          transport=transport, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            if "text/html" not in ctype and "xhtml" not in ctype:
                return None  # 非网页正文（PDF/二进制等）→ 不抓取，走摘要/用户上传
            raw = resp.text
    except (httpx.RequestError, httpx.HTTPStatusError):
        return None
    text = _html_to_text(raw, max_chars=max(1000, s.fetch_page_max_chars))
    return text or None


__all__ = [
    "SearchBackendError",
    "provider_status",
    "search_web",
    "fetch_page_text",
    "KNOWN_PROVIDERS",
]
