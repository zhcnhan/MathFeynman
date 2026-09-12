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
    ChallengeCheckIn,
    ChallengeIn,
    ClassifyErrorIn,
    ExplainIn,
    FeynmanEvaluateIn,
    FeynmanFollowupIn,
    FeynmanFollowupOut,
    GapCheckIn,
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
from . import feynman_ledger as fl
from . import progress, review as review_svc
from .library import ensure_user, get_library
from .progress import mark_learning, mark_mastered

STAGE_EXPLAIN = "explain"
STAGE_EXAMPLE = "example"
STAGE_PRACTICE = "practice"
STAGE_FEYNMAN = "feynman"
STAGE_DONE = "done"
# **R54 A**：内容不足时下发的"卡片"步骤（不是学习阶段——只给中文说明 + 一键生成）
STEP_CONTENT_MISSING = "content_missing"

STAGE_ORDER = [STAGE_EXPLAIN, STAGE_EXAMPLE, STAGE_PRACTICE, STAGE_FEYNMAN, STAGE_DONE]

TARGET_STREAK = 3           # docs/03 §2：连续答对 ≥3
PRACTICE_CAP = 5            # docs/05 §2：练习上限 5 题（一轮）
# R27 轮次预算（宽，取代旧 MAX_FEYNMAN_ROUNDS 单计数）：
#   整体稿评分 ≤3（首讲 + ≤2 次终验）；补答 ≤2（须有未答缺口；同一缺口答不对保留、可再追一次）。
MAX_FEYNMAN_ROUNDS = 3      # 兼容旧常量 = 整体稿评分预算（docs/09 R27 §4）
MAX_FEYNMAN_EVALS = 3       # 整体评分（feynman_submit）预算
MAX_FEYNMAN_ANSWERS = 2     # 补答（feynman_answer）预算

ACTIONS = {
    "next",                # 阶段前进（讲解→例题→练习 等）
    "ask_question",
    "submit_exercise",
    "request_hint",
    "regen_explain",       # R8：清理 lecture_cache 并重新生成讲解（脏讲解/重新讲解入口）
    "reissue_after_regen", # R25：内容纠错替换后，一键把正在做的旧题换成新题（带保护）
    "feynman_submit",      # R27：完整稿（首讲 / 整合重讲）→ 整体评分 feynman_evaluate
    "feynman_answer",      # R27：补答（只答当前追问）→ 轻量缺口补答评估（不再等同整体重评）
    # R35 S3 挑战题池（**永不出现在默认流程**；不设额度/不计轮次/不影响任何进度）：
    "challenge_start",     # 用户点「挑战一下」→ 单独调模型生成一道挑战题
    "challenge_begin",     # 开始作答（纯 UI 状态推进，无任何后果）
    "challenge_submit",    # 提交挑战题作答 → 单独判分；**只记复盘**
    "challenge_cancel",    # 取消本次挑战（丢掉这题，无任何后果，不记 attempts）
    "challenge_abandon",   # 明确放弃（"我不会/我不感兴趣"）→ 只记复盘，无任何后果
    "finish",
    "quit",
    "get",                 # 恢复/刷新当前步
}

CHALLENGE_ACTIONS = {"challenge_start", "challenge_begin", "challenge_submit",
                     "challenge_cancel", "challenge_abandon"}

# R35 S3：UI/接口**必须显式标注**的挑战题说明（后端直出，前端只渲染——口径唯一）
CHALLENGE_NOTICE = "挑战题：需要讲解之外的知识，答不出不影响任何进度"


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
        # **R54 A**：讲解**是否真的展示过**——学生没看到讲解，就不许被要求开讲（费曼）。
        # 置位点：explain 阶段正常下发讲解正文之后（`_response`）；老会话默认 False → 会被退回讲解。
        "explained_seen": False,
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
            "rounds_done": 0,          # 整体稿评分次数（首讲 + 终验）
            "passed": False,
            "last_combined": None,     # 实时综合分（账本 max 合成）——通过判定依据
            "last_scores": [],
            "last_transcript": "",     # 最近一次完整稿（整体评分对象；不拼历史合并稿）
            "followup": None,          # 最近一次追问文本
            "followup_gap": None,      # R27：该追问定向的缺口 key（补答只更新该维度）
            "answers_done": 0,         # R27：补答次数（预算 ≤2）
            "ledger": fl.empty_ledger(),  # R27：缺口账本（维度历轮最高分 + 缺口清单）
            "edge_think": False,      # R12：上轮 fast 边缘分 → 本轮升 think（消费一次）
            "last_strategy": None,    # R12：最近一轮评分所用档位（评分卡标注）
        },
        # R35 S3：挑战题池（**与掌握/费曼完全隔离**：这四个键只被 challenge_* 动作读写）
        "challenge": {
            "current": None,     # 当前挑战题 {prompt_md, answer_hint_md, why_hard_md, difficulty}
            "phase": "idle",     # idle | offered | answering | graded（单题三态；任何相位都无后果）
            "asked": 0,          # 已生成次数（**仅统计展示**，不限额、不参与任何门禁）
            "answered": 0,       # 已作答次数（**仅统计展示**，不计轮次、不参与任何门禁）
            "last": None,        # 最近一次判分结果（复盘展示用）
        },
    }


# --------------------------------------------------------------------------
# R29 引申（R30）：flow schema 演进的**单一自愈入口**（读会话即深度补齐 + 类型校验）
#
# R29 热修曾用 `_backfill_feynman_keys(f)` 单点回填费曼键；本批按裁决收敛为 `_ensure_flow_shape`
# （超集：费曼键 + practice 子键 + ledger 结构 + lecture_cache + stage/类型校验），
# 热修行为与回归用例（test_r27_legacy_session.py）保持不变。
# --------------------------------------------------------------------------
# 各子键的期望类型（None 一并列出 = 允许空值；bool 是 int 子类，故数值判断宽松）
_PRACTICE_SHAPE: dict[str, tuple[type, ...]] = {
    "issued": (int,),
    "streak": (int,),
    "streak_min": (int, float, type(None)),
    "attempts_this": (int,),
    "hints_this": (int,),
    "current": (dict, type(None)),
    "passed": (bool,),
    "cap_reached": (bool,),
    "excluded": (list,),
}
_FEYNMAN_SHAPE: dict[str, tuple[type, ...]] = {
    "rounds_done": (int,),
    "passed": (bool,),
    "last_combined": (int, float, type(None)),
    "last_scores": (list,),
    "last_transcript": (str,),
    "followup": (str, type(None)),
    "followup_gap": (str, type(None)),
    "answers_done": (int,),
    "ledger": (dict,),
    "edge_think": (bool,),
    "last_strategy": (str, type(None)),
}
# R35 S3：挑战题块（与费曼/练习并列的独立块——**它的存在本身不影响任何进度**）
_CHALLENGE_SHAPE: dict[str, tuple[type, ...]] = {
    "current": (dict, type(None)),
    "phase": (str,),
    "asked": (int,),
    "answered": (int,),
    "last": (dict, type(None)),
}


def _ensure_block(flow: dict[str, Any], name: str, shape: dict[str, tuple[type, ...]]) -> dict[str, Any]:
    """补齐/校验 flow 的一个子块（整块缺失 → 建默认块；单键缺/错类型 → 单键回退默认）。"""
    defaults = new_flow()[name]
    block = flow.get(name)
    if not isinstance(block, dict):
        block = {}
        flow[name] = block
    for key, types in shape.items():
        if key not in block or not isinstance(block[key], types):
            block[key] = deepcopy(defaults[key])
    return block


def _ensure_flow_shape(flow: dict[str, Any] | None) -> dict[str, Any]:
    """R29 引申：flow schema 演进的**单一自愈入口**（幂等；合法值一律保留）。

    治的是同一类历史缺陷：**新增 flow 键没有迁移**，而分支按 ``flow[...]`` 直接取值
    → ``KeyError`` → 500（真人阻断，见 docs/09 R29）。规则：

    - **整块缺失 / 非 dict**（``flow`` 本身、``practice`` / ``feynman`` 子块）→ 按 ``new_flow()`` 补；
    - **缺键**（R12 lecture_cache / R21 cache 子键 / R25 regen_reissue_used / R27 answers_done +
      ledger + followup_gap …）→ 补当前默认值，**不覆盖已有值**；
    - **错类型 / 非法取值**（stage 越界、streak 变字符串、ledger 变数组…）→ 该键**单键回退默认**，
      不牵连其它字段的真实进度；
    - ``ledger`` 深结构（``dims`` / ``gaps`` / ``rounds``）→ 复用 ``feynman_ledger.normalize_ledger``
      的同一口径，不另写一套。
    """
    if not isinstance(flow, dict):
        return new_flow()
    for key, default in new_flow().items():
        if key not in flow:
            flow[key] = deepcopy(default)
    if flow.get("stage") not in STAGE_ORDER:
        flow["stage"] = STAGE_EXPLAIN
    _ensure_block(flow, "practice", _PRACTICE_SHAPE)
    f = _ensure_block(flow, "feynman", _FEYNMAN_SHAPE)
    ch = _ensure_block(flow, "challenge", _CHALLENGE_SHAPE)
    if ch.get("phase") not in ("idle", "offered", "answering", "graded"):
        ch["phase"] = "idle"
    # R21/R12：lecture_cache 合法形态 = None 或含 lecture_md(str) 的 dict（脏缓存宁可重生成）
    cache = flow.get("lecture_cache")
    if cache is not None and not (isinstance(cache, dict) and isinstance(cache.get("lecture_md"), str)):
        flow["lecture_cache"] = None
    # R25/R12 的单次/临时键：缺省即合法；类型不对则回退默认
    for key, default, types in (
        ("regen_reissue_used", 0, (int,)),
        ("regen_think_override", False, (bool,)),
        ("explained_seen", False, (bool,)),   # R54 A：讲解是否展示过（老会话默认 False）
    ):
        if key in flow and not isinstance(flow[key], types):
            flow[key] = default
    fl.normalize_ledger(f, ())  # R27 账本结构（dims/gaps/rounds）自愈——与账本口径同一实现
    return flow


def _feynman_reset(f: dict[str, Any]) -> None:
    """R17/R27：费曼阶段完整复位（回炉重学/轮次满防御用）——含账本与补答计数。"""
    f.update(
        rounds_done=0,
        passed=False,
        last_combined=None,
        last_scores=[],
        last_transcript="",
        followup=None,
        followup_gap=None,
        answers_done=0,
        ledger=fl.empty_ledger(),
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
        from . import outline_gate

        # **R54 C**：单元在大纲里但**还没有内容** → 不算"节点不存在"，而是"先补内容"：
        # 建会话并回卡片（界面就地给一键生成），不让用户撞 404/409 的墙、更不进空会话。
        res_unit = outline_gate.resolve_subject_unit(db, node_id)
        if loaded is None and res_unit is None:
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

        blocked = (self._missing_node_card(db, node_id) if loaded is None
                   else self._content_gate(db, loaded.doc))
        if blocked is None:
            # 门禁：先判学科停用（B4"移除可恢复"：停用学科不可进入学习），再按学科分流——
            # 通用学科（custom）走大纲权威（service.outline_gate）；math 走蓝图总序（service.path）。
            # 仅"进入新节点"受控（既有会话恢复/练习费曼续走不受影响）。
            subj_id = outline_gate.subject_of_node(db, node_id)
            if subj_id is not None and outline_gate.is_subject_disabled(db, subj_id):
                raise SessionError(
                    f"学科「{subj_id}」已停用（可从学科页重新启用后继续学习）",
                    code="invalid_state",
                )
            if res_unit is not None:
                ok_gate, missing = outline_gate.unit_allowed(db, self.user_id, res_unit[0], res_unit[1])
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
        if blocked is not None:
            # **R54 C/A**：内容不足或还没有内容 → **不建会话**（内容库还没有这个节点，会话外键也挂不上），
            # 直接回"先补内容"卡片：界面据此就地提示 + 一键生成，不把人带进空会话。
            return {
                "step": STEP_CONTENT_MISSING,
                "payload": {"first_open": False, "content_missing": blocked},
                "events": [{"type": "content_missing", "reason": blocked["reason_zh"]}],
                "session": {"id": "", "node_id": node_id, "state": "blocked",
                            "stage": STEP_CONTENT_MISSING},
            }
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
        # R29 引申：flow schema 演进自愈（缺键/错类型/整块缺失）——step() 是真正的 choke point，
        # 不能只挂在 resume()（R29 首修只改 _ensure_invariants → 探针仍复现的教训）。
        sess.flow_json = _ensure_flow_shape(sess.flow_json)
        # **R54 A：前置内容守卫**——内容不足（或节点已不在库）时，除"退出"外的任何动作都不该继续：
        # 不调模型、不判题、不评费曼，只回"缺什么 + 一键生成"的卡片。
        if action != "quit":
            node, blocked = self._node_or_gate(db, sess)
            if blocked is not None:
                return self._content_missing_response(db, sess, blocked)
        else:
            node = None
            try:
                node = self._node_of(db, sess)
            except SessionError:
                node = None
        assert node is not None or action == "quit"
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
        if action == "reissue_after_regen":
            return self._act_reissue_after_regen(db, sess, node)
        if action in ("feynman_submit", "feynman_answer"):
            text = str(payload.get("transcript", payload.get("answer", "")))
            if action == "feynman_answer":
                return self._act_feynman_answer(db, sess, node, text, payload)
            return self._act_feynman(db, sess, node, text, payload)
        if action == "finish":
            return self._act_finish(db, sess, node)
        if action in CHALLENGE_ACTIONS:
            return self._act_challenge(db, sess, node, action, payload)
        if action == "quit":
            sess.state = "quit"
            db.flush()
            return {"ok": True, "step": sess.flow_json.get("stage"), "session": self._session_meta(db, sess)}
        # get
        return self._response(db, sess, events=[])

    # ------------------------------------------------------------------
    # 内部：阶段前进
    # ------------------------------------------------------------------
    def _act_reissue_after_regen(self, db: Session, sess: models.Session, node: NodeDoc) -> dict[str, Any]:
        """R25 保护式"一键换题"：仅当本节点最近 15 分钟内有成功的内容纠错替换，
        且当前确在做练习（未达标、有当前题）时才允许；每节点每会话限 2 次，防被当"跳过题"滥用。"""
        flow = sess.flow_json
        p = flow["practice"]
        if flow.get("stage") != "practice":
            raise SessionError("只有练习阶段可以换题", code="invalid_state")
        if p.get("passed"):
            raise SessionError("练习已达标，不能再换题", code="invalid_state")
        if not p.get("current"):
            raise SessionError("当前没有待作答题目", code="invalid_state")
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
        recent = (
            db.query(models.Feedback)
            .filter(
                models.Feedback.node_id == node.id,
                models.Feedback.status == "regenerated",
                models.Feedback.updated_at >= cutoff,
            )
            .first()
        )
        if recent is None:
            raise SessionError("本节点最近没有刚纠错替换的新内容，暂不能换题", code="invalid_state")
        used = int(flow.get("regen_reissue_used", 0))
        if used >= 2:
            raise SessionError("本节点本轮最多换 2 次题，请继续作答或退出后重进", code="invalid_state")
        flow["regen_reissue_used"] = used + 1
        p["current"] = None
        p["attempts_this"] = 0
        p["hints_this"] = 0
        db.flush()
        return self._response(
            db, sess, events=[{"type": "question_reissued", "reason": "内容纠错已替换，抽新题"}]
        )

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
        decision = self._resolve_tier(db, node=node, override=override, call_name="answer_question")
        out, degraded = self._call(db, self.gateway.answer_question, ctx, strategy=decision.strategy)
        upgraded = False
        strategy_used = decision.strategy
        if (
            decision.strategy == ai_tier.FAST
            and self._model_mode(db) == "smart"
            and getattr(out, "out_of_scope", False)
        ):
            # 超纲/需深思 → think 重生成一次覆盖回复（用户感知"这问题值得深思"）
            think_decision = self._resolve_tier(db, node=node, override=True, call_name="answer_question")
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
        decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"), call_name="hint_on_error")
        out, degraded = self._call(db, self.gateway.hint_on_error, ctx, strategy=decision.strategy)
        p["hints_this"] += 1
        db.flush()
        return self._response(
            db,
            sess,
            events=[{"type": "hint_given", "count": p["hints_this"]}],
            extra_payload={"hint_md": out.hint_md, "degraded": degraded, "strategy": decision.strategy},
        )

    def _subject_is_all_ai(self, db: Session, node: NodeDoc) -> bool:
        """该节点所属学科是不是「图片为主的教材（全 AI 模式）」（工单 §3-A 的模式隔离口径）。"""
        try:
            head, sep, _ = str(node.id).partition(".")
            if not sep:
                return False
            from ..outline import materials as mat

            return mat.subject_mode(db, head) == mat.MODE_ALL_AI
        except Exception:      # 判不出来不许影响主流程（宁可当文字路径，也不炸会话）
            return False

    def _act_submit_ai(self, db: Session, sess: models.Session, node: NodeDoc,
                       cur: RenderedExercise, user_answer: str) -> dict[str, Any]:
        """**R56 第 3 步**：图示教材模式的判题（模型判）＋**诚实出口**。

        - 判对/部分对/判错 → 走**同一套流程骨架**（进度、连对、进费曼都由程序决定）；
        - **判不出来**（模型说 uncertain）→ **不打分、不动进度**，如实告诉学生并记一条中文账；
        - 分数与结论**原样来自模型**（程序不验算、不改分）。
        """
        p = sess.flow_json["practice"]
        from ..outline import mode_pages
        from . import mode_ai

        head, _, _ = str(node.id).partition(".")
        pages_digest = ""
        try:
            pages_digest = mode_pages.pages_digest(db, head)
        except Exception:
            pages_digest = ""
        # 判题要"能直接问模型的 provider"：真网关藏在 `_p` 后面；离线网关没有 → 走诚实出口
        gw = self.gateway
        provider = gw if hasattr(gw, "chat_json") else getattr(gw, "_p", None)
        if provider is None or not hasattr(provider, "chat_json"):
            from . import ledger as _ledger

            reason = "现在没有可用的模型（离线），这道题判不了"
            _ledger.note(_ledger.CAT_MODEL_CALL, "判题（图示教材模式）",
                         reason + "——已如实告诉学生（不算对也不算错）。",
                         impact=_ledger.SCOPE_UNIT, remedy=_ledger.REMEDY_CONFIRM,
                         subject_id=head, unit_id=node.id,
                         detail={"kind": "judge_uncertain", "reason": "no_model"})
            return self._response(db, sess, events=[{"type": "judge_uncertain", "node_id": node.id}],
                                  extra_payload={"verdict": "uncertain", "judged_by": "model",
                                                 "reason_zh": reason + "（不算对也不算错）",
                                                 "progress": self._progress_view(p)})
        out = mode_ai.judge(
            provider,
            mode_ai.ModeJudgeIn(
                prompt=cur.prompt, kind=str(getattr(cur, "ai_answer_kind", "") or "short"),
                options=list(getattr(cur, "options", []) or []),
                reference_answer=str(getattr(cur, "ai_answer", "") or ""),
                explanation=str(getattr(cur, "ai_explanation", "") or ""),
                student_answer=user_answer, pages_digest=pages_digest),
            subject_id=head, unit_id=node.id, pages=pages_digest)

        status = str(out.get("status") or "uncertain")
        if status == "uncertain":
            # **诚实出口**：不算对也不算错；模型给的分不落地（`counted=False` 在 mode_ai 里已记账）
            return self._response(db, sess, events=[{"type": "judge_uncertain", "node_id": node.id}],
                                  extra_payload={
                                      "verdict": "uncertain",
                                      "reason_zh": out.get("reason_zh") or "这一次没判出来",
                                      "feedback_md": out.get("feedback_md") or "",
                                      "progress": self._progress_view(p),
                                      "judged_by": "model"})

        correct = status == "correct"
        result = JudgeResult(correct=correct, expected=str(getattr(cur, "ai_answer", "") or ""),
                             detail=f"[图示教材模式·模型判] {status}"
                                    + (f"｜{str(out.get('feedback_md') or '')[:120]}"))
        self._record_attempt(db, sess, node, cur, user_answer, result)
        events: list[dict] = [{"type": "exercise_judged_by_model", "node_id": node.id,
                               "status": status}]
        extra: dict[str, Any] = {"judged_by": "model", "verdict": status,
                                 "feedback_md": out.get("feedback_md") or "",
                                 "better_md": out.get("better_md") or "",
                                 "basis_pages": list(out.get("basis_pages") or []),
                                 "score_0_1": float(out.get("score_0_1") or 0.0)}
        if correct:
            p["attempts_this"] = 0
            p["streak"] += 1
            p["streak_min"] = (float(cur.difficulty) if p["streak_min"] is None
                               else min(p["streak_min"], float(cur.difficulty)))
            events.append({"type": "exercise_correct", "node_id": node.id,
                           "consecutive_correct": p["streak"]})
            if p["streak"] >= TARGET_STREAK:
                p["passed"] = True
                events.append({"type": "practice_passed", "consecutive_correct": p["streak"]})
                self._enter_feynman(db, sess, node, events)
                return self._response(db, sess, events=events, extra_payload=extra)
            if p["issued"] >= PRACTICE_CAP:
                self._cap_fail_cycle(db, sess, node, events)
            else:
                self._issue_next(db, sess, node)
                events.append({"type": "question_issued"})
            extra["progress"] = self._progress_view(p)
            return self._response(db, sess, events=events, extra_payload=extra)

        # 部分对 / 判错：**不扣连对**（部分对）或按答错处理；提示直接用模型给的反馈
        if status == "partial":
            extra["progress"] = self._progress_view(p)
            return self._response(db, sess, events=events + [{"type": "exercise_partial"}],
                                  extra_payload=extra)
        p["streak"] = 0
        p["streak_min"] = None
        p["attempts_this"] += 1
        events.append({"type": "exercise_wrong", "retry_left": max(0, 2 - p["attempts_this"])})
        if p["attempts_this"] >= 2:
            # 两次判错 → 回炉看讲解（本模式直接回讲解阶段；讲解就是本单元的正文）
            sess.flow_json["stage"] = STAGE_EXPLAIN
            sess.flow_json["explained_seen"] = False
            p["attempts_this"] = 0
            events.append({"type": "relearn_explain"})
        else:
            self._issue_next(db, sess, node)
            events.append({"type": "question_issued"})
        extra["progress"] = self._progress_view(p)
        return self._response(db, sess, events=events, extra_payload=extra)

    def _act_submit(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any]) -> dict[str, Any]:
        p = sess.flow_json["practice"]
        cur = self._require_current(sess, node)
        ex_id = payload.get("exercise_id")
        if ex_id != cur.exercise_id or int(payload.get("params_seed", -1)) != cur.seed:
            raise SessionError("提交的题目与当前题目不一致，请刷新", code="invalid_state")
        user_answer = str(payload.get("user_answer", "")).strip()

        # **R56 第 3 步 · 模式隔离**：图示教材模式的题（check.mode == "ai"）**判对错由模型做**——
        # 走本模式分支，**不碰** sympy 判题（工单 §1/§3-A：两条路不许共用判题逻辑）。
        if str(getattr(cur, "mode", "")) == "ai":
            return self._act_submit_ai(db, sess, node, cur, user_answer)

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
        hint_decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"), call_name="hint_on_error")
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
        """R27：``feynman_submit`` = **完整稿**（首讲 / 整合重讲）→ 整体评分。

        - 评分对象 = 本轮完整稿（**不再拼"最初稿 + 追问 + 补充"合并稿**：R25 语义被 R27 取代，
          治"新增回答被旧文锚定、两轮逐字同分"）；
        - ``previously_acknowledged`` = 账本已认可内容摘要（没重抄已认可点不扣分）；
        - evidence 包含校验：引文不在本轮文本 → 该维度降级并标记（防"没读新内容还打分"）；
        - 账本取历轮最高分 → 实时综合分；**只有完整稿 ≥ threshold 才 pass**（补答不能单独过关）；
        - R30 F6：本轮综合分落**边缘带**（threshold −0.05/+0.08）且本轮非 think → 以 think
          复评一次，取两次较高者并入账本（防"同一篇讲解这次过、下次不过"的阈值抖动）。
        """
        flow = sess.flow_json = _ensure_flow_shape(sess.flow_json)  # R29 引申：进费曼前再自愈一次
        p = flow["practice"]
        f = flow["feynman"]
        # **R54 A**：没看过讲解就不许开讲（用户实测场景）——不报错，直接把人送回讲解。
        if not flow.get("explained_seen"):
            return self._rewind_to_explain(db, sess,
                                           "你还没有看过这一节的讲解——先看完讲解，再讲一遍就能继续。")
        if not p["passed"]:
            raise SessionError("费曼环节需要先完成练习达标（连续答对 3 题）", code="invalid_state")
        dims = [d.model_dump() for d in node.feynman.rubric.dimensions]
        ledger = fl.normalize_ledger(f, dims)
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
        # R35 S4：学生没有可引用的实质内容（"我不知道"类敷衍）→ **退回讲解补讲（reteach）**，
        # 不烧评分额度、不生成"无法回答的追问"（确定性前置；模型层另有 student_quote 兜底）。
        if not fl.has_quotable_content(text):
            events.append({"type": "feynman_reteach", "reason": "transcript_no_quotable_content"})
            return self._response(db, sess, events=events,
                                  extra_payload=self._reteach_payload(db, sess, node, "no_quotable_content"))
        threshold = node.feynman.rubric.pass_threshold
        eval_rounds = self._feynman_eval_rounds(f)
        if eval_rounds >= MAX_FEYNMAN_EVALS:
            raise SessionError("费曼整体稿评分已达上限（首讲 + 2 次终验），请重新学习后再来", code="invalid_state")

        ctx = FeynmanEvaluateIn(
            session_id=sess.id,
            node_id=node.id,
            task_prompt=node.feynman.task_prompt,
            rubric_dimensions=dims,
            core_concepts=list(node.core_concepts),
            transcript=text,                       # R27：本轮完整稿（不拼历史）
            previous_round=(
                {
                    "round": eval_rounds,
                    "combined": round(fl.combined(ledger), 3),
                    "dims": f["last_scores"][-1],  # 上一轮分维卡（热修 R10）
                }
                if f["last_scores"]
                else None
            ),
            previously_acknowledged=fl.candidate_acknowledged(ledger),  # R27：已认可内容摘要
        )
        # R12：费曼档位 = 基础档(学段/content.thinking) + 触发(边缘分上轮 flag / 轮次≥2)
        # + 用户覆盖(model_mode / payload.think_deep)
        trigger_think = bool(f.get("edge_think")) or ai_tier.feynman_round_should_think(eval_rounds + 1)
        decision = self._resolve_tier(
            db, node=node, override=payload.get("think_deep"), extra_think=trigger_think,
            call_name="feynman_evaluate",
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

        round_no = eval_rounds + 1
        f["rounds_done"] = round_no
        f["last_transcript"] = text
        # ---- R30 F6：边缘带复评（本轮综合分接近门槛且本轮非 think → think 复评一次取高分） ----
        # 判定与比较都在**净化后的本轮评分卡**上做（evidence 校验/降级口径与入账一致）。
        first_card, first_penalty = fl.clean_card(self._card_of(node, out.dimension_scores), transcript=text)
        first_combined = round(fl.card_combined(first_card), 3)
        card, evidence_penalty = first_card, first_penalty
        adopted_strategy, adopted_reason = decision.strategy, decision.reason
        taken = "first"
        recheck: dict[str, Any] = {
            "used": False,
            "first_combined": first_combined,
            "second_combined": None,
            "taken": taken,
        }
        # 触发三条件（R30 §F6.2）：落边缘带 + 本轮档位非 think + 本轮尚未复评过。
        # "尚未复评过"由结构保证：本分支在单次完整稿提交内只走一次，且复评结果并入账本后
        # rounds_done 递增 → 同一轮不可能再次触发（无循环、每轮最多 1 次额外 heavy 调用）。
        if decision.strategy != ai_tier.THINK and ai_tier.feynman_recheck_band(first_combined, threshold):
            recheck["used"] = True
            try:
                out2 = self.gateway.feynman_evaluate(ctx, strategy=ai_tier.THINK)
            except AiCallError:
                # R30 §F6.4：复评失败保留首次结果，不因复评失败而失败（不 500、不换档位）
                events.append(
                    {"type": "feynman_edge_recheck", "first": first_combined, "second": None, "taken": taken}
                )
            else:
                second_card, second_penalty = fl.clean_card(
                    self._card_of(node, out2.dimension_scores), transcript=text
                )
                second_combined = round(fl.card_combined(second_card), 3)
                recheck["second_combined"] = second_combined
                if second_combined > first_combined:
                    card, evidence_penalty = second_card, second_penalty
                    out = out2  # recommend_action / confidence 同取采用的这一次
                    adopted_strategy, adopted_reason = ai_tier.THINK, "edge_recheck=think"
                    taken = "second"
                recheck["taken"] = taken
                events.append(
                    {"type": "feynman_edge_recheck", "first": first_combined, "second": second_combined, "taken": taken}
                )
        f["last_strategy"] = adopted_strategy
        # 以"采用那一次"的卡并入账本（维度仍取 max）；首轮判分卡已净化，禁止二次降级
        fl.merge_clean_card(ledger, card, round_no=round_no)
        f["last_scores"].append(card)
        f["last_combined"] = round(fl.combined(ledger), 3)  # 实时综合分 = 账本 max 合成
        fl.extract_gaps(ledger, card, threshold, round_no=round_no)  # 未达标维度 → 缺口清单
        passed = f["last_combined"] >= threshold
        self._record_feynman_attempt(
            db, sess, node, text,
            "pass" if passed else "fail",
            f["last_combined"],
            meta={
                "dims": card,
                "recommend_action": out.recommend_action,
                "strategy": adopted_strategy,           # R12/R30：**实际采用**那次的档位（评分卡标注）
                "strategy_reason": adopted_reason,
                "confidence": getattr(out, "confidence", None),
                "evidence_penalty": evidence_penalty,
                "ledger_combined": f["last_combined"],
                "eval_rounds_done": round_no,
                "recheck": recheck,                     # R30 F6：两次评分卡与采用结论
            },
        )
        if passed:
            f["passed"] = True
            events.append({"type": "feynman_passed", "score": f["last_combined"]})
            # R27：通过时同样回传本轮评分卡（复盘/UI 展示"这一轮是怎么过的"）
            return self._master_if_ready(
                db, sess, node, events,
                extra_payload={
                    "verdict": "pass",
                    "dimension_scores": card,
                    "evidence_penalty": evidence_penalty,
                    "strategy": adopted_strategy,
                    "strategy_reason": adopted_reason,
                },
            )
        # 未过：命中边缘区间 → 下轮升 think（R12 触发 a；R30 已用 think 复评过则不必再标）
        if (
            adopted_strategy == ai_tier.FAST
            and self._model_mode(db) == "smart"
            and ai_tier.feynman_edge(f["last_combined"], threshold)
        ):
            f["edge_think"] = True
        events.append({"type": "feynman_failed", "score": f["last_combined"], "round": round_no})
        if evidence_penalty:
            events.append({"type": "feynman_evidence_flagged", "reason": "部分评分引文不在本轮提交文本中，已降级"})
        # R27 §4 预算：两额度尽或整体稿评分满 3 次仍未过 → 回炉（沿用 _feynman_reset）
        if round_no >= MAX_FEYNMAN_EVALS or (
            f["answers_done"] >= MAX_FEYNMAN_ANSWERS and fl.weakest(ledger, threshold) is None
        ):
            self._relearn_explain(db, sess, node, events, reason="费曼未通过（整体稿/补答额度已尽）")
            events.append({"type": "feynman_relearn"})
            return self._response(db, sess, events=events)

        gap = fl.weakest(ledger, threshold)
        q_out, q_degraded, q_gap, reteach_reason = self._feynman_followup(db, sess, node, f, text, gap, payload)
        if reteach_reason:
            # S4：追问必须逐字引用学生原话；引用不成立/学生无可引用内容 → **不发追问**，退回讲解
            f["followup"] = None
            f["followup_gap"] = None
            events.append({"type": "feynman_reteach", "reason": reteach_reason})
            return self._response(db, sess, events=events,
                                  extra_payload=self._reteach_payload(db, sess, node, reteach_reason))
        events.append({"type": "feynman_followup", "round": round_no, "target_gap": (q_gap or {}).get("key")})
        db.flush()
        return self._response(
            db,
            sess,
            events=events,
            extra_payload={
                "verdict": "fail",
                "combined": f["last_combined"],
                "threshold": threshold,
                "dimension_scores": card,
                "followup_question": q_out.question_md,
                # R35 S4：追问携带"逐字引用的学生原话"与"这句话缺了什么"
                "followup_quote": str(getattr(q_out, "student_quote", "") or ""),
                "followup_missing": str(getattr(q_out, "missing", "") or ""),
                "followup_gap": q_gap,
                "evidence_penalty": evidence_penalty,
                "next_action": "answer",
                "degraded": q_degraded,
                "strategy": adopted_strategy,  # R12/R30：**实际采用**那次评分的档位
                "strategy_reason": adopted_reason,
            },
        )

    def _act_feynman_answer(self, db: Session, sess: models.Session, node: NodeDoc, answer: str, payload: dict[str, Any]) -> dict[str, Any]:
        """R27：``feynman_answer`` = **补答**（只答当前追问）→ 轻量缺口补答评估。

        - 只更新缺口所属维度（``dimension_updates`` 仅含该维度），账本取历轮最高分 →
          答对立刻可见涨分（"答对认账"）；
        - **不能单独过关**：补答只涨账本与展示进度，通过仍需完整稿 ≥ threshold（防挤牙膏式被动应答）；
        - 预算 ≤2；同一缺口答不对 → 缺口保留、可再追一次；额度尽且无剩余缺口 → review 请求整合终验。
        """
        flow = sess.flow_json = _ensure_flow_shape(sess.flow_json)  # R29 引申：补答前再自愈一次
        p = flow["practice"]
        f = flow["feynman"]
        # **R54 A**：没看过讲解就不许补答（同 `_act_feynman`：送回讲解而不是报错）
        if not flow.get("explained_seen"):
            return self._rewind_to_explain(db, sess,
                                           "你还没有看过这一节的讲解——先看完讲解，再继续作答。")
        if not p["passed"]:
            raise SessionError("费曼环节需要先完成练习达标（连续答对 3 题）", code="invalid_state")
        dims = [d.model_dump() for d in node.feynman.rubric.dimensions]
        ledger = fl.normalize_ledger(f, dims)
        threshold = node.feynman.rubric.pass_threshold
        question = str(f.get("followup") or "")
        gap = next((g for g in (ledger.get("gaps") or []) if g.get("key") == f.get("followup_gap")), None)
        if not question or not gap or gap.get("filled"):
            raise SessionError(
                "当前没有待补答的追问：请直接提交完整讲解（整合重讲）由整体评分判定。",
                code="invalid_state",
            )
        if f["answers_done"] >= MAX_FEYNMAN_ANSWERS:
            raise SessionError("补答次数已达上限（2 次），请提交整合后的完整讲解。", code="invalid_state")
        text = answer.strip()
        events: list[dict] = []
        if len(text) < 10:
            events.append({"type": "feynman_answer_too_short", "min_chars": 10})
            return self._response(
                db,
                sess,
                events=events,
                extra_payload={"verdict": "gap", "message": "补答太短（少于 10 字），请具体回答追问里要你补讲的那一点。"},
            )
        gap_key = str(gap.get("key") or "")
        entry = ledger["dims"].get(gap_key) or {}
        prev_evidence = str(entry.get("evidence_quote") or "")
        ctx = GapCheckIn(
            session_id=sess.id,
            node_id=node.id,
            task_prompt=node.feynman.task_prompt,
            rubric_dimensions=dims,
            core_concepts=list(node.core_concepts),
            followup_question=question,
            student_answer=text,
            target_gap={
                "key": gap_key,
                "description": gap.get("description") or "",
                "evidence_quote": prev_evidence or gap.get("evidence_quote") or "",
                "comment": gap.get("comment") or "",
                "previous_score": gap.get("score"),
            },
        )
        decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"),
                                      call_name="feynman_gap_check")
        try:
            # R7 精神：LLM 调用前先提交（补答评估虽为 light 档，仍不持写锁）
            db.commit()
        except Exception:
            db.rollback()
            raise
        out, degraded = self._call(db, self.gateway.feynman_gap_check, ctx, strategy=decision.strategy)
        round_no = self._feynman_eval_rounds(f)
        f["answers_done"] += 1
        # 只认缺口所属维度（模型多给的键一律忽略，防越权改分）
        updates = [u for u in (out.dimension_updates or []) if str(getattr(u, "key", "")) == gap_key]
        filled = False
        rows: list[dict] = []
        penalty = False
        for u in updates:
            row, pen = fl.update_dimension(
                ledger,
                key=gap_key,
                score=float(u.score),
                evidence_quote=str(u.evidence_quote),
                comment=str(u.comment),
                transcript=text,
                round_no=round_no,
            )
            penalty = penalty or pen
            rows.append(row)
            if row["score"] >= threshold:
                filled = True
        if not updates:
            # 无有效更新（模型判 gap_filled=false 或分数为 0）→ 该维度零分入账（best 不变）
            row, pen = fl.update_dimension(
                ledger, key=gap_key, score=0.0, evidence_quote="", comment=str(out.comment or ""),
                transcript=text, round_no=round_no,
            )
            penalty = penalty or pen
            rows.append(row)
        fl.mark_gap_attempt(ledger, gap_key, filled=filled)
        f["last_combined"] = round(fl.combined(ledger), 3)
        f["followup"] = None
        f["followup_gap"] = None
        self._record_feynman_attempt(
            db, sess, node, text, "gap_filled" if filled else "gap_open", None,
            meta={
                "gap_key": gap_key,
                "gap_filled": bool(filled),
                "dimension_updates": rows,
                "strategy": decision.strategy,
                "ledger_combined": f["last_combined"],
                "answers_done": f["answers_done"],
            },
        )
        events.append({"type": "feynman_gap_filled" if filled else "feynman_gap_open",
                       "gap": gap_key, "score": rows[0]["score"] if rows else 0.0})
        if penalty:
            events.append({"type": "feynman_evidence_flagged", "reason": "补答评分引文不在本轮文本中，已降级"})
        threshold_msg = f"（该维度认定线 {threshold}）"
        if filled:
            note = f"✅ 缺口已补上：{gap.get('description') or gap_key} {threshold_msg}。接着请把整段讲解整合重讲一遍——通过仍需完整稿达标。"
        else:
            note = f"❌ 这次还没答到位：{gap.get('description') or gap_key} {threshold_msg}。缺口保留在账本里——**再交一次完整讲解后，会针对该缺口再问**。"
        db.flush()
        return self._response(
            db,
            sess,
            events=events,
            extra_payload={
                "verdict": "gap",
                "gap_filled": bool(filled),
                "gap_key": gap_key,
                "gap_description": gap.get("description") or "",
                "gap_update": rows[0] if rows else None,
                "dimension_updates": rows,
                "combined": f["last_combined"],
                "threshold": threshold,
                "message": note,
                "next_action": "submit",  # 补答只涨账本；通过必须交完整稿（R27 §5）
                "strategy": decision.strategy,
                "degraded": degraded,
            },
        )

    # ------------------------------------------------------------------
    # 内部：费曼账本/预算/追问（R27）
    # ------------------------------------------------------------------
    @staticmethod
    def _feynman_eval_rounds(f: dict[str, Any]) -> int:
        """整体稿评分次数（rounds_done 为准，兼容历史会话）。"""
        return int(f.get("rounds_done") or 0)

    def _feynman_followup(
        self,
        db: Session,
        sess: models.Session,
        node: NodeDoc,
        f: dict[str, Any],
        transcript: str,
        gap: dict | None,
        payload: dict[str, Any],
    ) -> tuple[FeynmanFollowupOut, bool, dict | None, str]:
        """R27 定向追问 + **R35 S4 追问纪律**。返回 (追问, 是否降级, 目标缺口, reteach 原因)。

        S4（本批新增，逐条落在代码上）：
        - 追问**必须逐字引用学生刚说的话**：`student_quote` 必须能在本轮完整稿里逐字找到
          （`feynman_ledger.quote_valid`，与 evidence/basis 同一把尺子）；
        - 并指出**这句话缺了什么**：`missing` 非空；
        - 学生**无可引用内容**、或引文不成立、或模型自陈 `reteach` → **不发追问**，
          第四个返回值给出原因，由调用方返回 `reteach`（退回讲解补讲）；
        - socratic 主题**只有在 basis 逐字成立时**才作为语料下发（模板套话不得兜底）。
        """
        if gap is None:
            # 无缺口：这不是"追问"，而是"请交完整稿"的指令（不适用引文要求）
            return (
                FeynmanFollowupOut(question_md="把追问里补上的内容整合进完整讲解，再提交一次完整稿（终验）。"),
                False,
                None,
                "",
            )
        q_ctx = FeynmanFollowupIn(
            session_id=sess.id,
            node_id=node.id,
            student_transcript=transcript,   # R27：本轮完整稿（不拼历史）
            previous_scores=(f["last_scores"][-1] if f["last_scores"] else []),  # R10：最近一轮分维卡
            socratic_followups=self._backed_socratic(node),  # S4：只带有据的主题（模板套话不下发）
            unmet_gaps=[dict(g) for g in (gap,)],  # R27：最弱缺口（一次一个）
        )
        q_decision = self._resolve_tier(
            db, node=node, override=payload.get("think_deep"),
            extra_think=bool(f.get("edge_think")) or ai_tier.feynman_round_should_think(f["rounds_done"] + 1),
            call_name="feynman_followup",
        )
        q_out, q_degraded = self._call(db, self.gateway.feynman_followup, q_ctx, strategy=q_decision.strategy)
        quote = str(getattr(q_out, "student_quote", "") or "")
        missing = str(getattr(q_out, "missing", "") or "")
        question = str(getattr(q_out, "question_md", "") or "")
        if getattr(q_out, "reteach", False):
            return FeynmanFollowupOut(reteach=True), q_degraded, gap, "model_says_reteach"
        if not fl.has_quotable_content(transcript):
            return FeynmanFollowupOut(reteach=True), q_degraded, gap, "no_quotable_content"
        if not quote or not fl.quote_valid(quote, transcript):
            return FeynmanFollowupOut(reteach=True), q_degraded, gap, "quote_not_verbatim"
        if not missing.strip():
            return FeynmanFollowupOut(reteach=True), q_degraded, gap, "missing_not_stated"
        if not question.strip():
            return FeynmanFollowupOut(reteach=True), q_degraded, gap, "question_empty"
        f["followup"] = question
        f["followup_gap"] = gap.get("key")
        return q_out, q_degraded, gap, ""

    def _reteach_payload(self, db: Session, sess: models.Session, node: NodeDoc, reason: str) -> dict[str, Any]:
        """S4 `reteach` 响应体：**退回讲解补讲**（不翻转 state 机、不动任何账本）。

        **为什么不把 stage 翻回 `explain`**（本批明确决策，见 NOTES §66）：练习已通过时
        "讲解→例题→练习"会**重新出题**并再次计入 practice 账目，等于用一次"敷衍回答"
        污染练习记录——与 S4 的目的（把学生送回讲解）背道而驰。
        改为：**原阶段不动**，随响应直接下发讲解原文 + `next_action="reteach"`，
        学生当场就能看讲解、补讲后再交一次完整稿。
        """
        cache = sess.flow_json.get("lecture_cache") or {}
        lecture = str(cache.get("lecture_md") or "") or (node.explanation.body or node.body_md or "")
        reasons = {
            "no_quotable_content": "你这次没有讲出可供引用的实质内容（例如只说「我不知道」），"
                                   "没有可以追问的点",
            "quote_not_verbatim": "这次追问没能逐字引用你刚说过的话（服务端引文校验未通过）",
            "missing_not_stated": "这次追问没有说清「你这句话缺了什么」",
            "model_says_reteach": "这次没有可追问的实质内容",
            "question_empty": "这次追问生成失败（内容为空）",
        }
        why = reasons.get(reason, "这次没有可追问的实质内容")
        return {
            "verdict": "reteach",
            "next_action": "reteach",
            "reteach": {
                "reason": reason,
                "message_md": (
                    f"📖 **退回讲解补讲**：{why}。\n\n"
                    "请先回看下面的讲解稿（尤其是本次未达标的维度），"
                    "然后**再交一次完整讲解**——我不会拿一条你答不出的问题来逼你想。"
                ),
                "lecture_md": lecture,
                "missing_dimensions": [
                    {"key": g.get("key"), "description": g.get("description")}
                    for g in (sess.flow_json.get("feynman", {}).get("ledger", {}).get("gaps") or [])
                    if not g.get("filled")
                ],
            },
        }

    @staticmethod
    def _backed_socratic(node: NodeDoc) -> list[str]:
        """S4：**只有 basis 逐字成立**的 socratic 主题才作为追问语料下发（模板套话不得兜底）。

        复用 `content.answerability.check_basis`（引文纪律**同一实现**，不重写包含校验）。
        """
        from ..content import answerability

        lecture = node.explanation.body or node.body_md or ""
        ids = answerability.fact_id_set(node.taught_facts or [])
        follows = list(node.feynman.socratic_followups or [])
        bases = list(node.feynman.socratic_basis or [])
        out: list[str] = []
        for i, ask in enumerate(follows):
            basis = bases[i] if i < len(bases) else None
            ok, _ = answerability.check_basis(basis, lecture=lecture, fact_ids=ids,
                                              label=f"socratic[{i + 1}]")
            if ok:
                out.append(ask)
        return out

    @staticmethod
    def _card_of(node: NodeDoc, dim_scores) -> list[dict]:
        """评分卡（含权重，供账本合成分与 UI 展示）。"""
        weights = {d.key: d.weight for d in node.feynman.rubric.dimensions}
        return [
            {
                "key": ds.key,
                "score": ds.score,
                "weight": weights.get(ds.key, 0.0),
                "evidence_quote": ds.evidence_quote,
                "comment": ds.comment,
            }
            for ds in dim_scores
        ]

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
    # R35 S3：挑战题池（**完全不上算**）
    #
    # 红线（docs/09 R35 §10 红线③ / 工单 §3b）：挑战题的作答**不进费曼账本**、**不参与 mastery**、
    # **不消耗**整体稿/补答额度、**不计入**掌握统计（`user_nodes`）——只记复盘（`attempts.kind="challenge"`）。
    # 它**永不出现在默认流程**：本节的四个键只被 `challenge_*` 动作读写，默认 `_response` 不带它们。
    # 单题三态（开始作答/取消/明确放弃）**都要能点、都要无后果**：`asked/answered` 只是展示计数，
    # **不设额度、不计轮次、不做任何门禁**（任何一处拿它们做判断都算违规）。
    # ------------------------------------------------------------------
    def _act_challenge(self, db: Session, sess: models.Session, node: NodeDoc, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        flow = sess.flow_json
        ch = flow["challenge"]
        if action == "challenge_start":
            return self._challenge_start(db, sess, node, payload, ch)
        if action == "challenge_begin":
            if ch.get("current") is None:
                raise SessionError("当前没有挑战题：请先点「挑战一下」生成一道", code="invalid_state")
            ch["phase"] = "answering"          # 纯 UI 状态推进：无任何后果
            db.flush()
            return self._response(db, sess, events=[{"type": "challenge_begin"}],
                                  extra_payload=self._challenge_payload(ch))
        if action == "challenge_submit":
            return self._challenge_submit(db, sess, node, payload, ch)
        if action == "challenge_cancel":
            had = ch.get("current") is not None
            ch["current"] = None
            ch["phase"] = "idle"
            db.flush()
            events = [{"type": "challenge_cancelled"}] if had else []
            return self._response(
                db, sess, events=events,
                extra_payload={**self._challenge_payload(ch),
                               "message": "已取消本次挑战（**什么都没记**，进度不受影响）。"
                               if had else "当前没有进行中的挑战题。"})
        # challenge_abandon：明确放弃（"我不会/我不感兴趣"）—— 只记复盘，同样无后果
        had = ch.get("current") is not None
        if had:
            self._record_challenge(db, sess, node, ch["current"], "", "abandoned", 0.0,
                                   meta={"reason": "学习者明确放弃（我不会/我不感兴趣）"})
        ch["current"] = None
        ch["phase"] = "idle"
        db.flush()
        events = [{"type": "challenge_abandoned"}] if had else []
        return self._response(
            db, sess, events=events,
            extra_payload={**self._challenge_payload(ch),
                           "message": "已记下你放弃这道挑战题——**不影响任何进度**（只进复盘）。"
                           if had else "当前没有进行中的挑战题。"})

    def _challenge_start(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any], ch: dict[str, Any]) -> dict[str, Any]:
        """「挑战一下」：**单独调模型生成**一道挑战题（永不出现在默认流程）。"""
        ctx = ChallengeIn(
            session_id=sess.id,
            node_id=node.id,
            node_title=node.title,
            level=node.level,
            explanation_body=node.explanation.body,
            worked_examples=[w.prompt for w in node.worked_examples],
            core_concepts=list(node.core_concepts),
            whitelist=list(node.core_concepts) + node.prereqs,
            profile_style_block=self._style_block(db),
            asked=int(ch.get("asked") or 0),
        )
        decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"),
                                      call_name="challenge_exercise")
        out, degraded = self._call(db, self.gateway.challenge_exercise, ctx, strategy=decision.strategy)
        ch["asked"] = int(ch.get("asked") or 0) + 1          # 仅计数展示：不限额、不作门禁
        ch["current"] = {
            "prompt_md": str(out.prompt_md or ""),
            "answer_hint_md": str(out.answer_hint_md or ""),
            "why_hard_md": str(out.why_hard_md or ""),
            "difficulty": int(out.difficulty or 3),
        }
        ch["phase"] = "offered"
        ch["last"] = None
        db.flush()
        return self._response(db, sess, events=[{"type": "challenge_offered", "degraded": degraded}],
                              extra_payload=self._challenge_payload(ch, degraded=degraded))

    def _challenge_submit(self, db: Session, sess: models.Session, node: NodeDoc, payload: dict[str, Any], ch: dict[str, Any]) -> dict[str, Any]:
        """提交挑战题作答 → **单独判分**；结果只记复盘。"""
        cur = ch.get("current")
        if not cur:
            raise SessionError("当前没有挑战题：请先点「挑战一下」生成一道", code="invalid_state")
        text = str(payload.get("answer", payload.get("user_answer", ""))).strip()
        if not text:
            raise SessionError("挑战题作答不能为空（想放弃请点「明确放弃」——同样不影响任何进度）",
                               code="validation_error")
        ctx = ChallengeCheckIn(session_id=sess.id, node_id=node.id, node_title=node.title,
                               prompt_md=str(cur.get("prompt_md") or ""), student_answer=text)
        decision = self._resolve_tier(db, node=node, override=payload.get("think_deep"),
                                      call_name="challenge_check")
        out, degraded = self._call(db, self.gateway.challenge_check, ctx, strategy=decision.strategy)
        ch["answered"] = int(ch.get("answered") or 0) + 1    # 仅计数展示：不计轮次、不作门禁
        ch["phase"] = "graded"
        ch["last"] = {
            "correct": bool(out.correct),
            "score": float(out.score or 0.0),
            "feedback_md": str(out.feedback_md or ""),
            "better_md": str(out.better_md or ""),
        }
        self._record_challenge(db, sess, node, cur, text,
                               "correct" if out.correct else "wrong", float(out.score or 0.0))
        db.flush()
        return self._response(
            db, sess,
            events=[{"type": "challenge_graded", "correct": bool(out.correct)}],
            extra_payload={**self._challenge_payload(ch, degraded=degraded),
                           "verdict": "challenge",
                           "message": CHALLENGE_NOTICE + "（本次结果**只进复盘**）"})

    def _record_challenge(self, db: Session, sess: models.Session, node: NodeDoc, cur: dict[str, Any],
                          answer: str, verdict: str, score: float, meta: dict[str, Any] | None = None) -> None:
        """挑战题留痕 → **只进复盘**（`attempts.kind="challenge"`）。

        **绝不**写 `user_nodes`、**绝不**动 `practice`/`feynman`/账本/额度/画像——
        本方法是挑战题唯一的落库点，据此保证"作答后四项均不变"。
        """
        db.add(
            models.Attempt(
                session_id=sess.id,
                node_id=node.id,
                kind="challenge",
                exercise_id=None,
                user_input=answer,
                verdict=verdict,
                meta_json={"source": "challenge", "score": score,
                           "prompt_md": str(cur.get("prompt_md") or ""), **(meta or {})},
            )
        )
        db.flush()

    @staticmethod
    def _challenge_payload(ch: dict[str, Any], *, degraded: bool = False) -> dict[str, Any]:
        """挑战题响应视图（**只随 challenge_* 动作下发**，默认流程不带它）。"""
        return {
            "challenge": {
                "notice": CHALLENGE_NOTICE,
                "phase": str(ch.get("phase") or "idle"),
                "question": ch.get("current"),
                "last": ch.get("last"),
                "asked": int(ch.get("asked") or 0),
                "answered": int(ch.get("answered") or 0),
                "degraded": degraded,
                # 显式契约位：前端据此**不渲染任何进度/分数影响**（R35 S3 红线）
                "counts_nothing": True,
            }
        }

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
        """回炉到讲解重学（练习连错 2 次 / 费曼额度尽）。

        **R44 B（R41 §3-③）**：这里也是"回炉发生点" → 在 **R39 总账**留一条**引用条目**
        （`detail.ref="relearn_logs"`，只做索引不复制明细）；**同一次回炉幂等**（按会话+节点+原因去重）。
        """
        flow = sess.flow_json
        _practice_reset_cycle(flow["practice"])  # 模块级函数，非方法（热修 R11）
        _feynman_reset(flow["feynman"])  # R17：同上——回炉后重新走费曼必须从第 0 轮开始
        flow["stage"] = STAGE_EXPLAIN
        events.append({"type": "relearn_notice", "reason": reason})
        try:  # 记账失败不阻塞回炉本身
            from . import progress as progress_svc

            progress_svc.note_relearn_in_ledger(
                db, user_id=self.user_id, node_id=node.id, reason=reason,
                extra_key=f"{sess.id}:{reason}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部：费曼/达标
    # ------------------------------------------------------------------
    def _enter_feynman(self, db: Session, sess: models.Session, node: NodeDoc, events: list[dict]) -> None:
        flow = sess.flow_json
        # R17 防御：进入费曼前若整体稿评分已达上限（历史回炉未清零的会话/数据迁移遗留），
        # 视为新费曼阶段自动清零，避免用户"重学后仍 409 锁死"。
        if self._feynman_eval_rounds(flow["feynman"]) >= MAX_FEYNMAN_EVALS:
            _feynman_reset(flow["feynman"])
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

    def _master_if_ready(
        self,
        db: Session,
        sess: models.Session,
        node: NodeDoc,
        events: list[dict],
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            return self._response(db, sess, events=events, extra_payload=extra_payload or {})

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
            extra_payload={**(extra_payload or {}), **extra},
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
        """读取时自愈：flow 结构（R30 单一入口 `_ensure_flow_shape`）+ stage 回退等不变量。

        **R54 A**：进费曼前必须"讲解已展示过"——老会话/历史数据里 `practice.passed=True`
        但这轮从没下发过讲解（用户实测：打开一章直接被要求开讲）→ **退回讲解**，不许把人留在半步上。
        """
        # R29 → R30：老会话缺键/错类型/整块缺失一律由单一入口深度补齐（含 R27 费曼键）
        flow = _ensure_flow_shape(sess.flow_json)
        sess.flow_json = flow
        stage = flow["stage"]
        if stage in (STAGE_FEYNMAN, STAGE_DONE) and not flow.get("explained_seen"):
            # 讲解没看过就想进费曼（或已"完成"）——退回讲解，先看讲解
            flow["stage"] = STAGE_EXPLAIN
            stage = STAGE_EXPLAIN
            flow["_rewound_zh"] = "之前没有看过这一节的讲解，已退回讲解：看完再讲一遍就能继续。"
        if stage == STAGE_PRACTICE and flow["practice"]["current"] is None:
            node = self._node_of(db, sess)
            if flow["practice"]["passed"] and not flow["feynman"]["passed"] and flow.get("explained_seen"):
                flow["stage"] = STAGE_FEYNMAN  # 练习已过且讲解看过 → 推进费曼
            else:
                self._issue_next(db, sess, node)

    # ------------------------------------------------------------------
    # 响应组装（06 §2 契约：step/payload/events/session）
    # ------------------------------------------------------------------
    def _response(self, db: Session, sess: models.Session, events: list[dict], *, extra_payload: dict | None = None, first_open: bool = False) -> dict[str, Any]:
        # R30：响应组装前再自愈一次（读会话即补齐；响应体是"永不下发半截结构"的最后一道闸）
        flow = _ensure_flow_shape(sess.flow_json)
        sess.flow_json = flow
        stage = flow["stage"]
        payload: dict[str, Any] = {"first_open": first_open}
        # **R54 A：前置内容守卫**——内容不足以学（或节点已不在内容库）→ 只下发说明 + 一键生成，
        # 绝不下发学习步骤/作答入口（用户实测："我都没看过他的讲解我讲什么"）。
        node, blocked = self._node_or_gate(db, sess)
        if blocked is not None:
            return self._content_missing_response(db, sess, blocked)
        assert node is not None

        # R27：费曼账本/预算永远随响应下发（回炉/达标后仍可展示"当时的进度"）
        f = flow.get("feynman") or {}
        ledger_view = fl.gap_view(
            fl.normalize_ledger(f, node.feynman.rubric.dimensions), node.feynman.rubric.pass_threshold
        )
        payload["ledger"] = ledger_view
        payload["combined"] = ledger_view["combined"]
        payload["threshold"] = node.feynman.rubric.pass_threshold
        payload["eval_budget"] = MAX_FEYNMAN_EVALS
        payload["answer_budget"] = MAX_FEYNMAN_ANSWERS
        payload["evals_done"] = self._feynman_eval_rounds(f)
        payload["answers_done"] = int(f.get("answers_done") or 0)

        if stage == STAGE_EXPLAIN:
            payload.update(self._payload_explain(db, sess, node))
            # **R54 A**：讲解**真的下发过**（正文非空）才算"已展示"——之后才允许进费曼。
            if str(payload.get("lecture_md") or "").strip():
                flow["explained_seen"] = True
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
            payload["rounds_done"] = self._feynman_eval_rounds(f)     # 兼容旧字段：整体稿评分次数
            payload["max_rounds"] = MAX_FEYNMAN_ROUNDS
            payload["followup_question"] = f.get("followup")
            payload["followup_gap"] = next(
                (g for g in ledger_view["gaps"] if g.get("key") == f.get("followup_gap")), None
            )
            payload["next_action"] = "answer" if (f.get("followup") and f.get("followup_gap")) else "submit"
        elif stage == STAGE_DONE:
            payload["mastered"] = True

        payload.update(extra_payload or {})
        # **R54 A**：被守卫退回时，把中文说明带给界面（"之前没看过讲解，已退回讲解"）——只带一次
        rewound = str(flow.pop("_rewound_zh", "") or "")
        if rewound:
            payload["rewound_zh"] = rewound
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
        # **R56 第 3 步**：图示教材模式（全 AI 模式）**不重写讲解**——直接把本单元讲解正文给出来。
        # 理由：这条路的内容本来就是模型按页面记录写好的（`mode_lesson`），再让路径②的
        # 「讲解演绎」调用点改写一遍，等于把两条口径混在一起（工单 §3-A 禁止）。
        if self._subject_is_all_ai(db, node):
            return {"lecture_md": node.explanation.body or node.body_md,
                    "asks": [], "asks_basis": [], "degraded": False,
                    "strategy": "mode", "lecture_from": "all_ai"}
        cache = flow.get("lecture_cache")
        # 档位联动（R21）：缓存非"手动单次指定"（explicit）且其档位 ≠ 当前全局解析档位 →
        # 自动作废，按新档位重生成（用户切换 快/深 后旧讲解不残留旧档）。
        if cache is not None and not cache.get("explicit"):
            desired = self._resolve_tier(db, node=node, override=None, call_name="explain_node")
            if cache.get("strategy") and cache["strategy"] != desired.strategy:
                flow["lecture_cache"] = None
                cache = None
        if cache is None:
            # R12：regen_explain 可携带单次 think_deep → 本帧消费（视为显式单次，不被联动翻回）
            regen_override = flow.pop("regen_think_override", None)
            explicit = regen_override is not None
            decision = self._resolve_tier(db, node=node, override=regen_override,
                                          call_name="explain_node")
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
                # R35 S6：把本节点声明的事实句交给讲解调用点（小思考必须能在讲解里找到依据）
                taught_facts=[f.model_dump() for f in (node.taught_facts or [])],
            )
            out, degraded = self._call(db, self.gateway.explain_node, ctx, strategy=decision.strategy)
            flow["lecture_cache"] = {
                "lecture_md": out.lecture_md,
                "asks": out.asked_to_confirm,
                "asks_basis": [b.model_dump() for b in (out.asks_basis or [])],  # R35 S6：留档
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

    def _resolve_tier(self, db: Session, *, node: NodeDoc | None = None, override: Any = None,
                      extra_think: bool = False, call_name: str = ""):
        """R12：按 基础档(学段/content.thinking) + 触发(extra_think) + 用户覆盖 决策 fast|think。

        **R42 C1**：决策链的**唯一出口** → 在此统一判断"是否降档（本该 think 却跑了 fast）"，
        是则逐次 `ledger.note(CAT_MODEL_CALL, …)` 记中文原因（架构侧 R41 §3-③ 裁决）。
        """
        content_think = bool(node.feynman.thinking) if node is not None else None
        level = node.level if node is not None else None
        model_mode = self._model_mode(db)
        decision = ai_tier.resolve(
            level=level,
            content_think=content_think,
            model_mode=model_mode,
            override=(None if override is None else bool(override)),
            extra_think=extra_think,
        )
        try:  # 降档显性（不阻塞主流程）
            ai_tier.note_downgrade(
                decision, subject_id="", unit_id=(node.id if node is not None else ""),
                call_name=call_name, level=level, content_think=content_think,
                model_mode=model_mode, override=(None if override is None else bool(override)),
            )
        except Exception:
            pass
        return decision

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
    # **R54 A**：前置内容守卫（"没看到讲解不许进讲解环节"）
    # ------------------------------------------------------------------
    def _content_gate(self, db: Session, node: NodeDoc) -> dict[str, Any] | None:
        """当前节点内容是否足以进入学习流程；不足 → 返回中文说明 + 生成入口（含学科/单元）。

        口径与大纲页/覆盖账**同源**（`outline_gate.unit_content_status`）：讲解正文非空
        且至少 1 道练习。缺失时**不抛异常**（抛异常＝用户看到红字报错），而是让状态机下发
        ``content_missing`` 卡片：说清缺什么、给一键生成。
        """
        from . import outline_gate

        status = outline_gate.unit_content_status(node.id)
        if status["usable"]:
            return None
        res = outline_gate.resolve_subject_unit(db, node.id)   # 通用学科才有"生成该单元"入口
        subject_id, unit_id = (res if res is not None else ("", ""))
        return {"kind": f"no_{status['missing']}" if status["missing"] else "no_content",
                "missing": status["missing"], "reason_zh": status["reason_zh"],
                "node_id": node.id, "node_title": node.title,
                "subject_id": subject_id, "unit_id": unit_id,
                "can_generate": bool(subject_id and unit_id),
                "content_status": status}

    def _missing_node_card(self, db: Session, node_id: str) -> dict[str, Any]:
        """**R54 A/C**：单元还没有内容（或内容文件已被删）→ 中文说明 + 生成入口。

        不许直接 404/409 把人卡住（老会话恢复、点了没内容的单元，都是常见路径）。
        """
        from . import outline_gate

        res = outline_gate.resolve_subject_unit(db, node_id)
        subject_id, unit_id = (res if res is not None else ("", ""))
        # **R55 B**：整节内容都在图里 → 单元**本来就不会有内容文件**。这时说"还没有生成"
        # 会让人以为是漏生成、反复点生成也是白点；改用覆盖记录里的**真正原因**（同源）。
        status = outline_gate.unit_content_status(node_id)
        if status.get("figure_unavailable"):
            reason = str(status.get("reason_zh") or "")
        else:
            reason = ("这个单元还没有生成内容（或者内容已经不在了）。"
                      "先生成内容，才能开始学。")
        return {"kind": "no_content", "missing": "content",
                "reason_zh": reason,
                "node_id": node_id, "node_title": node_id,
                "subject_id": subject_id, "unit_id": unit_id,
                "can_generate": bool(subject_id and unit_id),
                "content_status": {"exists": bool(status.get("exists")),
                                   "usable": bool(status.get("usable")),
                                   "missing": str(status.get("missing") or "content"),
                                   "reason_zh": str(status.get("reason_zh") or ""),
                                   "exercises": int(status.get("exercises") or 0),
                                   "taught_facts": int(status.get("taught_facts") or 0)}}

    def _node_or_gate(self, db: Session, sess: models.Session) -> tuple[NodeDoc | None, dict | None]:
        """取节点并判断内容是否够学；返回 ``(node, 阻断说明)``（两者必有一个为 None）。"""
        try:
            node = self._node_of(db, sess)
        except SessionError:
            return None, self._missing_node_card(db, sess.node_id)
        return node, self._content_gate(db, node)

    def _content_missing_response(self, db: Session, sess: models.Session,
                                  blocked: dict[str, Any]) -> dict[str, Any]:
        """\"内容不足\"卡片：不给学习步骤、不给作答入口，只给说明 + 一键生成。"""
        flow = _ensure_flow_shape(sess.flow_json)
        sess.flow_json = deepcopy(flow)
        flag_modified(sess, "flow_json")
        db.flush()
        return {
            "step": STEP_CONTENT_MISSING,
            "payload": {"first_open": False, "content_missing": blocked},
            "events": [{"type": "content_missing", "reason": blocked["reason_zh"]}],
            "session": self._session_meta(db, sess),
        }

    def _rewind_to_explain(self, db: Session, sess: models.Session, why_zh: str) -> dict[str, Any]:
        """**R54 A**：把人退回讲解阶段并说明原因（不报错、不留在半步）。"""
        flow = _ensure_flow_shape(sess.flow_json)
        flow["stage"] = STAGE_EXPLAIN
        flow["_rewound_zh"] = why_zh
        sess.flow_json = flow
        return self._response(db, sess, events=[{"type": "need_explain", "reason": why_zh}])

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
    "MAX_FEYNMAN_EVALS",
    "MAX_FEYNMAN_ANSWERS",
    "STAGE_EXPLAIN",
    "STAGE_EXAMPLE",
    "STAGE_PRACTICE",
    "STAGE_FEYNMAN",
    "STAGE_DONE",
]
