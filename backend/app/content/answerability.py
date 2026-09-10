"""app.content.answerability：**可答性**（R35）——"向学习者提出的问题必须能从已讲内容推出"。

原则（docs/09 R35 §2，一句话）：
> 任何问题（练习 / socratic / 🤔 小思考 / 追问）要么**复述已述事实**，要么**由 ≥2 条已述事实
> 经明确推理规则推出**；否则**不许出**。零基础假设：没教过的一律当不会。

本模块是这条规矩的**服务端判定**（学科无关，禁任何特例分支）：
- `taught_facts`：本单元**显式陈述**的事实句（`text` 必须**逐字出自讲解**，封闭集合）；
- `derivable`：允许的推理（结论 + 所依据的事实 id + 规则）；
- 每个问题的 `basis`：引用的 `fact_ids` + **讲解原文引文**（推理题另附 `premises` + `rule`）。

判定用的引文尺子是 `app.content.citations`（**单一实现**，R36 已收敛，`MIN_QUOTE_CHARS=6`）。

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


@dataclass
class AnswerabilityReport:
    """一次判定结果（生成端据此**丢弃**不合规的问题，而不是让整份内容失败）。"""

    facts: list[TaughtFact] = field(default_factory=list)
    derivable: list[Derivable] = field(default_factory=list)
    exercises: list[ExerciseDoc] = field(default_factory=list)
    dropped_exercises: list[dict] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)              # 存活的 socratic
    asks_basis: list[BasisDoc] = field(default_factory=list)
    dropped_asks: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    verified: bool = False                                     # 是否声明了知识包

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


def clean_facts(raw_facts: list, lecture: str) -> tuple[list[TaughtFact], list[str]]:
    """事实句归一 + 逐字来源校验：`text` 必须能在讲解里找到（citations 同一把尺子）。"""
    kept: list[TaughtFact] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_facts or [], start=1):
        item = _as_dict(raw)
        text = str(item.get("text") or "").strip()
        fid = str(item.get("id") or "").strip() or f"f{i}"
        if not text:
            continue
        ok, reason = citations.check(text, lecture, where="本单元讲解")
        if not ok:
            problems.append(f"事实 {fid} 未逐字出自讲解（{reason}）：{text[:40]}…")
            continue
        if fid in seen_ids:
            fid = f"{fid}-{i}"
        seen_ids.add(fid)
        kept.append(TaughtFact(id=fid, text=text))
    return kept, problems


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
                derivable: list[Derivable] | None = None, label: str = "题目") -> tuple[bool, str]:
    """单条 `basis` 判定 → (是否可答, 中文原因)。"""
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


def gate_node(doc: NodeDoc, *, drop: bool = True) -> AnswerabilityReport:
    """对一个 NodeDoc 做可答性判定。

    `drop=True`（生成端默认）：不合规的**核心题**与 socratic 一律**丢弃**（S5：丢弃该题，不是让内容失败），
    并把通过校验的事实/推理/题/追问回填到 doc（供落盘留档）。
    `drop=False`（审计/只读）：只报告，不改 doc。
    """
    lecture = doc.explanation.body or doc.body_md or ""
    facts, fp = clean_facts(doc.taught_facts, lecture)
    derivable, dp = clean_derivable(doc.derivable, fact_id_set(facts))
    report = AnswerabilityReport(facts=facts, derivable=derivable, problems=list(fp) + list(dp))
    report.verified = bool(facts)
    if not facts:
        report.problems.append(NO_PACK_PROBLEM)

    ids = fact_id_set(facts)
    kept_ex: list[ExerciseDoc] = []
    for ex in doc.exercises:
        ok, reason = check_basis(ex.basis, lecture=lecture, fact_ids=ids, derivable=derivable,
                                 label=f"练习 {ex.id}")
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
                                 label=f"socratic[{i + 1}]")
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


__all__ = [
    "MIN_PREMISES_FOR_REASONING",
    "NO_PACK_PROBLEM",
    "AnswerabilityReport",
    "fact_id_set",
    "clean_facts",
    "clean_derivable",
    "check_basis",
    "gate_node",
    "exercises_answerable",
]
