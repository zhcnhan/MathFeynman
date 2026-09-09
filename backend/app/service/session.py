"""service.session：单知识点教学会话状态机（docs/05 §2、06 §2 契约）。

流程：START → explain(讲解/答疑) → example(例题) → practice(练习，sympy 判题)
     → feynman(口述评分+追问) → END(mastery 达标 → FSRS 首次排程)。

- 状态机是程序真源：LLM 只经 AiGateway 以 schema 化调用点返回数据，service 裁决后生效；
  任何 AiCallError → 内容库兜底/人工复核，不脏状态（docs/05 §6）。
- 会话可中断/恢复：flow_json 全量持久化于 sessions 表。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import models
from ..ai.calls import (
    AiCallError,
    AnswerQuestionIn,
    ClassifyErrorIn,
    ExplainIn,
    FeynmanEvaluateIn,
    FeynmanFollowupIn,
    HintOnErrorIn,
)
from ..ai import tier as ai_tier
from ..ai.gateway import AiGateway, MIN_FEYNMAN_CHARS
from ..content.schemas import NodeDoc
from ..content.templates import RenderedExercise, render_exercise
from ..domain import judge as judge_mod
from ..domain.judge import JudgeError, JudgeResult, NotationError
from ..domain.mastery import MISS_REASON_FEYNMAN, MISS_REASON_PRACTICE, MasteryStats, evaluate_pass
from ..domain.profile import Profile
from . import progress, review as review_svc
from .library import ensure_user, get_library
from .progress import mark_learning, mark_mastered

STAGE_EXPLAIN = "explain"
STAGE_EXAMPLE = "example"
STAGE_PRACTICE = "practice"
STAGE_FEYNMAN = "feynman"
STAGE_DONE = "done"

STAGE_ORDER = [STAGE_EXPLAIN, STAGE_EXAMPLE, STAGE_PRACTICE, STAGE_FEYNMAN, STAGE_DONE]

TARGET_STREAK = 3           # docs/03 §2：连续答对 ≥3
PRACTICE_CAP = 5            # docs/05 §2：练习上限 5 题（一轮）
MAX_FEYNMAN_ROUNDS = 3      # docs/05 §5：评分轮次上限（≤2 追问 + 首评）

ACTIONS = {
    "next",                # 阶段前进（讲解→例题→练习 等）
    "ask_question",
    "submit_exercise",
    "request_hint",
    "regen_explain",       # R8：清理 lecture_cache 并重新生成讲解（脏讲解/重新讲解入口）
    "feynman_submit",
    "feynman_answer",      # 别名：对追问的作答（等同 feynman_submit）
    "finish",
    "quit",
    "get",                 # 恢复/刷新当前步
}


class SessionError(ValueError):
    """会话状态非法（api 层映射 invalid_state / validation_error）。"""

    def __init__(self, message: str, code: str = "invalid_state"):
        self.code = code
        super().__init__(message)


class ExerciseBrokenError(SessionError):
    def __init__(self, message: str):
        super().__init__(message, code="exercise_broken")


# --------------------------------------------------------------------------
# flow 结构
# --------------------------------------------------------------------------
def new_flow() -> dict[str, Any]:
    return {
        "stage": STAGE_EXPLAIN,
        "lecture_cache": None,  # {lecture_md, asks, degraded}
        "practice": {
            "issued": 0,
            "streak": 0,
            "streak_min": None,
            "attempts_this": 0,
            "hints_this": 0,
            "current": None,  # {"exercise_id", "seed"}
            "passed": False,
            "cap_reached": False,
            "excluded": [],
        },
        "feynman": {
            "rounds_done": 0,
            "passed": False,
            "last_combined": None,
            "last_scores": [],
            "last_transcript": "",
            "followup": None,  # 最近一次追问文本
            "edge_think": False,      # R12：上轮 fast 边缘分 → 本轮升 think（消费一次）
            "last_strategy": None,    # R12：最近一轮评分所用档位（评分卡标注）
        },
    }


def _feynman_reset(f: dict[str, Any]) -> None:
    """R17：费曼阶段完整复位（回炉重学/轮次满防御用）。"""
    f.update(
        rounds_done=0,
        passed=False,
        last_combined=None,
        last_scores=[],
        last_transcript="",
        followup=None,
    )


def _practice_reset_cycle(p: dict[str, Any]) -> None:
    """回炉后开始新练习轮：保留 passed 与 excluded。"""
    p.update(
        issued=0,
        streak=0,
        streak_min=None,
        attempts_this=0,
        hints_this=0,
        current=None,
        cap_reached=False,
    )


def _seed_for(session_id: str, question_no: int, exercise_id: str) -> int:
    h = hashlib.sha1(f"{session_id}:{exercise_id}:{question_no}".encode()).hexdigest()
    return int(h[:8], 16)


# --------------------------------------------------------------------------
# 会话主服务
# --------------------------------------------------------------------------
class SessionService:
    def __init__(self, gateway: AiGateway, user_id: str = "local"):
        self.gateway = gateway
        self.user_id = user_id

    # ---------- 会话建立 ----------
    def start(self, db: Session, node_id: str) -> dict[str, Any]:
        lib = get_library()
        loaded = lib.by_id.get(node_id)
        if loaded is None:
            raise SessionError(f"节点不存在: {node_id}", code="not_found")
        ensure_user(db, self.user_id)
        # 已有进行中会话 → 恢复
        existing = (
            db.query(models.Session)
            .filter(
                models.Session.user_id == self.user_id,
                models.Session.node_id == node_id,
                models.Session.state.in_(["learning", "quit"]),
            )
            .order_by(models.Session.updated_at.desc())
            .first()
        )
        if existing:
            if existing.state == "quit":
                existing.state = "learning"
            existing.flow_json = json.loads(json.dumps(existing.flow_json or new_flow()))
            db.flush()
            return self.resume(db, existing.id)

        # 门禁：先判学科停用（B4"移除可恢复"：停用学科不可进入学习），再按学科分流——
        # 通用学科（custom）走大纲权威（service.outline_gate）；math 走蓝图总序（service.path）。
        # 仅"进入新节点"受控（既有会话恢复/练习费曼续走不受影响）。
        from . import outline_gate

        subj_id = outline_gate.subject_of_node(db, node_id)
        if subj_id is not None and outline_gate.is_subject_disabled(db, subj_id):
            raise SessionError(
                f"学科「{subj_id}」已停用（可从学科页重新启用后继续学习）",
                code="invalid_state",
            )
        res = outline_gate.resolve_subject_unit(db, node_id)
        if res is not None:
            ok_gate, missing = outline_gate.unit_allowed(db, self.user_id, res[0], res[1])
        else:
            from .path import make_engine

            mastered = {
                nid
                for (nid,) in db.query(models.UserNode.node_id)
                .filter(
                    models.UserNode.user_id == self.user_id,
                    models.UserNode.state == "mastered",
                )
                .all()
            }
            eng = make_engine(mastered, lib=lib)
            ok_gate, missing = eng.node_allowed(
                node_id,
                kind=loaded.doc.kind or "",
                level=loaded.doc.level or "",
                topic=loaded.doc.topic or "",
                prereqs=list(loaded.doc.prereqs or ()),
            )
        if not ok_gate:
            raise SessionError(
                "当前节点尚未解锁（须按课程顺序先学前置）：" + "；".join(missing or ["总序前置未达成"]),
                code="invalid_state",
            )

        sess_id = _new_session_id(node_id)
        sess = models.Session(
            id=sess_id,
            user_id=self.user_id,
            node_id=node_id,
            state="learning",
            flow_json=new_flow(),
        )
        db.add(sess)
        db.flush()
        mark_learning(db, self.user_id, node_id, lib.graph)
        return self.resume(db, sess_id, first_open=True)

    # ---------- 恢复 ----------
    def resume(self, db: Session, session_id: str, first_open: bool = False) -> dict[str, Any]:
        sess = self._get_session(db, session_id)
        self._ensure_invariants(db, sess)
        db.flush()
        return self._response(db, sess, events=[], first_open=first_open)

    # ---------- 步进 ----------
    def step(self, db: Session, session_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if action not in ACTIONS:
            raise SessionError(f"未知 action: {action}", code="validation_error")
        payload = payload or {}
        sess = self._get_session(db, session_id)
        node = self._node_of(db, sess)
        if action == "next":
            return self._act_next(db, sess, node)
        if action == "ask_question":
            return self._act_ask(db, sess, node, str(payload.get("question", "")), payload)
        if action == "submit_exercise":
            return self._act_submit(db, sess, node, payload)
        if action == "request_hint":
            return self._act_hint(db, sess, node, payload)
        if action == "regen_explain":
            return self._act_regen_explain(db, sess, node, payload)
        if action in ("feynman_submit", "feynman_answer"):
            return self._act_feynman(db, sess, node, str(payload.get("transcript", payload.get("answer", ""))), payload)
        if action == "finish":
            return self._act_finish(db, sess, node)
        if action == "quit":
            sess.state = "quit"
            db.flush()
            return {"ok": True, "step": sess.flow_json.get("stage"), "session": self._session_meta(db, sess)}
        # get
        return self._response(db, sess, events=[])

    # ------------------------------------------------------------------
    # 内部：阶段前进
    # ------------------------------------------------------------------
    def _act_next(self, db: Session, sess: models.Session, node: NodeDoc) -> dict[str, Any]:
        flow = sess.flow_json
        stage = flow["stage"]
        if stage == STAGE_EXPLAIN:
            flow["stage"] = STAGE_EXAMPLE
            return self._response(db, sess, events=[{"type": "stage_example"}])
        if stage == STAGE_EXAMPLE:
            flow["stage"] = STAGE_PRACTICE
            self._issue_next(db, sess, node)
            return self._response(db, sess, events=[{"type": "stage_practice"}])
        if stage == STAGE_PRACTICE:
            # 练习中不允许"跳过"；仅回炉后重进用 next 返回练习
            if not flow["practice"]["passed"] and flow["practice"]["current"] is None:
                self._issue_next(db, sess, node)
                return self._response(db, sess, events=[])
            raise SessionError("练习阶段请先作答当前题目", code="invalid_state")
        if stage == STAGE_DONE:
            return self._response(db, sess, events=[])
        raise SessionError(f"stage {stage} 不支持 next")

    def _act_ask(self, db: Session, sess: models.Session, node: NodeDoc, question: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not question.strip():
            raise SessionError("question 不能为空", code="validation_error")
        ctx = AnswerQuestionIn(
            session_id=sess.id,
            node_id=node.id,
            node_title=node.title,
            level=node.level,
            explanation_body=node.explanation.body,
            whitelist=list(node.core_concepts) + node.prereqs,
            profile_style_block=self._style_block(db),
            student_question=question,
        )
        # R12：策略档 → 触发 b（超纲 out_of_scope 时自动 think 重生成一次）
        override = payload.get("think_deep")
        decision = self._resolve_tier(db, node=node, override=override)
        out, degraded = self._call(db, self.gateway.answer_question, ctx, strategy=decision.strategy)
        upgraded = False
        strategy_used = decision.strategy
        if (
            decision.strategy == ai_tier.FAST
            and self._model_mode(db) == "smart"
            and getattr(out, "out_of_scope", False)
        ):
            # 超纲/需深思 → think 重生成一次覆盖回复（用户感知"这问题值得深思"）
            think_decision = self._resolve_tier(db, node=node, override=True)
            out2, deg2 = self._call(db, self.gateway.answer_question, ctx, strategy=think_decision.strategy)
            out, degraded, upgraded = out2, deg2, True
            strategy_used = think_decision.strategy
        return self._response(
            db,
            sess,
            events=[{"type": "answered", "degraded": degraded, "upgraded": upgraded}],
            extra_payload={
                "answer": {
                    "reply_md": out.reply_md,
                    "needs_more_info": out.needs_more_info,
                    "out_of_scope": getattr(out, "out_of_scope", False),
                    "upgraded": upgraded,
                    "strategy": strategy_used,  # 评分卡/交互标注本次档位
                    "degraded": degraded,
                }
            },
        )

    def _act_hint(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any]) -> dict[str, Any]:
        p = sess.flow_json["practice"]
        if p["current"] is None or p["attempts_this"] < 1:
            raise SessionError("提示只能在本题首次答错后请求（请先作答一次）", code="invalid_state")
        ex_id = payload.get("exercise_id")
        if ex_id and ex_id != p["current"]["exercise_id"]:
            raise SessionError("exercise_id 与当前题目不符", code="validation_error")
        cur = self._render_current(sess, node)
        detail = payload.get("judge_detail", "")
        ctx = HintOnErrorIn(
            node_id=node.id,
            prompt=cur.prompt,
            mode=cur.mode,
            user_answer=str(payload.get("user_answer", "")),
            judge_detail=detail,
        )
        decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"))
        out, degraded = self._call(db, self.gateway.hint_on_error, ctx, strategy=decision.strategy)
        p["hints_this"] += 1
        db.flush()
        return self._response(
            db,
            sess,
            events=[{"type": "hint_given", "count": p["hints_this"]}],
            extra_payload={"hint_md": out.hint_md, "degraded": degraded, "strategy": decision.strategy},
        )

    def _act_submit(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any]) -> dict[str, Any]:
        p = sess.flow_json["practice"]
        cur = self._require_current(sess, node)
        ex_id = payload.get("exercise_id")
        if ex_id != cur.exercise_id or int(payload.get("params_seed", -1)) != cur.seed:
            raise SessionError("提交的题目与当前题目不一致，请刷新", code="invalid_state")
        user_answer = str(payload.get("user_answer", "")).strip()

        # 判题：只走 sympy（domain.judge）
        try:
            result = judge_mod.judge(user_answer=user_answer, **cur.judge_payload())
        except NotationError as e:
            db.flush()
            return self._response(
                db,
                sess,
                events=[{"type": "notation_error"}],
                extra_payload={
                    "verdict": "notation",
                    "message": str(e).split(":")[-1].strip(),
                    "progress": self._progress_view(p),
                },
            )
        except JudgeError as e:
            raise ExerciseBrokenError(str(e)) from e

        self._record_attempt(db, sess, node, cur, user_answer, result)
        events: list[dict] = []
        if result.correct:
            p["attempts_this"] = 0
            p["streak"] += 1
            p["streak_min"] = float(cur.difficulty) if p["streak_min"] is None else min(p["streak_min"], float(cur.difficulty))
            events.append({"type": "exercise_correct", "node_id": node.id, "consecutive_correct": p["streak"]})
            if p["streak"] >= TARGET_STREAK:
                p["passed"] = True
                events.append({"type": "practice_passed", "consecutive_correct": p["streak"]})
                self._enter_feynman(db, sess, node, events)
                return self._response(db, sess, events=events)
            # 发下一题（本轮未超 cap）
            if p["issued"] >= PRACTICE_CAP:
                self._cap_fail_cycle(db, sess, node, events)
            else:
                self._issue_next(db, sess, node)
                events.append({"type": "question_issued"})
            return self._response(db, sess, events=events)

        # 答错
        p["streak"] = 0
        p["streak_min"] = None
        p["attempts_this"] += 1
        events.append({"type": "exercise_wrong", "retry_left": max(0, 2 - p["attempts_this"])})
        hint_decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"))
        hint_out, degraded = self._call(db,
            self.gateway.hint_on_error,
            HintOnErrorIn(
                node_id=node.id,
                prompt=cur.prompt,
                mode=cur.mode,
                user_answer=user_answer,
                judge_detail=result.detail,
            ),
            strategy=hint_decision.strategy,
        )
        if p["attempts_this"] >= 2:
            # 仍错 → 讲解回炉 + 答疑（docs/05 §2）
            self._relearn_explain(db, sess, node, events)
            events.append({"type": "practice_retry_exhausted"})
            return self._response(db, sess, events=events)
        db.flush()
        return self._response(
            db,
            sess,
            events=events,
            extra_payload={
                "verdict": "wrong",
                "hint_md": hint_out.hint_md,
                "degraded": degraded,
                "attempts_left": 2 - p["attempts_this"],
                "progress": self._progress_view(p),
            },
        )

    def _act_regen_explain(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any]) -> dict[str, Any]:
        """R8 清理路径：清掉缓存的（可能脏的）讲解，回到 explain 阶段重新生成。"""
        # R12：重新生成可携带单次 think_deep 覆盖（存临时标记，_payload_explain 消费）
        override = payload.get("think_deep")
        flow = sess.flow_json
        flow["lecture_cache"] = None
        if override is not None:
            flow["regen_think_override"] = bool(override)
        flow["stage"] = STAGE_EXPLAIN
        db.flush()
        return self._response(
            db,
            sess,
            events=[{"type": "lecture_regenerated", "node_id": node.id}],
        )

    def _act_feynman(self, db: Session, sess: models.Session, node: NodeDoc, transcript: str, payload: dict[str, Any]) -> dict[str, Any]:
        flow = sess.flow_json
        p = flow["practice"]
        f = flow["feynman"]
        if not p["passed"]:
            raise SessionError("费曼环节需要先完成练习达标（连续答对 3 题）", code="invalid_state")
        text = transcript.strip()
        events: list[dict] = []
        if len(text) < MIN_FEYNMAN_CHARS:
            events.append({"type": "feynman_too_short", "min_chars": MIN_FEYNMAN_CHARS})
            return self._response(
                db,
                sess,
                events=events,
                extra_payload={"verdict": "deferred", "message": f"口述太短（{len(text)} 字），请像对老师讲解一样完整说一遍（≥{MIN_FEYNMAN_CHARS} 字）。"},
            )
        if f["rounds_done"] >= MAX_FEYNMAN_ROUNDS:
            raise SessionError("费曼轮次已达上限，请重新学习后再来", code="invalid_state")

        dims = [d.model_dump() for d in node.feynman.rubric.dimensions]
        ctx = FeynmanEvaluateIn(
            session_id=sess.id,
            node_id=node.id,
            task_prompt=node.feynman.task_prompt,
            rubric_dimensions=dims,
            core_concepts=list(node.core_concepts),
            transcript=text,
            previous_round=(
                {
                    "round": f["rounds_done"],
                    "combined": f["last_combined"],
                    "dims": f["last_scores"][-1],  # 上一轮分维卡（热修 R10）
                }
                if f["last_scores"]
                else None
            ),
        )
        # R12：费曼档位 = 基础档(学段/content.thinking) + 触发(边缘分上轮 flag / 轮次≥2)
        # + 用户覆盖(model_mode / payload.think_deep)
        trigger_think = bool(f.get("edge_think")) or ai_tier.feynman_round_should_think(f["rounds_done"] + 1)
        decision = self._resolve_tier(
            db, node=node, override=payload.get("think_deep"), extra_think=trigger_think
        )
        f["edge_think"] = False  # 消费边缘 flag（仅对下一轮生效一次）
        f["last_strategy"] = decision.strategy
        try:
            # R7 精神：重型评分调用前先提交，释放写锁（若本事务此前有写则一并落库）
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            out = self.gateway.feynman_evaluate(ctx, strategy=decision.strategy)
        except AiCallError as e:
            # 降级：评分不可用 → 进人工复核队列（verdict deferred），不判过/不过
            self._record_feynman_attempt(db, sess, node, text, "deferred", None, meta={"error": str(e), "degraded": True})
            events.append({"type": "feynman_deferred", "reason": "评分服务不可用，记录待人工复核"})
            return self._response(db, sess, events=events, extra_payload={"verdict": "deferred", "strategy": decision.strategy})

        f["rounds_done"] += 1
        f["last_transcript"] = text
        combined, card = self._combine_scores(node, out.dimension_scores)
        f["last_combined"] = combined
        f["last_scores"].append(card)
        threshold = node.feynman.rubric.pass_threshold
        passed = combined >= threshold
        self._record_feynman_attempt(
            db, sess, node, text,
            "pass" if passed else "fail",
            round(combined, 3),
            meta={
                "dims": card,
                "recommend_action": out.recommend_action,
                "strategy": decision.strategy,          # R12：评分所用档位（评分卡标注）
                "confidence": getattr(out, "confidence", None),
            },
        )
        if passed:
            f["passed"] = True
            events.append({"type": "feynman_passed", "score": round(combined, 3)})
            return self._master_if_ready(db, sess, node, events)
        # 未过：命中边缘区间 → 下轮升 think（R12 触发 a）
        if (
            decision.strategy == ai_tier.FAST
            and self._model_mode(db) == "smart"
            and ai_tier.feynman_edge(combined, threshold)
        ):
            f["edge_think"] = True
        events.append({"type": "feynman_failed", "score": round(combined, 3), "round": f["rounds_done"]})
        if f["rounds_done"] >= MAX_FEYNMAN_ROUNDS:
            self._relearn_explain(db, sess, node, events, reason="费曼 3 轮未通过")
            events.append({"type": "feynman_relearn"})
            return self._response(db, sess, events=events)
        # Socratic 追问
        q_ctx = FeynmanFollowupIn(
            session_id=sess.id,
            node_id=node.id,
            student_transcript=text,
            previous_scores=(f["last_scores"][-1] if f["last_scores"] else []),  # R10：传最近一轮分维卡，非历史列表
            socratic_followups=list(node.feynman.socratic_followups),
        )
        q_decision = self._resolve_tier(
            db, node=node, override=payload.get("think_deep"),
            extra_think=bool(f.get("edge_think")) or ai_tier.feynman_round_should_think(f["rounds_done"] + 1),
        )
        q_out, q_degraded = self._call(db, self.gateway.feynman_followup, q_ctx, strategy=q_decision.strategy)
        f["followup"] = q_out.question_md
        events.append({"type": "feynman_followup", "round": f["rounds_done"]})
        db.flush()
        return self._response(
            db,
            sess,
            events=events,
            extra_payload={
                "verdict": "fail",
                "combined": round(combined, 3),
                "threshold": threshold,
                "dimension_scores": card,
                "followup_question": q_out.question_md,
                "degraded": q_degraded,
                "strategy": decision.strategy,  # R12：评分卡标注本次所用档位
                "strategy_reason": decision.reason,
            },
        )

    def _act_finish(self, db: Session, sess: models.Session, node: NodeDoc) -> dict[str, Any]:
        flow = sess.flow_json
        p, f = flow["practice"], flow["feynman"]
        events: list[dict] = []
        if flow["stage"] == STAGE_DONE:
            return self._response(db, sess, events=[])
        if p["passed"] and f["passed"]:
            return self._master_if_ready(db, sess, node, events)
        missing = []
        if not p["passed"]:
            missing.append("练习：连续答对 3 题")
        if not f["passed"]:
            missing.append("费曼：口述评分通过")
        return self._response(
            db,
            sess,
            events=events,
            extra_payload={"message": "尚未达标，还差：" + "、".join(missing), "missing": missing},
        )

    # ------------------------------------------------------------------
    # 内部：练习题目
    # ------------------------------------------------------------------
    def _issue_next(self, db: Session, sess: models.Session, node: NodeDoc) -> dict | None:
        """发出下一道题（记录 current）。题目 = 模板渲染，seed 确定性。"""
        p = sess.flow_json["practice"]
        exercises = node.exercises
        if not exercises:
            raise ExerciseBrokenError(f"节点 {node.id} 没有可用练习")
        excluded = set(p.get("excluded", []))
        # 轮转：跳过最近用过的（窗口 = 全部 ex 数-1）
        pool = [e for e in exercises if e.id not in excluded] or exercises
        idx = p["issued"] % len(pool)
        ex = pool[idx]
        seed = _seed_for(sess.id, p["issued"] + 1, ex.id)
        rendered = render_exercise(node.id, ex, seed)
        if rendered.broken:
            raise ExerciseBrokenError(f"练习 {ex.id} 渲染失败: {rendered.detail}")
        p["current"] = {"exercise_id": ex.id, "seed": seed}
        p["issued"] += 1
        p["attempts_this"] = 0
        p["hints_this"] = 0
        # 去重窗口维护
        used = list(excluded)
        used.append(ex.id)
        p["excluded"] = used[-6:]
        db.flush()
        return None

    def _render_current(self, sess: models.Session, node: NodeDoc) -> RenderedExercise:
        p = sess.flow_json["practice"]
        cur = p["current"]
        ex = next((e for e in node.exercises if e.id == cur["exercise_id"]), None)
        if ex is None:
            raise ExerciseBrokenError(f"练习 {cur['exercise_id']} 不在内容库")
        return render_exercise(node.id, ex, cur["seed"])

    def _require_current(self, sess: models.Session, node: NodeDoc) -> RenderedExercise:
        if sess.flow_json["practice"]["current"] is None:
            raise SessionError("当前没有待作答题目，请先进入练习阶段", code="invalid_state")
        return self._render_current(sess, node)

    def _cap_fail_cycle(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict]) -> None:
        """5 题未达标 → 回炉讲解（重置本轮，保留练习通过标记语义）。"""
        flow = sess.flow_json
        events.append({"type": "practice_cap_reached", "cap": PRACTICE_CAP})
        _practice_reset_cycle(flow["practice"])  # 模块级函数，非方法（热修 R11）
        _feynman_reset(flow["feynman"])  # R17：回炉重学需重置费曼轮次，防"轮次上限"锁死
        flow["stage"] = STAGE_EXPLAIN
        events.append({"type": "relearn_notice", "reason": "本轮 5 题未连续答对 3 题，请重读讲解后再试"})

    def _relearn_explain(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict], reason: str = "练习连续答错") -> None:
        flow = sess.flow_json
        _practice_reset_cycle(flow["practice"])  # 模块级函数，非方法（热修 R11）
        _feynman_reset(flow["feynman"])  # R17：同上——回炉后重新走费曼必须从第 0 轮开始
        flow["stage"] = STAGE_EXPLAIN
        events.append({"type": "relearn_notice", "reason": reason})

    def _enter_feynman(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict]) -> None:
        flow = sess.flow_json
        # R17 防御：进入费曼前若轮次已满（历史回炉未清零的会话/数据迁移遗留），
        # 视为新费曼阶段自动清零，避免用户"重学后仍 409 锁死"。
        if flow["feynman"]["rounds_done"] >= MAX_FEYNMAN_ROUNDS:
            _feynman_reset(flow["feynman"])
        flow["stage"] = STAGE_FEYNMAN
        events.append({"type": "stage_feynman"})

    # ------------------------------------------------------------------
    # 内部：费曼/达标
    # ------------------------------------------------------------------
    def _enter_feynman(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict]) -> None:
        flow = sess.flow_json
        flow["stage"] = STAGE_FEYNMAN
        events.append({"type": "stage_feynman"})

    def _combine_scores(self, node: NodeDoc, dim_scores) -> tuple[float, list[dict]]:
        """service 按 rubric 权重合成分数（docs/05 §5 step4；归一化权重）。"""
        dims = node.feynman.rubric.dimensions
        weights = {d.key: d.weight for d in dims}
        card: list[dict] = []
        total_w = sum(weights.values()) or 1.0
        weighted = 0.0
        for ds in dim_scores:
            w = weights.get(ds.key, 0.0)
            weighted += w * ds.score
            card.append(
                {
                    "key": ds.key,
                    "score": ds.score,
                    "weight": weights.get(ds.key, 0.0),
                    "evidence_quote": ds.evidence_quote,
                    "comment": ds.comment,
                }
            )
        return weighted / total_w, card

    def _master_if_ready(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict]) -> dict[str, Any]:
        """练习 + 费曼都达标 → mastery 判定 → mastered + FSRS 首次排程。"""
        p = sess.flow_json["practice"]
        f = sess.flow_json["feynman"]
        verdict = evaluate_pass(
            MasteryStats(
                consecutive_correct=p["streak"],
                min_difficulty_among_streak=p["streak_min"] or 0.0,
                feynman_score=f["last_combined"],
                feynman_threshold=node.feynman.rubric.pass_threshold,
            )
        )
        if not verdict.passed:
            events.append({"type": "mastery_not_yet", "missing": verdict.missing})
            return self._response(db, sess, events=events)

        lib = get_library()
        mark_mastered(db, self.user_id, node.id, lib.graph)
        rstate = review_svc.schedule_first(db, self.user_id, node.id)
        sess.flow_json["stage"] = STAGE_DONE
        sess.state = "finished"
        db.flush()
        events.append({"type": "node_mastered", "node_id": node.id})

        extra: dict[str, Any] = {
            "mastered": True,
            "mastery": {
                "consecutive_correct": p["streak"],
                "feynman_score": round(f["last_combined"] or 0.0, 3),
                "next_review_due_at": rstate.due_at.isoformat() if rstate.due_at else None,
            },
        }
        # docs/10 §2.1：首领（boss）节点通过 → 学段小结/下一学段入口/复习整合提示
        if getattr(node, "kind", "normal") == "boss":
            from . import campaign as campaign_svc

            snap = campaign_svc.snapshot(db, self.user_id)
            group_of_topic = None
            for lv in snap["levels"]:
                if lv["level"] == node.level:
                    for g in lv["groups"]:
                        if g["topic"] == node.topic:
                            group_of_topic = g
            stage_completed = any(
                lv["level"] == node.level and all(gr["completed"] for gr in lv["groups"])
                for lv in snap["levels"]
            )
            boss_meta: dict[str, Any] = {
                "level": node.level,
                "topic": node.topic,
                "group_completed": bool(group_of_topic and group_of_topic["completed"]),
                "stage_completed": stage_completed,
                "next_stage_unlocked": stage_completed,  # 表现层：下一学段入口开放
                "next_generating": snap["next_generating"],
            }
            try:
                group_obj = campaign_svc._groups_by_level().get(node.level) or []
                grp = next((gr for gr in group_obj if gr.topic == node.topic), None)
                if grp:
                    boss_meta["recap"] = campaign_svc.boss_recap(db, self.user_id, grp)
            except Exception:
                pass  # recap 为增强信息，失败不影响主流程
            events.append({"type": "boss_passed", **boss_meta})
            extra["campaign"] = boss_meta
        return self._response(
            db,
            sess,
            events=events,
            extra_payload=extra,
        )

    # ------------------------------------------------------------------
    # 内部：尝试落库 / 画像
    # ------------------------------------------------------------------
    def _record_attempt(self, db: Session, sess: models.Session, node: NodeDoc, cur: RenderedExercise, user_answer: str, result: JudgeResult) -> None:
        db.add(
            models.Attempt(
                session_id=sess.id,
                node_id=node.id,
                kind="exercise",
                exercise_id=cur.exercise_id,
                params_json={"seed": cur.seed},
                user_input=user_answer,
                verdict="correct" if result.correct else "wrong",
                error_type=None,  # M3 起由 classify_error 填充
                meta_json={"mode": cur.mode, "difficulty": cur.difficulty, "detail": result.detail},
            )
        )
        db.flush()
        if not result.correct:
            self._classify_and_record(db, node, cur, user_answer)

    def _classify_and_record(self, db: Session, node: NodeDoc, cur: RenderedExercise, user_answer: str) -> None:
        """错误类型识别（docs/03 §4/§5，调用点 8）。失败（含离线 unknown）静默，不影响状态。"""
        try:
            # R7 精神：分类前先提交（attempt 已 flush），分类为轻 LLM 也不持写锁
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            out = self.gateway.classify_error(
                ClassifyErrorIn(
                    node_id=node.id,
                    prompt=cur.prompt,
                    correct_solution=cur.canonical_answer,
                    user_answer=user_answer,
                )
            )
        except AiCallError:
            return
        if out.error_type == "unknown":
            return  # 不污染画像
        profile = self._profile(db)
        profile.record_error(out.error_type)
        db.flush()

    def _record_feynman_attempt(self, db: Session, sess: models.Session, node: NodeDoc, transcript: str, verdict: str, score: float | None, meta: dict) -> None:
        db.add(
            models.Attempt(
                session_id=sess.id,
                node_id=node.id,
                kind="feynman",
                user_input=transcript,
                verdict=verdict,
                meta_json={**(meta or {}), "score": score},
            )
        )
        db.flush()

    # ------------------------------------------------------------------
    # 内部：持久化辅助
    # ------------------------------------------------------------------
    def _get_session(self, db: Session, session_id: str) -> models.Session:
        sess = db.get(models.Session, session_id)
        if sess is None or sess.user_id != self.user_id:
            raise SessionError(f"会话不存在: {session_id}", code="not_found")
        return sess

    def _node_of(self, db: Session, sess: models.Session) -> NodeDoc:
        lib = get_library()
        loaded = lib.by_id.get(sess.node_id)
        if loaded is None:
            raise SessionError(f"会话节点 {sess.node_id} 已不在内容库（内容可能已改动）", code="invalid_state")
        return loaded.doc

    def _ensure_invariants(self, db: Session, sess: models.Session) -> None:
        """读取时自愈：stage 回退等不变量。"""
        flow = sess.flow_json or new_flow()
        if "practice" not in flow or "feynman" not in flow:
            base = new_flow()
            base.update(flow)
            flow = base
        sess.flow_json = flow
        stage = flow["stage"]
        if stage == STAGE_PRACTICE and flow["practice"]["current"] is None:
            node = self._node_of(db, sess)
            if flow["practice"]["passed"] and not flow["feynman"]["passed"]:
                flow["stage"] = STAGE_FEYNMAN  # 练习已过而卡在 practice → 推进费曼
            else:
                self._issue_next(db, sess, node)

    # ------------------------------------------------------------------
    # 响应组装（06 §2 契约：step/payload/events/session）
    # ------------------------------------------------------------------
    def _response(self, db: Session, sess: models.Session, events: list[dict], *, extra_payload: dict | None = None, first_open: bool = False) -> dict[str, Any]:
        flow = sess.flow_json
        stage = flow["stage"]
        payload: dict[str, Any] = {"first_open": first_open}
        node = self._node_of(db, sess)

        if stage == STAGE_EXPLAIN:
            payload.update(self._payload_explain(db, sess, node))
        elif stage == STAGE_EXAMPLE:
            payload["worked_examples"] = [
                {"prompt": w.prompt, "solution_steps": w.solution_steps}
                for w in node.worked_examples
            ] or [{"prompt": "（本节点暂无例题）", "solution_steps": []}]
        elif stage == STAGE_PRACTICE:
            if flow["practice"]["current"] is None:
                self._issue_next(db, sess, node)  # 防御：确保有当前题
            cur = self._render_current(sess, node)
            payload["exercise"] = self._exercise_view(cur)
            payload["progress"] = self._progress_view(flow["practice"])
        elif stage == STAGE_FEYNMAN:
            f = flow["feynman"]
            payload["task_prompt"] = node.feynman.task_prompt
            payload["rubric"] = [d.model_dump() for d in node.feynman.rubric.dimensions]
            payload["pass_threshold"] = node.feynman.rubric.pass_threshold
            payload["rounds_done"] = f["rounds_done"]
            payload["max_rounds"] = MAX_FEYNMAN_ROUNDS
            payload["followup_question"] = f.get("followup")
        elif stage == STAGE_DONE:
            payload["mastered"] = True

        payload.update(extra_payload or {})
        # flow_json 是嵌套 dict：原地修改后须以新对象 + flag_modified 强制触发 UPDATE
        sess.flow_json = deepcopy(flow)
        flag_modified(sess, "flow_json")
        sess.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        return {
            "step": stage,
            "payload": payload,
            "events": events,
            "session": self._session_meta(db, sess),
        }

    def _payload_explain(self, db: Session, sess: models.Session, node: NodeDoc) -> dict[str, Any]:
        flow = sess.flow_json
        cache = flow.get("lecture_cache")
        # 档位联动（R21）：缓存非"手动单次指定"（explicit）且其档位 ≠ 当前全局解析档位 →
        # 自动作废，按新档位重生成（用户切换 快/深 后旧讲解不残留旧档）。
        if cache is not None and not cache.get("explicit"):
            desired = self._resolve_tier(db, node=node, override=None)
            if cache.get("strategy") and cache["strategy"] != desired.strategy:
                flow["lecture_cache"] = None
                cache = None
        if cache is None:
            # R12：regen_explain 可携带单次 think_deep → 本帧消费（视为显式单次，不被联动翻回）
            regen_override = flow.pop("regen_think_override", None)
            explicit = regen_override is not None
            decision = self._resolve_tier(db, node=node, override=regen_override)
            ctx = ExplainIn(
                session_id=sess.id,
                node_id=node.id,
                node_title=node.title,
                level=node.level,
                explanation_body=node.explanation.body,
                worked_examples=[w.prompt for w in node.worked_examples],
                core_concepts=list(node.core_concepts),
                prereq_titles=self._prereq_titles(node),
                whitelist=list(node.core_concepts) + node.prereqs,
                profile_style_block=self._style_block(db),
            )
            out, degraded = self._call(db, self.gateway.explain_node, ctx, strategy=decision.strategy)
            flow["lecture_cache"] = {
                "lecture_md": out.lecture_md,
                "asks": out.asked_to_confirm,
                "degraded": degraded,
                "strategy": decision.strategy,  # R12：标注本次讲解档位（审计/UI）
                "explicit": explicit,           # R21：是否手动单次指定（不被档位联动自动翻）
            }
        cache = flow["lecture_cache"]
        return {
            "node": {
                "id": node.id,
                "title": node.title,
                "level": node.level,
                "topic": node.topic,
                "core_concepts": node.core_concepts,
                "objectives": node.objectives,
            },
            "lecture_md": cache["lecture_md"],
            "asks": cache.get("asks", []),
            "degraded": cache.get("degraded", False),
            "strategy": cache.get("strategy"),  # 讲解所用档位（fast/think/None=未知）
        }

    def _prereq_titles(self, node: NodeDoc) -> list[str]:
        lib = get_library()
        return [lib.by_id[p].doc.title for p in node.prereqs if p in lib.by_id]

    def _style_block(self, db: Session) -> str:
        from ..domain.profile import style_block

        return style_block(self._profile(db))

    def _model_mode(self, db: Session) -> str:
        """R12：当前用户全局模型模式（smart|light|deep）。"""
        return self._profile(db).model_mode

    def _resolve_tier(self, db: Session, *, node: NodeDoc | None = None, override: Any = None, extra_think: bool = False):
        """R12：按 基础档(学段/content.thinking) + 触发(extra_think) + 用户覆盖 决策 fast|think。"""
        content_think = bool(node.feynman.thinking) if node is not None else None
        level = node.level if node is not None else None
        return ai_tier.resolve(
            level=level,
            content_think=content_think,
            model_mode=self._model_mode(db),
            override=(None if override is None else bool(override)),
            extra_think=extra_think,
        )

    def _profile(self, db: Session) -> Profile:
        user = ensure_user(db, self.user_id)
        return Profile.from_dict(user.profile_json or {})

    def _progress_view(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "consecutive_correct": p["streak"],
            "target": TARGET_STREAK,
            "issued": p["issued"],
            "cap": PRACTICE_CAP,
        }

    def _exercise_view(self, cur: RenderedExercise) -> dict[str, Any]:
        view: dict[str, Any] = {
            "exercise_id": cur.exercise_id,
            "prompt": cur.prompt,
            "mode": cur.mode,
            "difficulty": cur.difficulty,
            "interactive": cur.interactive,
            "seed": cur.seed,
        }
        if cur.mode == "single_choice" and cur.options:
            view["options"] = list(cur.options)  # B2：选择题选项（答案由服务端判定，不外泄 index）
        return view

    def _session_meta(self, db: Session, sess: models.Session) -> dict[str, Any]:
        return {
            "id": sess.id,
            "node_id": sess.node_id,
            "state": sess.state,
            "stage": sess.flow_json.get("stage"),
        }

    # ------------------------------------------------------------------
    # AI 调用兜底
    # ------------------------------------------------------------------
    @staticmethod
    def _call(db: Session, method, ctx, *, strategy: str | None = None):
        """调用网关（热修 R7）：先提交当前事务释放 SQLite 写锁，再调 LLM。

        LLM 调用（explain/费曼评分等）可达 60–100s，若不先提交，事务会长时间占
        SQLite 写锁，并发写请求 5s 超时抛 "database is locked"（docs/09 R7）。
        AiCallError → 内容库兜底（offline 网关即兜底本身）。返回 (out, degraded)。
        strategy（R12）非空时传给网关（fast|think 选模型）；None 兼容旧网关签名。
        """
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            out = method(ctx, strategy=strategy) if strategy is not None else method(ctx)
            return out, False
        except AiCallError:
            from ..ai.gateway import OfflineGateway

            fallback = OfflineGateway()
            fb = getattr(fallback, method.__name__)(ctx)
            return fb, True


def _new_session_id(node_id: str) -> str:
    import uuid

    return f"{node_id}:{uuid.uuid4().hex[:10]}"


__all__ = [
    "SessionService",
    "SessionError",
    "ExerciseBrokenError",
    "TARGET_STREAK",
    "PRACTICE_CAP",
    "MAX_FEYNMAN_ROUNDS",
    "STAGE_EXPLAIN",
    "STAGE_EXAMPLE",
    "STAGE_PRACTICE",
    "STAGE_FEYNMAN",
    "STAGE_DONE",
]
