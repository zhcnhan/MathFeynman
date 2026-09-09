"""outline.materials：材料层基础（docs/14 §8 · Phase B B3）。

- 本地导入：用户自有/授权文本 → 本地引用库（分节文本 + 来源标注，入库
  content/subjects/<sid>/materials/<slug>-<hash>.md）；
- 联网候选：search 返回候选清单（无网/未接检索后端时给提示）；select 将勾选候选
  （标题/来源/摘要）本地化入库为 web 引用——**不整本下载**；
- 生成单元时引用：materials_summaries() 供 outline.generate 注入 AI 起草上下文
  （可追溯来源标注）。
来源策略 source_policy（ai|import|web|mixed，默认 ai）存 subjects.meta_json；
math（preset）同样支持（材料作讲解增强，不影响 roadmap 内容）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..outline import store as outline_store
from .schemas import OutlineError

POLICY_AI = "ai"
POLICY_IMPORT = "import"
POLICY_WEB = "web"
POLICY_MIXED = "mixed"
SOURCE_POLICIES = (POLICY_AI, POLICY_IMPORT, POLICY_WEB, POLICY_MIXED)
DEFAULT_POLICY = POLICY_AI

_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(s: str) -> str:
    return _SLUG.sub("_", s).strip("_")[:32] or "doc"


def materials_dir(subject_id: str) -> Path:
    d = outline_store.subject_dir(subject_id) / "materials"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_policy(db, subject_id: str) -> str:
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    return str((row.meta_json or {}).get("source_policy") or DEFAULT_POLICY)


def set_policy(db, subject_id: str, policy: str) -> str:
    if policy not in SOURCE_POLICIES:
        raise OutlineError(f"来源策略非法: {policy!r}（∈ {SOURCE_POLICIES}）")
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    meta = dict(row.meta_json or {})
    meta["source_policy"] = policy
    row.meta_json = meta
    db.commit()
    return policy


def add_material(db, subject_id: str, *, title: str, text: str, source: str = "本地导入",
                 url: str = "") -> dict:
    """本地/联网引用入库（文本必填；分节文本按段落/标题切分存正文）。"""
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise OutlineError("材料标题与正文不能为空")
    entry_id = "mat-" + hashlib.sha1(f"{subject_id}:{title}:{url}:{text[:80]}".encode("utf-8")).hexdigest()[:10]
    p = materials_dir(subject_id) / f"{_slug(title)}-{entry_id[4:]}.md"
    if not p.exists():
        meta_lines = [
            "---",
            f"id: {entry_id}",
            f"title: {title}",
            f"source: {source}",
            f"url: {url}",
            "kind: " + ("web" if url else "local"),
            "---",
            "",
        ]
        p.write_text("\n".join(meta_lines) + "\n" + text + "\n", encoding="utf-8")
    return {"id": entry_id, "title": title, "source": source, "url": url,
            "kind": "web" if url else "local", "file": p.name}


def _parse_entry(p: Path) -> dict | None:
    raw = p.read_text(encoding="utf-8")
    fm = {}
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end > 0:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
            body = raw[end + 4 :].strip()
            return {
                "id": fm.get("id", p.stem),
                "title": fm.get("title", p.stem),
                "source": fm.get("source", "本地导入"),
                "url": fm.get("url", ""),
                "kind": fm.get("kind", "local"),
                "file": p.name,
                "body": body,
            }
    return None


def list_materials(db, subject_id: str) -> list[dict]:
    d = materials_dir(subject_id)
    out = []
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e:
            out.append({"id": e["id"], "title": e["title"], "source": e["source"],
                        "url": e["url"], "kind": e["kind"], "file": e["file"]})
    return out


def delete_material(db, subject_id: str, material_id: str) -> bool:
    d = materials_dir(subject_id)
    removed = False
    for p in d.glob("*.md"):
        e = _parse_entry(p)
        if e and e["id"] == material_id:
            p.unlink(missing_ok=True)
            removed = True
    return removed


def materials_summaries(db, subject_id: str, *, limit_chars: int = 220) -> list[dict]:
    """引用材料摘要（生成单元时注入 AI 起草上下文；可追溯 title/source/url）。"""
    out = []
    for e in list_materials(db, subject_id):
        body = e.get("body", "")
        out.append({
            "title": e["title"],
            "source": e["source"],
            "url": e["url"],
            "summary": body[:limit_chars] + ("…" if len(body) > limit_chars else ""),
        })
    return out


def search_candidates(db, subject_id: str, query: str) -> dict:
    """联网候选（Phase C C1：检索后端 provider 抽象；默认未启用 → 明确中文提示）。

    返回：{items: [{title,url,source,summary,reason?}], note: str, backend: {configured,provider,url}}。
    - 未配置 provider → 提示"未配置检索后端…可用本地导入"（items 空）；
    - 配置 SearXNG → 真实检索 →（配 LLM_API_KEY）LLM 整理候选清单 → items。
    """
    from ..config import get_settings
    from . import search as search_svc

    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    settings = get_settings()
    status = search_svc.provider_status(settings)
    if not status.get("configured"):
        return {"items": [], "note": _no_backend_note(status), "backend": status}
    try:
        raw = search_svc.search_web(query, settings=settings)
    except search_svc.SearchBackendError as e:
        return {"items": [], "note": f"联网检索失败：{e}", "backend": status}
    if not raw:
        return {"items": [], "note": "未检索到与查询匹配的候选：可换关键词重试，或使用「本地导入」上传自有/授权资料。",
                "backend": status}
    items = _refine_candidates(db, row, query, raw, settings)
    return {"items": items, "note": "", "backend": status}


def _no_backend_note(status: dict) -> str:
    provider = status.get("provider") or "none"
    if provider == "searxng":
        return ("联网检索后端未配置完成：已选 SearXNG 但缺少实例地址（设 MF_SEARXNG_URL）。"
                "配置后可用联网候选，或现在用「本地导入」上传自有/授权资料。")
    return ("联网检索后端未配置（当前无检索 provider）。可选方案：自托管 SearXNG（设 "
            "MF_SEARCH_PROVIDER=searxng 与 MF_SEARXNG_URL），或先用「本地导入」上传自有/授权资料。")


def _refine_candidates(db, subj, query: str, raw: list[dict], settings) -> list[dict]:
    """LLM 整理候选（配 LLM_API_KEY 时；输出 url 回滤原始集防杜撰；失败/无 key → 原始直出）。"""
    if not settings.llm_api_key:
        return raw[: max(1, settings.search_max_items)]
    try:
        from ..ai.calls import CALL_SEARCH_CANDIDATES
        from ..ai.provider import OpenAICompatibleProvider
        from ..service.ai_sink import make_ai_log_sink

        provider = OpenAICompatibleProvider(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url,
            model_heavy=settings.llm_model_heavy, model_light=settings.llm_model_light,
            log_sink=make_ai_log_sink(),
        )
        sys = (
            "你是资料检索助理。给定一次联网检索的**原始结果清单**与学习者的学科背景，"
            "挑选最适合作为**学习参考材料**的条目（优先：权威/可读/与学科目标相关），"
            '输出 JSON：{"items":[{"title","url","source","summary","reason"}]}。'
            "要求：只从原始结果中挑选（禁止自造 url）；3–8 条；summary 为 1–2 句要点摘要；"
            "reason 一句说明为何适合做学习材料。"
        )
        user = (
            f"学科：{subj.id}（{subj.label or ''}）\n"
            f"检索词：{query}\n原始结果：\n"
            + "\n".join(f"- {r.get('title', '')} | {r.get('url', '')} | {r.get('summary', '')[:200]}"
                        for r in raw[:12])
        )
        outcome = provider.chat_json(
            CALL_SEARCH_CANDIDATES,
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            strategy="fast",
        )
        valid_urls = {r.get("url") for r in raw}
        refined = []
        for it in (outcome.parsed.get("items") or []):
            url = str(it.get("url") or "").strip()
            if url not in valid_urls:  # 防 LLM 杜撰来源
                continue
            title = str(it.get("title") or "").strip()
            summary = str(it.get("summary") or "").strip()
            if not title or not summary:
                continue
            refined.append({
                "title": title,
                "url": url,
                "source": str(it.get("source") or next(
                    (r.get("source", "") for r in raw if r.get("url") == url), "")),
                "summary": summary,
                "reason": str(it.get("reason") or ""),
            })
        if refined:
            return refined[: max(1, settings.search_max_items)]
        return raw[: max(1, settings.search_max_items)]  # LLM 整理失败 → 原始直出
    except Exception:
        return raw[: max(1, settings.search_max_items)]  # AI 异常不阻塞检索流


def select_candidates(db, subject_id: str, items: list[dict],
                      *, fetch_pages: bool = False) -> list[dict]:
    """勾选候选 → 本地化引用（标题/来源/摘要入库；**不整本下载**）。

    fetch_pages=True（用户勾选动作）→ 对 http(s) 公开网页抓正文入库（大小上限/失败回落摘要）；
    书籍类 URL/非 html 不抓取（PDF 走 C2 用户上传路径）。
    """
    from . import search as search_svc

    saved = []
    for it in items:
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or "").strip()
        summary = str(it.get("summary") or "").strip()
        if not title or not (summary or url):
            continue
        text = summary + ("\n（来源：" + url + "）" if url else "")
        if fetch_pages and url:
            fetched = search_svc.fetch_page_text(url)
            if fetched:
                text = ("（以下为该公开网页正文的本地化摘录，用户勾选抓取：）\n\n"
                        + fetched + "\n\n【原始候选摘要】\n" + summary)
        saved.append(add_material(db, subject_id, title=title, text=text,
                                  source=str(it.get("source") or url or "联网候选"), url=url))
    if not saved:
        raise OutlineError("请勾选至少 1 条候选（标题与摘要不能为空）")
    return saved


__all__ = [
    "SOURCE_POLICIES",
    "DEFAULT_POLICY",
    "materials_dir",
    "get_policy",
    "set_policy",
    "add_material",
    "list_materials",
    "delete_material",
    "materials_summaries",
    "search_candidates",
    "select_candidates",
]
