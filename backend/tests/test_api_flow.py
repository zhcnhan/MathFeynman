"""M2 验收：API 全链路走通（docs/08 M2 完成判据）。

链路（无 LLM，OfflineGateway 桩）：讲解→例题→练习答对3题→费曼通过→mastered→复习队列。
判题答案由测试内用同一内容模板渲染器复算（canonical），不依赖接口泄露。
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.content.templates import render_exercise
from app.db import SessionLocal
from app.domain.fsrs import RATING_AGAIN
from app.main import app
from app.service.library import get_library


@pytest.fixture(scope="module")
def client():
    """模块内独立 TestClient；先重置业务数据，再播种"总序头部" auto 内容（R18：
    primary 数与运算头 4 条 s01–s04 落库 → 0 掌握时推荐 primary.s01，链可从根推进）。"""
    _reset_db()
    _seed_primary_head()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _seed_primary_head() -> None:
    """把 primary 数与运算头链（s01–s04）auto 内容落到 hermetic 副本 + DB 同步。"""
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap
    from app.db import SessionLocal
    from app.service.library import refresh_library, sync_content

    rd = load_roadmap("primary")
    head = ["primary.s01", "primary.s02", "primary.s03", "primary.s04"]
    pl.generate_sequence(rd, head)
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()


def _reset_db() -> None:
    """模块级干净库：清空业务表 → 重新同步内容（跨模块共享同一 sqlite 文件时的顺序隔离）。"""
    from sqlalchemy import text

    from app import models as m
    from app.db import init_db
    from app.service.library import ensure_user, sync_content

    init_db()  # 保证表存在（本模块可单独运行）
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes", "edges", "ai_logs", "nodes", "users"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def canonical_answer(node_id: str, exercise_id: str, seed: int) -> str:
    lib = get_library()
    loaded = lib.by_id[node_id]
    ex = next(e for e in loaded.doc.exercises if e.id == exercise_id)
    return render_exercise(node_id, ex, seed).canonical_answer


def unlock_before(node_id: str) -> None:
    """R18：进入目标节点前，按蓝图总序生成链上缺失 auto 并把闭包达成（目标自身除外）。"""
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, node_id)
        db.commit()


def start_practice(client, node_id: str) -> dict:
    unlock_before(node_id)  # R18 总序：先把前置链达成（目标节点留给本流程真学）
    r = client.post("/api/session/start", json={"node_id": node_id})
    assert r.status_code == 200, r.text
    sess = r.json()
    assert sess["step"] == "explain"
    # 讲解 → 例题 → 练习
    assert client.post("/api/session/step", json={"session_id": sess["session"]["id"], "action": "next"}).json()["step"] == "example"
    pr = client.post("/api/session/step", json={"session_id": sess["session"]["id"], "action": "next"}).json()
    assert pr["step"] == "practice"
    return sess, pr


def submit(client, sid: str, payload: dict) -> dict:
    r = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "submit_exercise", "payload": payload},
    )
    assert r.status_code == 200, r.text
    return r.json()


def pass_node_via_feynman(client, node_id: str, transcript: str):
    """学习一个节点直到 mastered（离线桩：口述含核心概念即过）。

    练习阶段：先故意答错一次验证 hint/retry 路径，随后全对至 3 连对 → 费曼口述 → mastered。
    """
    sess, pr = start_practice(client, node_id)
    sid = sess["session"]["id"]
    wrong_done = False
    while True:
        step = pr["step"]
        if step == "feynman":
            # 费曼口述提交（含核心概念 → 离线桩判过）
            r = client.post(
                "/api/session/step",
                json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": transcript}},
            )
            assert r.status_code == 200, r.text
            res = r.json()
            if any(e["type"] == "node_mastered" for e in res["events"]):
                return res
            # 首评未过 → 有追问 → 二轮作答（同转写加强版）
            assert res["payload"].get("followup_question")
            r2 = client.post(
                "/api/session/step",
                json={"session_id": sid, "action": "feynman_answer", "payload": {"answer": transcript}},
            )
            assert r2.status_code == 200, r2.text
            res = r2.json()
            assert any(e["type"] == "node_mastered" for e in res["events"])
            return res
        if step == "done":
            return pr
        # practice 阶段
        ex = pr["payload"]["exercise"]
        if not wrong_done:
            wrong_done = True
            ans0 = canonical_answer(node_id, ex["exercise_id"], ex["seed"])
            wrong = _wrong_for_mode(ex["mode"], ans0)
            res = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": wrong})
            if res["payload"].get("verdict") == "notation":
                res = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": "x+1"})
            assert any(e["type"] == "exercise_wrong" for e in res["events"])
            assert res["payload"]["hint_md"]
            pr = res  # 同题重试（attempts_left 内）
            continue
        ans = canonical_answer(node_id, ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})


def _wrong_for_mode(mode: str, canonical: str) -> str:
    """构造'语法合法但错误'的作答（解析失败不算错答，见 _wrong_answer_for）。"""
    if mode == "boolean_judgment":
        return "错" if canonical.strip().rstrip("。") in ("对", "正确") else "对"
    if mode in ("symbolic_equivalence", "numeric_value"):
        return f"({canonical}) + 1"  # 合法但不等价/不相等
    return "x = 99999999"  # equation_solution


def test_full_chain_master_both_nodes(client):
    # R18 总序：0 掌握时唯一可学 = primary 数与运算首节点 primary.s01（seeded auto）
    d0 = client.get("/api/dashboard").json()
    assert d0["stats"]["mastered"] == 0
    assert d0["recommended_node"] is not None
    assert d0["recommended_node"]["level"] == "primary"
    assert d0["recommended_node"]["id"] == "primary.s01"  # 总序首节点（不再直接推 middle/high 根）

    # 节点 1：middle.0101（一元一次方程概念；start_practice 内部按总序自动完成 primary 通关与
    # 链上整式 m03 的内容/达成，目标节点留给本流程真学）
    res1 = pass_node_via_feynman(
        client,
        "middle.0101",
        "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"
        "x平方加一等于五不是一元一次因为它次数是二；一加二等于三没有未知数所以不是方程。",
    )
    assert res1["payload"].get("mastered") is True
    assert any(e["type"] == "feynman_passed" for e in res1["events"])
    assert any(e["type"] == "node_mastered" for e in res1["events"])

    # 仪表盘：预铺达成（primary 4 锚 + s01–s04 seed + 0201/0202 + m03 = 11）+ 概念真学 1 = 12
    d = client.get("/api/dashboard").json()
    assert d["stats"]["mastered"] == 12
    assert d["recommended_node"] is not None
    g = client.get("/api/graph").json()
    states = {n["id"]: n["state"] for n in g["nodes"]}
    assert states["middle.0101"] == "mastered"
    # R18 顺序修正断言：概念之后解锁"等式性质(0104)"，解方程(0102) 必须先学性质 → 仍锁
    assert states["middle.0104"] == "available"
    assert states["middle.0102"] == "locked"

    # 节点 2：middle.0104（等式的性质——蓝图 m12，紧随概念 m11）
    res2a = pass_node_via_feynman(
        client,
        "middle.0104",
        "等式的性质有两条：两边同加或两边同减同一个数等式仍成立；两边同乘或除以非零数也仍成立。"
        "天平模型里两边放相同重量仍保持平衡，移项变号就来自这两条等式性质。除以零会把零当除数所以不行。",
    )
    assert res2a["payload"].get("mastered") is True

    # 节点 3：middle.0102（解方程——蓝图 m13，前置 m12(0104) 已达成 → 现在解锁）
    res2 = pass_node_via_feynman(
        client,
        "middle.0102",
        "解方程要先移项并且移项要变号，因为移项本质是两边同时加或减同一个数。"
        "然后合并同类项，系数化一得到x等于几，最后代回验根。两边乘以零会把方程变成零零相等丢掉解所以不行。",
    )
    assert res2["payload"].get("mastered") is True
    assert any(e["type"] == "node_mastered" for e in res2["events"])
    assert res2["payload"]["mastery"]["next_review_due_at"]

    d2 = client.get("/api/dashboard").json()
    assert d2["stats"]["mastered"] >= 14  # 12(预铺+概念) + 0104 + 0102（直插幂等可能更多，只保下界）
    g2 = client.get("/api/graph").json()
    st2 = {n["id"]: n["state"] for n in g2["nodes"]}
    assert st2["middle.0102"] == "mastered" and st2["middle.0104"] == "mastered"
    # 到期队列为空（首次排程在 ~2 天后）
    q = client.get("/api/review/queue").json()
    assert q["total_due"] == 0


def test_session_interrupt_and_resume(client):
    # 中途退出 → 恢复保留进度（回炉场景：重进练习继续）
    sess, pr = start_practice(client, "middle.0102")
    sid = sess["session"]["id"]
    ex = pr["payload"]["exercise"]
    ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
    res = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert any(e["type"] == "exercise_correct" for e in res["events"])
    r = client.post("/api/session/step", json={"session_id": sid, "action": "quit"})
    assert r.status_code == 200
    # 恢复：get 会话仍在 practice 阶段
    back = client.get(f"/api/session/{sid}").json()
    assert back["step"] == "practice"
    assert back["payload"]["exercise"]


def test_review_relearn_after_two_again(client):
    """复习 rating again×2 → mastered 降级 learning（docs/03 §3 行为规则）。"""
    with SessionLocal() as db:
        from app import models

        # 把 middle.0102 的复习强制到期（跨日模拟）
        row = db.query(models.Review).filter(models.Review.node_id == "middle.0102").first()
        assert row is not None
        row.due_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        db.commit()

    q = client.get("/api/review/queue").json()
    assert any(item["node_id"] == "middle.0102" for item in q["due"])

    # 第一次 again（lapse 1）→ 仍排程
    r1 = client.post("/api/review/submit", json={"node_id": "middle.0102", "rating": RATING_AGAIN})
    assert r1.status_code == 200
    assert r1.json()["action"] == "scheduled"

    # 再次强制到期，第二次 again（lapse 2）→ 降级
    with SessionLocal() as db:
        from app import models

        row = db.query(models.Review).filter(models.Review.node_id == "middle.0102").first()
        assert row is not None
        row.due_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        db.commit()
    r2 = client.post("/api/review/submit", json={"node_id": "middle.0102", "rating": RATING_AGAIN})
    assert r2.status_code == 200
    body = r2.json()
    assert body["action"] == "relearn"

    g = client.get("/api/graph").json()
    states = {n["id"]: n["state"] for n in g["nodes"]}
    assert states["middle.0102"] == "learning"  # 回炉重学
    assert states["middle.0101"] == "mastered"

    # 复习降级留痕
    with SessionLocal() as db:
        from app import models

        logs = db.query(models.RelearnLog).filter(models.RelearnLog.node_id == "middle.0102").all()
        assert len(logs) == 1


def test_exercises_check_endpoint_stateless(client):
    # 幂等判题 + hint 不泄答案 + notation 提示
    nxt = client.post("/api/exercises/next", json={"node_id": "middle.0102"}).json()
    ex = nxt["exercise"]
    ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
    ok = client.post(
        "/api/exercises/check",
        json={"node_id": "middle.0102", "exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans},
    ).json()
    assert ok["correct"] is True and ok["verdict"] == "correct"
    wrong = _wrong_for_mode(ex["mode"], ans)
    bad = client.post(
        "/api/exercises/check",
        json={"node_id": "middle.0102", "exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": wrong},
    ).json()
    assert bad["correct"] is False and bad["verdict"] == "wrong"
    assert "expected" not in bad  # 不泄答案（红线）
    hint = bad["hint"]
    assert hint and "999" not in hint and "x=5" not in hint
    nota = client.post(
        "/api/exercises/check",
        json={"node_id": "middle.0101", "exercise_id": "ex1", "params_seed": 0, "user_answer": "？？？"},
    ).json()
    assert nota["verdict"] == "notation"


def test_profile_and_config(client):
    p = client.get("/api/profile").json()
    assert p["user_id"] == "local"
    up = client.patch("/api/profile", json={"preferred_explanation_depth": 4}).json()
    assert up["preferred_explanation_depth"] == 4
    cfg = client.get("/api/config/models").json()
    assert set(cfg["tiers"]) == {"heavy", "light"}
    assert cfg["configured"] is False  # 无 key → 离线模式


def test_regen_explain_clears_dirty_lecture(client):
    """R8 清理路径：regen_explain 重置 lecture_cache → 回到讲解并重新生成。"""
    r = client.post("/api/session/start", json={"node_id": "primary.0101"})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    step = client.post("/api/session/step", json={"session_id": sid, "action": "regen_explain"}).json()
    assert step["step"] == "explain"
    assert any(e["type"] == "lecture_regenerated" for e in step["events"])
    assert step["payload"]["lecture_md"]


def test_feynman_fail_then_followup_pass(client):
    """R10 回归（测试盲区）：费曼首轮未达标 → 追问构造(previous_scores=最近一轮卡)
    → 二轮评分(previous_round=摘要 dict) → 通过并 mastered，全程不得 500。

    用离线启发式评分驱动确定性分支：首轮口述不含核心概念 → 未过+追问；
    二轮回答含核心概念 → 通过。
    """
    # 进入 middle.0101 的费曼阶段（练习全对）
    sess, pr = start_practice(client, "middle.0101")
    sid = sess["session"]["id"]
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer("middle.0101", ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman", pr["step"]

    # 首轮：足够长但不含任何核心概念 → 判未过 → 进入 Socratic 追问
    bad_transcript = (
        "我先组织一下语言，嗯…… 这个问题其实我还没有完全想明白，"
        "让我再仔细回忆一下刚才看到的例子再回答。"
    )
    r1 = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": bad_transcript}},
    )
    assert r1.status_code == 200, r1.text  # R10：首轮不过→追问不得 500
    j1 = r1.json()
    assert j1["payload"]["verdict"] == "fail"
    assert j1["payload"]["rounds_done"] == 1
    assert j1["payload"]["followup_question"]
    assert any(e["type"] == "feynman_failed" for e in j1["events"])
    assert any(e["type"] == "feynman_followup" for e in j1["events"])

    # 二轮：回答追问（含核心概念）→ 通过 → mastered
    good_answer = "方程是含有未知数的等式；一元一次方程只有一个未知数且最高次数是一。"
    r2 = client.post(
        "/api/session/step",
        json={"session_id": sid, "action": "feynman_answer", "payload": {"answer": good_answer}},
    )
    assert r2.status_code == 200, r2.text  # R10：二轮评分(previous_round 摘要)不得 500
    j2 = r2.json()
    assert j2["payload"].get("mastered") is True
    assert any(e["type"] == "feynman_passed" for e in j2["events"])
    assert any(e["type"] == "node_mastered" for e in j2["events"])


# --------------------------------------------------------------------------
# R11 盲区回归：练习回炉三分支（连错2次 / 一轮5题cap / 费曼3轮不过）
# --------------------------------------------------------------------------
def _fail_transcript() -> str:
    """不含任何核心概念、长度≥20 的"未达标口述"（离线启发式必然判不过）。"""
    return "我先组织一下语言…… 嗯这个问题我其实还没有想明白，让我再仔细回忆一下例子再讲。"


def _reset_node(node_id: str) -> None:
    """清除某节点的进度与会话，保证分支测试从干净 explain 开始（隔离模块内顺序）。"""
    from app import models as m

    with SessionLocal() as db:
        db.query(m.Attempt).filter(m.Attempt.node_id == node_id).delete()
        db.query(m.Session).filter(m.Session.node_id == node_id).delete()
        db.query(m.Review).filter(m.Review.node_id == node_id).delete()
        db.query(m.UserNode).filter(m.UserNode.node_id == node_id).delete()
        db.commit()


def test_practice_two_wrongs_triggers_relearn(client):
    """R11：同一题连续答错 2 次 → 回炉讲解（stage=explain、事件流正确、200）。"""
    _reset_node("middle.0102")
    sess, pr = start_practice(client, "middle.0102")
    sid = sess["session"]["id"]
    assert pr["step"] == "practice"
    ex = pr["payload"]["exercise"]
    ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
    wrong = _wrong_for_mode(ex["mode"], ans)

    r1 = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": wrong})
    assert any(e["type"] == "exercise_wrong" for e in r1["events"])
    assert r1["payload"]["attempts_left"] == 1

    r2 = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": wrong})
    assert r2["step"] == "explain"  # 回炉
    assert any(e["type"] == "relearn_notice" for e in r2["events"])
    assert any(e["type"] == "practice_retry_exhausted" for e in r2["events"])
    assert r2["payload"]["lecture_md"]


def test_practice_cap_five_questions_relearn(client):
    """R11：一轮 5 题仍未 3 连对 → cap 回炉（stage=explain、事件流正确）。"""
    _reset_node("middle.0102")
    sess, pr = start_practice(client, "middle.0102")
    sid = sess["session"]["id"]
    issued = 0
    for _ in range(12):
        if pr["step"] != "practice":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
        # 每题先错一次（重置连对），再答对推进下一题 → 连对恒 ≤1，永不提前达标
        submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": _wrong_for_mode(ex["mode"], ans)})
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
        issued = pr["payload"].get("progress", {}).get("issued", issued)
    assert pr["step"] == "explain"
    assert any(e["type"] == "practice_cap_reached" for e in pr["events"])
    assert any(e["type"] == "relearn_notice" for e in pr["events"])


def test_feynman_three_fails_relearn(client):
    """R11：费曼 3 轮不过 → 回炉（stage=explain；R10/R11 同款盲区）。"""
    _reset_node("middle.0102")
    # 练习全对进费曼
    sess, pr = start_practice(client, "middle.0102")
    sid = sess["session"]["id"]
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman"

    rounds = 0
    last = None
    for idx in range(3):
        r = client.post(
            "/api/session/step",
            json={"session_id": sid, "action": "feynman_submit", "payload": {"transcript": _fail_transcript()}},
        )
        assert r.status_code == 200, r.text
        last = r.json()
        rounds = idx + 1  # 第 idx+1 次口述（第三轮回炉响应不再携带 rounds_done）
        if last["step"] == "explain":
            break
        assert last["payload"]["verdict"] == "fail"  # 前两轮有明确 fail+追问
        assert last["payload"].get("followup_question")
    assert rounds == 3
    assert last["step"] == "explain"
    assert any(e["type"] == "feynman_relearn" for e in last["events"])
    assert any(e["type"] == "relearn_notice" for e in last["events"])


def test_feynman_relearn_then_relearn_again_submit_200(client):
    """R17 回归（原盲区）：费曼 3 轮不过 → 回炉 → 重学（练习）→ 再次进入费曼提交
    必须 200（轮次已清零，不再 409 "轮次已达上限"锁死）。"""
    _reset_node("middle.0102")
    sess, pr = start_practice(client, "middle.0102")
    sid = sess["session"]["id"]
    # 1) 练习全对进费曼，连败 3 轮 → 回炉 explain
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman"
    for _ in range(3):
        r = client.post("/api/session/step", json={"session_id": sid, "action": "feynman_submit",
                                                   "payload": {"transcript": _fail_transcript()}})
        assert r.status_code == 200, r.text
        pr = r.json()
        if pr["step"] == "explain":
            break
    assert pr["step"] == "explain"  # 回炉
    # 2) 重学：讲解→例题→练习全对 → 再次进入费曼
    assert client.post("/api/session/step", json={"session_id": sid, "action": "next"}).json()["step"] == "example"
    pr = client.post("/api/session/step", json={"session_id": sid, "action": "next"}).json()
    assert pr["step"] == "practice"
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer("middle.0102", ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman", pr["step"]
    # 3) 再次费曼提交（含核心概念 → 离线桩判过）→ 200 + mastered（R17 锁死回归必现 409）
    good = "等式性质是两边同加同减、同乘同除非零数仍相等；移项就是等式性质的应用。"
    r = client.post("/api/session/step", json={"session_id": sid, "action": "feynman_submit",
                                               "payload": {"transcript": good}})
    assert r.status_code == 200, r.text  # R17：不得再 409
    assert any(e["type"] == "node_mastered" for e in r.json()["events"])


def test_model_mode_and_answer_strategy_annotation(client):
    """R12-a：画像 model_mode 默认 smart 可切换；答疑响应标注本次档位。"""
    _reset_node("middle.0101")
    p0 = client.get("/api/profile").json()
    assert p0["model_mode"] == "smart"

    r = client.post("/api/session/start", json={"node_id": "middle.0101"})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]

    def ask(text: str) -> dict:
        resp = client.post(
            "/api/session/step",
            json={"session_id": sid, "action": "ask_question", "payload": {"question": text}},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "answer" in body["payload"] and "strategy" in body["payload"]["answer"]
        return body["payload"]["answer"]

    try:
        ans_smart = ask("为什么移项要变号？")
        assert ans_smart["strategy"] == "fast"  # middle + smart 基础档 fast
        assert ans_smart.get("out_of_scope") is False
        assert ans_smart.get("upgraded") is False

        # 切到 🧠深度 → 同一次提问应标注 think
        client.patch("/api/profile", json={"model_mode": "deep"})
        ans_deep = ask("请用天平解释等式性质")
        assert ans_deep["strategy"] == "think"

        p1 = client.get("/api/profile").json()
        assert p1["model_mode"] == "deep"
    finally:
        client.patch("/api/profile", json={"model_mode": "smart"})


def _parse_sse(stream_lines) -> dict:
    """把 'event: x' / 'data: …' 行解析为 {event: data(json字符串)}（同名事件取最后一个）。"""
    events: dict[str, str] = {}
    ev: str | None = None
    for raw in stream_lines:
        raw = (raw or "").strip()
        if not raw:
            continue
        if raw.startswith("event: "):
            ev = raw[len("event: "):]
        elif raw.startswith("data: ") and ev:
            events[ev] = raw[len("data: "):]
    return events


def test_session_step_sse_stream(client):
    """R12-b：?stream=1 → SSE 事件流（start/ping/result），result 与普通 JSON 一致；坏 action → error 事件。"""
    import json as _json

    _reset_node("middle.0101")
    r = client.post("/api/session/start", json={"node_id": "middle.0101"})
    sid = r.json()["session"]["id"]

    with client.stream(
        "POST",
        "/api/session/step?stream=1",
        json={"session_id": sid, "action": "next"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.iter_lines())
    assert "start" in events
    assert "result" in events
    body = _json.loads(events["result"])
    assert body["step"] == "example"
    assert body["session"]["id"] == sid

    # 非法 action → error 事件（前端据此回退/提示）
    with client.stream(
        "POST",
        "/api/session/step?stream=1",
        json={"session_id": sid, "action": "no_such_action"},
    ) as resp:
        events = _parse_sse(resp.iter_lines())
    assert "error" in events
    err = _json.loads(events["error"])
    assert err["code"] == "validation_error"


def test_campaign_snapshot_and_boss_pass(client):
    """阶段 2：关卡地图快照 + 首领(boss)通过 → boss_passed 事件/组完成/复习整合提示。"""
    import json as _json
    from app import models as m

    BOSS = "middle.0199"
    PREREQS = ["middle.0101", "middle.0102", "middle.0103", "middle.0104"]

    # 干净起点：清除 boss 进度，按总序把归属主题组（蓝图 m11–m19）达成 → boss 可开
    _reset_node(BOSS)
    unlock_before(BOSS)

    cam0 = client.get("/api/campaign").json()
    assert cam0["levels"], "campaign 需返回学段视图"
    middle_level = next(lv for lv in cam0["levels"] if lv["level"] == "middle")
    topic_group = next(g for g in middle_level["groups"] if g["topic"] == "代数·方程")
    assert topic_group["boss"] and topic_group["boss"]["id"] == BOSS
    assert topic_group["boss"]["state"] == "available"

    # 走 boss 会话：练习全对 → 费曼综述（含核心词）→ mastered
    sess, pr = start_practice(client, BOSS)
    sid = sess["session"]["id"]
    for _ in range(12):
        if pr["step"] == "feynman":
            break
        ex = pr["payload"]["exercise"]
        ans = canonical_answer(BOSS, ex["exercise_id"], ex["seed"])
        pr = submit(client, sid, {"exercise_id": ex["exercise_id"], "params_seed": ex["seed"], "user_answer": ans})
    assert pr["step"] == "feynman"
    r = client.post(
        "/api/session/step",
        json={
            "session_id": sid,
            "action": "feynman_submit",
            "payload": {
                "transcript": (
                    "一元一次方程先看是不是等式且含一个未知数次数为一；移项要变号因为本质是两边同加同减；"
                    "然后合并同类项系数化一最后验根；应用题四步法先设未知数再找等量关系列方程再解再检验。"
                )
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(e["type"] == "node_mastered" for e in body["events"])
    assert any(e["type"] == "boss_passed" for e in body["events"])
    boss_ev = next(e for e in body["events"] if e["type"] == "boss_passed")
    assert boss_ev["level"] == "middle" and boss_ev["topic"] == "代数·方程"
    assert boss_ev["group_completed"] is True
    assert "recap" in boss_ev and "suggestion" in boss_ev["recap"]

    cam1 = client.get("/api/campaign").json()
    middle1 = next(lv for lv in cam1["levels"] if lv["level"] == "middle")
    grp1 = next(g for g in middle1["groups"] if g["topic"] == "代数·方程")
    assert grp1["completed"] is True


def _reset_node_db(db, node_id: str) -> None:
    """DB 级重置单个节点（attempts/sessions/reviews/user_nodes），供测试快设状态。"""
    from app import models as m

    db.query(m.Attempt).filter(m.Attempt.node_id == node_id).delete()
    db.query(m.Session).filter(m.Session.node_id == node_id).delete()
    db.query(m.Review).filter(m.Review.node_id == node_id).delete()
    db.query(m.UserNode).filter(m.UserNode.node_id == node_id).delete()
