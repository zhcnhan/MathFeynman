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
                 url: str = "", kind: str | None = None, filename: str = "") -> dict:
    """本地/联网引用入库（文本必填；分节文本按段落/标题切分存正文）。

    kind ∈ local|web|pdf（缺省按 url 推导：有 url=web、无=local；pdf 由 C2 解析器显式传入）；
    filename 记录源文件名（PDF/文档导入的展示与追溯）。
    """
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise OutlineError("材料标题与正文不能为空")
    effective_kind = kind or ("web" if url else "local")
    if effective_kind not in ("local", "web", "pdf"):
        raise OutlineError(f"材料 kind 非法: {effective_kind!r}")
    entry_id = "mat-" + hashlib.sha1(f"{subject_id}:{title}:{url}:{text[:80]}".encode("utf-8")).hexdigest()[:10]
    p = materials_dir(subject_id) / f"{_slug(title)}-{entry_id[4:]}.md"
    if not p.exists():
        meta_lines = [
            "---",
            f"id: {entry_id}",
            f"title: {title}",
            f"source: {source}",
            f"url: {url}",
            f"kind: {effective_kind}",
        ]
        if filename:
            meta_lines.append(f"filename: {filename}")
        meta_lines += ["", "---", ""]
        p.write_text("\n".join(meta_lines) + "\n" + text + "\n", encoding="utf-8")
    return {"id": entry_id, "title": title, "source": source, "url": url,
            "kind": effective_kind, "file": p.name,
            "filename": filename or p.name}


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
                "filename": fm.get("filename", ""),
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
                        "url": e["url"], "kind": e["kind"], "file": e["file"],
                        "filename": e.get("filename", "")})
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


# ---------- R36 D1/D2/D4：大纲起草读材料（可选输入）＋逐单元溯源 ----------

DEFAULT_INJECT_MAX_CHARS = 6000   # 单次起草注入的材料正文总字符预算（config 可覆盖，D4）
DEFAULT_SECTION_CHARS = 400       # 每节摘要字符上限（分节摘要降级用）
MAX_SECTIONS_PER_MATERIAL = 12    # 每份材料最多展示的节数（超出的节进"已截取"口径）

_PAGE_MARK = re.compile(r"^【第\s*(\d+)\s*页】\s*$")
_HEADING_MARK = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _entries_with_body(subject_id: str) -> list[dict]:
    """材料条目（含正文 body）——服务端校验/注入用；对外 API 不下发正文。"""
    out = []
    for p in sorted(materials_dir(subject_id).glob("*.md")):
        e = _parse_entry(p)
        if e:
            out.append(e)
    return out


def material_sections(body: str, *, max_sections: int = MAX_SECTIONS_PER_MATERIAL,
                      section_chars: int = DEFAULT_SECTION_CHARS) -> list[dict]:
    """把材料正文切成"可引用的节"：PDF 的 `【第 N 页】` → Markdown 标题 → 段落兜底。

    返回 ``[{label, text}]``：label＝章节名（第 N 页 / 标题 / 第 N 节），供 D2 溯源与 D4 分节摘要。
    text 已按 ``section_chars`` 截断（超长留 `…` 标记）。
    """
    raw = (body or "").strip()
    if not raw:
        return []
    sections: list[dict] = []
    buf: list[str] = []
    label = ""

    def _flush() -> None:
        nonlocal buf, label
        text = "\n".join(buf).strip()
        if text:
            cut = len(text) > section_chars
            sections.append({
                "label": label or f"第 {len(sections) + 1} 节",
                "text": text[:section_chars] + ("…" if cut else ""),
            })
        buf = []

    for line in raw.splitlines():
        s = line.strip()
        m = _PAGE_MARK.match(s)
        if m:
            _flush()
            label = f"第 {m.group(1)} 页"
            continue
        h = _HEADING_MARK.match(s)
        if h:
            _flush()
            label = h.group(1).strip()
            continue
        buf.append(line)
    _flush()
    return sections[:max_sections]


def draft_materials(db, subject_id: str, *, max_chars: int = DEFAULT_INJECT_MAX_CHARS) -> dict:
    """D1＋D4：大纲起草的**材料注入包**（唯一入口）。

    返回:
    - ``text``：注入 prompt 的材料块（分节摘要 + 章节名；受 ``max_chars`` 总预算硬约束）；
    - ``index``：``[{id,title,source,url,body,sections}]``——**服务端 D2 校验用**（含正文，不下发前端）；
    - ``used_chars`` / ``dropped``（未注入的材料标题）/ ``truncated``（是否因预算截断）。

    预算纪律（D4）：**绝不整本塞进一次调用**——先到先得 + 总字符上限；超出即截断并留痕；
    每日 token 上限仍由 ``LLM_MAX_TOKENS_PER_DAY``（provider 侧）保护。
    """
    index = []
    for e in _entries_with_body(subject_id):
        index.append({
            "id": e["id"], "title": e["title"], "source": e["source"], "url": e["url"],
            "body": e.get("body", ""), "sections": material_sections(e.get("body", "")),
        })
    used = 0
    blocks: list[str] = []
    dropped: list[str] = []
    truncated = False
    for m in index:
        head = f"### 材料《{m['title']}》（{m['source'] or '本地'}"
        head += f"，{m['url']}" if m["url"] else ""
        head += "）"
        block_used = len(head)
        if used + block_used > max_chars:  # 标题都放不下 → 整份材料不注入（留痕）
            dropped.append(m["title"])
            truncated = True
            continue
        lines: list[str] = []
        for sec in m["sections"]:
            line = f"- [{sec['label']}] {sec['text']}"
            if used + block_used + len(line) > max_chars:
                truncated = True
                break
            lines.append(line)
            block_used += len(line)
        if not lines:
            dropped.append(m["title"])
            continue
        used += block_used
        blocks.append(head + "\n" + "\n".join(lines))
    text = "\n\n".join(blocks)
    if dropped:
        text += ("\n\n（另有 %d 份材料因超出本次注入预算未展示：%s）"
                 % (len(dropped), "、".join(dropped)))
    return {"text": text, "index": index, "used_chars": used, "dropped": dropped,
            "truncated": truncated, "count": len(index)}


def check_unit_material(ref: dict, index: list[dict]) -> tuple[dict | None, str]:
    """D2：校验单个 ``{title, section}`` 溯源引用 → ``(规范化引用 | None, 中文问题)``。

    规则：① ``title`` 必须真实存在于该学科引用库；② ``section`` 必须是该材料的**真实章节名**
    （第 N 页 / 标题，见 ``material_sections``）**或逐字出自其正文的引文**——
    后者复用 ``content.citations`` 的同一把尺子（归一化 + ≥6 字 + 子串包含），
    与 R35 S2 的 basis 引文纪律同源，不另写一份。
    """
    from ..content import citations

    title = str((ref or {}).get("title") or "").strip()
    section = str((ref or {}).get("section") or "").strip()
    if not title:
        return None, "材料溯源项缺少材料标题（title）"
    hit = next((m for m in index if m["title"] == title), None)
    if hit is None:
        return None, f"材料溯源不成立：该学科引用库里没有名为「{title}」的材料"
    if not section:
        return None, f"材料《{title}》的溯源缺少 section（须给出真实章节名或逐字引文）"
    if citations.normalize(section) in {citations.normalize(s["label"]) for s in hit["sections"]}:
        return {"title": hit["title"], "section": section}, ""
    ok, reason = citations.check(section, hit["body"], where=f"材料《{hit['title']}》正文")
    if ok:
        return {"title": hit["title"], "section": section}, ""
    return None, f"材料《{hit['title']}》溯源不成立：{reason}"


def material_ids_for_titles(db, subject_id: str, titles: list[str]) -> tuple[list[str], list[str]]:
    """D3：材料标题 → material_id（按首次出现序去重）；返回 ``(ids, 未找到的标题)``。"""
    by_title = {e["title"]: e["id"] for e in _entries_with_body(subject_id)}
    ids: list[str] = []
    missing: list[str] = []
    for t in titles:
        t = str(t or "").strip()
        if not t:
            continue
        mid = by_title.get(t)
        if mid is None:
            missing.append(t)
            continue
        if mid not in ids:
            ids.append(mid)
    return ids, missing


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
    "DEFAULT_INJECT_MAX_CHARS",
    "materials_dir",
    "get_policy",
    "set_policy",
    "add_material",
    "list_materials",
    "delete_material",
    "materials_summaries",
    "material_sections",
    "draft_materials",
    "check_unit_material",
    "material_ids_for_titles",
    "search_candidates",
    "select_candidates",
]
