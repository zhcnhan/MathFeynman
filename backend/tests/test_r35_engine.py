"""R35b（引擎侧 · P0）：S6 🤔 小思考引文纪律 + S7「这题我没法答」反馈入口。全部离线。

S6：`explain_node` 的每条 asked_to_confirm 必须能在讲解里找到依据（引文逐字、≥6 字）；
    无据的那条**不下发**（模板套话不再兜底）——离线兜底与真模型两条路径都过同一把尺子。
S7：复用 `feedback` 表加一种 `kind=answerability`（**不新建表**）；**不计失败/不扣分**
    （不写 attempts、不动掌握度）；若正卡在会话里的这道题 → 直接换一题；auto 内容走既有重生成闭环。
"""
from __future__ import annotations

import uuid

from app.ai.calls import CALL_EXPLAIN_NODE, CiteBasis, ExplainIn, ExplainOut
from app.ai.gateway import OfflineGateway, filter_asks, sentence_with
from app.service import feedback as fb_svc
from app.service import guardrails

LECTURE = "恒星是由自身引力维持并自行发光的巨大球体。行星自身不发光，围绕恒星运行。"


def _any_node_with_exercise(app_client) -> tuple[str, str]:
    """取任意一个"有练习的"节点 + 其首题 id（S7 端点只校验存在性，不要求已解锁）。"""
    from app.service.library import get_library

    lib = get_library()
    for nid, loaded in lib.by_id.items():
        if loaded.doc.exercises:
            return nid, loaded.doc.exercises[0].id
    raise AssertionError("测试内容库应有带练习的节点")


# ---------- S6：判定与过滤 ----------

def test_sentence_with_picks_containing_sentence():
    q = sentence_with(LECTURE, "恒星")
    assert q.startswith("恒星是") and "自行发光" in q
    assert sentence_with(LECTURE, "黑洞") == ""


def test_filter_asks_keeps_only_cited_ones():
    out = ExplainOut(
        lecture_md=LECTURE,
        asked_to_confirm=["有据的", "无引文的", "引文过短的", "引文不在讲解里的", "引用未知事实 id 的"],
        asks_basis=[
            CiteBasis(quote="恒星是由自身引力维持并自行发光的巨大球体"),
            CiteBasis(quote=""),
            CiteBasis(quote="恒星"),
            CiteBasis(quote="讲解里根本没出现过的那一句话"),
            CiteBasis(quote="恒星是由自身引力维持并自行发光的巨大球体", fact_ids=["fX"]),
        ],
    )
    kept = filter_asks(out, sources=[LECTURE], fact_ids={"f1"})
    assert kept.asked_to_confirm == ["有据的"]
    assert len(kept.asks_basis) == 1 and kept.asks_basis[0].quote.startswith("恒星是")
    # 不声明事实包（旧内容）时，fact_ids 不参与判定 → 该条保留
    kept2 = filter_asks(out, sources=[LECTURE])
    assert kept2.asked_to_confirm == ["有据的", "引用未知事实 id 的"]


def test_offline_gateway_ask_requires_lecture_basis():
    gw = OfflineGateway()

    def ctx(concept: str) -> ExplainIn:
        return ExplainIn(session_id="s", node_id="n", node_title="T", level="primary",
                         explanation_body=LECTURE, core_concepts=[concept])

    ok = gw.explain_node(ctx("恒星"))
    assert ok.asked_to_confirm and ok.asks_basis
    assert ok.asks_basis[0].quote in LECTURE          # 引文逐字出自讲解
    none = gw.explain_node(ctx("黑洞"))                # 讲解里没有的概念 → 不出这条
    assert none.asked_to_confirm == [] and none.asks_basis == []


def test_explain_call_schema_carries_asks_basis():
    """接线锁（R36 §8 三处同改）：`CALL_EXPLAIN_NODE` 输出 schema 必须声明 asks_basis。"""
    parsed = CALL_EXPLAIN_NODE.output_schema.model_validate({
        "lecture_md": "讲解",
        "asked_to_confirm": ["小思考"],
        "asks_basis": [{"fact_ids": ["f1"], "quote": "讲解里的一句原话"}],
    })
    assert parsed.asks_basis and parsed.asks_basis[0].quote == "讲解里的一句原话"


def test_session_payload_asks_are_all_backed(app_client):
    """端到端（离线网关 · 自定义学科单元）：讲解里的每条 🤔 小思考都有讲解依据。

    基线 13 节点受总序门禁限制（不可直接 start），故用"自建单元素学科"做端到端靶子——
    这也正是用户实际路径（新建学科 → 生成内容 → 学习）。
    """
    import uuid as _uuid

    from app.content import citations
    from app.service.library import refresh_library

    sid = f"r35s6{_uuid.uuid4().hex[:6]}"
    assert app_client.post("/api/subjects", json={"label": "R35 S6 学科", "subject_id": sid}).status_code == 201
    try:
        assert app_client.put(f"/api/subjects/{sid}/outline", json={"units": [
            {"id": f"{sid}.u01", "title": "第一讲 恒星", "group": "第一章",
             "objectives": ["认识恒星"], "concept_tags": ["恒星"], "difficulty": 1}],
            "status": "active", "source": "manual"}).status_code == 200
        assert app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content").json()["status"] == "created"
        refresh_library()
        r = app_client.post("/api/session/start", json={"node_id": f"{sid}.u01"})
        assert r.status_code == 200, r.text
        sid_session = r.json()["session"]["id"]
        assert r.json()["payload"].get("asks"), "讲解帧应带至少 1 条有据的小思考"
        from app import models
        from app.db import SessionLocal

        with SessionLocal() as db:
            flow = db.get(models.Session, sid_session).flow_json
        cache = flow.get("lecture_cache") or {}
        asks, bases = cache.get("asks") or [], cache.get("asks_basis") or []
        assert asks and len(bases) == len(asks), cache
        lecture = cache.get("lecture_md", "")
        for b in bases:
            assert citations.is_valid(b["quote"], lecture), b
    finally:
        from app.db import SessionLocal
        from app.outline import store as ostore

        with SessionLocal() as db:
            ostore.delete_subject(db, sid, hard=True)


# ---------- S7：反馈入口 ----------

def test_feedback_kind_answerability_registered_in_guardrails():
    """融合约束断言①：S7 复用 feedback 表加 kind（不建表），且与 guardrails 同口径。"""
    assert "answerability" in fb_svc.KINDS
    assert "answerability" in guardrails.KINDS


def test_report_unanswerable_records_feedback_without_penalty(app_client):
    """S7：记录投诉、**不写 attempts**、不动掌握度；返回中文说明。"""
    from app import models
    from app.db import SessionLocal

    node_id, ex_id = _any_node_with_exercise(app_client)

    def counts() -> tuple[int, int]:
        from sqlalchemy import func

        with SessionLocal() as db:
            a = db.query(func.count(models.Attempt.id)).scalar() or 0
            u = db.query(func.count(models.UserNode.node_id)).scalar() or 0
            return a, u

    before = counts()
    r = app_client.post("/api/exercises/unanswerable",
                        json={"node_id": node_id, "exercise_id": ex_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["item"]["kind"] == "answerability"
    assert "不计失败" in body["message"]
    assert counts() == before, "可答性投诉不得计入 attempts / 掌握度行"

    items = app_client.get(f"/api/feedback?node_id={node_id}").json()["items"]
    assert any(i["kind"] == "answerability" and i["exercise_id"] == ex_id for i in items)


def test_report_unanswerable_rejects_unknown_exercise_zh(app_client):
    r = app_client.post("/api/exercises/unanswerable",
                        json={"node_id": "no.such.node", "exercise_id": "x"})
    assert r.status_code == 404
    assert "不存在" in r.json()["detail"]["error"]["message"]


def test_clear_current_exercise_replaces_question(app_client):
    """S7：正卡在会话里的这道题 → 清空换题（attempts_this 归零，**不产生失败记录**）。"""
    from sqlalchemy.orm.attributes import flag_modified

    from app import models
    from app.api.exercises import _clear_current_if_matches
    from app.db import SessionLocal

    node_id, ex_id = _any_node_with_exercise(app_client)
    with SessionLocal() as db:
        sess = models.Session(id=f"t-{uuid.uuid4().hex[:10]}", user_id="local", node_id=node_id,
                              state="learning",
                              flow_json={"stage": "practice",
                                         "practice": {"current": {"exercise_id": ex_id, "seed": 0},
                                                      "attempts_this": 1, "hints_this": 0, "passed": False}})
        db.add(sess)
        db.flush()
        sid = sess.id
        db.commit()
        assert _clear_current_if_matches(db, sid, ex_id) is True
        sess = db.get(models.Session, sid)
        assert sess.flow_json["practice"]["current"] is None
        assert sess.flow_json["practice"]["attempts_this"] == 0
        # 不匹配的题 id → 不动
        sess.flow_json["practice"]["current"] = {"exercise_id": ex_id, "seed": 0}
        flag_modified(sess, "flow_json")
        db.commit()
        assert _clear_current_if_matches(db, sid, "other-ex") is False
        db.delete(db.get(models.Session, sid))
        db.commit()
