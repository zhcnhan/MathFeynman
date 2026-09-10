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
from ..content import answerability
from ..content.loader import load_library
from ..content.schemas import (
    BasisDoc,
    CheckDoc,
    Derivable,
    ExerciseDoc,
    ExplanationDoc,
    FeynmanDoc,
    NodeDoc,
    RubricDimension,
    RubricDoc,
    TaughtFact,
    WorkedExampleDoc,
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


def _shuffle_single(options: list[str], seed_key: str) -> tuple[list[str], int]:
    """single_choice 选项**确定性打乱**并同步 answer_index（R23 B1#1 · Phase C C4）。

    - 种子 = sha1(seed_key)（unit.id + 题 id）→ 同单元/同大纲结构下选项序可复现（内容幂等）；
    - 消除"正项恒第 1 项"的做题套路；选项序与判题 answer_index 一一同步（B1 起 judge 按
      编号/文本比对，UI 按 options 顺序渲染）。
    """
    import random

    n = len(options)
    if n <= 1:
        return list(options), 0
    seed = int(hashlib.sha1(seed_key.encode("utf-8")).hexdigest()[:8], 16)
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return [options[i] for i in order], order.index(0)


def heuristic_lecture(unit: OutlineUnit) -> str:
    """离线启发式讲解（确定性；**句句都能被 taught_facts 逐字引用**）。"""
    tags = [str(t).strip() for t in (unit.concept_tags or []) if str(t).strip()] or [str(unit.title).strip()]
    objectives = [str(o).strip() for o in (unit.objectives or []) if str(o).strip()] \
        or [f"掌握「{unit.title}」的核心内容"]
    lines = [f"本单元核心概念：{t}。" for t in tags[:4]]
    lines += [f"本单元要求：{o}。" for o in objectives[:3]]
    lines.append("学习路径：先建立直观理解，再用练习题自查，最后用自己的话讲给 AI 听。")
    return "\n".join(lines)


def heuristic_facts(unit: OutlineUnit, lecture: str) -> list[dict]:
    """启发式知识包：事实句就是讲解里那几句（逐字），故必然通过 S1 来源校验。"""
    return [{"id": f"f{i}", "text": line.strip()} for i, line in enumerate(lecture.splitlines()[:8], start=1)
            if line.strip()]


def heuristic_asks(unit: OutlineUnit, lecture: str) -> list[dict]:
    """启发式 socratic：只问"讲解里讲了什么"（可答），不再用"举实例/它与你学过的联系"这类模板套话。"""
    first = lecture.splitlines()[0].strip() if lecture.strip() else ""
    if not first:
        return []
    return [{"ask": "请说出本单元的一个核心概念，并用一句话说明它是什么。",
             "basis": {"fact_ids": ["f1"], "quote": first}}]


def heuristic_exercises(unit: OutlineUnit, *, sibling_tags: list[str], max_ex: int = 5,
                        facts: list[dict] | None = None) -> list[ExerciseDoc]:
    """离线确定性出题：3–5 道、≥2 题型、题面去重 + **每题带 basis**（R35 S2）。

    事实直接来自大纲元数据（本单元概念/目标），正确答案确定，杜绝歧义/杜撰：
    - boolean：概念归属（安全陈述，答案恒可判）；
    - single_choice：概念归属选择（正项=本单元标签，干扰=其它单元/组标签或他目标）；
    - fill_text：补全本单元核心概念/标题词。
    """
    facts = list(facts or [])
    fact_ids = [f["id"] for f in facts] or ["f1"]
    concept_quote = facts[0]["text"] if facts else str(unit.title)

    def basis_for(quote: str) -> BasisDoc:
        """引文必须 ≥6 字（citations 最短门槛）；按引文找回对应的事实 id。"""
        fid = next((f["id"] for f in facts if f["text"] == quote), fact_ids[0])
        return BasisDoc(fact_ids=[fid], quote=quote)

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
                        answer_bool=True, basis=basis_for(concept_quote),
                        check=CheckDoc(mode="boolean_judgment")))
    if tags and distractors:
        opts, idx = _shuffle_single([tags[0]] + distractors[:3],
                                    seed_key=f"{unit.id}:choose-tag")
        add("选择：以下哪一项属于本单元核心概念？",
            ExerciseDoc(id="choose-tag", kind="fixed", difficulty=min(unit.difficulty + 1, 3),
                        prompt=f"选择题：下列概念中属于本单元「{unit.title}」的是哪一项？",
                        options=opts, answer_index=idx, basis=basis_for(concept_quote),
                        check=CheckDoc(mode="single_choice")))
    if fill_pool:
        add("填空：请写出本单元核心概念之一。",
            ExerciseDoc(id="fill-tag", kind="fixed", difficulty=min(unit.difficulty, 3),
                        prompt=f"填空题：本单元（{unit.title}）涉及的核心概念之一是「___」。",
                        expected=fill_pool[0], aliases=fill_pool[1:], basis=basis_for(concept_quote),
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
        opts, idx = _shuffle_single(opts, seed_key=f"{unit.id}:choose-obj-{i}")
        add(f"选择：与目标「{phrase}…」对应的学习要求是？",
            ExerciseDoc(id=f"choose-obj-{i}", kind="fixed",
                        difficulty=min(unit.difficulty + 1, 3),
                        prompt=f"选择题：关于本单元目标「{phrase}…」，正确的理解是？",
                        options=opts, answer_index=idx,
                        basis=basis_for(f"本单元要求：{obj}。"),
                        check=CheckDoc(mode="single_choice")))
    if len(exercises) < 3:  # 兜底（标签/目标极少）
        add("判断：学完本单元后应能用自己的话简要复述主题。",
            ExerciseDoc(id="judge-min", kind="fixed", difficulty=1,
                        prompt="判断题：学完本单元后，你能用自己的话简要复述主题吗？（应能）",
                        answer_bool=True, basis=basis_for(concept_quote),
                        check=CheckDoc(mode="boolean_judgment")))
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
    facts: list[dict] | None = None,
    derivable: list[dict] | None = None,
    worked_examples: list[dict] | None = None,
    asks: list[dict] | None = None,
) -> NodeDoc:
    """单元 → 学科化 NodeDoc（目标驱动讲解稿 + 多题型 + 学科 rubric + 费曼任务 + R35 知识包）。

    R35：`facts`/`derivable`/`worked_examples`/`asks` 一并落盘（asks 带 basis）；
    **不再内置"举实例 / 它与你学过的联系"这类模板套话**——那正是被审计判为不可答的写法。
    """
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
    keep_asks: list[str] = []
    keep_basis: list[BasisDoc] = []
    for a in (asks or []):
        item = a if isinstance(a, dict) else (a.model_dump() if hasattr(a, "model_dump") else {})
        ask = str(item.get("ask") or "").strip()
        basis = _basis_from(item.get("basis"))
        if not ask or basis is None:
            continue  # 无依据的 socratic **不落盘**（R35 S2：不下发模板套话）
        keep_asks.append(ask)
        keep_basis.append(basis)
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
        worked_examples=[
            WorkedExampleDoc(prompt=str((w or {}).get("prompt") or ""),
                             solution_steps=[str(s) for s in ((w or {}).get("solution_steps") or [])])
            for w in (worked_examples or []) if str((w or {}).get("prompt") or "").strip()
        ],
        exercises=exercises or [ExerciseDoc(
            id="judge-min", kind="fixed", difficulty=1,
            prompt="判断题：学完本单元后，你应能用自己的话简要复述主题。",
            answer_bool=True, check=CheckDoc(mode="boolean_judgment"))],
        feynman=FeynmanDoc(
            task_prompt=task,
            rubric=rubric,
            socratic_followups=keep_asks,
            socratic_basis=keep_basis,
            thinking=False,
        ),
        taught_facts=list(facts or []),
        derivable=list(derivable or []),
        body_md=body,
    )


# ---------------------------------------------------------------------------
# 内容多样/自检校验（入库前；供 AI 重试反馈）
# ---------------------------------------------------------------------------
def validate_generic_content(doc: NodeDoc) -> list[str]:
    """结构/题型多样/重复/自检问题清单（**不含**可答性——那是 `answerability.gate_node()` 的职责）。"""
    from ..content.templates import render_exercise

    problems: list[str] = []
    modes = {e.check.mode for e in doc.exercises}
    if len(modes) < 2:
        problems.append(f"题型不足：仅 {sorted(modes)}（要求 ≥2 种题型）")
    if len(doc.exercises) < 3:
        problems.append(f"题量不足：{len(doc.exercises)} < 3")
    if not doc.worked_examples:
        problems.append("缺少例题：auto 出稿必须产出 worked_examples ≥1（R35 A3：例题是合法作答的示范）")
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


def _answerability_structure_problems(doc: NodeDoc, report) -> list[str]:
    """可答性判定**之后**的结构后果：全丢光了也算不合格（避免落盘空壳）。"""
    problems: list[str] = []
    if not report.verified:
        problems.append("未声明可答知识包（taught_facts）：本单元事实句未逐字取自讲解")
    if not doc.exercises:
        problems.append("可答性判定后无任何合规练习（全部因缺依据被丢弃）")
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
        if e.basis is not None:  # R35 S2：依据（引文纪律）随题落盘
            item["basis"] = e.basis.model_dump()
        exercises.append(item)
    meta = {
        "id": doc.id, "title": doc.title, "level": doc.level, "topic": doc.topic,
        "prereqs": doc.prereqs, "kind": doc.kind, "objectives": doc.objectives,
        "core_concepts": doc.core_concepts, "source": "auto",
        "explanation": {"role": "教师讲解稿", "body": doc.explanation.body},
        # R35 S1：声明式知识包（事实句必须逐字出自讲解；能通过可答性校验才允许落盘）
        "taught_facts": [f.model_dump() for f in doc.taught_facts],
        "derivable": [d.model_dump() for d in doc.derivable],
        "worked_examples": [w.model_dump() for w in doc.worked_examples],
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
            "socratic_basis": [b.model_dump() for b in (doc.feynman.socratic_basis or [])],
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
        raise OutlineError("预置学科内容由课程蓝图流水线生成（不走本模块）")
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
    a11y_problems: list[str] = []
    if use_ai:
        errs: list[str] = []
        for attempt in range(1, 3):
            try:
                payload = _ai_draft(
                    subject_id, unit, material_summaries=material_summaries, errors=errs or None)
                doc = build_node_doc(unit, subject_id=subject_id, subject_label=subj.label,
                                     exercises=payload["exercises"], feynman_task=payload["task"],
                                     lecture=payload["lecture"], facts=payload["facts"],
                                     derivable=payload["derivable"],
                                     worked_examples=payload["worked_examples"], asks=payload["asks"])
            except Exception as e:
                errs.append(f"[attempt {attempt}] AI 出稿异常: {e}")
                doc = None
                continue
            problems = validate_generic_content(doc)
            # R35 S1/S2/S5：可答性判定（**独立函数、独立调用**，不揉进结构校验）——
            # 不合规的题/追问被丢弃；若丢弃后不满足题量/题型/例题要求 → 带原因重生成
            report = answerability.gate_node(
            doc, known_concepts={str(t) for t in (unit.concept_tags or []) if str(t).strip()})
            a11y_problems = list(report.problems)
            problems = problems + _answerability_structure_problems(doc, report)
            if not problems:
                break
            # 丢弃原因回灌给模型（这是"修生成器"的输入，不是只改某一题文案）
            errs.extend(f"[attempt {attempt}] {p}" for p in (problems + a11y_problems[:3]))
            doc = None
    if doc is None:
        lecture = heuristic_lecture(unit)
        facts = heuristic_facts(unit, lecture)
        exercises = heuristic_exercises(unit, sibling_tags=_sibling_tags(subject_id, unit), facts=facts)
        doc = build_node_doc(unit, subject_id=subject_id, subject_label=subj.label,
                             exercises=exercises, lecture=lecture, facts=facts,
                             worked_examples=[{
                                 "prompt": f"示例：如何用一句话说清「{unit.title}」的核心内容？",
                                 "solution_steps": ["先说出本单元的核心概念（讲解第一句已给出）",
                                                    "再用自己的话解释它，并举一个讲解里出现过的例子"],
                             }],
                             asks=heuristic_asks(unit, lecture))
        report = answerability.gate_node(
            doc, known_concepts={str(t) for t in (unit.concept_tags or []) if str(t).strip()})
        a11y_problems = list(report.problems)
        problems = validate_generic_content(doc) + _answerability_structure_problems(doc, report)
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
) -> dict:
    """真模型学科化出稿（CALL_UNIT_CONTENT · light 档 · JSON schema 校验）。

    R35 S1/S2：出稿必须**同时产出** `taught_facts`（逐字取自讲解的事实句）、每题 `basis`
    （引用 fact_ids + 讲解原文引文）、`worked_examples ≥1`、以及带依据的 socratic `asks`。
    ⚠️ 新增输出字段三处同改（R36 §8 纪律）：`ai/calls.py` schema + 本 prompt + 往返用例。
    """
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
        '{"lecture":"Markdown 讲解（含 1 个直观例子）",'
        '"taught_facts":[{"id":"f1","text":"讲解里逐字出现过的一句话"}],'
        '"derivable":[{"conclusion":"可由已述事实推出的结论","premises":["f1","f2"],"rule":"所用规则"}],'
        '"worked_examples":[{"prompt":"例题题干","solution_steps":["步骤1","步骤2"]}],'
        '"asks":[{"ask":"引导确认/小思考（学生应能自己回答）","basis":{"fact_ids":["f1"],"quote":"讲解原文引文"}}],'
        '"feynman_task":"费曼口述任务（一段话）",'
        '"exercises":[{"kind":"boolean|choice|fill","prompt":"…",'
        '"answer_bool":true（boolean 用）,"options":[…],"answer_index":0（choice 用,0 起）,'
        '"expected":"…","aliases":[…]（fill 用）,'
        '"basis":{"fact_ids":["f1"],"quote":"讲解原文里逐字出现的一句依据"}}]}\n'
        "**可答性硬要求（R35，违反即被服务端丢弃）**：\n"
        "1) 零基础假设：学习者**只读过本单元讲解**，没教过的一律当不会（不许假设常识/课外知识）；\n"
        "2) `taught_facts[].text` 必须是**讲解里逐字出现过**的句子（≥6 字，不得改写）；\n"
        "3) 每道题/每条 asks 必须带 `basis`：`fact_ids` 只能引用上面声明的事实 id，"
        "`quote` 必须**逐字出自讲解**（≥6 字）；\n"
        "4) **只能问讲解讲过的东西**：可以复述已述事实，或由 ≥2 条已述事实经 `derivable` 里的规则推出；"
        "**不许问个体比较/排序/课外事实**（例：讲了「整类体积大」就不能问「哪一个最大」）；\n"
        "5) 讲解写了整类的性质时，**不要**出需要个体之间比较的题；\n"
        "6) `worked_examples` **至少 1 个**（示范如何合法作答）；`asks` 1–3 条，"
        "指代必须明确（禁止「这个概念/它」这类无指向的说法）；\n"
        "7) `exercises` 3–5 道且**至少含 2 种题型**、题面互不相同；判断陈述明确可判；讲解简洁准确。"
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
        basis = _basis_from(spec.get("basis"))
        if kind == "boolean":
            exercises.append(ExerciseDoc(
                id=f"b{i + 1}", kind="fixed", difficulty=min(unit.difficulty, 3), prompt=prompt,
                answer_bool=bool(spec.get("answer_bool")), basis=basis,
                check=CheckDoc(mode="boolean_judgment")))
        elif kind == "choice":
            options = [str(o) for o in (spec.get("options") or []) if str(o).strip()]
            idx = int(spec.get("answer_index") or 0)
            if not options:
                continue
            exercises.append(ExerciseDoc(
                id=f"c{i + 1}", kind="fixed", difficulty=min(unit.difficulty + 1, 3), prompt=prompt,
                options=options[:6], answer_index=max(0, min(idx, len(options) - 1)), basis=basis,
                check=CheckDoc(mode="single_choice")))
        elif kind == "fill":
            expected = str(spec.get("expected") or "").strip()
            if not expected:
                continue
            exercises.append(ExerciseDoc(
                id=f"f{i + 1}", kind="fixed", difficulty=min(unit.difficulty, 3), prompt=prompt,
                expected=expected, basis=basis,
                aliases=[str(a) for a in (spec.get("aliases") or []) if str(a).strip()],
                check=CheckDoc(mode="fill_text")))
    if not exercises:
        raise ValueError("AI 未输出任何可用练习题")
    return {
        "exercises": exercises,
        "task": str(data.get("feynman_task") or ""),
        "lecture": str(data.get("lecture") or ""),
        "facts": list(data.get("taught_facts") or []),
        "derivable": list(data.get("derivable") or []),
        "worked_examples": list(data.get("worked_examples") or []),
        "asks": list(data.get("asks") or []),
    }


def _basis_from(raw) -> BasisDoc | None:
    """把 AI/provider 的 basis（dict 或模型）转成 BasisDoc；缺失返回 None（→ 判为不可答）。"""
    if raw is None:
        return None
    if isinstance(raw, BasisDoc):
        return raw
    dump = getattr(raw, "model_dump", None)
    data = dump() if callable(dump) else (raw if isinstance(raw, dict) else None)
    if not data:
        return None
    return BasisDoc(
        fact_ids=[str(x) for x in (data.get("fact_ids") or []) if str(x).strip()],
        quote=str(data.get("quote") or ""),
        premises=[str(x) for x in (data.get("premises") or []) if str(x).strip()],
        rule=str(data.get("rule") or ""),
    )


__all__ = [
    "generate_unit_content",
    "heuristic_exercises",
    "build_node_doc",
    "validate_generic_content",
    "rubric_for",
]
