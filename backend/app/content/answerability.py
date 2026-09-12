"""app.content.answerability：**可答性**（R35）——"向学习者提出的问题必须能从已讲内容推出"。

原则（docs/09 R35 §2，一句话）：
> 任何问题（练习 / socratic / 🤔 小思考 / 追问）要么**复述已述事实**，要么**由 ≥2 条已述事实
> 经明确推理规则推出**；否则**不许出**。零基础假设：没教过的一律当不会。

本模块是这条规矩的**服务端判定**（学科无关，禁任何特例分支）：
- `taught_facts`：本单元**显式陈述**的事实句（`text` 必须**逐字出自讲解**，封闭集合）；
- `derivable`：允许的推理（结论 + 所依据的事实 id + 规则）；
- 每个问题的 `basis`：引用的 `fact_ids` + **讲解原文引文**（推理题另附 `premises` + `rule`）。

判定用的引文尺子是 `app.content.citations`（**单一实现**，R36 已收敛，`MIN_QUOTE_CHARS=6`）。

**R37 S5（教材锚定 · 第三类校验）**：有教材时，"已教集合"从"AI 写的讲解"**上移一层**到
**教材原文**——`taught_facts[].text` 与 `basis.quote` 还必须**逐字出自该学科材料正文**：
- 事实句在教材里找不到 → **丢弃该事实**（一条不剩 → 调用方判**整单元失败**，不得编造）；
- 题目/追问引文在教材里找不到 → **丢弃该题/该追问**（重试后仍不行就丢，不放行）；
- 违规信息全中文，并**说明缺什么**（"教材里没有这句话" vs "该句没讲到"），便于用户判断是
  模型编了、还是这一节确实没讲。**不做 OCR、不猜**。

兼容（S1）：**没有** `taught_facts` 的旧内容**不阻塞加载**，但**不得**通过可答性校验——
`gate_node()` 会把它标成 `verified=False` 并把其中的问题全部判为"未声明依据"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import citations
from .schemas import BasisDoc, Derivable, ExerciseDoc, FeynmanDoc, NodeDoc, TaughtFact

# 推理题（非"逐字复述"）须有 ≥2 条已述事实作前提 + 一条明确规则
MIN_PREMISES_FOR_REASONING = 2

NO_PACK_PROBLEM = (
    "未声明 taught_facts 知识包：旧内容不阻塞加载，但**不得**通过可答性校验"
    "（R35 S1；重新生成即可获得声明）"
)

# R37 S5：教材锚定的默认原文名（违规文案里对用户说"哪里找不到"）
MATERIAL_WHERE = "教材正文"
NO_MATERIAL_COVERAGE = (
    "教材未覆盖此单元：模型两轮都没能产出「逐字出自教材」的内容。"
    "可能是本节对应的教材段落没有讲到该主题，或模型在用自己的知识编——"
    "系统不编造、不落盘（R37 S3/S6）。"
)


@dataclass
class AnswerabilityReport:
    """一次判定结果（生成端据此**丢弃**不合规的问题，而不是让整份内容失败）。"""

    facts: list[TaughtFact] = field(default_factory=list)
    derivable: list[Derivable] = field(default_factory=list)
    exercises: list[ExerciseDoc] = field(default_factory=list)
    dropped_exercises: list[dict] = field(default_factory=list)
    dropped_facts: list[dict] = field(default_factory=list)   # R37 S5：教材里找不到的事实句
    asks: list[str] = field(default_factory=list)              # 存活的 socratic
    asks_basis: list[BasisDoc] = field(default_factory=list)
    dropped_asks: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    verified: bool = False                                     # 是否声明了知识包
    material_checked: bool = False                             # R37 S5：本次是否做了教材锚定

    @property
    def dropped(self) -> int:
        return len(self.dropped_exercises) + len(self.dropped_asks)


def _as_dict(raw) -> dict:
    """兼容 dict 与 pydantic 模型（NodeDoc 里已是 TaughtFact/Derivable 实例）。"""
    if isinstance(raw, dict):
        return raw
    dump = getattr(raw, "model_dump", None)
    if callable(dump):
        return dump()
    return {"text": str(raw)}


def fact_id_set(facts: list[TaughtFact]) -> set[str]:
    return {f.id for f in facts}


def _in_figure_only(text: str, material: str, figure_text: str,
                    material_where: str) -> str:
    """**R55 B**：该引文是不是"只落在引用了图/表的段落里"？是 → 返回中文原因，否则空串。

    判据：引文在**图段文本**里能逐字找到，而在**去掉图段的正文**里找不到
    → 它是那张图的说明文字，模型看不到图，**不许拿它当依据**（宁缺勿造）。
    """
    if not figure_text or not text:
        return ""
    ok_fig, _ = citations.check(text, figure_text, where=material_where)
    if not ok_fig:
        return ""
    clean = _strip_figure_segments(material)
    ok_clean, _ = citations.check(text, clean, where=material_where)
    if ok_clean:
        return ""      # 别处也有这句话 → 仍可作依据
    return (f"这句话只出现在{material_where}**引用了图/表**的段落里"
            "（原文说「如图/见表…」，但系统读不到图片内容）——按 R55 不猜，丢弃")


def _strip_figure_segments(material: str) -> str:
    """去掉"引用了图/表的句子"后的教材正文（与 materials 的**同一口径、同一实现**）。"""
    from ..outline.materials import non_figure_text

    return non_figure_text(material)


def clean_facts(raw_facts: list, lecture: str, *,
                known_concepts: set[str] | None = None,
                material: str = "", material_where: str = MATERIAL_WHERE,
                figure_text: str = "",
                ) -> tuple[list[TaughtFact], list[str], list[dict]]:
    """事实句归一 + 逐字来源校验：`text` 必须能在讲解里找到（citations 同一把尺子）。

    R37 S5：给了 `material`（教材正文）时，还**必须逐字出自教材**——找不到的事实句被丢弃，
    并给出中文原因（含"教材里没有这句话"与所在位置）。
    **R55 B**：``figure_text``（引用了图/表的段落）里的句子**不得**当依据（读不到图，不许猜）。

    `known_concepts`（R35 §11）：给出时，`concept_id` **必须指向已注册概念**，否则剔除并记问题——
    保证"讲过的概念/考的概念"共用同一套 id（不新建第二套概念系统）。

    返回 ``(保留的事实, 问题清单, 被丢弃的事实)``。
    """
    kept: list[TaughtFact] = []
    problems: list[str] = []
    dropped: list[dict] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_facts or [], start=1):
        item = _as_dict(raw)
        text = str(item.get("text") or "").strip()
        fid = str(item.get("id") or "").strip() or f"f{i}"
        concept_id = str(item.get("concept_id") or "").strip()
        if not text:
            continue
        ok, reason = citations.check(text, lecture, where="本单元讲解")
        if not ok:
            msg = f"事实 {fid} 未逐字出自讲解（{reason}）：{text[:40]}…"
            problems.append(msg)
            dropped.append({"id": fid, "text": text[:60], "reason": msg})
            continue
        if material:
            ok2, reason2 = citations.check(text, material, where=material_where)
            if not ok2:
                msg = (f"事实 {fid} 未逐字出自{material_where}（{reason2}）：{text[:40]}…"
                       "——教材里找不到这句话：可能是模型用自己的知识编的，"
                       "也可能本单元对应的教材段落没讲到它（教材锚定 R37 S5）")
                problems.append(msg)
                dropped.append({"id": fid, "text": text[:60], "reason": msg})
                continue
            fig_reason = _in_figure_only(text, material, figure_text, material_where)
            if fig_reason:
                msg = f"事实 {fid}：{fig_reason}：{text[:40]}…"
                problems.append(msg)
                dropped.append({"id": fid, "text": text[:60], "reason": msg,
                                "drop_kind": "figure_unavailable"})
                continue
        if concept_id and known_concepts is not None and concept_id not in known_concepts:
            problems.append(f"事实 {fid} 的 concept_id {concept_id!r} 未注册（须指向既有概念注册表）")
            continue
        if fid in seen_ids:
            fid = f"{fid}-{i}"
        seen_ids.add(fid)
        kept.append(TaughtFact(id=fid, text=text, concept_id=concept_id))
    return kept, problems, dropped


def clean_derivable(raw_items: list, fact_ids: set[str]) -> tuple[list[Derivable], list[str]]:
    """推理条目归一：前提必须是已声明事实、规则非空（结论不要求逐字）。"""
    kept: list[Derivable] = []
    problems: list[str] = []
    for raw in raw_items or []:
        item = _as_dict(raw)
        conclusion = str(item.get("conclusion") or "").strip()
        rule = str(item.get("rule") or "").strip()
        premises = [str(p) for p in (item.get("premises") or []) if str(p).strip()]
        if not conclusion:
            continue
        bad = [p for p in premises if p not in fact_ids]
        if not premises or bad or not rule:
            problems.append(
                f"推理条目不成立（前提 {premises or '空'} / 规则 {'有' if rule else '空'}）：{conclusion[:40]}"
            )
            continue
        kept.append(Derivable(conclusion=conclusion, premises=premises, rule=rule))
    return kept, problems


def check_basis(basis: BasisDoc | dict | None, *, lecture: str, fact_ids: set[str],
                derivable: list[Derivable] | None = None, label: str = "题目",
                material: str = "", material_where: str = MATERIAL_WHERE,
                figure_text: str = "") -> tuple[bool, str]:
    """单条 `basis` 判定 → (是否可答, 中文原因)。

    R37 S5：给了 `material` 时，引文还必须**逐字出自教材正文**（第三类校验，教材锚定）。
    **R55 B**：引文若只出现在"引用了图/表的段落"里 → 判不可答（读不到图，不许猜）。
    """
    if basis is None:
        return False, f"{label}未声明依据（basis 缺失）——零基础学习者无从推出，按不可答处理"
    b = basis if isinstance(basis, BasisDoc) else BasisDoc(**basis)
    ids = [str(x) for x in (b.fact_ids or []) if str(x).strip()]
    if not ids:
        return False, f"{label}未引用任何已述事实（basis.fact_ids 为空）"
    unknown = [x for x in ids if x not in fact_ids]
    if unknown:
        return False, f"{label}引用了未声明的事实 id：{'、'.join(unknown)}"
    if not str(b.quote or "").strip():
        return False, f"{label}未给出讲解原文引文（basis.quote 为空）"
    ok, reason = citations.check(b.quote, lecture, where="本单元讲解原文")
    if not ok:
        return False, f"{label}的引文不成立：{reason}"
    if material:
        ok2, reason2 = citations.check(b.quote, material, where=material_where)
        if not ok2:
            return False, (f"{label}的引文不在{material_where}中（教材锚定未通过：{reason2}）"
                           "——教材里没有这句话，不能拿它当出题依据（R37 S5）")
        fig_reason = _in_figure_only(str(b.quote), material, figure_text, material_where)
        if fig_reason:
            return False, f"{label}的引文{fig_reason}"
    premises = [str(x) for x in (b.premises or []) if str(x).strip()]
    rule = str(b.rule or "").strip()
    if premises or rule:  # 推理题：须 ≥2 条已述事实前提 + 明确规则
        bad = [p for p in premises if p not in fact_ids]
        if bad or len(premises) < MIN_PREMISES_FOR_REASONING or not rule:
            return False, (
                f"{label}属推理题，但前提不足或规则缺失（需 ≥{MIN_PREMISES_FOR_REASONING} 条已述事实 + rule；"
                f"当前 premises={premises or '空'}、rule={'有' if rule else '空'}）"
            )
        known = derivable or []
        if known and not any(
            set(premises) <= set(d.premises) and d.rule == rule for d in known
        ):
            return False, f"{label}的推理未落在本单元已声明的 derivable 内（须用本单元教过的规则）"
    return True, ""


def _drop_exercise(ex: ExerciseDoc, reason: str) -> dict:
    return {"id": ex.id, "prompt": (ex.prompt or "")[:60], "reason": reason}


def gate_node(doc: NodeDoc, *, drop: bool = True,
              known_concepts: set[str] | None = None,
              material: str | None = None,
              material_where: str = MATERIAL_WHERE,
              figure_text: str = "") -> AnswerabilityReport:
    """对一个 NodeDoc 做可答性判定（R35）＋**教材锚定**（R37 S5）。

    `drop=True`（生成端默认）：不合规的**核心题**与 socratic 一律**丢弃**（S5：丢弃该题，不是让内容失败），
    并把通过校验的事实/推理/题/追问回填到 doc（供落盘留档）。
    `drop=False`（审计/只读）：只报告，不改 doc。
    `known_concepts`（R35 §11）：给出时，`taught_facts[].concept_id` 必须落在其中。
    `material`（R37 S5）：给出时（该学科有教材），事实句与引文还必须**逐字出自教材正文**——
    这是闸门的**第三类校验**；教材里找不到的事实句被丢弃，一条不剩 → `report.facts` 为空，
    调用方据此判**整单元失败**（不得回退"自己编的启发式内容"）。
    `figure_text`（**R55 B**）：原文**引用了图/表**的段落——那里的句子不得当依据（读不到图，不许猜）。
    """
    lecture = doc.explanation.body or doc.body_md or ""
    material = material or ""
    facts, fp, dropped_facts = clean_facts(doc.taught_facts, lecture,
                                           known_concepts=known_concepts,
                                           material=material, material_where=material_where,
                                           figure_text=figure_text)
    derivable, dp = clean_derivable(doc.derivable, fact_id_set(facts))
    report = AnswerabilityReport(facts=facts, derivable=derivable,
                                 problems=list(fp) + list(dp),
                                 dropped_facts=dropped_facts,
                                 material_checked=bool(material))
    report.verified = bool(facts)
    if not facts:
        report.problems.append(NO_PACK_PROBLEM)
        if material:
            report.problems.append(NO_MATERIAL_COVERAGE)

    ids = fact_id_set(facts)
    kept_ex: list[ExerciseDoc] = []
    for ex in doc.exercises:
        ok, reason = check_basis(ex.basis, lecture=lecture, fact_ids=ids, derivable=derivable,
                                 label=f"练习 {ex.id}", material=material,
                                 material_where=material_where, figure_text=figure_text)
        if ok:
            kept_ex.append(ex)
        else:
            report.dropped_exercises.append(_drop_exercise(ex, reason))
            report.problems.append(f"练习 {ex.id} 丢弃：{reason}")
    report.exercises = kept_ex

    follows = list(doc.feynman.socratic_followups or [])
    bases = list(doc.feynman.socratic_basis or [])
    for i, ask in enumerate(follows):
        basis = bases[i] if i < len(bases) else None
        ok, reason = check_basis(basis, lecture=lecture, fact_ids=ids, derivable=derivable,
                                 label=f"socratic[{i + 1}]", material=material,
                                 material_where=material_where, figure_text=figure_text)
        if ok:
            report.asks.append(ask)
            report.asks_basis.append(basis if isinstance(basis, BasisDoc) else BasisDoc(**basis))
        else:
            report.dropped_asks.append({"ask": ask[:60], "reason": reason})
            report.problems.append(f"socratic[{i + 1}] 丢弃：{reason}")

    if drop:
        doc.taught_facts = facts
        doc.derivable = derivable
        doc.exercises = kept_ex
        doc.feynman = FeynmanDoc(
            task_prompt=doc.feynman.task_prompt,
            rubric=doc.feynman.rubric,
            socratic_followups=report.asks,
            socratic_basis=report.asks_basis,
            thinking=doc.feynman.thinking,
        )
    return report


def exercises_answerable(doc: NodeDoc) -> bool:
    """轻量布尔：核心题是否**全部**有据（不修改 doc）。"""
    lecture = doc.explanation.body or doc.body_md or ""
    ids = fact_id_set(clean_facts(doc.taught_facts, lecture)[0])
    return bool(doc.exercises) and all(
        check_basis(ex.basis, lecture=lecture, fact_ids=ids, label=ex.id)[0] for ex in doc.exercises
    )

def check_progression(doc: NodeDoc, prereq_docs: list[NodeDoc]) -> list[str]:
    """**P4 机器校验**（R36 欠账）：难度提升只能靠"已教事实的累积"。

    两条判定（都用 `taught_facts`/`derivable`，学科无关）：
    1. **引用必须已教**：题/追问的 `basis.fact_ids` 必须落在
       「已教集合 = 本单元 taught_facts ∪ 已掌握前置单元的 taught_facts」内——
       引用了既非本单元、也非前置单元声明过的事实 → 违规（等于问没教过的）。
    2. **加难必须加事实**：若本单元的练习难度**高于**所有前置单元（或前置为空而难度≥2），
       则本单元必须**新增**至少一条已述事实；一条都不新增却更难 → 违规（凭空加难）。
    """
    problems: list[str] = []
    own_lecture = doc.explanation.body or doc.body_md or ""
    own_facts, _, _ = clean_facts(doc.taught_facts, own_lecture)
    own_ids = fact_id_set(own_facts)
    inherited: set[str] = set()
    for pd in prereq_docs or []:
        p_lecture = pd.explanation.body or pd.body_md or ""
        p_facts, _, _ = clean_facts(pd.taught_facts, p_lecture)
        inherited |= fact_id_set(p_facts)
    allowed = own_ids | inherited

    for ex in doc.exercises:
        if ex.basis is None:
            continue
        _b = ex.basis if isinstance(ex.basis, BasisDoc) else BasisDoc(**(ex.basis or {}))
        for fid in (_b.fact_ids or []):
            if str(fid) not in allowed:
                problems.append(
                    f"P4：练习 {ex.id} 引用了**未教过**的事实 id {fid!r}"
                    "（既不在本单元 taught_facts，也不在已学前置单元里）")
    prereq_levels = []
    for pd in prereq_docs or []:
        diffs = [e.difficulty for e in pd.exercises if e.difficulty]
        if diffs:
            prereq_levels.append(max(diffs))
    max_prereq = max(prereq_levels) if prereq_levels else 0
    my_diff = max([e.difficulty for e in doc.exercises if e.difficulty] or [0])
    new_facts = own_ids - inherited
    if my_diff > max_prereq and max_prereq > 0 and not new_facts:
        problems.append(
            f"P4：本单元练习难度 {my_diff} 高于全部前置单元（最高 {max_prereq}），"
            "但**没有新增任何已述事实**——难度提升必须靠已教事实的累积，不得凭空加难")
    if max_prereq == 0 and my_diff >= 2 and not own_facts:
        problems.append("P4：前置为空而难度≥2，但未声明任何已述事实（taught_facts 为空）")
    return problems


__all__ = [
    "MIN_PREMISES_FOR_REASONING",
    "NO_PACK_PROBLEM",
    "MATERIAL_WHERE",
    "NO_MATERIAL_COVERAGE",
    "AnswerabilityReport",
    "fact_id_set",
    "clean_facts",
    "clean_derivable",
    "check_basis",
    "gate_node",
    "check_progression",
    "exercises_answerable",
]
