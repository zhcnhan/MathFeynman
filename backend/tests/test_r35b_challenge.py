"""R35 S3（挑战题双池）：核心题池计入掌握/费曼；**挑战题池完全不上算**。

验收核心（工单 · 任务2）：
- 两个池：核心题（计入掌握与费曼）/ 挑战题（**完全不上算**）；
- 「挑战一下」由用户主动触发、**单独调模型生成**、**永不出现在默认流程**；
- 单题三态（开始作答 / 取消 / 明确放弃）**都要能点、都要无后果**；
- 不设额度、不计轮次、不影响进度；UI 显式标注；
- **必交断言**：挑战题作答后 **mastery / 费曼账本 / 整体稿与补答额度 / 掌握统计 四项均不变**
  （仅记复盘 = `attempts.kind="challenge"`）。

全程离线（OfflineGateway）：挑战题也走**同一套**学科无关链路（换学科仍成立）。
"""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app import models
from app.ai.calls import CALLS, CALL_CHALLENGE_CHECK, CALL_CHALLENGE_EXERCISE
from app.db import SessionLocal
from app.main import app
from app.service.session import ACTIONS, CHALLENGE_ACTIONS, CHALLENGE_NOTICE

from test_api_flow import _reset_db, _reset_node, _seed_primary_head, canonical_answer, start_practice, submit  # noqa: E402

NODE = "middle.0101"
BAD = (
    "我先组织一下语言，嗯…… 这个问题其实我还没有完全想明白，让我再仔细回忆一下"
    "刚才看到的例子，再好好想一想应该怎么回答。"
)  # 离线启发式必判不过（不含任何核心概念）


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


def _ledgers(sid: str) -> dict:
    """四项账目快照：练习块 / 费曼块（含账本与两个额度）/ 掌握统计（user_nodes）。"""
    with SessionLocal() as db:
        flow = db.get(models.Session, sid).flow_json
        user_nodes = sorted(
            (r.node_id, r.state, int(r.consecutive_correct or 0), int(r.attempts_total or 0))
            for r in db.query(models.UserNode).all()
        )
    return {
        "practice": copy.deepcopy(flow.get("practice")),
        "feynman": copy.deepcopy(flow.get("feynman")),
        "user_nodes": user_nodes,
    }


def _counts() -> dict:
    from sqlalchemy import func

    with SessionLocal() as db:
        return {
            "exercise": db.query(func.count(models.Attempt.id)).filter(models.Attempt.kind == "exercise").scalar(),
            "feynman": db.query(func.count(models.Attempt.id)).filter(models.Attempt.kind == "feynman").scalar(),
            "challenge": db.query(func.count(models.Attempt.id)).filter(models.Attempt.kind == "challenge").scalar(),
        }


# --------------------------------------------------------------------------
# 池的分界：默认流程永不出现挑战题
# --------------------------------------------------------------------------
def test_challenge_actions_are_registered_outside_default_flow(client):
    assert CHALLENGE_ACTIONS <= ACTIONS
    _reset_node(NODE)
    sess, pr = start_practice(client, NODE)
    sid = sess["session"]["id"]
    # 讲解帧/练习帧/恢复帧**都不带** challenge（挑战题不是默认流程的一部分）
    assert "challenge" not in sess["payload"]
    assert "challenge" not in pr["payload"]
    assert "challenge" not in client.get(f"/api/session/{sid}").json()["payload"]


def test_challenge_pool_is_not_the_content_pool(client):
    """两个池的物理隔离：挑战题不在内容库的 exercises 里（它是**运行时单独生成**的）。"""
    _reset_node(NODE)
    sess, _ = start_practice(client, NODE)
    sid = sess["session"]["id"]
    j = _step(client, sid, "challenge_start")
    text = j["payload"]["challenge"]["question"]["prompt_md"]
    from app.service.library import get_library

    lib = get_library()
    assert all(
        text not in (ex.prompt or "")
        for loaded in lib.nodes
        for ex in loaded.doc.exercises
    ), "挑战题不得来自内容库核心题池"


def test_challenge_callpoints_registered():
    """接线锁（R36 §8 三处同改）：两个独立调用点必须注册且输出 schema 声明齐全。"""
    assert CALLS["challenge_exercise"] is CALL_CHALLENGE_EXERCISE
    assert CALLS["challenge_check"] is CALL_CHALLENGE_CHECK
    out = CALL_CHALLENGE_EXERCISE.output_schema.model_validate(
        {"prompt_md": "题面", "answer_hint_md": "提示", "why_hard_md": "为何难", "difficulty": 3}
    )
    assert out.prompt_md == "题面" and out.why_hard_md == "为何难"
    chk = CALL_CHALLENGE_CHECK.output_schema.model_validate(
        {"correct": True, "score": 0.8, "feedback_md": "不错", "better_md": "参考"}
    )
    assert chk.correct is True and chk.better_md == "参考"


# --------------------------------------------------------------------------
# 必交断言：挑战题作答后四项账目**均不变**（仅记复盘）
# --------------------------------------------------------------------------
def test_challenge_submit_changes_nothing_but_review_log(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    # 先制造真实账本数据（首讲未过 → 有账本分/缺口/已用 1 次整体稿额度）
    j1 = _step(client, sid, "feynman_submit", transcript=BAD)
    assert j1["payload"]["verdict"] == "fail" and j1["payload"]["ledger"]["combined"] > 0
    assert j1["payload"]["evals_done"] == 1 and j1["payload"]["answers_done"] == 0

    before = _ledgers(sid)
    counts_before = _counts()
    stats_before = client.get("/api/dashboard").json()["stats"]

    # —— 挑战题全流程：生成 → 开始作答 → 提交 ——
    j_start = _step(client, sid, "challenge_start")
    ch = j_start["payload"]["challenge"]
    assert ch["notice"] == CHALLENGE_NOTICE and "答不出不影响任何进度" in ch["notice"], ch["notice"]
    assert ch["counts_nothing"] is True and ch["question"]["prompt_md"]
    assert any(e["type"] == "challenge_offered" for e in j_start["events"])

    j_begin = _step(client, sid, "challenge_begin")
    assert j_begin["payload"]["challenge"]["phase"] == "answering"
    assert _ledgers(sid) == before and _counts() == counts_before   # 开始作答：无后果

    j_sub = _step(client, sid, "challenge_submit", answer="我觉得换一类对象结论会变，因为条件不一样了。")
    assert j_sub["payload"]["verdict"] == "challenge"
    assert j_sub["payload"]["challenge"]["last"] is not None
    assert any(e["type"] == "challenge_graded" for e in j_sub["events"])
    assert "只进复盘" in j_sub["payload"]["message"]

    # ① mastery / 练习块 ② 费曼账本（含 rounds_done/answers_done/额度） ③ 掌握统计（user_nodes）**均不变**
    assert _ledgers(sid) == before, "挑战题不得改动 practice/feynman/掌握统计 任何一项"
    after_counts = _counts()
    assert after_counts["exercise"] == counts_before["exercise"]
    assert after_counts["feynman"] == counts_before["feynman"], "挑战题不得写 feynman attempts"
    assert after_counts["challenge"] == counts_before["challenge"] + 1, "只记复盘（kind=challenge）"
    assert client.get("/api/dashboard").json()["stats"] == stats_before  # 掌握统计不变

    # 「仅记复盘」的落点 = /history/challenge（**不建新表**，与费曼复盘同一张 attempts）
    items = client.get("/api/history/challenge").json()["items"]
    assert items and items[0]["meta"]["source"] == "challenge" and items[0]["node_id"] == NODE
    assert "仅复盘用" in client.get("/api/history/challenge").json()["notice"]


def test_challenge_no_quota_and_core_flow_still_passes_afterwards(client):
    """不设额度、不计轮次：连做多道挑战题后，核心流程照样能过关（掌握判定不受影响）。"""
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    for i in range(3):
        _step(client, sid, "challenge_start")
        _step(client, sid, "challenge_submit", answer=f"第 {i} 次的判断与理由：条件变了结论就会变。")
    j = _step(client, sid, "feynman_submit", transcript=(
        "方程是含有未知数的等式；一元一次方程只有一个未知数、且未知数的最高次数是一。"
        "依据是判断时要逐条核对定义。我原先以为有等号就行，其实还必须含未知数——这点我改正了。"
        "反例：x+y=3 有两个未知数，不是一元一次方程。"
    ))
    assert j["payload"]["verdict"] == "pass"
    assert any(e["type"] == "node_mastered" for e in j["events"])


# --------------------------------------------------------------------------
# 单题三态：取消 / 明确放弃 —— 都能点、都无后果
# --------------------------------------------------------------------------
def test_challenge_cancel_and_abandon_are_consequence_free(client):
    _reset_node(NODE)
    sid = _drive_to_feynman(client)
    _step(client, sid, "feynman_submit", transcript=BAD)
    before = _ledgers(sid)
    counts_before = _counts()

    # 取消：不写 attempts、不动任何账目
    _step(client, sid, "challenge_start")
    j = _step(client, sid, "challenge_cancel")
    assert any(e["type"] == "challenge_cancelled" for e in j["events"])
    assert j["payload"]["challenge"]["question"] is None
    assert "什么都没记" in j["payload"]["message"]
    assert _counts() == counts_before and _ledgers(sid) == before

    # 无进行中挑战时重复点取消/放弃 → 不报错（都要能点）
    j2 = _step(client, sid, "challenge_cancel")
    assert j2["payload"]["challenge"]["question"] is None
    j3 = _step(client, sid, "challenge_abandon")
    assert j3["payload"]["challenge"]["question"] is None

    # 明确放弃：只记复盘（verdict=abandoned），账目仍不变
    _step(client, sid, "challenge_start")
    _step(client, sid, "challenge_begin")
    j4 = _step(client, sid, "challenge_abandon")
    assert any(e["type"] == "challenge_abandoned" for e in j4["events"])
    assert "不影响任何进度" in j4["payload"]["message"]
    assert _counts()["challenge"] == counts_before["challenge"] + 1
    assert _ledgers(sid) == before
    with SessionLocal() as db:
        row = db.query(models.Attempt).filter(models.Attempt.kind == "challenge").order_by(models.Attempt.id.desc()).first()
        assert row.verdict == "abandoned" and row.user_input == ""


# --------------------------------------------------------------------------
# 「换个学科还成立吗？」——挑战题链路学科无关（非数学学科同样生效）
# --------------------------------------------------------------------------
def test_challenge_works_for_non_math_subject(app_client):
    """非数学（自建学科）同样能出挑战题、同样四账不变——**没有学科分支**。"""
    import uuid as _uuid

    from app.content import pipeline as pl
    from app.db import SessionLocal as _SL
    from app.service.library import refresh_library
    from app.outline import store as ostore

    sid_subj = f"r35ch{_uuid.uuid4().hex[:6]}"
    assert app_client.post("/api/subjects", json={"label": "R35 挑战题学科", "subject_id": sid_subj}).status_code == 201
    try:
        assert app_client.put(f"/api/subjects/{sid_subj}/outline", json={"units": [
            {"id": f"{sid_subj}.u01", "title": "第一讲 平均分", "group": "第一章",
             "objectives": ["会平均分"], "concept_tags": ["平均分"], "difficulty": 1}],
            "status": "active", "source": "manual"}).status_code == 200
        assert app_client.post(f"/api/subjects/{sid_subj}/units/{sid_subj}.u01/content").json()["status"] == "created"
        refresh_library()
        r = app_client.post("/api/session/start", json={"node_id": f"{sid_subj}.u01"})
        assert r.status_code == 200, r.text
        sess_id = r.json()["session"]["id"]
        j = app_client.post("/api/session/step", json={
            "session_id": sess_id, "action": "challenge_start", "payload": {}}).json()
        assert j["payload"]["challenge"]["question"]["prompt_md"], "非数学学科也必须能出挑战题"
        assert j["payload"]["challenge"]["notice"] == CHALLENGE_NOTICE
        with _SL() as db:
            flow_before = copy.deepcopy(db.get(models.Session, sess_id).flow_json)
            flow_before.pop("challenge", None)
        js = app_client.post("/api/session/step", json={
            "session_id": sess_id, "action": "challenge_submit",
            "payload": {"answer": "我觉得换个数量级结果会变，因为份数不同了。"}}).json()
        assert js["payload"]["challenge"]["last"] is not None
        with _SL() as db:
            flow_after = copy.deepcopy(db.get(models.Session, sess_id).flow_json)
            flow_after.pop("challenge", None)
        assert flow_after == flow_before, "非数学路径同样：除挑战题块外什么都不许动"
    finally:
        with _SL() as db:
            ostore.delete_subject(db, sid_subj, hard=True)
        refresh_library()
