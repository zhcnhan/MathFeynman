"""app.outline.generate：通用学科单元内容的学科化出稿（docs/14 Phase B · B1/B2）。

替代 A4 的单一"语义判断题"桩：出稿支持**多题型混合**（boolean 判断 / single_choice 选择 /
fill_text 填空；计算式/数学类仍走既有 sympy 路径），每单元 ≥2 种题型、≥3 题、题面去重，
杜绝"三题相同 / 全是'能否讲述'自评"。

出稿策略：
1. **heuristic（离线确定性，默认）**：由大纲元数据（title/objectives/concept_tags/邻组标签）
   确定性构造可信事实类习题（判断=引用本单元概念、选择=概念归属、填空=补全核心概念），
   全部可自动判题并过自检——无 key 离线可测；
2. **AI（配 LLM_API_KEY）**：CALL_UNIT_CONTENT 学科化起草（schema 化 JSON → NodeDoc 组装 →
   多样/去重/自检校验；失败带校验错误重试 ≤2 次，仍失败降级 heuristic）；
3. 费曼 rubric 学科化：默认四维 + 科学类模板（rubric_for() 启发式选用）；
4. 落盘沿用 source:auto + refresh/sync（幂等），练习沿用既有会话状态机判题（domain/judge）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..content import stages_dir
from ..content.loader import load_library
from ..content.schemas import (
    CheckDoc,
    ExerciseDoc,
    ExplanationDoc,
    FeynmanDoc,
    NodeDoc,
    RubricDimension,
    RubricDoc,
)
from ..outline import store as outline_store
from .schemas import OutlineError, OutlineUnit

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

# ---------------------------------------------------------------------------
# 学科化费曼 rubric（B1：科学类模板 + 通用四维）
# ---------------------------------------------------------------------------
_RUBRIC_COMMON = RubricDoc(
    dimensions=[
        RubricDimension(key="correctness", weight=0.4, description="概念正确性：核心内容无事实错误"),
        RubricDimension(key="own_words", weight=0.25, description="用自己的话：能脱离原文复述"),
        RubricDimension(key="example_and_edge", weight=0.2, description="例子与边界：有例证、知例外"),
        RubricDimension(key="self_correction", weight=0.15, description="自纠能力：被追问时能自我修正"),
    ],
    pass_threshold=0.7,
)

_RUBRIC_SCIENCE = RubricDoc(
    dimensions=[
        RubricDimension(key="correctness", weight=0.4, description="概念与事实正确（含单位/量级）"),
        RubricDimension(key="own_words", weight=0.2, description="用自己的话讲清原理（不背书）"),
        RubricDimension(key="evidence", weight=0.25,
                        description="证据与推理：给出依据（观察/实验/推导），能区分事实与推断"),
        RubricDimension(key="self_correction", weight=0.15, description="自纠能力：追问时能修正错误认识"),
    ],
    pass_threshold=0.7,
)

_SCIENCE_KEYS = ("科学", "物理", "化学", "生物", "行星", "天文", "地理", "地质", "science", "physics")


def rubric_for(subject_id: str, label: str, unit_tags: list[str]) -> RubricDoc:
    """学科 rubric 选择（MVP：科学类关键词启发式；更细按 subject 配置属 B3 治理项）。"""
    hay = f"{subject_id} {label} {' '.join(unit_tags)}".lower()
    if any(k in hay for k in _SCIENCE_KEYS):
        return _RUBRIC_SCIENCE
    return _RUBRIC_COMMON


# ---------------------------------------------------------------------------
# 习题构造（确定性 heuristic + AI 组装共用）
# ---------------------------------------------------------------------------
def _tags_of(unit: OutlineUnit) -> list[str]:
    return [t for t in (unit.concept_tags or []) if t.strip()]


def _obj_lines(unit: OutlineUnit) -> list[str]:
    return [o for o in (unit.objectives or []) if str(o).strip()][:5]


def heuristic_exercises(unit: OutlineUnit, *, sibling_tags: list[str], max_ex: int = 5) -> list[ExerciseDoc]:
    """离线确定性出题：3–5 道、≥2 题型、题面去重。

    事实直接来自大纲元数据（本单元概念/目标），正确答案确定，杜绝歧义/杜撰：
    - boolean：概念归属（安全陈述，答案恒可判）；
    - single_choice：概念归属选择（正项=本单元标签，干扰=其它单元/组标签或他目标）；
    - fill_text：补全本单元核心概念/标题词。
    """
    tags = _tags_of(unit)
    objectives = _obj_lines(unit)
    local_tags = tags or [str(unit.title).strip()]
    distractors = [t for t in sibling_tags if t not in set(tags)][:5]
    head = re.sub(r"[（(].*?[)）]", "", unit.title).split("·")[0].strip()
    fill_pool = list(dict.fromkeys(
        local_tags + ([head] if head and head not in local_tags else [])))[:4]

    exercises: list[ExerciseDoc] = []
    seen_prompts: set[str] = set()

    def add(prompt: str, ex: ExerciseDoc) -> None:
        norm = re.sub(r"\s+", "", prompt)
        if norm in seen_prompts:
            return
        seen_prompts.add(norm)
        exercises.append(ex)

    if local_tags:
        add(f"判断：完成本单元后，你应能说清「{local_tags[0]}」是什么并举例。",
            ExerciseDoc(id="judge-tag1", kind="fixed", difficulty=min(unit.difficulty, 3),
                        prompt=f"判断题：本单元要求掌握的核心概念包括「{local_tags[0]}」。",
                        answer_bool=True, check=CheckDoc(mode="boolean_judgment")))
    if tags and distractors:
        add("选择：以下哪一项属于本单元核心概念？",
            ExerciseDoc(id="choose-tag", kind="fixed", difficulty=min(unit.difficulty + 1, 3),
                        prompt=f"选择题：下列概念中属于本单元「{unit.title}」的是哪一项？",
                        options=[tags[0]] + distractors[:3], answer_index=0,
                        check=CheckDoc(mode="single_choice")))
    if fill_pool:
        add("填空：请写出本单元核心概念之一。",
            ExerciseDoc(id="fill-tag", kind="fixed", difficulty=min(unit.difficulty, 3),
                        prompt=f"填空题：本单元（{unit.title}）涉及的核心概念之一是「___」。",
                        expected=fill_pool[0], aliases=fill_pool[1:],
                        check=CheckDoc(mode="fill_text")))
    # 用目标句补足至 ≤max_ex（不同题面，选择题形式）
    used_obj = set()
    for i, obj in enumerate(objectives):
        if len(exercises) >= max_ex:
            break
        if obj in used_obj:
            continue
        used_obj.add(obj)
        phrase = re.sub(r"[「」『』。，,\s]+", "", obj)[:16] or obj[:16]
        if not phrase:
            continue
        opts = [obj] + [o for o in objectives if o != obj][:2] or ["无需掌握"]
        if len(opts) < 2:
            opts = opts + ["以上都不需要"]
        add(f"选择：与目标「{phrase}…」对应的学习要求是？",
            ExerciseDoc(id=f"choose-obj-{i}", kind="fixed",
                        difficulty=min(unit.difficulty + 1, 3),
                        prompt=f"选择题：关于本单元目标「{phrase}…」，正确的理解是？",
                        options=opts, answer_index=0,
                        check=CheckDoc(mode="single_choice")))
    if len(exercises) < 3:  # 兜底（标签/目标极少）
        add("判断：学完本单元后应能用自己的话简要复述主题。",
            ExerciseDoc(id="judge-min", kind="fixed", difficulty=1,
                        prompt="判断题：学完本单元后，你能用自己的话简要复述主题吗？（应能）",
                        answer_bool=True, check=CheckDoc(mode="boolean_judgment")))
    return exercises[:max_ex]


# ---------------------------------------------------------------------------
# 组装 NodeDoc
# ---------------------------------------------------------------------------
def build_node_doc(
    unit: OutlineUnit,
    *,
    subject_id: str,
    subject_label: str,
    exercises: list[ExerciseDoc],
    feynman_task: str = "",
    lecture: str = "",
) -> NodeDoc:
    """单元 → 学科化 NodeDoc（目标驱动讲解稿 + 多题型 + 学科 rubric + 费曼任务）。"""
    objectives = list(unit.objectives) or ["理解本单元核心内容"]
    lines = [f"# {unit.title}", "", f"【{subject_label or unit.group} · 学习目标】"]
    lines += [f"- {o}" for o in objectives]
    lines += ["", "## 讲解"]
    lines.append(lecture if lecture else (
        "围绕上述目标展开。本单元核心概念："
        + ("、".join(unit.concept_tags) if unit.concept_tags else "见学习目标")
        + "。建议逐条对照目标学习：先建立直观理解，再用练习题自查，最后用自己的话讲给 AI。"
    ))
    lines += ["", "## 自查", "对照学习目标逐条检查：能否不看书向他人解释？能否举例、说明边界？"]
    body = "\n".join(lines)
    rubric = rubric_for(subject_id, subject_label, unit.concept_tags)
    task = feynman_task or (
        f"请你把「{unit.title}」完整地讲给 AI 听：用自己的话讲清概念与目标要点，并举出实例、"
        "说明边界与依据；讲完后 AI 会按 rubric 追问。"
    )
    return NodeDoc(
        id=unit.id,
        title=unit.title,
        level=unit.group or unit.id.partition(".")[0],
        topic=unit.group,
        prereqs=[],
        kind="normal",
        objectives=objectives,
        core_concepts=list(unit.concept_tags),
        explanation=ExplanationDoc(role="教师讲解稿", body=body),
        worked_examples=[],
        exercises=exercises or [ExerciseDoc(
            id="judge-min", kind="fixed", difficulty=1,
            prompt="判断题：学完本单元后，你应能用自己的话简要复述主题。",
            answer_bool=True, check=CheckDoc(mode="boolean_judgment"))],
        feynman=FeynmanDoc(
            task_prompt=task,
            rubric=rubric,
            socratic_followups=[
                "能举一个实例说明这个概念吗？",
                "在什么情况下它不适用（边界/例外）？依据是什么？",
                "它与你学过的内容有什么联系？",
            ],
            thinking=False,
        ),
        body_md=body,
    )


# ---------------------------------------------------------------------------
# 内容多样/自检校验（入库前；供 AI 重试反馈）
# ---------------------------------------------------------------------------
def validate_generic_content(doc: NodeDoc) -> list[str]:
    """结构/题型多样/重复/自检问题清单。"""
    from ..content.templates import render_exercise

    problems: list[str] = []
    modes = {e.check.mode for e in doc.exercises}
    if len(modes) < 2:
        problems.append(f"题型不足：仅 {sorted(modes)}（要求 ≥2 种题型）")
    if len(doc.exercises) < 3:
        problems.append(f"题量不足：{len(doc.exercises)} < 3")
    seen: set[str] = set()
    for e in doc.exercises:
        key = re.sub(r"\s+", "", e.prompt)
        if key in seen:
            problems.append(f"练习题面重复：{e.prompt[:24]}…")
        seen.add(key)
        for seed in range(3):
            r = render_exercise(doc.id, e, seed)
            if r.broken:
                problems.append(f"练习 {e.id} 自检 broken: {r.detail}")
                break
    return problems


# ---------------------------------------------------------------------------
# 落盘 + 库/DB 同步（沿用 A4 机制）
# ---------------------------------------------------------------------------
def _slug(s: str) -> str:
    return _FILENAME_SAFE.sub("_", s).strip("_")[:48] or "unit"


def _node_file_path(subject_id: str, node_id: str) -> Path:
    d = stages_dir() / subject_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"node_{_slug(node_id)}_auto.md"


def _frontmatter_md(doc: NodeDoc) -> str:
    import yaml

    exercises = []
    for e in doc.exercises:
        item = {
            "id": e.id, "kind": e.kind, "difficulty": e.difficulty, "prompt": e.prompt,
            "check": {"mode": e.check.mode}, "interactive": list(e.interactive),
        }
        if e.check.mode == "boolean_judgment":
            item["answer_bool"] = e.answer_bool
        elif e.check.mode == "single_choice":
            item["options"] = list(e.options)
            item["answer_index"] = e.answer_index
        elif e.check.mode == "fill_text":
            item["expected"] = e.expected
            item["aliases"] = list(e.aliases)
        exercises.append(item)
    meta = {
        "id": doc.id, "title": doc.title, "level": doc.level, "topic": doc.topic,
        "prereqs": doc.prereqs, "kind": doc.kind, "objectives": doc.objectives,
        "core_concepts": doc.core_concepts, "source": "auto",
        "explanation": {"role": "教师讲解稿", "body": doc.explanation.body},
        "exercises": exercises,
        "feynman": {
            "task_prompt": doc.feynman.task_prompt,
            "rubric": {
                "dimensions": [
                    {"key": d.key, "weight": d.weight, "description": d.description}
                    for d in doc.feynman.rubric.dimensions
                ],
                "pass_threshold": doc.feynman.rubric.pass_threshold,
            },
            "socratic_followups": list(doc.feynman.socratic_followups),
            "thinking": doc.feynman.thinking,
        },
    }
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=100).rstrip()
    return "\n".join(["---", head, "---", "", doc.body_md])


def _sibling_tags(subject_id: str, unit: OutlineUnit) -> list[str]:
    """同大纲其它单元的标签池（选择题干扰项来源；确定性）。"""
    try:
        outline = outline_store.get_outline(subject_id)
        if outline is None:
            return []
        return [t for u in outline.units if u.id != unit.id for t in (u.concept_tags or [])]
    except OutlineError:
        return []


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def generate_unit_content(
    db,
    subject_id: str,
    unit_id: str,
    *,
    force: bool = False,
    drafter: str = "auto",  # auto=有 key 走 AI，否则 heuristic；heuristic=强制离线
    material_summaries: list[dict] | None = None,
) -> dict:
    """懒生成单元内容（学科化多题型 + 学科 rubric + 多样/自检校验）。

    AI 起草失败/校验不过 → 自动降级 heuristic；heuristic 也不过 → failed（带问题透传）。
    material_summaries（B3）：本地/联网引用材料摘要（注入 AI 起草上下文）。
    """
    subj = outline_store.get_subject(db, subject_id)
    if subj is None:
        raise OutlineError(f"学科未注册: {subject_id}")
    if subj.kind == "preset":
        raise OutlineError("math preset 内容由 roadmap 蓝图流水线生成（不走本模块）")
    outline = outline_store.get_outline(subject_id)
    if outline is None:
        raise OutlineError(f"学科 {subject_id} 尚无大纲")
    unit = outline.by_id().get(unit_id)
    if unit is None:
        raise OutlineError(f"单元不存在: {unit_id}")
    lib = load_library()
    if not force and unit.id in {n.id for n in lib.nodes}:
        return {"status": "exists", "node_id": unit.id, "path": "", "subject": subject_id,
                "unit": unit_id, "note": "内容已在库（懒生成幂等）"}
    from ..config import get_settings

    use_ai = drafter == "auto" and bool(get_settings().llm_api_key)
    doc: NodeDoc | None = None
    if use_ai:
        errs: list[str] = []
        for attempt in range(1, 3):
            try:
                exercises, task, lecture = _ai_draft(
                    subject_id, unit, material_summaries=material_summaries, errors=errs or None)
                doc = build_node_doc(unit, subject_id=subject_id, subject_label=subj.label,
                                     exercises=exercises, feynman_task=task, lecture=lecture)
            except Exception as e:
                errs.append(f"[attempt {attempt}] AI 出稿异常: {e}")
                doc = None
                continue
            problems = validate_generic_content(doc)
            if not problems:
                break
            errs.extend(f"[attempt {attempt}] {p}" for p in problems)
            doc = None
    if doc is None:
        exercises = heuristic_exercises(unit, sibling_tags=_sibling_tags(subject_id, unit))
        doc = build_node_doc(unit, subject_id=subject_id, subject_label=subj.label, exercises=exercises)
        problems = validate_generic_content(doc)
        if problems:
            return {"status": "failed", "node_id": unit.id, "path": "", "subject": subject_id,
                    "unit": unit_id, "note": "启发式内容校验未通过：" + "；".join(problems[:3])}
    # B3：引用材料可追溯（讲解正文附"参考材料"来源标注；AI 起草时摘要已注入上下文）
    if material_summaries:
        refs = "\n".join(
            f"- 「{m.get('title', '')}」（{m.get('source', '本地')}"
            + (f"，{m.get('url', '')}" if m.get("url") else "") + "）"
            for m in material_summaries[:8]
        )
        if refs:
            suffix = "\n\n## 参考材料（可追溯来源）\n" + refs + "\n"
            doc.body_md += suffix
            doc.explanation.body += suffix
    path = _node_file_path(subject_id, unit.id)
    path.write_text(_frontmatter_md(doc), encoding="utf-8")
    from ..service.library import refresh_library, sync_content

    refresh_library()
    report = sync_content(db)
    db.commit()
    if not report.ok:
        return {"status": "failed", "node_id": unit.id, "path": str(path), "subject": subject_id,
                "unit": unit_id, "note": "；".join(report.errors[:3])}
    return {"status": "created", "node_id": unit.id, "path": str(path), "subject": subject_id,
            "unit": unit_id, "note": f"出稿：{'AI' if use_ai else '启发式'}"}


def _ai_draft(
    subject_id: str,
    unit: OutlineUnit,
    *,
    material_summaries: list[dict] | None = None,
    errors: list[str] | None = None,
) -> tuple[list[ExerciseDoc], str, str]:
    """真模型学科化出稿（CALL_UNIT_CONTENT · light 档 · JSON schema 校验）。"""
    from ..ai.calls import CALL_UNIT_CONTENT
    from ..ai.provider import OpenAICompatibleProvider
    from ..config import get_settings
    from ..service.ai_sink import make_ai_log_sink

    settings = get_settings()
    provider = OpenAICompatibleProvider(
        api_key=settings.llm_api_key, base_url=settings.llm_base_url,
        model_heavy=settings.llm_model_heavy, model_light=settings.llm_model_light,
        log_sink=make_ai_log_sink(),
    )
    mats = "\n".join(
        f"- 「{m.get('title', '')}」{m.get('source', '')}: {m.get('summary', '')}"
        for m in (material_summaries or [])
    ) or "（无）"
    sys = (
        "你是学科内容作者。为一门课的知识点单元写学习内容：输出 JSON："
        '{"lecture":"Markdown 讲解（可结合概念标签/材料；含 1 个直观例子）",'
        '"feynman_task":"费曼口述任务（一段话）",'
        '"exercises":[{"kind":"boolean|choice|fill","prompt":"…",'
        '"answer_bool":true（boolean 用）,"options":[…],"answer_index":0（choice 用,0 起）,'
        '"expected":"…","aliases":[…]（fill 用）}]}\n'
        "要求：exercises 3–5 道且**至少含 2 种题型**、题面互不相同；"
        "题目答案必须可由本单元内容/材料确定，禁止杜撰事实；判断陈述明确可判；讲解简洁准确。"
    )
    user = (
        f"学科：{subject_id}\n单元：{unit.title}\n学习目标：" + "；".join(unit.objectives) +
        f"\n概念标签：{'、'.join(unit.concept_tags)}\n引用材料摘要：\n{mats}\n请起草本单元学习内容。"
        + (f"\n[上一轮未通过自动校验]\n{chr(10).join(errors[:6])}" if errors else "")
    )
    out = provider.chat_json(
        CALL_UNIT_CONTENT,
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        strategy="fast",
    )
    data = out.parsed
    exercises: list[ExerciseDoc] = []
    for i, spec in enumerate((data.get("exercises") or [])[:8]):
        kind = spec.get("kind")
        prompt = str(spec.get("prompt") or "").strip()
        if kind == "boolean":
            exercises.append(ExerciseDoc(
                id=f"b{i + 1}", kind="fixed", difficulty=min(unit.difficulty, 3), prompt=prompt,
                answer_bool=bool(spec.get("answer_bool")),
                check=CheckDoc(mode="boolean_judgment")))
        elif kind == "choice":
            options = [str(o) for o in (spec.get("options") or []) if str(o).strip()]
            idx = int(spec.get("answer_index") or 0)
            if not options:
                continue
            exercises.append(ExerciseDoc(
                id=f"c{i + 1}", kind="fixed", difficulty=min(unit.difficulty + 1, 3), prompt=prompt,
                options=options[:6], answer_index=max(0, min(idx, len(options) - 1)),
                check=CheckDoc(mode="single_choice")))
        elif kind == "fill":
            expected = str(spec.get("expected") or "").strip()
            if not expected:
                continue
            exercises.append(ExerciseDoc(
                id=f"f{i + 1}", kind="fixed", difficulty=min(unit.difficulty, 3), prompt=prompt,
                expected=expected,
                aliases=[str(a) for a in (spec.get("aliases") or []) if str(a).strip()],
                check=CheckDoc(mode="fill_text")))
    if not exercises:
        raise ValueError("AI 未输出任何可用练习题")
    return exercises, str(data.get("feynman_task") or ""), str(data.get("lecture") or "")


__all__ = [
    "generate_unit_content",
    "heuristic_exercises",
    "build_node_doc",
    "validate_generic_content",
    "rubric_for",
]
