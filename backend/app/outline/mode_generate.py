"""outline.mode_generate：**图示教材模式的单元内容生成**（R56 第 3 步的收尾件）。

口径（工单 §1：程序只负责四件事）：

1. 把该单元相关页面的"读到了什么"交给模型 → `mode_lesson` 写讲解、`mode_exercise` 出题
   （**标准答案与解析由模型给**）；
2. 组装成与既有内容库**同一种**节点文件（`node_<unit>_auto.md`），题目用 `check.mode="ai"`
   ——于是既有的懒生成/库同步/会话状态机全部照用（**流程骨架照旧**）；
3. **不走**路径②的任何一道机器：不调 `_ai_draft`、不做教材锚定/可答性闸门/引文比对、
   题目也不进 sympy 自检（`verify.check_node` 只查 `kind=="template"`，本模式的题一律 `fixed`）。

诚实边界照旧：读不出来的页在页面记录里已经写明，模型被明确要求"读不到就少讲/少出题"，
并且出题/讲解结果里哪些地方不确定都进审计（`ai_trace`）与返回值。
"""
from __future__ import annotations

from ..ai.calls import ModeExerciseIn, ModeLessonIn
from ..content.schemas import CheckDoc, ExerciseDoc, ExplanationDoc, NodeDoc
from ..service import mode_ai
from . import materials as mat
from . import mode_pages

MAX_AI_EXERCISES = 6


def generate_mode_unit(db, subject_id: str, unit, *, provider=None, want_count: int = 3) -> dict:
    """给一个单元生成"全 AI 模式"的内容并落盘 → ``{status, node_id, path, note, ...}``。"""
    pages = mode_pages.pages_digest(db, subject_id)
    if not pages.strip():
        from .schemas import OutlineError

        raise OutlineError("这个学科还没有页面记录：先用「图片为主的教材」导入页面图片，再生成内容")
    if provider is None:
        provider = _build_provider(db)

    lesson = mode_ai.lesson(provider, ModeLessonIn(
        unit_title=unit.title, objectives=list(unit.objectives or []), pages_digest=pages),
        subject_id=subject_id, unit_id=unit.id)
    exercises = mode_ai.exercises(provider, ModeExerciseIn(
        unit_title=unit.title, key_points=list(lesson.key_points or []), pages_digest=pages,
        want_count=max(1, min(want_count, MAX_AI_EXERCISES)), kind="practice"),
        subject_id=subject_id, unit_id=unit.id)

    doc = _to_node_doc(subject_id, unit, lesson, exercises)
    path = _write_node(doc)
    from ..service.library import refresh_library, sync_content

    refresh_library()
    out = sync_content(db)
    db.commit()
    if not out.ok:
        return {"status": "failed", "node_id": unit.id, "path": str(path),
                "note": "；".join(out.errors[:3])}
    return {"status": "created", "node_id": unit.id, "path": str(path),
            "note": (f"出稿：全 AI 模式（模型写讲解 + 出题，共 {len(doc.exercises)} 题）"
                     f"；这个模式没有独立的第二次核对"),
            "source_pages": list(lesson.source_pages or []),
            "lesson_uncertain": bool(lesson.uncertain),
            "exercise_uncertain": bool(exercises.uncertain)}


def _to_node_doc(subject_id: str, unit, lesson, exercises, subject_label: str = "") -> NodeDoc:
    """组装成**与路径②同一种**节点文件（复用 `build_node_doc`：rubric/费曼任务/结构都照旧）。"""
    from .generate import build_node_doc

    exs: list[ExerciseDoc] = []
    for i, e in enumerate(exercises.exercises or [], start=1):
        if not str(e.prompt or "").strip() or not str(e.answer or "").strip():
            continue          # 题面或答案不全的题**直接不要**（不许硬凑）
        exs.append(ExerciseDoc(
            id=f"ai{i}", kind="fixed", difficulty=int(getattr(unit, "difficulty", 1) or 1),
            prompt=str(e.prompt), options=list(e.options or []),
            check=CheckDoc(mode="ai", answer=str(e.answer),
                           explanation=str(e.explanation or ""),
                           basis_pages=[str(p) for p in (e.basis_pages or [])],
                           answer_kind=str(e.kind or "")),
            interactive=["workbench"]))
    if not exs:
        from .schemas import OutlineError

        raise OutlineError("模型这次没给出可用的题（题面或标准答案缺失）——这些页面可能读不出来，"
                           "请补更清晰的页面图片后重试")
    doc = build_node_doc(
        unit, subject_id=subject_id, subject_label=subject_label or "教材",
        exercises=exs,
        feynman_task=(f"请你用自己的话把「{unit.title}」讲一遍："
                      "讲清这一单元讲了什么、关键点是什么；讲完后我会追问。"),
        lecture=str(lesson.lecture_md or "").strip() or "（这一单元暂无讲解）",
        facts=[], derivable=[],
        worked_examples=list(lesson.worked_examples or []), asks=[])
    note = _boundary_note(lesson, exercises)
    doc.explanation.body = doc.explanation.body.rstrip() + "\n\n" + note
    doc.body_md = doc.body_md.rstrip() + "\n\n" + note
    return doc


def _boundary_note(lesson, exercises) -> str:
    lines = ["## 这个模式要说清的一件事",
             "讲解与题目都由模型给出，**程序没有替你复核**（没有独立的第二次核对，数学题也一样）；",
             "依据只能指到「页/图号」，没有逐字原文可查。"]
    if getattr(lesson, "uncertain", False):
        lines.append(f"> 讲解里有不确定的地方：{lesson.uncertain_reason}")
    if getattr(exercises, "uncertain", False):
        lines.append(f"> 出题时有保留：{exercises.uncertain_reason}")
    return "\n".join(lines)


def _write_node(doc: NodeDoc):
    from .generate import _frontmatter_md, _node_file_path

    path = _node_file_path(doc.id.split(".")[0], doc.id)
    path.write_text(_frontmatter_md(doc), encoding="utf-8")
    return path


def _build_provider(db):
    from ..ai.provider import OpenAICompatibleProvider
    from ..service import model_config
    from ..service.ai_sink import make_ai_log_sink

    s = model_config.effective_settings(db)
    return OpenAICompatibleProvider(
        api_key=s.llm_api_key, base_url=s.llm_base_url,
        model_heavy=s.llm_model_heavy, model_light=model_config.vision_model(db),
        log_sink=make_ai_log_sink())


__all__ = ["MAX_AI_EXERCISES", "generate_mode_unit"]
