"""app.outline.generate：通用学科单元内容的懒生成（docs/14 §2.3 · Phase A A4）。

语义：Outline 只存元数据；单元 Content 按需生成（学到哪条生成哪条），沿用现有流水线的
机制语义——落盘文件标注 source:auto（可被 `*_auto` 隔离/纠错识别），生成后刷新库并 DB 同步，
后续讲解/练习/费曼沿用既有 NodeDoc 会话状态机（判题：通用学科语义题走 boolean_judgment/
manual_review 确定性或费曼评估；数学内容仍走 sympy L1，本模块不触碰 math）。

通用学科内容形态（文档 v1）：
- id = 单元 id（`<subject>.<local>`，内容节点即大纲单元内容节点）；
- level = 单元分组（关卡组标识，非 LEVELS——图引擎/总序门禁已学科化：见 service/outline_gate）；
- prereqs = []：学习顺序权威 = 大纲门禁（不在内容文件复制依赖，防大纲重构后内容边悬空）；
- objectives/concept_tags 来自大纲单元；core_concepts = 概念标签原文；
- 练习：1 道 fixed + boolean_judgment（语义判断题，确定性可验）；费曼任务默认 rubric 四维。

出稿器：stub（无 key 离线机制验证：确定性文稿）或 ai（LLM_API_KEY 存在时经 ai/drafting
统一 schema 化入口生成文稿；学科化 rubric/题目块模板属 docs/14 Phase B 范围）。
"""
from __future__ import annotations

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
from ..db import Session  # noqa: F401  (类型标注)
from ..outline import store as outline_store
from .schemas import OutlineDoc, OutlineError, OutlineUnit

_GENERIC_RUBRIC = RubricDoc(
    dimensions=[
        RubricDimension(key="correctness", weight=0.4, description="概念正确性：核心内容无事实错误"),
        RubricDimension(key="own_words", weight=0.3, description="用自己的话：能脱离原文复述"),
        RubricDimension(key="example_and_edge", weight=0.2, description="例子与边界：有例证、知例外"),
        RubricDimension(key="self_correction", weight=0.1, description="自纠能力：被追问时能自我修正"),
    ],
    pass_threshold=0.7,
)

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(s: str) -> str:
    return _FILENAME_SAFE.sub("_", s).strip("_")[:48] or "unit"


def make_unit_node_doc(unit: OutlineUnit, *, subject_label: str = "") -> NodeDoc:
    """由大纲单元构造通用学科内容节点文档（stub 出稿：确定性机制文稿）。

    讲解稿 = 目标驱动演绎 + 自查问题；练习 = 语义判断题（boolean_judgment，固定期望由出稿器
    给出——stub 以目标成真句式表达，供机制验证；AI 出稿时由模型给出真实判断题与答案）。
    """
    objectives = list(unit.objectives) or ["理解本单元核心内容"]
    explain_lines = [
        f"# {unit.title}",
        "",
        f"【{subject_label or unit.group} · 学习目标】",
    ]
    explain_lines += [f"- {o}" for o in objectives]
    explain_lines += [
        "",
        "## 讲解",
        "本单元围绕上述目标展开。学习时请抓住每个目标对应的关键概念",
        "（" + ("、".join(unit.concept_tags) if unit.concept_tags else "见目标") + "），",
        "用自己的话讲给 AI 听，并通过自查题确认理解无误。",
        "",
        "## 自查",
        "对照学习目标逐条检查：能否不看书向他人解释本单元内容？能否举出实例、说出适用边界？",
    ]
    # 语义判断题（固定期望 = True：陈述直接取自学习目标，机制验证用；AI 出稿时可生成假命题）
    question = "完成本单元学习目标后，你能用自己的话向他人解释本单元的核心内容。"
    exercise = ExerciseDoc(
        id="semantic-check",
        kind="fixed",
        difficulty=unit.difficulty,
        prompt=question + "（请回答 对 / 错）",
        answer_bool=True,
        check=CheckDoc(mode="boolean_judgment"),
        interactive=["workbench"],
    )
    return NodeDoc(
        id=unit.id,
        title=unit.title,
        level=unit.group or unit.id.partition(".")[0],
        topic=unit.group,
        prereqs=[],  # 学习顺序权威 = 大纲门禁（service.outline_gate）
        kind="normal",
        objectives=objectives,
        core_concepts=list(unit.concept_tags),
        explanation=ExplanationDoc(role="教师讲解稿", body="\n".join(explain_lines)),
        worked_examples=[],
        exercises=[exercise],
        feynman=FeynmanDoc(
            task_prompt=(
                f"请你把「{unit.title}」完整地讲给 AI 听（用自己的话，讲清概念与目标要点，"
                f"可举例与说明边界）；讲完后 AI 会按 rubric 追问。"
            ),
            rubric=_GENERIC_RUBRIC,
            socratic_followups=[
                "这个概念能举一个例子说明吗？",
                "在什么情况下这个概念/方法不适用（边界与例外）？",
                "它与你之前学过的内容有什么联系？",
            ],
            thinking=False,
        ),
        body_md="\n".join(explain_lines),
    )


def _node_file_path(subject_id: str, node_id: str) -> Path:
    safe = _slug(node_id)
    d = stages_dir() / subject_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"node_{safe}_auto.md"


def _node_yaml(obj: dict) -> str:
    import yaml

    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=100).rstrip()


def _render_frontmatter(doc: NodeDoc, body: str) -> str:
    fm = {
        "id": doc.id,
        "title": doc.title,
        "level": doc.level,
        "topic": doc.topic,
        "prereqs": doc.prereqs,
        "kind": doc.kind,
        "objectives": doc.objectives,
        "core_concepts": doc.core_concepts,
        "source": "auto",  # 现有流水线语义：auto 节点可被纠错/熔断治理（docs/10 §3）
        "explanation": {"role": "教师讲解稿", "body": doc.explanation.body},
        "exercises": [
            {
                "id": e.id,
                "kind": e.kind,
                "difficulty": e.difficulty,
                "prompt": e.prompt,
                "answer_bool": e.answer_bool,
                "check": {"mode": e.check.mode},
                "interactive": e.interactive,
            }
            for e in doc.exercises
        ],
        "feynman": {
            "task_prompt": doc.feynman.task_prompt,
            "rubric": {
                "dimensions": [
                    {"key": d.key, "weight": d.weight, "description": d.description}
                    for d in doc.feynman.rubric.dimensions
                ],
                "pass_threshold": doc.feynman.rubric.pass_threshold,
            },
            "socratic_followups": doc.feynman.socratic_followups,
            "thinking": doc.feynman.thinking,
        },
    }
    return "\n".join(["---", _node_yaml(fm), "---", "", body or doc.body_md])


def generate_unit_content(db, subject_id: str, unit_id: str, *, force: bool = False) -> dict:
    """懒生成单元内容（source:auto 落盘 → 刷新库 → DB 同步 → 状态重算）。

    幂等：已有内容（库中或已落盘）→ 返回 exists（不重复出稿）；force=True 时重写。
    返回 {status: created|exists|failed, node_id, path, subject, unit}
    """
    subj = outline_store.get_subject(db, subject_id)
    if subj is None:
        raise OutlineError(f"学科未注册: {subject_id}")
    if subj.kind == "preset":
        raise OutlineError("math preset 内容由 roadmap 蓝图流水线生成（懒生成数学自动节点不走本模块）")
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
    doc = make_unit_node_doc(unit, subject_label=subj.label)
    body = doc.body_md
    doc.body_md = body
    path = _node_file_path(subject_id, unit.id)
    text = _render_frontmatter(doc, body)
    path.write_text(text, encoding="utf-8")
    from ..service.library import refresh_library, sync_content

    refresh_library()
    report = sync_content(db)
    db.commit()
    if not report.ok:
        return {"status": "failed", "node_id": unit.id, "path": str(path),
                "subject": subject_id, "unit": unit_id, "note": "；".join(report.errors[:3])}
    return {"status": "created", "node_id": unit.id, "path": str(path),
            "subject": subject_id, "unit": unit_id, "note": ""}


__all__ = ["generate_unit_content", "make_unit_node_doc"]
