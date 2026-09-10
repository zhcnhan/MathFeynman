"""R35a 回归：可答性（S1 声明式知识包 / S2 出题引文纪律 / S5 质检丢弃 / A3 例题）。全部离线。

覆盖：
- 判定器 `content.answerability`：事实必须逐字出自讲解；题/追问必须有据；推理题须 ≥2 条已述事实 + 规则；
  旧内容（无 taught_facts）不阻塞加载但**不得**通过校验；
- 生成端（自定义学科）：启发式与 AI 两条路径产出的内容都带 `taught_facts` + 每题 `basis` + 例题，
  不合约的题被**丢弃**（不是整份失败）；落盘文件可重新加载并再次通过判定；
- 接线锁定（R36 §8 纪律）：`CALL_UNIT_CONTENT` 输出 schema 必须声明 basis/taught_facts/例题/asks。
"""
from __future__ import annotations

import uuid

import pytest

from app.content import answerability as ab
from app.content.schemas import (
    BasisDoc,
    CheckDoc,
    ExerciseDoc,
    FeynmanDoc,
    NodeDoc,
    RubricDimension,
    RubricDoc,
)

LECTURE = (
    "恒星是由自身引力维持、内部发生核聚变并自行发光的巨大球体。\n"
    "太阳是离地球最近的恒星。\n"
    "行星自身不发光，围绕恒星运行。"
)
Q_FACT = "恒星是由自身引力维持、内部发生核聚变并自行发光的巨大球体"
Q_NEAR = "太阳是离地球最近的恒星"


def _ex(eid: str, basis: BasisDoc | None) -> ExerciseDoc:
    return ExerciseDoc(id=eid, kind="fixed", difficulty=1, prompt=f"题目 {eid}",
                       answer_bool=True, check=CheckDoc(mode="boolean_judgment"), basis=basis)


def _doc(*, exercises, facts, asks=(), asks_basis=(), lecture=LECTURE) -> NodeDoc:
    return NodeDoc(
        id="t.u01", title="测试单元", level="g", topic="g",
        explanation={"role": "教师讲解稿", "body": lecture},
        exercises=list(exercises),
        feynman=FeynmanDoc(
            task_prompt="请讲清本单元内容。",
            rubric=RubricDoc(dimensions=[RubricDimension(key="correctness", weight=1.0)]),
            socratic_followups=list(asks), socratic_basis=list(asks_basis)),
        taught_facts=list(facts),
    )


# ---------- 判定器：事实来源 ----------

def test_gate_drops_fact_not_verbatim_in_lecture():
    """事实句必须逐字出自讲解（S1）；写不进讲解的"事实"被剔除并记问题。"""
    doc = _doc(
        exercises=[_ex("a", BasisDoc(fact_ids=["f1"], quote=Q_FACT))],
        facts=[{"id": "f1", "text": Q_FACT},
               {"id": "f2", "text": "木星是太阳系体积最大的行星。"}],  # 讲解里没有
    )
    rep = ab.gate_node(doc)
    assert [f.id for f in rep.facts] == ["f1"]
    assert any("f2" in p and "未逐字出自讲解" in p for p in rep.problems)
    assert rep.verified is True


def test_gate_drops_questions_without_basis_and_keeps_valid_one():
    """无依据 / 引文不在讲解 / 引文过短（<6 字）→ 丢弃该题；有据的留下（S5）。"""
    doc = _doc(
        exercises=[
            _ex("ok", BasisDoc(fact_ids=["f1"], quote=Q_FACT)),
            _ex("no-basis", None),
            _ex("bogus", BasisDoc(fact_ids=["f1"], quote="讲解里根本没写的句子内容")),
            _ex("too-short", BasisDoc(fact_ids=["f1"], quote="恒星")),
            _ex("unknown-fact", BasisDoc(fact_ids=["f9"], quote=Q_FACT)),
        ],
        facts=[{"id": "f1", "text": Q_FACT}],
    )
    rep = ab.gate_node(doc)
    assert [e.id for e in rep.exercises] == ["ok"]
    dropped = {d["id"]: d["reason"] for d in rep.dropped_exercises}
    assert set(dropped) == {"no-basis", "bogus", "too-short", "unknown-fact"}
    assert "未声明依据" in dropped["no-basis"]
    assert "引文不成立" in dropped["bogus"]
    assert "过短" in dropped["too-short"]
    assert "未声明的事实 id" in dropped["unknown-fact"]


def test_gate_reasoning_question_needs_two_premises_and_rule():
    """推理题（非逐字复述）须 ≥2 条已述事实前提 + 明确规则（R35 §2 原则）。"""
    facts = [{"id": "f1", "text": Q_FACT}, {"id": "f2", "text": Q_NEAR}]
    one = _doc(exercises=[_ex("r1", BasisDoc(fact_ids=["f1"], quote=Q_FACT,
                                            premises=["f1"], rule="比较距离"))], facts=facts)
    two = _doc(exercises=[_ex("r2", BasisDoc(fact_ids=["f1", "f2"], quote=Q_NEAR,
                                            premises=["f1", "f2"], rule="比较距离"))], facts=facts)
    rep1 = ab.gate_node(one)
    rep2 = ab.gate_node(two)
    assert rep1.exercises == [] and "前提不足" in rep1.dropped_exercises[0]["reason"]
    assert [e.id for e in rep2.exercises] == ["r2"]


def test_gate_drops_socratic_without_basis():
    """socratic 模板套话（无依据）不再下发（S2/S4）；有据的留下。

    注：`socratic_basis` 与 `socratic_followups` **按下标对齐**；第 2 条没有对应 basis → 丢弃。
    """
    doc = _doc(
        exercises=[_ex("a", BasisDoc(fact_ids=["f1"], quote=Q_FACT))],
        facts=[{"id": "f1", "text": Q_FACT}],
        asks=["太阳和地球哪个离我们更近？", "它与你学过的内容有什么联系？"],
        asks_basis=[BasisDoc(fact_ids=["f1"], quote=Q_NEAR)],
    )
    rep = ab.gate_node(doc)
    assert rep.asks == ["太阳和地球哪个离我们更近？"]
    assert len(rep.dropped_asks) == 1
    assert "socratic[2]" in rep.dropped_asks[0]["reason"] or rep.dropped_asks[0]["ask"].startswith("它与你学过")


def test_gate_legacy_node_without_facts_loads_but_fails_answerability():
    """旧内容（无 taught_facts）：**不阻塞加载**，但不得通过可答性校验（S1 兼容口径）。"""
    doc = _doc(exercises=[_ex("legacy", None)], facts=[])
    assert doc.id == "t.u01" and len(doc.exercises) == 1   # 加载/解析正常
    rep = ab.gate_node(doc)
    assert rep.verified is False
    assert any("未声明 taught_facts" in p for p in rep.problems)
    assert rep.exercises == []


# ---------- 生成端：启发式（离线） ----------

def test_heuristic_generation_is_answerable_end_to_end(app_client):
    """自定义学科启发式出稿：落到盘上的内容必须带知识包+依据+例题，且再次判定通过。"""
    from app.content.loader import load_library
    from app.service.library import refresh_library, sync_content
    from app.db import SessionLocal

    sid = f"r35a{uuid.uuid4().hex[:6]}"
    assert app_client.post("/api/subjects", json={"label": "R35 测试学科", "subject_id": sid}).status_code == 201
    try:
        r = app_client.put(f"/api/subjects/{sid}/outline", json={"units": [
            {"id": f"{sid}.u01", "title": "第一讲 甲", "group": "第一章",
             "objectives": ["掌握甲概念并能举例"], "concept_tags": ["甲概念"], "difficulty": 1}],
            "status": "active", "source": "manual"})
        assert r.status_code == 200, r.text
        gen = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert gen.status_code == 200, gen.text
        assert gen.json()["status"] == "created", gen.json()

        refresh_library()
        doc = load_library().by_id[f"{sid}.u01"].doc
        assert doc.taught_facts, "落盘内容必须带 taught_facts"
        assert doc.worked_examples, "auto 出稿必须产出 worked_examples ≥1（A3）"
        assert all(e.basis is not None for e in doc.exercises), "每题必须带 basis"
        rep = ab.gate_node(doc, drop=False)
        assert rep.verified is True
        assert rep.exercises == list(doc.exercises) and not rep.dropped_exercises
        assert not rep.dropped_asks
    finally:
        with SessionLocal() as db:
            from app.outline import store as ostore

            ostore.delete_subject(db, sid, hard=True)


# ---------- 生成端：AI（假 provider） ----------

class _FakeProvider:
    def __init__(self, parsed: dict):
        self.parsed = parsed
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))

        class _Out:
            pass

        out = _Out()
        out.parsed = self.parsed
        return out


def test_ai_generation_drops_unanswerable_question_and_keeps_the_rest(app_client, monkeypatch):
    """S5 端到端：AI 给了 1 道越界题（无依据）→ 只丢那一题，其余正常入库。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r35")
    lecture = ("恒星的体积差异很大。太阳是一颗恒星，它是离地球最近的恒星。\n"
               "行星自身不发光，它们围绕恒星运行。")
    parsed = {
        "lecture": lecture,
        "feynman_task": "请你用自己的话讲清恒星与行星的区别。",
        "taught_facts": [{"id": "f1", "text": "太阳是一颗恒星，它是离地球最近的恒星。"},
                         {"id": "f2", "text": "行星自身不发光，它们围绕恒星运行。"}],
        "derivable": [],
        "worked_examples": [{"prompt": "例：太阳是什么？", "solution_steps": ["太阳是一颗恒星。"]}],
        "asks": [{"ask": "太阳是什么？", "basis": {"fact_ids": ["f1"], "quote": "太阳是一颗恒星，它是离地球最近的恒星。"}}],
        "exercises": [
            {"kind": "boolean", "prompt": "判断题：太阳是一颗恒星。", "answer_bool": True,
             "basis": {"fact_ids": ["f1"], "quote": "太阳是一颗恒星，它是离地球最近的恒星。"}},
            {"kind": "choice", "prompt": "选择题：下面哪一句是讲解里说过的？",
             "options": ["行星自身不发光", "木星体积最大", "地球是恒星", "太阳绕地球转"], "answer_index": 0,
             "basis": {"fact_ids": ["f2"], "quote": "行星自身不发光，它们围绕恒星运行。"}},
            # 越界题（用户命中的类型）：讲解没比较过个体 → 无依据 → 应被丢弃
            {"kind": "fill", "prompt": "填空题：太阳系中体积最大的行星是___。", "expected": "木星"},
            {"kind": "boolean", "prompt": "判断题：行星围绕恒星运行。", "answer_bool": True,
             "basis": {"fact_ids": ["f2"], "quote": "行星自身不发光，它们围绕恒星运行。"}},
        ],
    }
    import app.ai.provider as prov

    fake = _FakeProvider(parsed)
    monkeypatch.setattr(prov, "OpenAICompatibleProvider", lambda **kw: fake)

    sid = f"r35b{uuid.uuid4().hex[:6]}"
    assert app_client.post("/api/subjects", json={"label": "R35 AI 学科", "subject_id": sid}).status_code == 201
    try:
        r = app_client.put(f"/api/subjects/{sid}/outline", json={"units": [
            {"id": f"{sid}.u01", "title": "第一讲 恒星", "group": "第一章",
             "objectives": ["认识恒星与行星"], "concept_tags": ["恒星", "行星"], "difficulty": 1}],
            "status": "active", "source": "manual"})
        assert r.status_code == 200, r.text
        gen = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert gen.status_code == 200, gen.text
        assert gen.json()["status"] == "created", gen.json()
        from app.content.loader import load_library
        from app.service.library import refresh_library

        refresh_library()
        doc = load_library().by_id[f"{sid}.u01"].doc
        prompts = " ".join(e.prompt for e in doc.exercises)
        assert "体积最大的行星" not in prompts, "越界题（讲解没比较过个体）必须被丢弃"
        assert len(doc.exercises) >= 3 and all(e.basis for e in doc.exercises)
        assert ab.gate_node(doc, drop=False).verified is True
    finally:
        from app.db import SessionLocal

        with SessionLocal() as db:
            from app.outline import store as ostore

            ostore.delete_subject(db, sid, hard=True)


def test_unit_content_call_schema_carries_answerability_fields():
    """接线锁（R36 §8 三处同改）：输出 schema 必须声明 basis / taught_facts / 例题 / asks。"""
    from app.ai.calls import CALL_UNIT_CONTENT

    parsed = CALL_UNIT_CONTENT.output_schema.model_validate({
        "lecture": "讲解",
        "taught_facts": [{"id": "f1", "text": "讲解句"}],
        "derivable": [{"conclusion": "结论", "premises": ["f1"], "rule": "规则"}],
        "worked_examples": [{"prompt": "例", "solution_steps": ["步"]}],
        "asks": [{"ask": "小思考", "basis": {"fact_ids": ["f1"], "quote": "讲解句"}}],
        "exercises": [{"kind": "boolean", "prompt": "题", "answer_bool": True,
                       "basis": {"fact_ids": ["f1"], "quote": "讲解句"}}],
    })
    assert parsed.taught_facts and parsed.taught_facts[0].id == "f1"
    assert parsed.worked_examples and parsed.derivable and parsed.asks
    assert parsed.asks[0].basis is not None and parsed.asks[0].basis.fact_ids == ["f1"]
    assert parsed.exercises[0].basis is not None, "schema 丢了 basis → 可答性链路静默失效"
