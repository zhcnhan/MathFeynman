"""outline.materials：材料层基础（docs/14 §8 · Phase B B3；R37 教材真源化）。

- 本地导入：用户自有/授权文本 → 本地引用库（分节文本 + 来源标注，入库
  content/subjects/<sid>/materials/<slug>-<hash>.md）；
- 联网候选：search 返回候选清单（无网/未接检索后端时给提示）；select 将勾选候选
  （标题/来源/摘要）本地化入库为 web 引用——**不整本下载**；
- **R37 起（教材＝权威真源）**：
  - 注入默认**不设预算**（``MF_MATERIAL_INJECT_MAX_CHARS=0``＝不限）；按 ``bookmap`` 解析出的
    **章/节结构注入完整正文**，书太大时在章/页边界**结构化分段**（绝不"前 N 字"截断）；
  - 显式设置 ``MF_MATERIAL_INJECT_MAX_CHARS``/旧名 ``MF_OUTLINE_MATERIAL_MAX_CHARS`` > 0 时，
    沿用 R36 D4 的预算降级口径（截断留痕）——上限是**显式选择**，不再是默认；
  - 入库时检测**文本层健康度**（S7）：扫描/图片版 PDF 明确中文告知，不静默出稿；
  - 覆盖账本（S6）：章/节条目 ↔ 单元的映射由 ``coverage_ledger`` 统一算账。
来源策略 source_policy（ai|import|web|mixed，默认 ai）存 subjects.meta_json；
math（preset）同样支持（材料作讲解增强，不影响 roadmap 内容）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..config import get_settings, material_inject_budget
from ..outline import store as outline_store
from . import bookmap
from .schemas import OutlineError

POLICY_AI = "ai"
POLICY_IMPORT = "import"
POLICY_WEB = "web"
POLICY_MIXED = "mixed"
SOURCE_POLICIES = (POLICY_AI, POLICY_IMPORT, POLICY_WEB, POLICY_MIXED)
DEFAULT_POLICY = POLICY_AI

# ---------- R38 B2：材料角色（主教材 / 补充材料 / 未标注） ----------
# 说明：**未标注 ≠ 主教材**——未标注按导入顺序，覆盖账里注明"顺序依据：导入顺序"。
ROLE_MAIN = "main"
ROLE_SUPPLEMENT = "supplement"
ROLE_UNSET = ""
ROLES = (ROLE_MAIN, ROLE_SUPPLEMENT)
ROLE_LABELS_ZH = {ROLE_MAIN: "主教材", ROLE_SUPPLEMENT: "补充材料", ROLE_UNSET: "未标注"}

# ---------- R38 A1/A5：两个滑块（单次调用预算 / 总注入上限）的档位与内置默认 ----------
BATCH_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
INJECT_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
BUILTIN_BATCH_CHARS = 60000       # A5 内置默认：单次调用预算
BUILTIN_INJECT_MAX_CHARS = 0      # A2 内置默认：总注入上限＝不限（0）

_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
_PAGE_MARK = re.compile(r"^【第\s*(\d+)\s*页】\s*$", re.M)


def _slug(s: str) -> str:
    return _SLUG.sub("_", s).strip("_")[:32] or "doc"


def materials_dir(subject_id: str) -> Path:
    d = outline_store.subject_dir(subject_id) / "materials"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- R37 S7：文本层健康度（扫描/图片版 PDF 的诚实边界） ----------
THIN_CHARS_PER_PAGE = 40      # 每页平均字符数下限（低于此值视为"没提取到文字"）
MIN_PAGES_FOR_HEALTH = 5      # 页数过少（粘贴文本/短材料）不做扫描版判定
EMPTY_PAGE_CHARS = 20         # 单页字符数低于此值视为"空白页"


def text_health(body: str, *, min_chars_per_page: int | None = None,
                min_page_ratio: float | None = None) -> dict:
    """材料文本层健康度（每页字符数 / 空白页占比）→ 中文结论。

    - 页数 < ``MIN_PAGES_FOR_HEALTH``（粘贴短文本）→ 不做扫描版判定，如实标注"未判定"；
    - 页数 ≥ 3 且（每页平均字符数 < 下限 或 有文字页占比 < 下限）→ ``healthy=False``，
      note 直接给用户可执行的下一步（OCR / 换文本版），**不含糊**。
    """
    s = get_settings()
    cap = THIN_CHARS_PER_PAGE if min_chars_per_page is None else min_chars_per_page
    ratio = 0.5 if min_page_ratio is None else min_page_ratio
    text = body or ""
    marks = _PAGE_MARK.findall(text)
    pages = len(marks) if marks else 1
    chars = len(text.strip())
    per_page = chars / pages if pages else 0
    nonempty = 0
    if marks:
        parts = re.split(r"(?m)^【第\s*\d+\s*页】\s*$", text)
        nonempty = sum(1 for p in parts if len(p.strip()) >= EMPTY_PAGE_CHARS)
    else:
        nonempty = 1 if chars >= EMPTY_PAGE_CHARS else 0
    text_ratio = (nonempty / pages) if pages else 0.0
    if pages < MIN_PAGES_FOR_HEALTH:
        return {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
                "text_page_ratio": round(text_ratio, 2), "healthy": True, "checked": False,
                "note": "页数过少，未做扫描版判定（粘贴文本按可用处理）"}
    healthy = per_page >= cap and text_ratio >= ratio
    note = "" if healthy else (
        f"本书疑似扫描/图片版：{pages} 页仅提取到 {chars} 个字符"
        f"（每页约 {per_page:.0f} 字，下限 {cap}；有文字页 {nonempty}/{pages}）。"
        "请先 OCR 或改用文本版 PDF/粘贴文本后重新上传——"
        "系统不会在「没读到书」的情况下生成大纲（R37 S7）。"
    )
    return {"pages": pages, "chars": chars, "chars_per_page": round(per_page, 1),
            "text_page_ratio": round(text_ratio, 2), "healthy": healthy, "checked": True,
            "note": note}


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
    R37 S7：入库时计算文本层健康度并写入 frontmatter（扫描版 → 中文告知，见 ``text_health``）。
    """
    title = title.strip()
    text = text.strip()
    if not title or not text:
        raise OutlineError("材料标题与正文不能为空")
    effective_kind = kind or ("web" if url else "local")
    if effective_kind not in ("local", "web", "pdf"):
        raise OutlineError(f"材料 kind 非法: {effective_kind!r}")
    health = text_health(text)
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
        # R37 S7：健康度（明确结论 + 中文说明；扫描版在此留痕，供列表/起草闸门读取）
        meta_lines += [
            f"text_healthy: {'yes' if health['healthy'] else 'no'}",
            f"text_pages: {health['pages']}",
            f"chars_per_page: {health['chars_per_page']}",
        ]
        meta_lines += ["", "---", ""]
        p.write_text("\n".join(meta_lines) + "\n" + text + "\n", encoding="utf-8")
    return {"id": entry_id, "title": title, "source": source, "url": url,
            "kind": effective_kind, "file": p.name,
            "filename": filename or p.name, "text_health": health}


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
            healthy_raw = str(fm.get("text_healthy", "")).strip().lower()
            role_raw = str(fm.get("role", "")).strip().lower()
            return {
                "id": fm.get("id", p.stem),
                "title": fm.get("title", p.stem),
                "source": fm.get("source", "本地导入"),
                "url": fm.get("url", ""),
                "kind": fm.get("kind", "local"),
                "file": p.name,
                "filename": fm.get("filename", ""),
                "body": body,
                # R37 S7：入库时算的健康度（老材料没有该字段 → 现算一次，不让历史材料失去判定）
                "text_healthy": (healthy_raw != "no") if healthy_raw else None,
                # R38 B2：材料角色（main=主教材 / supplement=补充材料）；老材料无该字段
                # → 视为"未标注"（按导入顺序，覆盖账里注明）
                "role": role_raw if role_raw in ("main", "supplement") else "",
            }
    return None


def list_materials(db, subject_id: str) -> list[dict]:
    d = materials_dir(subject_id)
    out = []
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e:
            health = text_health(e.get("body", ""))
            if e.get("text_healthy") is False:
                health["healthy"] = False
            out.append({"id": e["id"], "title": e["title"], "source": e["source"],
                        "url": e["url"], "kind": e["kind"], "file": e["file"],
                        "filename": e.get("filename", ""),
                        # R38 B2：材料角色（未标注 → main 并标注 explicit=False，按导入顺序）
                        "role": e.get("role") or ROLE_UNSET,
                        "role_explicit": bool(e.get("role")),
                        "role_zh": ROLE_LABELS_ZH.get(e.get("role") or ROLE_UNSET),
                        "text_health": health})
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
    """**R36 遗留口径**（每份材料正文前 ``limit_chars`` 字摘要）——R37 起**不再用于注入**。

    保留仅为兼容既有调用/演示（材料列表摘要）；教材注入一律走 ``draft_materials``/``unit_material_pack``
    的**完整正文**路径（R37 S1：不用"前 N 字"糊弄）。
    """
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

DEFAULT_INJECT_MAX_CHARS = 0      # R37 S1：默认**不限**（0＝不设预算；旧值 6000 属 R36 D4 口径）
LEGACY_SECTION_CHARS = 400        # 每节摘要字符上限（**仅在显式设上限时**的降级口径）
MAX_SECTIONS_PER_MATERIAL = 12    # 每份材料最多展示的节数（同上，仅降级口径）
DEFAULT_BATCH_CHARS = 60000       # R37 S1：单次调用的结构化分段阈值（按章/页边界切，不截断）

_HEADING_MARK = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def inject_budget() -> int:
    """生效的注入上限（0 = 不限）；见 ``config.material_inject_budget``。"""
    return material_inject_budget()


def batch_budget() -> int:
    """单次调用的结构化分段阈值（字符）；0 = 不分段。"""
    return max(0, int(get_settings().material_batch_chars or 0))


def _entries_with_body(subject_id: str) -> list[dict]:
    """材料条目（含正文 body）——服务端校验/注入用；对外 API 不下发正文。"""
    out = []
    for p in sorted(materials_dir(subject_id).glob("*.md")):
        e = _parse_entry(p)
        if e:
            out.append(e)
    return out


def material_sections(body: str, *, max_sections: int = MAX_SECTIONS_PER_MATERIAL,
                      section_chars: int = LEGACY_SECTION_CHARS) -> list[dict]:
    """把材料正文切成"可引用的节"：PDF 的 `【第 N 页】` → Markdown 标题 → 段落兜底。

    返回 ``[{label, text}]``：label＝章节名（第 N 页 / 标题 / 第 N 节）。
    text 已按 ``section_chars`` 截断——**仅用于显式设上限时的降级口径**（R36 D4）；
    R37 默认路径用 ``bookmap`` 的章/节**完整正文**（见 ``material_structure``）。
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


def material_structure(body: str) -> dict:
    """R37 S1/S2/S8：材料正文 → **章 → 节**结构（完整正文，不截断）。

    返回 ``{"kind", "note", "entries": [MapEntry], "chapter_map": [dict]}``；
    解析器是 ``outline.bookmap``（唯一实现；大纲起草与单元出稿共用同一份地图）。
    """
    parsed = bookmap.parse_book(body or "")
    entries = parsed["entries"]
    return {
        "kind": parsed["kind"],
        "note": parsed["note"],
        "pages": parsed.get("pages", 0),
        "entries": entries,
        "chapter_map": bookmap.chapter_map(entries),
    }


def _material_index(db, subject_id: str) -> list[dict]:
    """材料索引（服务端用）：正文 + 章/节结构 + 健康度 + 角色（R38 B2）。"""
    out = []
    for e in _entries_with_body(subject_id):
        body = e.get("body", "")
        structure = material_structure(body)
        health = text_health(body)
        if e.get("text_healthy") is False:
            health["healthy"] = False
        role = str(e.get("role") or "")
        out.append({
            "id": e["id"], "title": e["title"], "source": e["source"], "url": e["url"],
            "kind": e.get("kind", "local"), "filename": e.get("filename", ""),
            "body": body, "sections": material_sections(body),
            "structure": structure, "text_health": health,
            "role": role or ROLE_UNSET, "role_explicit": bool(role),
        })
    return out


def _full_blocks(index: list[dict]) -> list[dict]:
    """R37 S1 默认口径：每份材料按章/节**完整正文**成块（不截断、不摘要）。"""
    blocks: list[dict] = []
    for m in index:
        if not m["text_health"]["healthy"]:
            continue
        for entry in m["structure"]["entries"]:
            secs = "；".join(entry.sections[:12])
            head = (f"#### [{entry.label}]（材料《{m['title']}》"
                    f"{'，节：' + secs if secs else ''}）")
            blocks.append({"material": m["title"], "material_id": m["id"],
                           "label": entry.label, "text": f"{head}\n{entry.text}",
                           "chars": entry.chars})
    return blocks


def draft_materials(db, subject_id: str, *, max_chars: int | None = None,
                    batch_chars: int | None = None,
                    inject_max_chars: int | None = None) -> dict:
    """D1（R36）＋ S1/S2/S8（R37）＋ **R38 S1/S2/S3/S4**：大纲起草的**材料注入包**（唯一入口）。

    返回:
    - ``text``：**首批**注入 prompt 的材料块（多批时见 ``batches``）；
    - ``index``：``[{id,title,source,url,body,sections,structure,text_health,role}]``
      ——**服务端校验用**（含正文与章/节地图，不下发前端）；
    - ``chapter_map``：整本书的章 → 节地图（**跨全部材料合并**；每条注明来自哪份材料）；
    - ``batches``：结构化分批（每批 ``text`` 完整可注入；按章/页边界切，**绝不截断句子**）；
    - ``used_chars``：全部批次注入的字符总量（**随书规模增长**；=0 时确实不限）；
    - ``per_call_chars``：**单次调用**的注入预算（生效值）；
    - ``budget``：``{batch_chars, inject_max_chars, batch_source, inject_source}``
      ——两个滑块的**生效值与来源**（"你设定的"/"默认"，R38 A1 必显）；
    - ``usage``：``{used_chars, batches, per_material:[…], blocked, truncated, dropped, order_basis}``
      ——**上一轮实际注入总量与批次数** + 逐材料吸纳明细（R38 A1/B1）；
    - ``dropped``：**恒为空**（R37/R38 §3 ＋ R39 铁则：**任何情况都不得静默丢材料/章节**）；
    - ``blocked``：健康度不合格（扫描/图片版）而被挡下的材料 ``[{title, note}]``（S7）；
    - ``ledger``：本次就地账目（**就地提示**通道；同时已落总账）。

    预算纪律（R37＋R38 §3 ＋ **R42 A**）：
    - **滑块 A（单次调用预算）**：默认不省成本，书太大按 ``MF_MATERIAL_BATCH_CHARS`` 在章/页边界
      分批；**调小只分更多批，绝不丢章节**（``dropped`` 恒空、覆盖账不变）；
    - **滑块 B（总注入上限 `MF_MATERIAL_INJECT_MAX_CHARS`）**：**真硬上限**（R41 §3-① 裁定）——
      跨批次累计注入字符，到顶后**在章/节边界停止**，剩余章节**整条不注入**，
      每一处未注入都进账本（中文原因）+ 进 ``usage.not_injected``（``reason=总注入上限``）；
      默认 0 = 不限，此时**行为与 R38 逐字一致**；
    - R38 A4 安全阀：按"字符 ≈ token"粗估，若**将超过模型上下文窗口** → 不硬发，改为**自动分批**
      并中文说明"本书较大，已分 N 批处理"（**任何情况不得静默失败**）。
    """
    from ..service import ledger

    budget = resolve_budget(db, subject_id, batch_chars=batch_chars,
                            inject_max_chars=(inject_max_chars if inject_max_chars is not None
                                              else max_chars))
    max_chars = int(budget["inject_max_chars"])
    per_call = int(budget["per_call_chars"])
    batch_chars = int(budget["batch_chars"])
    index = _ordered(_material_index(db, subject_id))
    blocked = [{"title": m["title"], "note": m["text_health"]["note"]}
               for m in index if not m["text_health"]["healthy"]]
    for b in blocked:  # R39 §1：被挡下的材料**必须显性**（不是只在 prompt 里提一句）
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{b['title']}》",
            "该材料**未被注入**（文本层健康度不合格，疑似扫描/图片版）：" + str(b["note"] or ""),
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "material_blocked", "title": b["title"]},
        )
    blocks = _full_blocks(index)
    # R38 A4 安全阀：单次调用预算再受"模型上下文硬上限"约束（超了自动分批，不硬发）
    valve = context_valve(db, batch_chars=per_call, blocks=blocks)
    if valve["applied"]:
        ledger.note(
            ledger.CAT_MATERIAL, "材料注入（安全阀）",
            f"本书较大，已分 {valve['batch_count']} 批处理：按「字符≈token」粗估，"
            f"单次调用最多 ~{valve['limit_chars']} 字（模型上下文硬上限 {valve['context_tokens']} token），"
            "不截断正文、不漏章节",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
            detail={"kind": "context_valve", **{k: valve[k] for k in
                                                ("limit_chars", "context_tokens", "batch_count")}},
        )
    batches = valve["batches"]
    # **R42 A：滑块 B「总注入上限」＝真硬上限**（架构侧 R41 §3-①）——
    # 跨批次累计到顶后**在章/节边界停止**，剩余章节整条不注入；每一处未注入都记账 + 进 not_injected。
    # ⚠️ cap=0（默认/不限）时不改变任何行为（与 R38 逐字一致）。
    batches, cap_skipped, cap_info = _apply_inject_cap(batches, max_chars, subject_id)
    if cap_info["configured"]:
        _note_inject_cap_skips(cap_skipped, index, cap_info, subject_id)
    used = sum(len(b["text"]) for b in batches)
    # R38 B1：任何**未被注入**的章/节都显式列出（含健康度挡下、未进批次、**因总上限跳过**三种原因）
    unmapped = _unmapped_entries(index, blocks) + _cap_skip_entries(cap_skipped, index)
    for u in unmapped:
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{u['material']}》· {u['label']}",
            (u.get("reason_zh") or "该章/节**未被注入任何批次**（不在任何材料块里）")
            + ("：" + str(u.get("note") or "") if u.get("note") else ""),
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "entry_not_injected", **u},
        )
    if not index:
        ledger.note(ledger.CAT_MATERIAL, "材料注入", "本学科没有引用材料：本次按 brief 起草（无教材依据）",
                    impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                    detail={"kind": "no_material"})
    per_material = _per_material_usage(index, batches)
    cap_detail = {
        "configured": bool(cap_info.get("configured")),
        "cap": int(cap_info.get("cap") or 0),
        "used_chars": int(cap_info.get("used_chars") or 0),
        "remaining": int(cap_info.get("remaining") or 0),
        # **R42 A3-⑤：预算视图必须能显示"因总上限未注入的章节数"**（不许两处都没有）
        "skipped_count": int(cap_info.get("skipped_count") or 0),
        "skipped_batches": int(cap_info.get("skipped_batches") or 0),
        "skipped_chars": int(cap_info.get("skipped_chars") or 0),
        "skipped_labels": list(cap_info.get("skipped_labels") or []),
        "first_batch_over_cap": bool(cap_info.get("first_batch_over_cap")),
        "skipped_by_material": _cap_skips_by_material(cap_skipped, index),
    }
    usage = {
        "used_chars": used, "batches": len(batches),
        "injected_chars_per_batch": [len(b["text"]) for b in batches],
        "per_material": per_material,
        "blocked": blocked, "not_injected": unmapped,
        "truncated": False, "dropped": [],
        "order_basis": order_basis(index),
        "inject_cap": cap_detail,
        "context_valve": {"applied": bool(valve["applied"]), "limit_chars": valve["limit_chars"],
                          "context_tokens": valve["context_tokens"]},
    }
    pack = {"text": batches[0]["text"] if batches else "", "used_chars": used,
            "dropped": [], "truncated": False, "batches": batches, "blocked": blocked,
            "per_call_chars": int(budget["per_call_chars"]), "batch_count": len(batches),
            "budget": budget, "usage": usage,
            "ledger": ledger.current().to_list() if ledger.current() else []}
    pack.update({
        "index": index,
        "chapter_map": [{"material_id": m["id"], "material": m["title"],
                         "role": m.get("role") or (ROLE_MAIN if m.get("role_explicit") else ROLE_UNSET),
                         "role_explicit": bool(m.get("role_explicit")),
                         "kind": m["structure"]["kind"], "note": m["structure"]["note"],
                         "entries": m["structure"]["chapter_map"]} for m in index],
        "count": len(index),
        "inject_max_chars": max_chars,
        "batch_chars": batch_chars,
    })
    return pack


ROLE_MAIN = "main"                # 主教材（定顺序与范围）
ROLE_SUPPLEMENT = "supplement"    # 补充材料（只补细节与例题）
ROLE_UNSET = ""                   # 未标注（**不等于主教材**：按导入顺序，覆盖账注明）
ROLES = (ROLE_MAIN, ROLE_SUPPLEMENT)
ROLE_LABELS_ZH = {ROLE_MAIN: "主教材", ROLE_SUPPLEMENT: "补充材料", ROLE_UNSET: "未标注"}

BATCH_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
INJECT_TIERS = (("省着用", 20000), ("常规（默认）", 60000), ("充裕", 150000), ("不限", 0))
BUILTIN_BATCH_CHARS = 60000       # A5 内置默认：单次调用预算
BUILTIN_INJECT_MAX_CHARS = 0      # A2 内置默认：总注入上限＝不限（0）


def _env_int(name: str) -> int | None:
    """环境变量里的非负整数（未设/非法 → None，**不静默当 0**）。"""
    import os

    raw = os.getenv(name)
    if raw in (None, ""):
        return None
    try:
        v = int(str(raw).strip())
    except ValueError:
        return None
    return max(0, v)


def subject_budget(db, subject_id: str) -> dict:
    """学科（滑块）里显式设过的值；``source`` ∈ subject / env / builtin。"""
    row = outline_store.get_subject(db, subject_id)
    meta = dict((row.meta_json if row is not None else None) or {})
    out: dict = {"batch_chars": None, "inject_max_chars": None, "source": "builtin"}
    b = meta.get("material_batch_chars")
    i = meta.get("material_inject_max_chars")
    if b is not None and str(b) != "":
        try:
            out["batch_chars"] = max(0, int(b))
        except (TypeError, ValueError):
            out["batch_chars"] = None
    if i is not None and str(i) != "":
        try:
            out["inject_max_chars"] = max(0, int(i))
        except (TypeError, ValueError):
            out["inject_max_chars"] = None
    if out["batch_chars"] is not None or out["inject_max_chars"] is not None:
        out["source"] = "subject"
    return out


def resolve_budget(db, subject_id: str, *, batch_chars: int | None = None,
                   inject_max_chars: int | None = None) -> dict:
    """A5 优先级：**单次请求参数 > 学科滑块 > .env > 内置默认**（逐项解析，来源可查）。

    返回 ``{batch_chars, inject_max_chars, per_call_chars, batch_source, inject_source}``。
    非法值（负数以外的怪值）由 API 层转**中文 422**；这里只做兜底解析（负 → 0）。
    """
    subj = subject_budget(db, subject_id)
    env_b = _env_int("MF_MATERIAL_BATCH_CHARS")
    env_i = _env_int("MF_MATERIAL_INJECT_MAX_CHARS")
    if env_i is None:
        env_i = _env_int("MF_OUTLINE_MATERIAL_MAX_CHARS")
    if batch_chars is not None:
        eff_b, src_b = max(0, int(batch_chars)), "request"
    elif subj["batch_chars"] is not None:
        eff_b, src_b = int(subj["batch_chars"]), "subject"
    elif env_b is not None:
        eff_b, src_b = env_b, "env"
    else:
        eff_b, src_b = BUILTIN_BATCH_CHARS, "builtin"
    if inject_max_chars is not None:
        eff_i, src_i = max(0, int(inject_max_chars)), "request"
    elif subj["inject_max_chars"] is not None:
        eff_i, src_i = int(subj["inject_max_chars"]), "subject"
    elif env_i is not None:
        eff_i, src_i = env_i, "env"
    else:
        eff_i, src_i = BUILTIN_INJECT_MAX_CHARS, "builtin"
    # R38 §3 共存口径：**单次调用预算**与**总注入上限**是两个概念——
    # - 单次调用预算 = 滑块 A（批量阈值）；A=0（不限）时再退回总上限；
    # - 总注入上限（滑块 B / 显式 env，>0）= **跨批次的累计上限**（见 ``draft_materials`` 的
    #   ``remaining`` 递减），R38 A1 说它是"想设花费天花板的用户"用的；
    # - ⚠️ 滑块 A **不得为了让总上限生效而被放大**：A=0 是"不限"，不是"每次装 60000"。
    if eff_b > 0:
        per_call = eff_b if eff_i <= 0 else min(eff_i, eff_b)
    else:
        per_call = eff_i  # A=不限 → 由 A4 安全阀兜底
    return {
        "batch_chars": eff_b, "inject_max_chars": eff_i, "per_call_chars": per_call,
        "batch_source": src_b, "inject_source": src_i,
        "batch_source_zh": SOURCE_LABELS_ZH.get(src_b, src_b),
        "inject_source_zh": SOURCE_LABELS_ZH.get(src_i, src_i),
    }


SOURCE_LABELS_ZH = {
    "request": "本次请求参数",
    "subject": "你设定的（本学科）",
    "env": ".env 配置",
    "builtin": "默认",
}


def set_budget(db, subject_id: str, *, batch_chars: int | None = None,
               inject_max_chars: int | None = None) -> dict:
    """写入学科滑块（复用 ``subjects.meta_json``，**不新建表**）；非法值 → ``OutlineError``（中文 422）。"""
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    meta = dict(row.meta_json or {})
    if batch_chars is not None:
        meta["material_batch_chars"] = _validate_budget("单次调用预算", batch_chars)
    if inject_max_chars is not None:
        meta["material_inject_max_chars"] = _validate_budget("总注入上限", inject_max_chars)
    row.meta_json = meta
    db.commit()
    from ..service import ledger

    ledger.note(
        ledger.CAT_MATERIAL, f"材料注入预算（学科 {subject_id}）",
        "用户调整了材料注入预算滑块：单次调用预算="
        + _budget_zh(meta.get("material_batch_chars")) + "，总注入上限="
        + _budget_zh(meta.get("material_inject_max_chars"))
        + "。调小单次预算**只是分成更多批，不会少学章节**（覆盖账不变）",
        impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
        detail={"batch_chars": meta.get("material_batch_chars"),
                "inject_max_chars": meta.get("material_inject_max_chars")},
    )
    return budget_view(db, subject_id)


def _validate_budget(label: str, value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise OutlineError(f"{label}非法：{value!r}（必须是整数，单位＝字符；0 = 不限）") from e
    if v < 0:
        raise OutlineError(f"{label}非法：{v}（不能为负数；0 = 不限）")
    if v > 5_000_000:
        raise OutlineError(f"{label}非法：{v}（上限 5,000,000 字符；0 = 不限）")
    return v


def _budget_zh(v) -> str:
    if v is None or str(v) == "":
        return "（未设，用默认）"
    return "不限" if int(v) == 0 else f"{int(v):,} 字符"


def budget_view(db, subject_id: str) -> dict:
    """R38 A1 必显数据（**R42 A3-⑤ 增补**）：两档当前值 + 来源 + 上一轮实际注入总量/批次数
    + **因总注入上限未注入的章节数** + 逐材料明细。

    ⚠️ **两个滑块的承诺不同**（R42 A1，界面必须分开写清）：
    滑块 A 调小只是分更多批（不丢章节）；滑块 B 是**真上限**（超了就真的不注入，但明说哪些没进去）。
    """
    eff = resolve_budget(db, subject_id)
    index = _material_index(db, subject_id)
    blocks = _full_blocks(index)
    valve = context_valve(db, batch_chars=int(eff["per_call_chars"]), blocks=blocks)
    keep, skipped, cap = _apply_inject_cap(valve["batches"], int(eff["inject_max_chars"]), subject_id)
    used = sum(len(b["text"]) for b in keep)
    row = outline_store.get_subject(db, subject_id)
    meta = dict((row.meta_json if row is not None else None) or {})
    return {
        "subject_id": subject_id,
        "batch_chars": {"value": int(eff["batch_chars"]), "source": eff["batch_source"],
                        "source_zh": eff["batch_source_zh"],
                        "set": meta.get("material_batch_chars")},
        "inject_max_chars": {"value": int(eff["inject_max_chars"]), "source": eff["inject_source"],
                             "source_zh": eff["inject_source_zh"],
                             "set": meta.get("material_inject_max_chars")},
        "per_call_chars": int(eff["per_call_chars"]),
        "tiers": {
            "batch": [{"label": lb, "value": v} for lb, v in BATCH_TIERS],
            "inject": [{"label": lb, "value": v} for lb, v in INJECT_TIERS],
        },
        # R42 A1：两个滑块各自的承诺（前端直接渲染，**不许**一句话糊两个滑块）
        "promises_zh": {
            "batch_chars": "调小「单次调用预算」→ 只是分更多批，**一个章节都不会少学**"
                           "（丢弃恒空、覆盖账不变）",
            "inject_max_chars": "「总注入上限」是**真上限**：超了就真的不再注入，"
                                "但**每一处没进去的章节都会被明确列出 + 中文原因**",
        },
        "last_usage": {
            "used_chars": used,
            "batch_count": len(keep),
            "per_material": _per_material_usage(index, keep, skipped),
            "truncated": False,
            "dropped": [],
            "order_basis": order_basis(index),
            "summary_zh": (f"共注入 {used:,} 字，分 {len(keep)} 批"
                           if keep else "尚无材料可注入"),
            # R42 A2：因总注入上限未注入的章节数（**不许两处都没有**）
            "cap_skipped_count": int(cap.get("skipped_count") or 0),
            "cap_skipped_labels": list(cap.get("skipped_labels") or []),
            "cap_skipped_by_material": _cap_skips_by_material(skipped, index),
            "note_zh": "调小「单次调用预算」只会分成更多批，**不会少学章节**（覆盖账不变）",
            "cap_note_zh": (
                f"因「总注入上限」{int(cap.get('cap') or 0):,} 字已用完，本教材有 "
                f"{int(cap.get('skipped_count') or 0)} 章/节**未纳入**（已在下方向你列明）"
                if int(cap.get("skipped_count") or 0) else ""),
        },
        "inject_cap": {
            "configured": bool(cap.get("configured")),
            "cap": int(cap.get("cap") or 0),
            "used_chars": int(cap.get("used_chars") or 0),
            "remaining": int(cap.get("remaining") or 0),
            "skipped_count": int(cap.get("skipped_count") or 0),
            "skipped_chars": int(cap.get("skipped_chars") or 0),
            "skipped_labels": list(cap.get("skipped_labels") or []),
            "skipped_by_material": _cap_skips_by_material(skipped, index),
            "first_batch_over_cap": bool(cap.get("first_batch_over_cap")),
        },
        "context_valve": {"applied": bool(valve["applied"]), "context_tokens": valve["context_tokens"],
                          "limit_chars": valve["limit_chars"]},
        "materials": [{"id": m["id"], "title": m["title"], "role": m.get("role") or ROLE_UNSET,
                       "role_explicit": bool(m.get("role_explicit")),
                       "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
                       "healthy": m["text_health"]["healthy"], "chars": len(m.get("body") or ""),
                       "entries": len((m["structure"] or {}).get("entries") or []),
                       "note": m["text_health"]["note"]} for m in index],
        "not_injected": _unmapped_entries(index, blocks) + _cap_skip_entries(skipped, index),
    }


def set_material_role(db, subject_id: str, material_id: str, role: str) -> dict:
    """R38 B2：标主教材 / 补充材料（写入材料 frontmatter；主教材定顺序与范围）。"""
    if role not in ROLES:
        raise OutlineError(f"材料角色非法：{role!r}（∈ {ROLES}）")
    d = materials_dir(subject_id)
    hit = None
    for p in sorted(d.glob("*.md")):
        e = _parse_entry(p)
        if e and e["id"] == material_id:
            hit = (p, e)
            break
    if hit is None:
        raise OutlineError(f"材料不存在: {material_id}")
    p, _ = hit
    raw = p.read_text(encoding="utf-8")
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        head = raw[4:end]
        body = raw[end + 4:]
        lines = [ln for ln in head.splitlines() if not ln.strip().startswith("role:")]
        lines.append(f"role: {role}")
        p.write_text("---\n" + "\n".join(lines) + "\n---" + body, encoding="utf-8")
    from ..service import ledger

    ledger.note(ledger.CAT_MATERIAL, f"材料《{hit[1]['title']}》",
                f"用户把该材料标为「{ROLE_LABELS_ZH[role]}」"
                + ("（主教材定顺序与范围）" if role == ROLE_MAIN else "（只补细节与例题）"),
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                detail={"material_id": material_id, "role": role})
    return {"material_id": material_id, "role": role, "role_zh": ROLE_LABELS_ZH[role]}


def order_basis(index: list[dict]) -> str:
    """R38 B2：顺序依据——有显式角色按角色（主教材在前），否则按**导入顺序**并注明。"""
    if any(m.get("role_explicit") for m in index):
        return "角色（主教材定顺序与范围，补充材料只补细节与例题）"
    return "导入顺序"


def _ordered(index: list[dict]) -> list[dict]:
    """按"主教材在前 + 导入顺序"排序（无显式角色 → 纯导入顺序，不改行为）。"""
    if not any(m.get("role_explicit") for m in index):
        return list(index)
    return sorted(index, key=lambda m: 0 if (m.get("role_explicit") and m.get("role") == ROLE_MAIN) else 1)


def _per_material_usage(index: list[dict], batches: list[dict],
                        skipped: list[dict] | None = None) -> list[dict]:
    """逐材料吸纳明细（注入了多少字 / 几批 / 哪些章进了批次 / **哪些因总上限被跳过**）。"""
    label_to_material: dict[str, str] = {}
    for m in index:
        for e in (m["structure"] or {}).get("entries") or []:
            label_to_material[str(e.label)] = m["title"]
    batch_of: dict[str, set[int]] = {m["title"]: set() for m in index}
    for i, b in enumerate(batches):
        for lab in b.get("labels") or []:
            title = label_to_material.get(str(lab))
            if title:
                batch_of.setdefault(title, set()).add(i + 1)
    skipped_of: dict[str, list[str]] = {m["title"]: [] for m in index}
    for b in skipped or []:
        for src in _block_sources(b):
            title = str(src.get("material") or "")
            if not title:
                title = label_to_material.get(str(src.get("label") or ""), "")
            if title:
                skipped_of.setdefault(title, []).append(str(src.get("label") or ""))
    out = []
    for m in index:
        ent = (m["structure"] or {}).get("entries") or []
        chars_total = len(m.get("body") or "")
        skipped_labels = skipped_of.get(m["title"]) or []
        out.append({
            "material_id": m["id"], "title": m["title"],
            "role": m.get("role") or ROLE_UNSET,
            "role_explicit": bool(m.get("role_explicit")),
            "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
            "chars_total": chars_total,
            "entries_total": len(ent),
            "entries_chars_total": sum(int(e.chars) for e in ent),
            "batches": sorted(batch_of.get(m["title"]) or []),
            "injected": m["text_health"]["healthy"] and not skipped_labels,
            "blocked_reason": "" if m["text_health"]["healthy"] else m["text_health"]["note"],
            # R42：因**总注入上限**跳过的章/节（按材料分组，供界面就地展示）
            "cap_skipped": skipped_labels,
            "cap_skipped_count": len(skipped_labels),
        })
    return out


def _unmapped_entries(index: list[dict], blocks: list[dict]) -> list[dict]:
    """**未被注入任何批次**的章/节（R38 B1：必须显式列出，不许只在 prompt 尾部提一句）。"""
    in_blocks = {(str(b.get("material_id") or ""), str(b.get("label") or "")) for b in blocks}
    out: list[dict] = []
    for m in index:
        if not m["text_health"]["healthy"]:
            out.append({"material": m["title"], "material_id": m["id"],
                        "label": "（整份材料）", "chars": len(m.get("body") or ""),
                        "note": "该材料未通过文本层健康度检查，整份未注入"})
            continue
        for e in (m["structure"] or {}).get("entries") or []:
            if (str(m["id"]), str(e.label)) not in in_blocks:
                out.append({"material": m["title"], "material_id": m["id"], "label": e.label,
                            "chars": int(e.chars), "note": "该章/节未进入任何注入批次"})
    return out


def estimate_tokens(chars: int) -> int:
    """R38 A4：按「字符 ≈ token」粗估（保守口径——宁可不发也不发不可能成功的请求）。"""
    return max(0, int(chars or 0))


def context_valve(db, *, batch_chars: int, blocks: list[dict]) -> dict:
    """R38 A4 **安全阀**：单次调用不得越过模型上下文硬上限；超了自动分批 + 中文说明。

    返回 ``{"applied", "limit_chars", "context_tokens", "batches", "batch_count"}``。
    - 有效预算 = ``min(用户单次预算, 上下文可容纳字符)``（0/不限 → 取上下文可容纳量）；
    - 单块自身仍超上限时：先在**页边界**切（``bookmap.split_entries``，不切断句子）；
      仍超 → 自成一批并**记账**（"单章超上下文"），绝不静默截断。
    """
    s = get_settings()
    ctx = max(0, int(getattr(s, "context_token_limit", 0) or 0))
    # 预留：prompt 模板 + 地图 + 输出（按上下文 45% 或固定 8k 中取小，避免把窗口吃满）
    reserve = min(max(2048, ctx // 5), 40000) if ctx else 0
    limit = max(0, ctx - reserve) if ctx else 0
    applied = False
    eff_batch = int(batch_chars or 0)
    if ctx and limit and (eff_batch <= 0 or eff_batch > limit):
        eff_batch = limit
        applied = True
    blocks2 = list(blocks)
    oversized: list[dict] = []
    if ctx and limit:
        from . import bookmap

        split: list[dict] = []
        for b in blocks2:
            if len(str(b.get("text") or "")) <= limit:
                split.append(b)
                continue
            parts = _split_block_at_pages(b, limit)
            if parts:
                split.extend(parts)
                applied = True
            else:
                oversized.append(b)
                split.append(b)
        blocks2 = split
    batches = _make_batches(blocks2, eff_batch)
    if oversized:
        from ..service import ledger

        for b in oversized[:5]:
            ledger.note(
                ledger.CAT_MATERIAL, f"材料《{b.get('material', '')}》· {b.get('label', '')}",
                f"该章/节自身约 {len(str(b.get('text') or '')):,} 字，超过单次调用上下文硬上限"
                f"（~{limit:,} 字）：已**独立成批**（不截断、不丢弃），建议调大模型上下文或拆分该章",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM,
                detail={"kind": "block_over_context", "chars": len(str(b.get("text") or "")),
                        "limit": limit},
            )
    return {"applied": applied, "limit_chars": limit, "context_tokens": ctx,
            "batches": batches, "batch_count": len(batches),
            "oversized_blocks": len(oversized)}


def _split_block_at_pages(block: dict, limit: int) -> list[dict]:
    """把超上限的块在**页边界**切成多块（不截断句子）；页结构对不上 → 返回空（调用方另行记账）。"""
    from . import bookmap

    pages = bookmap.PAGE_MARK.findall(str(block.get("text") or ""))
    if len(pages) <= 1:
        return []
    entry = bookmap.MapEntry(label=str(block.get("label") or ""),
                             text=str(block.get("text") or ""),
                             pages=[f"第 {n} 页" for n in pages])
    parts = bookmap.split_entries([entry], max_chars=limit)
    if len(parts) <= 1:
        return []
    return [{"material": block.get("material", ""), "material_id": block.get("material_id", ""),
             "label": p.label, "text": f"#### [{p.label}]（材料《{block.get('material', '')}》）\n{p.text}",
             "chars": p.chars} for p in parts]


def _apply_inject_cap(batches: list[dict], inject_max_chars: int,
                      subject_id: str) -> tuple[list[dict], list[dict], dict]:
    """**R42 A（架构侧 R41 §3-① 裁定）**：滑块 B「总注入上限」＝**真硬上限**。

    与滑块 A 的承诺**不同**（这是本批最重要的一句话）：

    - **滑块 A（单次调用预算）**：调小 → 只是分更多批，**绝不丢章节**（``dropped`` 恒空、覆盖账不变）；
    - **滑块 B（总注入上限）**：**是真上限**——跨批次累计正文注入字符，到达上限后**在章/节边界停止**，
      剩余章节**整条不注入**；但**每一处未注入都必须在账本里有中文原因 + 覆盖账显式列出**
      （不许静默截断、不许"名不副实地不封顶"）。

    口径：
    - 累计量＝已装入批次的 ``len(text)`` 之和（跨批次递增）；
    - 触顶后**不再装入**后续批次——按章/节边界整条停，**绝不在句子中间截断**；
    - 首批总是装入（单个章/节是原子单位；宁可不截断，也不"设了上限就一章都不给"）；
    - ``cap <= 0`` → 不限，**行为与 R38 逐字一致**（不动任何东西）。

    返回 ``(kept, skipped, info)``；``info`` 含 ``configured / cap / used_chars / remaining /
    skipped_count / skipped_chars / skipped_labels / first_batch_over_cap``。
    """
    cap = int(inject_max_chars or 0)
    if cap <= 0:
        return list(batches), [], {"configured": False, "cap": 0,
                                   "used_chars": sum(len(str(b.get("text") or "")) for b in batches),
                                   "remaining": -1, "skipped_count": 0, "skipped_chars": 0,
                                   "skipped_labels": [], "first_batch_over_cap": False}
    kept: list[dict] = []
    skipped: list[dict] = []
    used = 0
    for b in batches:
        blen = len(str(b.get("text") or ""))
        # 首批无条件装入（章/节是原子单位：宁可不截断，也不"一章都不给"）
        if not kept or used + blen <= cap:
            kept.append(b)
            used += blen
            continue
        skipped.append(b)
    skipped_chars = sum(len(str(b.get("text") or "")) for b in skipped)
    skipped_labels = [_block_labels(b) for b in skipped]
    skipped_labels = [lb for group in skipped_labels for lb in group]
    first_over = bool(kept) and used > cap
    info = {"configured": True, "cap": cap, "used_chars": used,
            "remaining": max(0, cap - used), "skipped_count": len(skipped_labels),
            "skipped_batches": len(skipped), "skipped_chars": skipped_chars,
            "skipped_labels": skipped_labels, "first_batch_over_cap": first_over}
    return kept, skipped, info


def _block_labels(block: dict) -> list[str]:
    """块/批次的标签集合（批次用 ``labels``，单块用 ``label``）。"""
    labels = [str(x) for x in (block.get("labels") or [])]
    if not labels and block.get("label"):
        labels = [str(block.get("label"))]
    return labels


def _cap_skip_entries(skipped: list[dict], index: list[dict]) -> list[dict]:
    """被总注入上限**跳过**的章/节（逐条给中文原因，进 ``not_injected`` 与账本）。"""
    by_id = {str(m["id"]): m for m in index}
    out: list[dict] = []
    for b in skipped:
        for src in _block_sources(b):
            mid = str(src.get("material_id") or "")
            m = by_id.get(mid) or {}
            out.append({
                "material": str(src.get("material") or m.get("title") or ""),
                "material_id": mid,
                "label": str(src.get("label") or ""),
                "chars": int(src.get("chars") or 0),
                "reason": "总注入上限",
                "reason_zh": "因「总注入上限」已用完，本章/节未注入",
                "note": "该章/节因「总注入上限」已用完而**未注入**（按章/节边界整条停止，未截断正文）",
            })
    return out


def _cap_skips_by_material(skipped: list[dict], index: list[dict]) -> list[dict]:
    """因总注入上限跳过的章节，**按材料分组**（覆盖账/预算视图用；R42 A2/A3）。"""
    by_id = {str(m["id"]): m for m in index}
    buckets: dict[str, dict] = {}
    for b in skipped:
        for src in _block_sources(b):
            mid = str(src.get("material_id") or "")
            title = str(src.get("material") or (by_id.get(mid) or {}).get("title") or "")
            bucket = buckets.setdefault(mid, {"material_id": mid, "title": title, "items": []})
            bucket["items"].append({"label": str(src.get("label") or ""),
                                    "chars": int(src.get("chars") or 0),
                                    "reason_zh": "因「总注入上限」已用完，本章/节未注入"})
    return list(buckets.values())


def _note_inject_cap_skips(skipped: list[dict], index: list[dict], info: dict,
                           subject_id: str) -> None:
    """R42 A2：**每一处未注入都写一条中文账目**（不是只写一条汇总）。"""
    from ..service import ledger

    cap = int(info.get("cap") or 0)
    if info.get("first_batch_over_cap"):
        ledger.note(
            ledger.CAT_MATERIAL, "材料注入（总注入上限）",
            f"你设定的总注入上限 {cap:,} 字**小于第一章/节本身**：为不截断正文，首批仍整章注入"
            f"（实际 {int(info.get('used_chars') or 0):,} 字，超出 {max(0, int(info.get('used_chars') or 0) - cap):,} 字）——"
            "请调大上限或设 0（不限），或改用「单次调用预算」分更多批（那样不会少学章节）",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "inject_cap_first_over", "cap": cap,
                    "used_chars": int(info.get("used_chars") or 0)},
        )
    entries = _cap_skip_entries(skipped, index)
    for e in entries:
        ledger.note(
            ledger.CAT_MATERIAL, f"材料《{e['material']}》· {e['label']}",
            f"总注入上限 {cap:,} 字已用完，**本章/节未注入**（已注入 {int(info.get('used_chars') or 0):,} 字）——"
            "按章/节边界整条停止，**未在句中截断**；调大上限或设 0（不限）后重新起草即可全部纳入",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "inject_cap_skipped", "cap": cap, "label": e["label"],
                    "material": e["material"], "chars": e["chars"]},
        )


def _make_batches(blocks: list[dict], batch_chars: int) -> list[dict]:
    """按章/节边界把材料块分批（``batch_chars<=0`` → 单批含全部）。

    **绝不丢正文**：单个章/节块自身超过预算时，它自成一批**整块注入**（不截断、不丢弃）——
    预算只影响"每批装多少块"，不影响"总共装哪些块"（R37 S1 ＋ R38 §3 ＋ R39 铁则）。
    """
    if not blocks:
        return []
    if batch_chars <= 0:
        return [_batch_of(blocks)]
    out: list[dict] = []
    cur: list[dict] = []
    size = 0
    for b in blocks:
        if cur and size + len(b["text"]) > batch_chars:
            out.append(_batch_of(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b["text"])
    if cur:
        out.append(_batch_of(cur))
    return out


def _batch_of(blocks: list[dict]) -> dict:
    text = "\n\n".join(b["text"] for b in blocks)
    materials = sorted({b["material"] for b in blocks})
    return {"text": text, "used_chars": len(text),
            "labels": [b["label"] for b in blocks],
            "materials": materials,
            # R42 A：批次保留"主要来源材料"（单材料批直给；跨材料批给材料列表）
            # ——用于「因总注入上限未注入」按材料分组（R42 A2/A3 的界面口径）。
            "material": materials[0] if len(materials) == 1 else "、".join(materials),
            "material_ids": sorted({str(b.get("material_id") or "") for b in blocks}),
            "blocks": [{"material": b["material"], "material_id": b.get("material_id", ""),
                        "label": b["label"], "chars": len(str(b.get("text") or ""))}
                       for b in blocks]}


def _block_sources(block: dict) -> list[dict]:
    """批次（或单块）里的**逐块来源**：``[{material, material_id, label, chars}]``。"""
    src = block.get("blocks")
    if src:
        return [dict(x) for x in src]
    return [{"material": str(block.get("material") or ""),
             "material_id": str(block.get("material_id") or ""),
             "label": str(block.get("label") or ""),
             "chars": len(str(block.get("text") or ""))}]


def valid_sections(hit: dict) -> set[str]:
    """材料的**合法溯源标签**全集（归一化后）：章/节地图标签 ∪ 页标签 ∪ 分节标签。"""
    from ..content import citations

    labels: set[str] = set()
    for sec in hit.get("sections") or []:
        labels.add(citations.normalize(str(sec.get("label") or "")))
    structure = hit.get("structure") or {}
    for entry in structure.get("entries") or []:
        labels.add(citations.normalize(entry.label))
        for pg in entry.pages:
            labels.add(citations.normalize(pg))
    return {x for x in labels if x}


def canonical_section(hit: dict, section: str) -> str | None:
    """把溯源 section **收敛成教材章节地图里的规范标签**（模型爱加方括号/空格 → 此处归一）。

    只在"归一化后等于某个条目/节标签"时收敛（页标签与逐字引文原样保留——它们各有语义）。
    返回 None = 不是已知标签（调用方再走引文包含校验）。
    """
    from ..content import citations

    norm = citations.normalize(section)
    if not norm:
        return None
    for sec in hit.get("sections") or []:
        if citations.normalize(str(sec.get("label") or "")) == norm:
            return str(sec.get("label"))
    for e in (hit.get("structure") or {}).get("entries") or []:
        if citations.normalize(e.label) == norm:
            return e.label
    return None


def check_unit_material(ref: dict, index: list[dict]) -> tuple[dict | None, str]:
    """D2（R36）＋ R37 S2：校验单个 ``{title, section}`` 溯源引用 → ``(规范化引用 | None, 中文问题)``。

    规则：① ``title`` 必须真实存在于该学科引用库；② ``section`` 必须是该材料的**真实章/节/页标签**
    （``bookmap`` 的章节地图或 ``material_sections`` 的节名）**或逐字出自其正文的引文**——
    后者复用 ``content.citations`` 的同一把尺子（归一化 + ≥6 字 + 子串包含），
    与 R35 S2 的 basis 引文纪律同源，不另写一份。
    命中的章/节标签会被**收敛为规范标签**（模型复制来的方括号/空格不落盘）。
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
    canonical = canonical_section(hit, section)
    if canonical is not None:
        return {"title": hit["title"], "section": canonical}, ""
    if citations.normalize(section) in valid_sections(hit):
        return {"title": hit["title"], "section": section}, ""
    ok, reason = citations.check(section, hit["body"], where=f"材料《{hit['title']}》正文")
    if ok:
        return {"title": hit["title"], "section": section}, ""
    return None, f"材料《{hit['title']}》溯源不成立：{reason}"


# ---------- R37 S2：章节全覆盖校验（未映射 → 违规） ----------
def _covered_entries(units: list, index: list[dict]) -> dict[tuple[str, str], list[str]]:
    """算账：地图条目 → 覆盖它的单元 id 列表。

    单元的一条 ``{title, section}`` 溯源**算覆盖**当且仅当：
    ① section 归一化后等于条目标签 / 该条目的任一页标签；或
    ② section 是**逐字引文**（≥6 字）且落在该条目正文内（同 ``citations`` 的尺子，不另写一份）。
    """
    from ..content import citations

    mapping: dict[tuple[str, str], list[str]] = {}
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            mapping[(m["id"], e.label)] = []
    for u in units:
        refs = (u.materials if hasattr(u, "materials") else (u or {}).get("materials")) or []
        uid = u.id if hasattr(u, "id") else str((u or {}).get("id") or "")
        for r in refs:
            title = str((r or {}).get("title") or "").strip()
            section = str((r or {}).get("section") or "").strip()
            norm = citations.normalize(section)
            if not norm:
                continue
            for m in index:
                if title and m["title"] != title:
                    continue
                for e in (m.get("structure") or {}).get("entries") or []:
                    labels = {citations.normalize(e.label)} | {citations.normalize(p) for p in e.pages}
                    body = citations.normalize(e.text)
                    if norm in labels or (len(norm) >= citations.MIN_QUOTE_CHARS and norm in body):
                        bucket = mapping.setdefault((m["id"], e.label), [])
                        if uid and uid not in bucket:
                            bucket.append(uid)
    return mapping


def coverage_problems(units: list, index: list[dict]) -> list[str]:
    """S2：每个地图条目（章/节）必须被 ≥1 个单元的溯源映射到；未映射 → 中文违规。

    ``index``：``draft_materials()["index"]`` 或 ``materials._material_index()``；
    空/无结构条目（无材料、未识别结构）→ 不报（退化为现状）。
    """
    mapping = _covered_entries(units, index)
    if not mapping:
        return []
    total = len(mapping)
    unmapped = [key[1] for key, ids in mapping.items() if not ids]
    if not unmapped:
        return []
    return [f"教材覆盖不全：{len(unmapped)}/{total} 个章/节条目没有任何单元对应"
            "（教材＝权威真源，不得悄悄丢章节）。未映射：" + "、".join(unmapped[:8])
            + ("…" if len(unmapped) > 8 else "")
            + "。请为每个条目至少派生 1 个单元（小条目可合并，但合并后 materials 必须列出全部被合并的条目标签）。"]


def coverage_summary(units: list, index: list[dict]) -> dict:
    """覆盖摘要（供起草候选/大纲页显示）：``{total, covered, uncovered:[标签]}``。"""
    mapping = _covered_entries(units, index)
    unmapped = [key[1] for key, ids in mapping.items() if not ids]
    return {"total": len(mapping), "covered": len(mapping) - len(unmapped), "uncovered": unmapped}


# ---------- R37 S3/S4：单元出稿的教材注入包 ----------
def unit_material_pack(db, subject_id: str, unit, *, batch_chars: int | None = None) -> dict:
    """单元出稿用的**教材注入包**（S3/S4 的唯一入口）。

    - 单元有 ``materials: [{title, section}]`` → 取对应章/节的**完整正文**（按标签匹配；
      标签对不上时退回该材料全文里包含该引文的章）；
    - 单元没有溯源（手工大纲）→ 用单元标题/概念标签在章节地图里做**确定性关键词检索**，
      取命中的章（找不到 → ``covered=False``，出稿端如实报"教材未覆盖此单元"，不编造）；
    - 返回 ``{"text", "entries", "sources", "binding_text", "covered", "note"}``：
      ``binding_text``＝该学科**全部材料正文**（S5 教材锚定校验的原文），``text``＝本次注入正文。
    """
    index = _material_index(db, subject_id)
    healthy = [m for m in index if m["text_health"]["healthy"]]
    if not index:
        return {"text": "", "entries": [], "sources": [], "binding_text": "",
                "covered": False, "no_materials": True, "note": "本学科没有引用材料"}
    if not healthy:
        return {"text": "", "entries": [], "sources": [{"title": m["title"]} for m in index],
                "binding_text": "", "covered": False, "no_materials": False,
                "note": "；".join(m["text_health"]["note"] for m in index)
                        or "该学科材料未通过文本层健康度检查（疑似扫描版）"}
    binding = "\n\n".join(f"《{m['title']}》\n{m['body']}" for m in healthy)
    picked: list[dict] = []
    sources: list[dict] = []
    refs = list(getattr(unit, "materials", None) or [])
    for ref in refs:
        title = str((ref or {}).get("title") or "").strip()
        section = str((ref or {}).get("section") or "").strip()
        for m in healthy:
            if title and m["title"] != title:
                continue
            hit = _entry_for_section(m, section)
            if hit is not None:
                picked.append({"material": m["title"], "label": hit.label, "text": hit.text})
                sources.append({"title": m["title"], "section": hit.label, "match": "declared"})
                break
    if not picked:  # 无溯源 / 溯源没落上 → 关键词检索（确定性；找不到就如实说未覆盖）
        for m in healthy:
            hit = _entry_by_terms(m, unit)
            if hit is not None:
                picked.append({"material": m["title"], "label": hit.label, "text": hit.text})
                sources.append({"title": m["title"], "section": hit.label, "match": "retrieved"})
    text = "\n\n".join(f"【教材段落：{p['label']}（材料《{p['material']}》）】\n{p['text']}"
                       for p in picked)
    return {"text": text, "entries": [p["label"] for p in picked], "sources": sources,
            "binding_text": binding, "covered": bool(picked), "no_materials": False,
            "note": "" if picked else "教材中未检索到与本节相关的章/节"}


def _entry_for_section(m: dict, section: str):
    """按标签匹配章/节条目（归一化比较）；失败则用引文包含关系定位所在条目。"""
    from ..content import citations

    entries = (m.get("structure") or {}).get("entries") or []
    if not entries:
        return None
    if section:
        norm = citations.normalize(section)
        for e in entries:
            if norm == citations.normalize(e.label) or norm in {citations.normalize(x) for x in e.pages}:
                return e
        for e in entries:
            if norm and norm in citations.normalize(e.text):
                return e
    return None


def entry_order(index: list[dict]) -> dict[str, int]:
    """章节地图条目的**书序**索引（归一化标签/页标签 → 位置）。

    R37 S2 复用点：大纲收尾据此把单元按**书序**排列（分批起草的批间顺序不可信，
    书的结构才是顺序真源）。返回空 dict = 没有可用的结构。
    """
    from ..content import citations

    order: dict[str, int] = {}
    i = 0
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            for key in [e.label, *e.pages]:
                norm = citations.normalize(str(key or ""))
                if norm and norm not in order:
                    order[norm] = i
            i += 1
    return order


def unit_order_key(unit, order: dict[str, int], default: int) -> int:
    """单元在书序中的位置（取它映射到的**最早**条目；没有映射 → ``default``）。"""
    from ..content import citations

    best = None
    refs = (unit.materials if hasattr(unit, "materials") else (unit or {}).get("materials")) or []
    for r in refs:
        norm = citations.normalize(str((r or {}).get("section") or ""))
        pos = order.get(norm)
        if pos is not None and (best is None or pos < best):
            best = pos
    return best if best is not None else default


def match_entry(m: dict, title: str = "", tags: list[str] | None = None):
    """确定性关键词检索：用标题/概念标签在章节地图里找最相关的条目（分数 0 → None）。

    R37 复用点：单元出稿的"无溯源回落"与大纲收尾的"溯源被剔除后回捞"共用同一实现。
    """
    from ..content import citations

    terms = [str(title or "")] + [str(t) for t in (tags or [])]
    grams: list[str] = []
    for t in terms:
        norm = citations.normalize(t)
        if len(norm) >= 2:
            grams += [norm[i:i + 3] for i in range(max(1, len(norm) - 2))]
    best = None
    best_score = 0
    for e in (m.get("structure") or {}).get("entries") or []:
        body = citations.normalize(e.text + " " + " ".join(e.sections))
        score = sum(1 for g in grams if g and g in body)
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 1 else None


def _entry_by_terms(m: dict, unit):
    """``match_entry`` 的单元适配（保留旧调用点语义）。"""
    return match_entry(m, getattr(unit, "title", "") or "",
                       list(getattr(unit, "concept_tags", None) or []))


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


# ---------- R37 S6 ＋ R38 B1：覆盖账本（跨全部材料） ----------
def coverage_ledger(db, subject_id: str) -> dict:
    """**覆盖账本**：章节地图 ↔ 单元映射 ↔ 单元覆盖状态（大纲页与 API 的唯一数据源）。

    R38 B1 增补（**多材料合并口径**）：
    - ``by_material``：**按材料分组**的 `已覆盖节 / 总节` + 未覆盖清单（材料页/大纲页直接渲染）；
    - ``uncovered_by_material``：未覆盖清单**按材料分组**（不许只在 prompt 尾部提一句）；
    - ``uncovered_materials``：**整份未纳入**的材料（健康度不合格/未注入）；
    - ``order_basis``：顺序依据（"角色：主教材在前" 或 "导入顺序"）；
    - ``entries[].pages`` + ``page_total/page_covered``：**章级统计、页级可下钻**（S1b）。

    返回::

        {
          "total": 章/节条目总数, "covered": …, "uncovered": […],
          "page_total": 全书页数, "page_covered": 有单元映射的页数,
          "by_material": [{material_id,title,role,role_zh,total,covered,uncovered:[…],chars}],
          "uncovered_materials": [{title,note}],
          "order_basis": "导入顺序" | "角色（…）",
          "materials": [{id,title,kind,healthy,note,kind_of_structure,structure_note,role}],
          "entries": [{material,material_id,label,chapter,chars,pages,sections,units,covered}],
          "units": [{unit_id,title,sources,status,note,grounded_facts,material_bound,dropped_exercises}]
        }
    """
    from ..content import citations

    index = _ordered(_material_index(db, subject_id))
    doc = outline_store.get_outline(subject_id)
    units = list(doc.units) if doc is not None else []
    mapping = _covered_entries(units, index)
    # **R42 A3：覆盖账如实降** —— 因「总注入上限」未注入的章节，即便有单元映射也**不算真覆盖**
    # （"没喂给模型"就谈不上"覆盖"）；同时在 not_injected 里说明它们去哪了。
    blocks = _full_blocks(index)
    eff = resolve_budget(db, subject_id)
    valve = context_valve(db, batch_chars=int(eff["per_call_chars"]), blocks=blocks)
    _keep, _skipped, cap = _apply_inject_cap(valve["batches"], int(eff["inject_max_chars"]), subject_id)
    cap_skips = _cap_skip_entries(_skipped, index)
    skipped_keys = {(str(x.get("material_id") or ""), str(x.get("label") or "")) for x in cap_skips}
    entries: list[dict] = []
    uncovered: list[str] = []
    page_total = 0
    page_covered = 0
    for m in index:
        for e in (m.get("structure") or {}).get("entries") or []:
            hit = sorted(set(mapping.get((m["id"], e.label)) or []))
            cap_skipped = (str(m["id"]), str(e.label)) in skipped_keys
            covered = bool(hit) and not cap_skipped
            if not covered:
                uncovered.append(f"{m['title']} · {e.label}")
            pages = list(e.pages)
            page_total += len(pages)
            if covered:
                page_covered += len(pages)
            entries.append({"material": m["title"], "material_id": m["id"], "label": e.label,
                            "chapter": e.chapter, "chars": e.chars, "sections": list(e.sections),
                            "pages": pages, "units": hit, "covered": covered,
                            # R42：这一条"去哪了"（可解释性——不许凭空消失）
                            "not_injected_reason": ("总注入上限" if cap_skipped
                                                    else ("" if covered else "无单元映射/未注入")),
                            "reason_zh": ("因「总注入上限」未注入（覆盖账如实降）" if cap_skipped
                                          else ("" if covered else "尚无单元映射到本章/节"))})
    # R38 B1：按材料分组统计（覆盖账跨全部材料）
    by_material: list[dict] = []
    uncovered_by_material: list[dict] = []
    uncovered_materials: list[dict] = []
    for m in index:
        mine = [e for e in entries if e["material_id"] == m["id"]]
        miss = [e for e in mine if not e["covered"]]
        by_material.append({
            "material_id": m["id"], "title": m["title"],
            "role": m.get("role") or ROLE_UNSET, "role_explicit": bool(m.get("role_explicit")),
            "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
            "total": len(mine), "covered": len(mine) - len(miss),
            "uncovered": [e["label"] for e in miss],
            "chars": len(m.get("body") or ""),
            "pages": sum(len(e["pages"]) for e in mine),
            "healthy": m["text_health"]["healthy"],
            "note": m["text_health"]["note"],
            # R42 A3：本材料因「总注入上限」未注入的章节（覆盖账里看得出"它去哪了"）
            "cap_skipped": [x["label"] for x in cap_skips if x["material_id"] == m["id"]],
            "cap_skipped_count": len([x for x in cap_skips if x["material_id"] == m["id"]]),
        })
        if miss:
            uncovered_by_material.append({
                "material_id": m["id"], "title": m["title"],
                "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
                "items": [{"label": e["label"], "chapter": e["chapter"], "chars": e["chars"],
                           "pages": e["pages"]} for e in miss],
            })
        if not m["text_health"]["healthy"]:
            uncovered_materials.append({"material_id": m["id"], "title": m["title"],
                                        "kind": "健康度不合格（未纳入任何注入）",
                                        "note": m["text_health"]["note"]})
    unit_ledger = []
    for u in units:
        meta = dict(u.meta or {})
        cov = dict(meta.get("coverage") or {})
        unit_ledger.append({
            "unit_id": u.id, "title": u.title,
            "sources": [dict(r) for r in (u.materials or [])],
            "status": str(cov.get("status") or "未知"),
            "note": str(cov.get("note") or ""),
            "grounded_facts": int(cov.get("grounded_facts") or 0),
            "material_bound": bool(cov.get("material_bound")),
            "dropped_exercises": int(cov.get("dropped_exercises") or 0),
            "generated_at": str(cov.get("at") or ""),
        })
    return {
        "subject": subject_id,
        "has_materials": bool(index),
        "total": len(entries),
        "covered": len(entries) - len(uncovered),
        "uncovered": uncovered,
        # R42 A3：**未纳入清单**（三种原因：健康度不合格 / 未进批次 / **总注入上限**），
        # 覆盖账与预算视图同源——"每一处没进去的都必须能解释"。
        "not_injected": (_unmapped_entries(index, blocks) + cap_skips),
        "inject_cap": {
            "configured": bool(cap.get("configured")),
            "cap": int(cap.get("cap") or 0),
            "used_chars": int(cap.get("used_chars") or 0),
            "remaining": int(cap.get("remaining") or 0),
            "skipped_count": int(cap.get("skipped_count") or 0),
            "skipped_labels": list(cap.get("skipped_labels") or []),
            "skipped_by_material": _cap_skips_by_material(_skipped, index),
        },
        "page_total": page_total,
        "page_covered": page_covered,
        "by_material": by_material,
        "uncovered_by_material": uncovered_by_material,
        "uncovered_materials": uncovered_materials,
        "order_basis": order_basis(index),
        "multi_material": len(index) > 1,
        "materials": [{"id": m["id"], "title": m["title"], "kind": m.get("kind", ""),
                       "healthy": m["text_health"]["healthy"],
                       "note": m["text_health"]["note"],
                       "role": m.get("role") or ROLE_UNSET,
                       "role_explicit": bool(m.get("role_explicit")),
                       "role_zh": ROLE_LABELS_ZH.get(m.get("role") or ROLE_UNSET),
                       "structure_kind": m["structure"]["kind"],
                       "structure_note": m["structure"]["note"]} for m in index],
        "entries": entries,
        "units": unit_ledger,
    }


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
    "DEFAULT_BATCH_CHARS",
    "materials_dir",
    "get_policy",
    "set_policy",
    "add_material",
    "list_materials",
    "delete_material",
    "materials_summaries",
    "text_health",
    "material_sections",
    "material_structure",
    "inject_budget",
    "batch_budget",
    "draft_materials",
    "valid_sections",
    "canonical_section",
    "check_unit_material",
    "coverage_problems",
    "coverage_summary",
    "coverage_ledger",
    "match_entry",
    "entry_order",
    "unit_order_key",
    "unit_material_pack",
    "material_ids_for_titles",
    "search_candidates",
    "select_candidates",
    # R38：预算滑块 + 多材料角色/合并口径
    "BATCH_TIERS",
    "INJECT_TIERS",
    "ROLE_MAIN",
    "ROLE_SUPPLEMENT",
    "ROLE_UNSET",
    "ROLE_LABELS_ZH",
    "resolve_budget",
    "subject_budget",
    "set_budget",
    "budget_view",
    "set_material_role",
    "order_basis",
    "context_valve",
    "estimate_tokens",
]
