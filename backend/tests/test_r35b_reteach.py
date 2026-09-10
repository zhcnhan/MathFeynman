"""R35 S4（追问纪律）：追问必须**逐字引用学生刚说的话**并指出"这句话缺了什么"；
学生无可引用内容（如只写"我不知道"）→ **返回 `reteach`（退回讲解补讲）**，禁止硬造发散题。

验收（工单 · 任务3）：**敷衍回答 → 收 reteach，而不是发一条无法回答的追问。**
另：socratic 模板**只有在 basis 逐字成立时**才作为追问语料下发（不得作为默认兜底）。
"""
from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from app.ai.calls import FeynmanFollowupOut
from app.ai.gateway import OfflineGateway
from app.content import citations
from app.db import SessionLocal
from app.main import app
from app.service.session import SessionService

from test_api_flow import _reset_db, _reset_node, _seed_primary_head, canonical_answer, start_practice, submit  # noqa: E402

NODE = "middle.0101"
BAD = (
    "我先组织一下语言，嗯…… 这个问题其实我还没有完全想明白，让我再仔细回忆一下"
    "刚才看到的例子，再好好想一想应该怎么回答。"
)  # 有实质内容但未达标（离线启发式不含核心概念 → 必判不过）
DISMISSIVE = "我不知道我不知道我不知道我不知道我不知道"   # 24 字：过了"太短"门槛，但**无可引用内容**
FULL = (
    "方程是含有未知数的等式；一元一次方程只有一个未知数、且未知数的最高次数是一。"
    "依据是判断时要逐条核对定义。我原先以为有等号就行，其实还必须含未知数——这点我改正了。"
    "反例：x+y=3 有两个未知数，不是一元一次方程。"
)


@pytest.fixture(scope="module")
def client():
    _reset_db()
    _seed_primary_head()
    with TestClient(app) as c:
        yield c


def _step(client, sid: str, action: str, **payload) -> dict:
    r = client.post("/api/session/step", json={"session_id": sid, "action": action, "payload": payload})
    assert r.status_code == 200, r.text
    return r.json()


def _drive_to_feynman(client) -> str:
    sess, pr = start_practice(client, NODE)
    sid = sess["session"]["id"]
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer(NODE, ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman", pr["step"]
    return sid


class _OfflineFallback:
    def __getattr__(self, name):
        return getattr(OfflineGateway(), name)


def _use_followup(reply):
    """把 feynman_followup 换成给定答复（其余方法回落离线网关）。"""

    class _Gw(_OfflineFallback):
        def feynman_followup(self, ctx, *, strategy=None):
            return reply(ctx) if callable(reply) else reply

    @contextlib.contextmanager
    def _ctx():
        from app.api import deps

        app.dependency_overrides[deps.get_session_service] = lambda: SessionService(_Gw())
        try:
            yield
        finally:
            app.dependency_overrides.pop(deps.get_session_service, None)

    return _ctx()


# --------------------------------------------------------------------------
# ① 敷衍回答 → reteach（不发无法回答的追问），且**不烧评分额度**
# --------------------------------------------------------------------------
def test_dismissive_transcript_returns_reteach_without_burning_budget(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)

    j = _step(client, sid, "feynman_submit", transcript=DISMISSIVE)
    assert j["payload"]["verdict"] == "reteach", j["payload"]
    assert any(e["type"] == "feynman_reteach" for e in j["events"])
    assert not any(e["type"] == "feynman_followup" for e in j["events"])
    assert j["payload"].get("followup_question") is None, "禁止发一条学生无法回答的追问"
    assert j["payload"]["next_action"] == "reteach"
    # 退回讲解补讲：讲解原文随响应下发（学生当场就能回看）
    assert j["payload"]["reteach"]["lecture_md"], "reteach 必须把讲解原文交回给学生"
    assert "退回讲解" in j["payload"]["reteach"]["message_md"]
    # **不消耗额度**：整体稿评分次数与补答次数都还是 0，账本未动
    assert j["payload"]["evals_done"] == 0 and j["payload"]["answers_done"] == 0
    assert j["payload"]["combined"] == 0

    # 补讲后照样能过（额度没被敷衍回答吃掉）
    j2 = _step(client, sid, "feynman_submit", transcript=FULL)
    assert j2["payload"]["verdict"] == "pass"
    assert any(e["type"] == "node_mastered" for e in j2["events"])


# --------------------------------------------------------------------------
# ② 追问必须逐字引用学生原话 + 指出"这句话缺了什么"（离线路径）
# --------------------------------------------------------------------------
def test_offline_followup_quotes_student_words_and_names_the_gap(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    j = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j["payload"]["verdict"] == "fail"
    quote = j["payload"]["followup_quote"]
    missing = j["payload"]["followup_missing"]
    assert quote and citations.is_valid(quote, BAD), f"追问引文必须逐字出自学生原话：{quote!r}"
    assert missing.strip(), "追问必须指出这句话缺了什么"
    assert quote in j["payload"]["followup_question"], "追问正文必须引用学生原话"
    assert any(e["type"] == "feynman_followup" for e in j["events"])


# --------------------------------------------------------------------------
# ③ 引文不成立 / 缺 missing / 模型自陈 reteach → 一律 reteach（不发追问）
# --------------------------------------------------------------------------
def test_non_verbatim_quote_becomes_reteach(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    with _use_followup(FeynmanFollowupOut(question_md="请解释一下这个概念。",
                                          student_quote="这句学生根本没说过的话",
                                          missing="缺依据")):
        j = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j["payload"]["verdict"] == "reteach", j["payload"]
    assert j["payload"]["reteach"]["reason"] == "quote_not_verbatim"
    assert j["payload"].get("followup_question") is None


def test_missing_not_stated_becomes_reteach(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    with _use_followup(lambda ctx: FeynmanFollowupOut(question_md="请再讲一遍。",
                                                     student_quote=ctx.student_transcript[:12],
                                                     missing="   ")):
        j = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j["payload"]["verdict"] == "reteach"
    assert j["payload"]["reteach"]["reason"] == "missing_not_stated"


def test_model_reteach_flag_is_honored(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    with _use_followup(FeynmanFollowupOut(reteach=True)):
        j = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j["payload"]["verdict"] == "reteach"
    assert j["payload"]["reteach"]["reason"] == "model_says_reteach"


def test_valid_quote_passes_through_after_reset(client):
    """正例：引文逐字 + missing 非空 → 正常追问（不是 reteach）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    with _use_followup(lambda ctx: FeynmanFollowupOut(
            question_md=f"你说「{ctx.student_transcript[:12]}」——这句话缺了关键一步的依据，请补讲。",
            student_quote=ctx.student_transcript[:12],
            missing="缺关键一步的依据")):
        j = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j["payload"]["verdict"] == "fail"
    assert j["payload"]["followup_quote"] == BAD[:12]
    assert j["payload"]["followup_missing"] == "缺关键一步的依据"


# --------------------------------------------------------------------------
# ④ socratic 模板**不得**作为默认兜底下发（只有 basis 逐字成立才带上）
# --------------------------------------------------------------------------
def test_socratic_topics_require_basis():
    from app.service.library import get_library

    node = get_library().by_id["middle.0102"].doc          # 人工锚点：有 socratic 套话、无 basis
    assert node.feynman.socratic_followups
    assert SessionService._backed_socratic(node) == [], "无据的模板套话不得下发给追问调用点"

    from app.content.schemas import NodeDoc

    doc = NodeDoc.model_validate({
        "id": "s-s4.u01", "title": "恒星", "level": "第一章", "topic": "第一章",
        "explanation": {"role": "教师讲解稿", "body": "恒星是由自身引力维持并自行发光的巨大球体。"},
        "exercises": [{"id": "e1", "kind": "fixed", "prompt": "p", "answer_bool": True,
                       "check": {"mode": "boolean_judgment"}}],
        "taught_facts": [{"id": "f1", "text": "恒星是由自身引力维持并自行发光的巨大球体。"}],
        "feynman": {"task_prompt": "t",
                    "rubric": {"dimensions": [{"key": "k", "weight": 1.0}]},
                    "socratic_followups": ["恒星自己会发光吗？", "恒星会一直存在吗？"],
                    "socratic_basis": [{"fact_ids": ["f1"], "quote": "恒星是由自身引力维持并自行发光的巨大球体"},
                                       {"fact_ids": ["f1"], "quote": "这句讲解里根本没有"}]},
    })
    assert SessionService._backed_socratic(doc) == ["恒星自己会发光吗？"]
