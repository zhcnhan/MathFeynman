"""service.mode_ai：**图示教材模式（全 AI 模式）** 的服务端分支（R56 第 2 步）。

这个模块是"程序只负责四件事"的落点：**装提示词 → 调模型 → 校验结构化输出 → 记账**。
除此之外它**故意什么都不做**（工单 §1 明确禁止）：

- ❌ 不用 sympy 独立验算答案（判对错由模型做）；
- ❌ 不做"可答性闸门"式的机器筛题（那是文字教材路径的规矩）；
- ❌ 不做"引文逐字比对"（本模式没有可检索原文，依据只能指到页/图号）；
- ❌ 不用规则改判模型给的分（分就是模型给的）。

**唯一的例外是"诚实出口"**（工单 §5-任务 C）：模型说"我判不了/读不出来"时，
这里**必须**把它如实透出并记一条中文账，**不许**静默当成答错或答对。
"""
from __future__ import annotations

from typing import Any

from ..ai import prompt_runtime
from ..ai.calls import (
    CALL_MODE_EXERCISE,
    CALL_MODE_FEYNMAN,
    CALL_MODE_FOLLOWUP,
    CALL_MODE_GAP_CHECK,
    CALL_MODE_JUDGE,
    CALL_MODE_LESSON,
    CALL_MODE_OUTLINE,
    CALL_MODE_QA,
    ModeExerciseIn,
    ModeExerciseOut,
    ModeFeynmanIn,
    ModeFeynmanOut,
    ModeFollowupIn,
    ModeFollowupOut,
    ModeGapCheckIn,
    ModeGapCheckOut,
    ModeJudgeIn,
    ModeJudgeOut,
    ModeLessonIn,
    ModeLessonOut,
    ModeOutlineIn,
    ModeOutlineOut,
    ModeQaIn,
    ModeQaOut,
)
from ..ai.prompt_templates import UI_PLACEHOLDER_DEFAULTS, render
from . import ledger

MODE_LABEL = "图示教材模式"


# ---------------------------------------------------------------------------
# 渲染 + 调用（唯一入口；用户改过提示词后**下一次调用即生效**）
# ---------------------------------------------------------------------------
def _render(call_name: str, *, task_vars: dict[str, Any], subject_id: str = "",
            unit_id: str = "") -> tuple[str, str, str]:
    """取生效模板并渲染 → ``(system, user, 版本标签)``（与既有 gateway 同一套运行机制）。"""
    rt = prompt_runtime.PromptRuntime(call_name, subject_id=subject_id, unit_id=unit_id)
    vars_: dict[str, str] = dict(UI_PLACEHOLDER_DEFAULTS)
    for k, v in (task_vars or {}).items():
        vars_[k] = v if isinstance(v, str) else _as_text(v)
    return render(rt.system_template, **vars_), render(rt.user_template, **vars_), rt.version


def _as_text(v: Any) -> str:
    import json

    if isinstance(v, (list, dict)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return str(v)


def _call(provider, call, system: str, user: str, version: str, *, subject_id: str = "",
          unit_id: str = ""):
    return provider.chat_json(
        call, [{"role": "system", "content": system}, {"role": "user", "content": user}],
        audit={"subject_id": subject_id, "unit_id": unit_id, "prompt_versions": version},
    )


def _digest(pages: list[dict] | list[str] | str) -> str:
    """把"各页读到了什么"拼成给模型看的摘要（只搬运，不改写、不删减）。"""
    if isinstance(pages, str):
        return pages
    lines: list[str] = []
    for item in pages or []:
        if isinstance(item, str):
            lines.append(item)
            continue
        label = str((item or {}).get("page_label") or "")
        if (item or {}).get("readable") is False:
            lines.append(f"[{label}] ⚠️ 这一页读不出来："
                         f"{str((item or {}).get('unreadable_reason') or '（没写原因）')}")
            continue
        bits: list[str] = []
        for key, title in (("key_points", "要点"), ("visible_text", "页面文字"),
                           ("formulas", "公式")):
            vals = [str(x) for x in ((item or {}).get(key) or []) if str(x).strip()]
            if vals:
                bits.append(f"{title}：" + "；".join(vals))
        figs = [f"{str(f.get('label') or '图')}（{str(f.get('kind') or '图')}）："
                f"{str(f.get('description') or '')}"
                for f in ((item or {}).get("figures") or [])]
        if figs:
            bits.append("图：" + "；".join(figs))
        unc = [str(x) for x in ((item or {}).get("uncertain") or []) if str(x).strip()]
        if unc:
            bits.append("看不清：" + "；".join(unc))
        lines.append(f"[{label}] " + ("；".join(bits) or "（这一页没有可用内容）"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 各环节（每个都对应一个可单独修改的提示词调用点）
# ---------------------------------------------------------------------------
def outline(provider, ctx: ModeOutlineIn, *, subject_id: str = "", unit_id: str = "",
            pages: list[dict] | str = "") -> ModeOutlineOut:
    system, user, ver = _render("mode_outline", subject_id=subject_id, unit_id=unit_id, task_vars={
        "subject_label": ctx.subject_label, "brief": ctx.brief, "want_count": str(ctx.want_count),
        "pages_digest": _digest(pages or ctx.pages_digest), "errors_block": ctx.errors,
    })
    return ModeOutlineOut(**_call(provider, CALL_MODE_OUTLINE, system, user, ver,
                                  subject_id=subject_id, unit_id=unit_id).parsed)


def lesson(provider, ctx: ModeLessonIn, *, subject_id: str = "", unit_id: str = "",
           pages: list[dict] | str = "") -> ModeLessonOut:
    system, user, ver = _render("mode_lesson", subject_id=subject_id, unit_id=unit_id, task_vars={
        "unit_title": ctx.unit_title, "objectives": ctx.objectives,
        "pages_digest": _digest(pages or ctx.pages_digest), "errors_block": ctx.errors,
    })
    return ModeLessonOut(**_call(provider, CALL_MODE_LESSON, system, user, ver,
                                 subject_id=subject_id, unit_id=unit_id).parsed)


def exercises(provider, ctx: ModeExerciseIn, *, subject_id: str = "", unit_id: str = "",
              pages: list[dict] | str = "") -> ModeExerciseOut:
    system, user, ver = _render("mode_exercise", subject_id=subject_id, unit_id=unit_id, task_vars={
        "unit_title": ctx.unit_title, "key_points": ctx.key_points,
        "want_count": str(ctx.want_count), "exercise_kind": ctx.kind,
        "asked_before": ctx.asked_before, "pages_digest": _digest(pages or ctx.pages_digest),
    })
    return ModeExerciseOut(**_call(provider, CALL_MODE_EXERCISE, system, user, ver,
                                   subject_id=subject_id, unit_id=unit_id).parsed)


def judge(provider, ctx: ModeJudgeIn, *, subject_id: str = "", unit_id: str = "",
          pages: list[dict] | str = "") -> dict:
    """判对错 → **带诚实出口**的判定结果。

    返回 ``{status, verdict, score_0_1, feedback_md, better_md, basis_pages, reason_zh, counted}``：
    - ``status ∈ correct | partial | wrong | uncertain``；
    - ``uncertain`` → **不打分、不计掌握**，并把中文原因记进唯一账本（不许静默当错/当对）；
    - 其它状态的分与结论**原样来自模型**（服务端不用规则改分）。
    """
    system, user, ver = _render("mode_judge", subject_id=subject_id, unit_id=unit_id, task_vars={
        "prompt": ctx.prompt, "kind": ctx.kind, "options": ctx.options,
        "reference_answer": ctx.reference_answer, "explanation": ctx.explanation,
        "student_answer": ctx.student_answer, "pages_digest": _digest(pages or ctx.pages_digest),
    })
    out = ModeJudgeOut(**_call(provider, CALL_MODE_JUDGE, system, user, ver,
                               subject_id=subject_id, unit_id=unit_id).parsed)
    if out.verdict == "uncertain":
        reason = (out.uncertain_reason or "").strip() or "模型没能判断这次作答（没有说明原因）"
        _note_uncertain("判题", reason, subject_id=subject_id, unit_id=unit_id,
                        detail={"kind": "judge_uncertain", "prompt": ctx.prompt[:120],
                                "prompt_versions": ver})
        return {"status": "uncertain", "verdict": "uncertain", "score_0_1": 0.0,
                "feedback_md": out.feedback_md, "better_md": out.better_md,
                "basis_pages": list(out.basis_pages), "counted": False,
                "reason_zh": f"这一次没判出来：{reason}（已经如实告诉你，不算对也不算错）"}
    return {"status": out.verdict, "verdict": out.verdict,
            "score_0_1": float(out.score_0_1 or 0.0),
            "feedback_md": out.feedback_md, "better_md": out.better_md,
            "basis_pages": list(out.basis_pages), "counted": True,
            "reason_zh": {"correct": "答对了", "partial": "答对了一部分",
                          "wrong": "这次答错了"}.get(out.verdict, out.verdict)}


def feynman(provider, ctx: ModeFeynmanIn, *, subject_id: str = "", unit_id: str = "",
            pages: list[dict] | str = "") -> ModeFeynmanOut:
    system, user, ver = _render("mode_feynman", subject_id=subject_id, unit_id=unit_id, task_vars={
        "task_prompt": ctx.task_prompt, "dimensions": ctx.dimensions,
        "pages_digest": _digest(pages or ctx.pages_digest), "transcript": ctx.transcript,
    })
    out = ModeFeynmanOut(**_call(provider, CALL_MODE_FEYNMAN, system, user, ver,
                                 subject_id=subject_id, unit_id=unit_id).parsed)
    if out.verdict == "uncertain":
        # 评不出来就不给结论：**不通过也不判失败**，如实说"这次评不了"（不许硬给分）
        reason = (out.uncertain_reason or "").strip() or "模型没能评这次口述（没有说明原因）"
        _note_uncertain("费曼评分", reason, subject_id=subject_id, unit_id=unit_id,
                        detail={"kind": "feynman_uncertain", "prompt_versions": ver})
        out = out.model_copy(update={"overall_note": (out.overall_note or "") +
                                     f"（这次评不了：{reason}）",
                                     "dimension_scores": []})
    return out


def followup(provider, ctx: ModeFollowupIn, *, subject_id: str = "", unit_id: str = "",
             pages: list[dict] | str = "") -> ModeFollowupOut:
    system, user, ver = _render("mode_followup", subject_id=subject_id, unit_id=unit_id, task_vars={
        "missing": ctx.missing, "pages_digest": _digest(pages or ctx.pages_digest),
        "transcript": ctx.transcript,
    })
    return ModeFollowupOut(**_call(provider, CALL_MODE_FOLLOWUP, system, user, ver,
                                   subject_id=subject_id, unit_id=unit_id).parsed)


def gap_check(provider, ctx: ModeGapCheckIn, *, subject_id: str = "", unit_id: str = "",
              pages: list[dict] | str = "") -> ModeGapCheckOut:
    system, user, ver = _render("mode_gap_check", subject_id=subject_id, unit_id=unit_id,
                                task_vars={
                                    "followup_question": ctx.followup_question,
                                    "target_dimension": ctx.target_dimension,
                                    "student_answer": ctx.student_answer,
                                    "pages_digest": _digest(pages or ctx.pages_digest),
                                })
    out = ModeGapCheckOut(**_call(provider, CALL_MODE_GAP_CHECK, system, user, ver,
                                  subject_id=subject_id, unit_id=unit_id).parsed)
    if out.uncertain:
        reason = (out.uncertain_reason or "").strip() or "模型没能判断这次补答（没有说明原因）"
        _note_uncertain("补答评估", reason, subject_id=subject_id, unit_id=unit_id,
                        detail={"kind": "gap_check_uncertain", "prompt_versions": ver})
        out = out.model_copy(update={"gap_filled": False, "score_0_1": 0.0})
    return out


def qa(provider, ctx: ModeQaIn, *, subject_id: str = "", unit_id: str = "",
       pages: list[dict] | str = "") -> ModeQaOut:
    system, user, ver = _render("mode_qa", subject_id=subject_id, unit_id=unit_id, task_vars={
        "unit_title": ctx.unit_title, "question": ctx.question,
        "pages_digest": _digest(pages or ctx.pages_digest),
    })
    return ModeQaOut(**_call(provider, CALL_MODE_QA, system, user, ver,
                             subject_id=subject_id, unit_id=unit_id).parsed)


def _note_uncertain(what: str, reason: str, *, subject_id: str, unit_id: str,
                    detail: dict | None = None) -> None:
    """**诚实出口必须可见**（工单 §5）：记一条中文账（就地提示 + 记录页都能看到）。"""
    ledger.note(
        ledger.CAT_MODEL_CALL, f"{what}（{MODE_LABEL}）",
        f"这一次没判出来：{reason}——已如实告诉学生（不算对也不算错，不硬给结论）。"
        "这个模式没有独立的第二次核对，所以宁可说「看不出来」。",
        impact=ledger.SCOPE_UNIT, remedy=ledger.REMEDY_CONFIRM,
        subject_id=subject_id, unit_id=unit_id, detail=dict(detail or {}),
    )


__all__ = ["MODE_LABEL", "outline", "lesson", "exercises", "judge", "feynman", "followup",
           "gap_check", "qa"]
