"""app.outline.draft：通用学科大纲的 AI 起草（docs/14 §2.1 · Phase A A4；R37 S2/S8 教材真源化）。

流程（"选择/新建学科 → AI 起草大纲（单元级）→ 校验 → 地图预览 → 采纳/改/重生成"）：
1. POST /subjects/{sid}/outline/draft（brief 学科简介 + 期望单元数 + 分组提示）；
2. 起草：LLM_API_KEY 存在 → OpenAICompatibleProvider 经 CALL_OUTLINE_DRAFT（light 档，JSON
   schema 化 + 校验 + 重试）起草；无 key → 离线启发式骨架（来源 heuristic，机制可跑通，
   真模型体验待配 key——AI 起草输出的质量与学科化模板属 docs/14 Phase B 治理项）；
2b. **R37 S2/S8（有教材时）**：先把教材解析成**章 → 节地图**（``outline.bookmap``，唯一实现），
   再由地图**派生单元**——每个地图条目必须映射到 ≥1 个单元；书太大时按章/页边界**分批**调用
   （每批注入该批章节的**完整正文**，不摘要、不截断），批次结果按书序合并；
   模型没映射到的条目由**教材目录本身**补齐（书的结构就是大纲，不是编造）并记问题；
3. 服务端兜底修复（AI 不可信输出纪律）：单元 id 统一 `<sid>.u<n>`；objectives 修剪 ≤3；
   prereqs 只许引用更早单元/既有大纲单元（剔除非法引用并记录问题）；概念标签去重 ≤5；
   pydantic + 结构校验报告随候选返回；
4. 候选不落盘：UI 预览 → PUT 采纳（revision+1）/ PATCH 局部改 / 再次 draft = 重生成。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import store as ostore
from .schemas import OutlineDoc, OutlineError, OutlineUnit, validate_outline_doc

UNIT_LOCAL = [f"u{i:02d}" for i in range(1, 61)]


class UnitDraft(BaseModel):
    """起草中间单元（本地序/既有 id 引用形式，finalize 收尾）。"""

    title: str
    objectives: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    group: str = ""
    prereqs: list[str] = Field(default_factory=list)
    difficulty: int = 2
    requires_thinking: bool = False


def heuristic_draft(subject_id: str, label: str, *, brief: str, count: int, group_hint: str) -> list[dict]:
    """离线启发式起草：确定性线性骨架（机制/演示用；配 key 后走 AI）。

    每个单元以"学科·第 n 单元"为标题、一个规范概念标签（可归一、保证非空）、目标 1 条、
    前置 = 前序单元（线性链，天然无环）。来源 heuristic 由调用方标注。
    """
    brief = (brief or label or "学科").strip()
    units: list[dict] = []
    for i in range(1, min(count, len(UNIT_LOCAL)) + 1):
        units.append(
            {
                "title": f"{brief} · 第 {i} 讲",
                "objectives": [f"掌握第 {i} 讲的核心要点，并能用自己的话讲解与举例"],
                "concept_tags": [f"{brief}核心{i}"],
                "group": group_hint or "主线",
                "prereqs": [UNIT_LOCAL[i - 2]] if i > 1 else [],
                "difficulty": 2 if i <= count // 2 else 3,
                "requires_thinking": i > count // 2,
            }
        )
    return units


def _min_entry_chars() -> int:
    """**R42 B1**：教材条目"过短"阈值（字符；默认 200，可配 ``MF_MIN_ENTRY_CHARS``）。

    过短条目＝标题/目录类（如"附录D 元素周期表" 45 字）：**不许静默成为单元，也不许静默丢弃**——
    优先并入相邻单元，否则标为跳过，两者都记账 + 覆盖账可解释。
    """
    try:
        from ..config import get_settings

        return max(0, int(getattr(get_settings(), "min_entry_chars", 200) or 0))
    except Exception:
        return 200


def _absorb_short_entry(units: list[OutlineUnit], index: list[dict], item: dict) -> str | None:
    """过短条目能否**安全并入**某个单元；不能 → ``None``（调用方标"跳过"）。

    **R42 B1 口径（宁缺勿造）**：只有"**已经有单元落在这一节上**"才允许并入——
    那种情况下该节本来就被覆盖，只是把粒度更细的条目挂回同一个单元；
    否则（没有任何单元引用它）**一律标为跳过**——给一个没引用本节的单元硬加溯源
    就是伪溯源（R36 D2 红线）。当前 ``bookmap`` 的条目标签就是节粒度，
    因此"没被任何单元映射"通常也就"没有单元落在该节上" → 走跳过路径（可解释、可追溯）。
    """
    if not units:
        return None
    label = str(item.get("label") or "")
    grounded = [u for u in units
                if any(str(r.get("section")) == label for r in (u.materials or []))]
    if not grounded:
        return None
    target = grounded[-1]
    meta = dict(target.meta or {})
    absorbed = list(meta.get("absorbed_short") or [])
    absorbed.append({"label": label, "chars": int(item.get("chars") or 0)})
    meta["absorbed_short"] = absorbed
    units[units.index(target)] = target.model_copy(update={"meta": meta})
    return target.id


def _note_short_entries(index: list[dict], short: list[dict], merged: list[str],
                        skipped: list[str], subject_id: str) -> None:
    """**R42 B1**：过短条目的两种处理**逐条记中文账目**（"已并入相邻单元" / "已跳过（过短）"）。"""
    from ..service import ledger

    merged_labels = {x.split("→", 1)[0] for x in merged}
    for item in short:
        label = str(item.get("label") or "")
        where = next((x.split("→", 1)[1] for x in merged if x.split("→", 1)[0] == label), "")
        if label in merged_labels:
            ledger.note(
                ledger.CAT_MATERIAL, f"材料《{item.get('material', '')}》· {label}",
                f"条目过短（{int(item.get('chars') or 0)} 字，疑似标题/目录类），"
                f"**已并入相邻单元 {where}**（覆盖账里记为已映射，未丢失）",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                detail={"kind": "short_entry_merged", **item, "into": where},
            )
        else:
            ledger.note(
                ledger.CAT_MATERIAL, f"材料《{item.get('material', '')}》· {label}",
                f"条目过短（{int(item.get('chars') or 0)} 字，疑似标题/目录类），"
                "**已跳过（过短），未成为单元**——不作为覆盖缺口统计，但在此显式留痕（不静默吞掉）",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_YES, subject_id=subject_id,
                detail={"kind": "short_entry_skipped", **item},
            )


def _note_difficulty_raised(raised: list[dict], subject_id: str) -> None:
    """**R42 B2**：难度被"非降钳制"抬高 → 逐处记账（中文原因 + 影响面 + 可否补救）。"""
    from ..service import ledger

    for r in raised:
        ledger.note(
            ledger.CAT_GENERATION, f"单元难度（{r['unit_id']} · {r['title']}）",
            f"难度因**先修单调性被抬高**：{r['from']} → {r['to']}"
            f"（书序上更早的单元 {r.get('because') or '—'} 已是 {r['to']}；"
            "先修难度不得高于后继，R36 P1/R37 S2）——**这是钳制的副作用，不是模型判断**",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "difficulty_raised", **r},
        )


def _entry_unit(subject_id: str, material_title: str, entry: dict, index: int,
                prev_id: str) -> dict:
    """**教材目录直接补齐**的单元（S2：模型没映射到的条目不得悄悄丢）。

    内容全部来自教材自身的结构（章标题 + 目录节名）——不是编造：
    标题＝章/节标签；目标＝该章下的节；概念标签＝章标签 + 前两个节名。
    """
    label = str(entry.get("label") or f"第 {index} 章")
    sections = [str(s) for s in (entry.get("sections") or []) if str(s).strip()]
    objectives = [f"学完《{label}》：{s}" for s in sections[:3]] or [f"掌握《{label}》的内容"]
    return {
        "id": f"{subject_id}.u{index:02d}",
        "title": label,
        "objectives": objectives,
        "concept_tags": [label] + sections[:2],
        "group": str(entry.get("chapter") or label),
        "prereqs": [prev_id] if prev_id else [],
        "difficulty": 1 + min(2, index // 5),
        "requires_thinking": index > 6,
        "materials": [{"title": material_title, "section": label}],
    }


def finalize_candidate(subject_id: str, raw_units: list[dict], *, label: str, source: str,
                       material_index: list[dict] | None = None) -> dict:
    """起草候选收尾：统一 id/序、修复非法引用、修剪字段、结构校验、材料溯源与**全覆盖**校验（不落盘）。

    R36 D2：每个单元的 ``materials: [{title, section}]`` 逐条过 ``check_unit_material``——
    不成立的引用**一律剔除并记问题**（宁缺勿造；调用方在 AI 路径上会据此驳回重生成一次）。
    R37 S2：地图条目未映射 → 用**教材目录**补齐单元（教材＝真源；不得悄悄丢章节），并记问题。
    **R42 B1**：条目**过短**（< ``MF_MIN_ENTRY_CHARS``，默认 200 字）→ **并入相邻单元**或**标为跳过**，
    两种处理都 ``ledger.note`` 记中文原因，并在覆盖账里可解释（``merged_short`` / ``skipped_short``）。
    **R42 B2**：难度因"非降钳制"被抬高 → 逐处 ``ledger.note`` 中文原因 + 单元 ``meta.difficulty_raised``
    （大纲页可见）。
    """
    from . import materials as mat

    existing = ostore.get_outline(subject_id)
    existing_ids = set(existing.by_id()) if existing else set()
    index = list(material_index or [])
    units: list[OutlineUnit] = []
    problems: list[str] = []
    local_map: dict[str, str] = {}
    # R42 B1：清掉上一轮收尾留下的"并入痕迹"（驳回重生成会再走一次本函数；
    # 否则第一次并入的过短条目会粘在重生成结果上——那是伪溯源）
    for raw in raw_units:
        if isinstance(raw, dict):
            raw.pop("__absorbed_short__", None)
    for i, raw in enumerate(raw_units[: len(UNIT_LOCAL)], start=1):
        local = UNIT_LOCAL[i - 1]
        node_id = f"{subject_id}.{local}"
        local_map[local] = node_id
        title = str(raw.get("title") or "").strip() or f"{label or subject_id} · 第 {i} 讲"
        objectives = [str(o) for o in (raw.get("objectives") or []) if str(o).strip()][:3]
        if not objectives:
            objectives = [f"掌握本单元核心要点并能讲清（{title}）"]
            problems.append(f"{node_id}: 目标缺失，回退占位目标")
        tags: list[str] = []
        seen: set[str] = set()
        for t in raw.get("concept_tags") or []:
            t = str(t).strip()
            if not t or t in seen:
                continue
            seen.add(t)
            tags.append(t)
        if len(tags) > 5:
            tags = tags[:5]
        if not tags:
            problems.append(f"{node_id}: 概念标签缺失（建议 2-4 个规范概念，等效跳过依赖标签）")
        prereqs: list[str] = []
        for p in raw.get("prereqs") or []:
            p = str(p)
            target = local_map.get(p)
            if target is None and p in existing_ids:
                target = p
            if target is None:
                problems.append(f"{node_id}: 前置引用 {p!r} 非法已剔除")
                continue
            prereqs.append(target)
        kept_refs: list[dict] = []
        if index:  # 只有该学科真有引用材料时才要求/校验溯源（无材料 → 退化为现状，不报错）
            for ref in raw.get("materials") or []:
                kept, why = mat.check_unit_material(ref, index)
                if kept is None:
                    problems.append(f"{node_id}: {why}")
                    continue
                kept_refs.append(kept)
        units.append(
            OutlineUnit(
                id=node_id,
                title=title,
                objectives=objectives,
                concept_tags=tags,
                group=str(raw.get("group") or "").strip() or "主线",
                prereqs=prereqs,
                difficulty=int(raw.get("difficulty") or 2),
                requires_thinking=bool(raw.get("requires_thinking")),
                materials=kept_refs,
            )
        )
    # R37 S2：全覆盖——未被任何单元映射的教材条目，先按标题/标签**回捞**已有单元，
    # 回捞不到才用**教材目录**补齐（内容取自书的目录，非编造）；两种情况都记问题（不得悄悄丢章节）
    # **R42 B1**：条目**过短**（标题/目录类）→ 优先**并入相邻单元**，否则**标为跳过**；
    # 两种处理都记账（中文原因）+ 覆盖账可解释——**不许静默吞掉**。
    filled: list[str] = []
    recovered: list[str] = []
    merged_short: list[str] = []
    skipped_short: list[str] = []
    short_entries: list[dict] = []
    if index:
        mapping = mat._covered_entries(units, index)
        for m in index:
            for entry in (m.get("structure") or {}).get("entries") or []:
                if mapping.get((m["id"], entry.label)):
                    continue
                target = None
                for u in units:  # ① 回捞：已有单元与条目确定性匹配 → 补上（服务端校验过的）章节溯源
                    if u.materials:
                        continue
                    hit = mat.match_entry(m, u.title, u.concept_tags)
                    if hit is not None and hit.label == entry.label:
                        target = u
                        break
                if target is not None:
                    units[units.index(target)] = target.model_copy(
                        update={"materials": [{"title": m["title"], "section": entry.label}]})
                    recovered.append(f"{target.id}←{entry.label}")
                    continue
                # ①.5 R42 B1：**过短条目**（< 阈值）——不静默成单元、也不静默丢弃
                if int(getattr(entry, "chars", 0) or 0) < _min_entry_chars():
                    short_entries.append({
                        "material_id": m["id"], "material": m["title"], "label": entry.label,
                        "chars": int(getattr(entry, "chars", 0) or 0),
                        "chapter": getattr(entry, "chapter", "") or "",
                    })
                    continue
                if len(units) >= len(UNIT_LOCAL):  # ② 目录补齐
                    problems.append(f"教材条目《{entry.label}》无单元映射，且单元数已达上限"
                                    f"（{len(UNIT_LOCAL)}）——请合并过细的节或拆批起草")
                    break
                prev = units[-1].id if units else ""
                filled.append(entry.label)
                spec = _entry_unit(subject_id, m["title"], {
                    "label": entry.label, "sections": list(entry.sections),
                    "chapter": entry.chapter,
                }, len(units) + 1, prev)
                units.append(OutlineUnit(
                    id=spec["id"], title=spec["title"], objectives=spec["objectives"],
                    concept_tags=spec["concept_tags"], group=spec["group"],
                    prereqs=[prev] if prev else [], difficulty=spec["difficulty"],
                    requires_thinking=spec["requires_thinking"], materials=spec["materials"],
                ))
                mapping.setdefault((m["id"], entry.label), []).append(spec["id"])
        # R42 B1 收口：过短条目逐个"并入相邻单元"或"标为跳过"，并逐条记账
        for item in short_entries:
            hit = _absorb_short_entry(units, index, item)
            if hit is None:
                skipped_short.append(item["label"])
                problems.append(
                    f"教材覆盖：条目《{item['label']}》仅 {item['chars']} 字（过短，疑似标题/目录类）"
                    "——**已标为跳过**，不成为单元（详见账本）")
            else:
                merged_short.append(f"{item['label']}→{hit}")
                problems.append(
                    f"教材覆盖：条目《{item['label']}》仅 {item['chars']} 字（过短）"
                    f"——**已并入相邻单元 {hit}**（详见账本）")
    if recovered:
        problems.append("教材覆盖：模型未标注章节依据的单元已按教材章节地图回捞 "
                        + f"{len(recovered)} 个（{('、'.join(recovered[:6]))}"
                        + ("…" if len(recovered) > 6 else "") + "）")
    if filled:
        problems.append("教材覆盖：模型未映射到单元的教材条目已按**教材目录**补齐 "
                        + f"{len(filled)} 个（{('、'.join(filled[:6]))}"
                        + ("…" if len(filled) > 6 else "") + "）——内容取自书的目录，非编造")
    if merged_short or skipped_short:
        _note_short_entries(index, short_entries, merged_short, skipped_short, subject_id)
    # R37 S2：**书序为主**——单元按教材章节顺序排列；先修线性串联；难度按书序单调化。
    # 理由：分批起草的批间 `prereqs`（模型按本批局部编号）不可靠；书的结构才是顺序真源
    # （规格原文："单元的顺序/prereqs 以书的顺序为主"）。规范化决定记在 notes 里（不是问题）。
    notes: list[str] = []
    raised: list[dict] = []
    if index and mat.entry_order(index):
        order = mat.entry_order(index)
        units.sort(key=lambda u: mat.unit_order_key(u, order, len(order)))
        # 重排后重新编号（id 必须跟列表序一致＝书序），再线性串联先修 + 难度单调化
        units = [u.model_copy(update={"id": f"{subject_id}.u{i:02d}"})
                 for i, u in enumerate(units, start=1)]
        rebuilt: list[OutlineUnit] = []
        for u in units:
            prev = rebuilt[-1].id if rebuilt else ""
            diff = u.difficulty if not rebuilt else max(u.difficulty, rebuilt[-1].difficulty)
            meta = dict(u.meta or {})
            if diff != u.difficulty:
                # **R42 B2：难度被"非降钳制"抬高 → 必须显性**（账本 + 大纲页单元行可见）
                raised.append({"unit_id": u.id, "title": u.title,
                               "from": int(u.difficulty), "to": int(diff),
                               "because": rebuilt[-1].id if rebuilt else ""})
                meta["difficulty_raised"] = {
                    "from": int(u.difficulty), "to": int(diff),
                    "reason_zh": f"难度因先修单调性被抬高：{int(u.difficulty)} → {int(diff)}"
                                 f"（书序上更早的单元 {rebuilt[-1].id} 已是 {int(diff)}；"
                                 "先修难度不得高于后继——R36 P1/R37 S2）",
                    "because": rebuilt[-1].id if rebuilt else "",
                }
            elif "difficulty_raised" in meta:
                meta.pop("difficulty_raised", None)
            rebuilt.append(u.model_copy(update={
                "prereqs": [prev] if prev else [], "difficulty": diff, "meta": meta}))
        units = rebuilt
        notes.append("教材结构：单元已按**书序**重排并重新编号、线性串联先修、难度按书序单调化"
                     "（分批起草的跨章 prereqs 不可靠；R37 S2「顺序以书序为主」）")
    if raised:
        _note_difficulty_raised(raised, subject_id)

    cand = OutlineDoc(subject=subject_id, label=label, status="draft", source=source, units=units)
    prob = validate_outline_doc(cand)
    referenced = {r["title"] for u in units for r in u.materials}
    source_materials = [m["id"] for m in index if m["title"] in referenced]
    return {
        "subject": subject_id,
        "label": label,
        "schema_version": cand.schema_version,
        "source": source,
        "base_revision": existing.revision if existing else 0,  # 采纳时 revision+1
        "source_materials": source_materials,                   # R36 D3：候选即给出将记录的依据材料
        "units": [u.model_dump(mode="json") for u in units],
        "problems": problems + prob,
        "notes": notes,                                         # R37 S2：已做的规范化决定（非问题）
        "coverage": (
            {**(mat.coverage_summary(units, index) if index else {}),
             # **R42 B1**：覆盖账要能**解释过短条目去哪了**（并入 / 跳过，都不是消失）
             "skipped_short": {"count": len(skipped_short), "labels": list(skipped_short)},
             "merged_short": {"count": len(merged_short), "items": list(merged_short)},
             "short_entry_min_chars": _min_entry_chars()}
            if index else None),
        # **R42 B2**：难度被抬高（非降钳制的副作用）——候选里直接可见
        "difficulty_raised": list(raised),
        "ok": not (problems or prob),
    }


def draft_outline(
    subject_id: str,
    *,
    brief: str = "",
    count: int = 6,
    group_hint: str = "",
    materials: dict | None = None,
) -> dict:
    """起草候选（不落盘）。有 LLM_API_KEY → AI；无 key/失败 → 离线启发式（降级标注）。

    R36 D1/D4 → **R37 S1/S2/S8**：``materials`` 传 ``outline.materials.draft_materials()`` 的注入包：
    - 有教材 → 先产出**章 → 节地图**，按地图**分批注入完整正文**（每批 = 若干章，不截断），
      由地图派生单元并逐单元溯源；每个地图条目必须映射到 ≥1 个单元（未映射的按教材目录补齐并记问题）；
    - 无教材 → 一切照旧，不报错（S2/§2"无材料时退回现状，并显式标注本内容无教材依据"；
      启发式候选本身即"无教材依据"，由调用方/UI 标注）；
    - 教材是扫描版/未提取到文字（S7）→ **拒绝起草**并中文告知（不得静默生成"没读到书的大纲"）。

    R39 §1 铁则：AI 失败降级启发式、溯源驳回重生成、无 key 离线出稿**全部记账**
    （响应里带 ``ledger`` 就地可见，总账页可见）。
    """
    from ..config import get_settings
    from ..outline.store import get_outline
    from ..service import ledger

    label = ""
    doc = get_outline(subject_id)
    if doc is not None and doc.label:
        label = doc.label
    else:
        from ..db import SessionLocal

        with SessionLocal() as db:
            subj = ostore.get_subject(db, subject_id)
            label = subj.label if subj else subject_id
    # **R56**：模型配置统一走「页面设置 > .env > 默认」的生效值（不再只读 .env）
    from ..service import model_config

    settings = model_config.effective_settings()
    mat_pack = materials or {}
    index = list(mat_pack.get("index") or [])
    batches = list(mat_pack.get("batches") or [])
    blocked = list(mat_pack.get("blocked") or [])
    if index and not any((m.get("text_health") or {}).get("healthy", True) for m in index):
        raise OutlineError(  # S7：不得静默生成"没读到书"的大纲
            "无法起草大纲：" + "；".join(b["note"] for b in blocked if b.get("note"))
            or "这份教材像是扫描件或图片版，程序读不到里面的文字。请换成文字版，或先做一次文字识别（OCR）。")
    usage = dict(mat_pack.get("usage") or {})
    usage.update({
        "count": int(mat_pack.get("count") or 0),
        "used_chars": int(mat_pack.get("used_chars") or 0),
        "dropped": list(mat_pack.get("dropped") or []),
        "truncated": bool(mat_pack.get("truncated")),
        "batches": int(mat_pack.get("batch_count") or len(batches)),
        "inject_max_chars": int(mat_pack.get("inject_max_chars") or 0),
        "batch_chars": int(mat_pack.get("batch_chars") or 0),
        "budget": dict(mat_pack.get("budget") or {}),
        "blocked": blocked,
    })
    if not settings.llm_api_key:
        if index:
            # **R40 裁决 §2-1（改为拒绝出稿）**：有教材但无可用模型 → 只能启发式出稿，产出必然
            # **无教材依据**（那正是 R37 要消灭的东西）。故**明确中文说明 + 不落盘**，并由 R39 铁则记账。
            # **R56**：指引统一指向**设置页**（不再引导用户去改 .env）。
            reason = ("还没有配模型 Key，无法依据教材生成大纲："
                      f"本学科有 {len(index)} 份引用材料，离线启发式只能产出**没有教材依据**的内容。"
                      "请到「设置 · 模型」里填一下 Key，然后重新起草。")
            ledger.note(
                ledger.CAT_MODEL_CALL, "大纲起草",
                reason + "（按 R40 裁决 §2-1：有教材且无可用模型 → **拒绝出稿**，不落盘）",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
                detail={"kind": "offline_refused_with_material", "material_count": len(index)},
            )
            raise OutlineError(reason)
        # 无教材：退化为"仅按 brief 起草"（如实标注无教材依据），机制保持可跑通
        raw = heuristic_draft(subject_id, label, brief=brief, count=count, group_hint=group_hint)
        out = finalize_candidate(subject_id, raw, label=label, source="heuristic")
        out["material_usage"] = usage
        out["no_material_grounding"] = True
        ledger.note(
            ledger.CAT_MODEL_CALL, "大纲起草",
            "还没有配模型 Key，本次大纲由离线启发式骨架产出，没有读教材——"
            "到「设置 · 模型」里填一下 Key，再重新起草就能得到读教材的大纲",
            impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_CONFIRM, subject_id=subject_id,
            detail={"kind": "offline_draft", "batches": usage["batches"]},
        )
        out["ledger"] = ledger.current().to_list() if ledger.current() else []
        return out
    try:
        raw = _ai_units_all_batches(
            subject_id, label, brief=brief, count=count, group_hint=group_hint,
            settings=settings, mat_pack=mat_pack, batches=batches)
        out = finalize_candidate(subject_id, raw, label=label, source="ai", material_index=index)
        # R36 D2：溯源引用不成立 → **驳回重生成一次**（把中文原因回灌给模型）
        # R37 S2 的覆盖缺口走"按教材目录补齐 + 记问题"（不重复调用模型：书的结构本身就是答案）
        rejected = [p for p in out["problems"] if "溯源" in p]
        if index and rejected:
            ledger.note(
                ledger.CAT_GENERATION, "大纲起草·材料溯源",
                f"首次候选有 {len(rejected)} 条材料溯源不成立，已把中文原因回灌并**驳回重生成一次**",
                impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_RETRY, subject_id=subject_id,
                detail={"rejected": rejected[:5]},
            )
            raw2 = _ai_units_all_batches(
                subject_id, label, brief=brief, count=count, group_hint=group_hint,
                settings=settings, mat_pack=mat_pack, batches=batches, errors=rejected[:5])
            out2 = finalize_candidate(subject_id, raw2, label=label, source="ai", material_index=index)
            still = [p for p in out2["problems"] if "溯源" in p]
            out2["problems"] = out2["problems"] + (
                ["材料溯源：首次候选引用不成立，已按驳回重生成一次"
                 + ("（重生成后仍有 %d 条不成立，已剔除该引用）" % len(still) if still else "")])
            if still:
                ledger.note(
                    ledger.CAT_GENERATION, "大纲起草·材料溯源",
                    f"驳回重生成后仍有 {len(still)} 条材料溯源不成立，**已剔除该引用**"
                    "（宁缺勿造：不保留编造的溯源）",
                    impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_RETRY, subject_id=subject_id,
                    detail={"still": still[:5]},
                )
            out = out2
        out["material_usage"] = usage
        out["ledger"] = ledger.current().to_list() if ledger.current() else []
        return out
    except OutlineError:
        raise
    except Exception as e:  # AI 失败 → 降级启发式（离线可用优先）
        ledger.note(
            ledger.CAT_MODEL_CALL, "大纲起草",
            f"AI 起草失败，本次已**降级为离线启发式骨架**（内容无教材锚定）：{e}",
            impact=ledger.SCOPE_SUBJECT, remedy=ledger.REMEDY_RETRY, subject_id=subject_id,
            detail={"error": str(e)[:300], "kind": "ai_draft_failed"},
        )
        raw = heuristic_draft(subject_id, label, brief=brief, count=count, group_hint=group_hint)
        out = finalize_candidate(subject_id, raw, label=label, source="heuristic")
        out["problems"] = out["problems"] + [f"AI 起草失败已降级启发式: {e}"]
        out["material_usage"] = usage
        out["no_material_grounding"] = True
        out["ledger"] = ledger.current().to_list() if ledger.current() else []
        return out


def _ai_units_all_batches(subject_id: str, label: str, *, brief: str, count: int, group_hint: str,
                          settings, mat_pack: dict, batches: list[dict],
                          errors: list[str] | None = None) -> list[dict]:
    """按**结构化分批**逐批起草并合并（S1/S2）：每批注入该批章节的完整正文。

    - 有地图（batches 各带 ``labels``）→ 每批只派生**本批条目**的单元，批间按书序拼接；
    - 无地图（小材料/无结构）→ 单次调用（与 R36 行为一致）。
    """
    entries_total = sum(len(b.get("labels") or []) for b in batches)
    if not batches or not entries_total:
        text = str(mat_pack.get("text") or "")
        return _ai_draft_units(subject_id, label, brief=brief,
                               count=count, group_hint=group_hint, settings=settings,
                               material_text=text, errors=errors,
                               chapter_map=_map_lines(mat_pack), entries=[])
    raw: list[dict] = []
    for i, b in enumerate(batches):
        labels = list(b.get("labels") or [])
        raw.extend(_ai_draft_units(
            subject_id, label, brief=brief, count=max(len(labels), 1), group_hint=group_hint,
            settings=settings, material_text=str(b.get("text") or ""),
            errors=(errors if i == 0 else None),
            chapter_map=_map_lines(mat_pack), entries=labels,
            batch_note=f"（第 {i + 1}/{len(batches)} 批：只处理本批列出的 {len(labels)} 个条目标签）",
        ))
    return raw


def _map_lines(mat_pack: dict) -> str:
    """章节地图的紧凑文本（供 prompt：模型必须知道整本书的结构，即使本次只处理一批）。

    ⚠️ 仅**不省成本**的默认路径（S1）注入全书地图；显式设了字符上限（R36 D4 降级口径）时
    不注入——那条路径的字面约定是"绝不整本塞进一次调用"。
    """
    if mat_pack.get("truncated"):
        return ""
    lines: list[str] = []
    for m in mat_pack.get("chapter_map") or []:
        lines.append(f"- 材料《{m.get('material', '')}》（结构识别：{m.get('kind', '')}；{m.get('note', '')}）")
        for e in m.get("entries") or []:
            secs = "；".join((e.get("sections") or [])[:8])
            lines.append(f"  · [{e.get('label')}]（{e.get('chars', 0)} 字"
                         + (f"；节：{secs}" if secs else "") + "）")
    return "\n".join(lines)


def _ai_draft_units(
    subject_id: str, label: str, *, brief: str, count: int, group_hint: str, settings,
    material_text: str = "", errors: list[str] | None = None,
    chapter_map: str = "", entries: list[str] | None = None, batch_note: str = "",
) -> list[dict]:
    """真模型起草（CALL_OUTLINE_DRAFT · light 档 · JSON schema 校验）。

    P2/P3/P4（R36）写在 system prompt 里（机器校验见 R35 的 taught_facts/derivable 与 P4）；
    D2 的 ``materials: [{title, section}]`` 亦为硬性输出要求，服务端再校验。
    R37 S2/S8：注入**整本书的章节地图** + 本批章节的**完整正文**，要求单元＝书的目录派生。
    R39 §2：system/user 模板都取自**可编辑的提示词注册表**（``ai.prompt_templates``）——
    用户在设置里改了大纲起草提示词，下一次起草**立即生效**（审计页可对照）。
    """
    from ..ai.calls import CALL_OUTLINE_DRAFT
    from ..ai import prompt_runtime
    from ..ai.prompt_templates import _MATERIAL_DISCIPLINE
    from ..ai.provider import OpenAICompatibleProvider
    from ..service.ai_sink import make_ai_log_sink

    provider = OpenAICompatibleProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_heavy=settings.llm_model_heavy,
        model_light=settings.llm_model_light,
        log_sink=make_ai_log_sink(),
    )
    sys, user, version = prompt_runtime.render_pair(
        "outline_draft",
        system_vars={"material_discipline": _MATERIAL_DISCIPLINE if material_text else ""},
        user_vars={
            "label": label, "subject_id": subject_id, "brief": brief or "入门到进阶",
            "group_hint": group_hint or "不指定（你来定）",
            "chapter_map_block": (
                "\n===== 教材章节地图（整本书的结构；覆盖校验的尺子）=====\n" + chapter_map + "\n"
                if chapter_map else ""),
            "entries_block": (
                "\n===== 本次必须覆盖的条目标签 =====\n"
                + "、".join(f"[{e}]" for e in entries)
                + f"\n请为上述 {len(entries)} 个条目各派生至少 1 个单元"
                  "（小条目可合并，但 materials 必须列出全部被合并标签）；"
                  "本批第一个单元的 prereqs 留空（跨批先修由服务端按书序串联）。\n"
                if entries else
                f"\n请起草 {max(1, min(count, 30))} 个单元"
                f"（编号 u01…u{max(1, min(count, 30)):02d}）。\n"),
            "batch_note": batch_note or "",
            "material_block": (
                "\n===== 教材章节正文（**完整正文**，逐字引用它来写目标与溯源）=====\n"
                + material_text + "\n===== 教材正文结束 =====\n"
                if material_text else ""),
            "errors_block": (
                "\n\n[上一轮输出未通过服务端校验] 校验错误：\n"
                + "\n".join(f"- {e}" for e in errors[:5])
                + "\n请修正后重新输出完整 JSON（不要解释）。"
                if errors else ""),
        },
        subject_id=subject_id,
    )
    outcome = provider.chat_json(
        CALL_OUTLINE_DRAFT,
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        strategy="fast",
        audit={"subject_id": subject_id, "unit_id": "", "prompt_versions": version},
    )
    return list(outcome.parsed.get("units") or [])


__all__ = ["draft_outline", "heuristic_draft", "finalize_candidate", "UnitDraft"]
