"""app.outline.draft：通用学科大纲的 AI 起草（docs/14 §2.1 · Phase A A4）。

流程（"选择/新建学科 → AI 起草大纲（单元级）→ 校验 → 地图预览 → 采纳/改/重生成"）：
1. POST /subjects/{sid}/outline/draft（brief 学科简介 + 期望单元数 + 分组提示）；
2. 起草：LLM_API_KEY 存在 → OpenAICompatibleProvider 经 CALL_OUTLINE_DRAFT（light 档，JSON
   schema 化 + 校验 + 重试）起草；无 key → 离线启发式骨架（来源 heuristic，机制可跑通，
   真模型体验待配 key——AI 起草输出的质量与学科化模板属 docs/14 Phase B 治理项）；
3. 服务端兜底修复（AI 不可信输出纪律）：单元 id 统一 `<sid>.u<n>`；objectives 修剪 ≤3；
   prereqs 只许引用更早单元/既有大纲单元（剔除非法引用并记录问题）；概念标签去重 ≤5；
   pydantic + 结构校验报告随候选返回；
4. 候选不落盘：UI 预览 → PUT 采纳（revision+1）/ PATCH 局部改 / 再次 draft = 重生成。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import store as ostore
from .schemas import OutlineDoc, OutlineUnit, validate_outline_doc

UNIT_LOCAL = [f"u{i:02d}" for i in range(1, 31)]


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


def finalize_candidate(subject_id: str, raw_units: list[dict], *, label: str, source: str,
                       material_index: list[dict] | None = None) -> dict:
    """起草候选收尾：统一 id/序、修复非法引用、修剪字段、结构校验、材料溯源校验（不落盘）。

    R36 D2：每个单元的 ``materials: [{title, section}]`` 逐条过 ``check_unit_material``——
    不成立的引用**一律剔除并记问题**（宁缺勿造；调用方在 AI 路径上会据此驳回重生成一次）。
    """
    from . import materials as mat

    existing = ostore.get_outline(subject_id)
    existing_ids = set(existing.by_id()) if existing else set()
    index = list(material_index or [])
    units: list[OutlineUnit] = []
    problems: list[str] = []
    local_map: dict[str, str] = {}
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

    R36 D1/D4：``materials`` 传 ``outline.materials.draft_materials()`` 的注入包（**可选**）：
    有材料 → 注入 prompt（分节摘要，受字符预算约束）并要求逐单元溯源；
    **无材料 → 一切照旧，不报错**。
    """
    from ..config import get_settings
    from ..outline.store import get_outline

    label = ""
    doc = get_outline(subject_id)
    if doc is not None and doc.label:
        label = doc.label
    else:
        from ..db import SessionLocal

        with SessionLocal() as db:
            subj = ostore.get_subject(db, subject_id)
            label = subj.label if subj else subject_id
    settings = get_settings()
    mat_pack = materials or {}
    material_text = str(mat_pack.get("text") or "")
    index = list(mat_pack.get("index") or [])
    usage = {
        "count": int(mat_pack.get("count") or 0),
        "used_chars": int(mat_pack.get("used_chars") or 0),
        "dropped": list(mat_pack.get("dropped") or []),
        "truncated": bool(mat_pack.get("truncated")),
    }
    if not settings.llm_api_key:
        raw = heuristic_draft(subject_id, label, brief=brief, count=count, group_hint=group_hint)
        out = finalize_candidate(subject_id, raw, label=label, source="heuristic")
        out["material_usage"] = usage
        return out
    try:
        raw = _ai_draft_units(subject_id, label, brief=brief, count=count, group_hint=group_hint,
                              settings=settings, material_text=material_text)
        out = finalize_candidate(subject_id, raw, label=label, source="ai", material_index=index)
        # R36 D2：材料溯源驳回 → **重生成一次**（把不成立的原因回灌给模型）；仍不成立则保留剔除结果
        rejected = [p for p in out["problems"] if "溯源" in p]
        if index and rejected:
            raw2 = _ai_draft_units(subject_id, label, brief=brief, count=count, group_hint=group_hint,
                                   settings=settings, material_text=material_text, errors=rejected)
            out2 = finalize_candidate(subject_id, raw2, label=label, source="ai", material_index=index)
            still = [p for p in out2["problems"] if "溯源" in p]
            out2["problems"] = out2["problems"] + (
                ["材料溯源：首次候选引用不成立，已按驳回重生成一次"
                 + ("（重生成后仍有 %d 条不成立，已剔除该引用）" % len(still) if still else "")])
            out = out2
        out["material_usage"] = usage
        return out
    except Exception as e:  # AI 失败 → 降级启发式（离线可用优先；provider 侧已审计 ai_logs）
        raw = heuristic_draft(subject_id, label, brief=brief, count=count, group_hint=group_hint)
        out = finalize_candidate(subject_id, raw, label=label, source="heuristic")
        out["problems"] = out["problems"] + [f"AI 起草失败已降级启发式: {e}"]
        out["material_usage"] = usage
        return out


def _ai_draft_units(
    subject_id: str, label: str, *, brief: str, count: int, group_hint: str, settings,
    material_text: str = "", errors: list[str] | None = None,
) -> list[dict]:
    """真模型起草（CALL_OUTLINE_DRAFT · light 档 · JSON schema 校验）。

    P2/P3/P4（R36）写在 system prompt 里（机器校验待 R35 的 taught_facts/derivable）；
    D2 的 ``materials: [{title, section}]`` 亦为硬性输出要求，服务端再校验。
    """
    from ..ai.calls import CALL_OUTLINE_DRAFT
    from ..ai.provider import OpenAICompatibleProvider
    from ..service.ai_sink import make_ai_log_sink

    provider = OpenAICompatibleProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_heavy=settings.llm_model_heavy,
        model_light=settings.llm_model_light,
        log_sink=make_ai_log_sink(),
    )
    sys = (
        "你是课程大纲设计专家。请为学习者起草一门新学科的**知识点单元级**大纲。"
        "输出 JSON：{\"units\":[{...}]}，unit 字段：title(单元标题), objectives(1-3 条学习目标), "
        "concept_tags(2-4 个简洁规范的**概念标签**——命名稳定、可跨大纲复用，禁长句), "
        "group(分组名，先到先得), prereqs(引用更早单元的编号如 \"u01\"；根单元留空；只能引用更早单元), "
        "difficulty(1-3), requires_thinking(是否需要深度思考模型，布尔), "
        "materials(该单元依据的引用材料，形如 [{\"title\":\"材料标题\",\"section\":\"章节名或逐字引文\"}]；"
        "无依据则给空数组 [])。"
        "要求：单元数 = 用户指定；单元粒度到「单个知识点可独立学习」；单元间依赖严谨、无环。"
        "**由易到难（R36 P1/P3）**：单元顺序必须构成一条由易到难的学习路径——"
        "先修单元的 difficulty **不得高于**后继单元；group 用于表达「章/阶段」层次，组内同样先易后难。"
        "**零基础起点（R36 P2）**：第一个单元（prereqs 为空）必须能被**完全零基础**者学会，"
        "不得假定任何前置概念或课外常识（零基础假设：没教过的一律认为学习者不会）。"
        "**难度只能靠已教事实累积（R36 P4）**：后续单元可以更难，但加难只能建立在**前面单元已经讲过**的内容上，"
        "不得默认学习者已知道尚未讲过的概念。"
    )
    if material_text:
        sys += (
            "**必须读材料（R36 D1/D2）**：下面是用户为该学科上传的引用材料（分节摘要）。"
            "大纲应尽量贴合材料的结构与顺序，并为每个单元标注 materials 溯源："
            "title **只能**取下方给出的材料标题；section 必须是该材料的**真实章节名**"
            "（如 \"第 3 页\"）或**逐字取自材料正文的引文**（≥6 字，不得改写、不得编造）；"
            "无依据就留空数组 []——宁缺勿造，编造的溯源会被服务端驳回。"
        )
    user = (
        f"学科名：{label}（id={subject_id}）\n用户学这门课的目标/背景：{brief or '入门到进阶'}\n"
        f"分组方向：{group_hint or '不指定（你来定）'}\n请起草 {max(1, min(count, 30))} 个单元"
        f"（编号 u01…u{max(1, min(count, 30)):02d}）。"
    )
    if material_text:
        user += "\n\n===== 引用材料（分节摘要，注入量受预算约束）=====\n" + material_text
    if errors:
        user += ("\n\n[上一轮输出未通过服务端校验] 校验错误：\n"
                 + "\n".join(f"- {e}" for e in errors[:5])
                 + "\n请修正后重新输出完整 JSON（不要解释）。")
    outcome = provider.chat_json(
        CALL_OUTLINE_DRAFT,
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        strategy="fast",
    )
    return list(outcome.parsed.get("units") or [])


__all__ = ["draft_outline", "heuristic_draft", "finalize_candidate", "UnitDraft"]
