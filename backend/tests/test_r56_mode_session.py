"""R56 第 3 步收尾用例：**图示教材模式真的能学起来，而且判题走本模式分支**。

口径（工单 §1/§3-A/§5）：
- 内容生成：本模式学科的单元内容由 `mode_lesson` + `mode_exercise` 产出，
  落成与既有内容库**同一种**节点文件（题目 `check.mode="ai"`）；
- 会话：讲解**直接给**模型的讲解正文（不再让路径②的"讲解演绎"改写）；
  提交答案 → 判对错走**本模式分支（模型判）**，**sympy 判题一次都不碰**；
- **诚实出口**：模型说判不了 → 不打分、不动进度、如实显示、账本有中文记录；
- 路径②回归：本模块只加不改，既有 27 个节点的校验统计不变。
"""
from __future__ import annotations

import base64

import pytest

from app.service import model_config
from r55_support import adopt_outline, cleanup_subjects, gen_unit, make_subject, unit

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")
MAT_TITLE = "图片页面教材"


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _ModeProvider:
    """假 provider：读页 / 写讲解 / 出题 / 判题四种返回；记录调用点顺序。"""

    def __init__(self, *, judge: list[dict] | None = None):
        self.judge_queue = list(judge or [])
        self.calls: list[str] = []

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        self.calls.append(call.name)
        if call.name == "read_page":
            return _Outcome({"page_label": "第 1 页", "readable": True,
                             "key_points": ["太阳系由太阳和八颗行星组成"],
                             "visible_text": ["图 1.1 太阳系示意图"],
                             "figures": [{"label": "图 1.1", "kind": "示意图",
                                          "description": "中心是太阳，外围是行星轨道"}],
                             "uncertain": [], "confidence": 0.9})
        if call.name == "mode_lesson":
            return _Outcome({"lecture_md": "太阳系由太阳和八颗行星组成。行星沿椭圆轨道运行。",
                             "key_points": ["八颗行星", "沿椭圆轨道运行"],
                             "worked_examples": [{"prompt": "太阳系有几颗行星？",
                                                  "solution_steps": ["数一数：八颗"]}],
                             "source_pages": ["第 1 页"], "uncertain": False,
                             "uncertain_reason": ""})
        if call.name == "mode_exercise":
            return _Outcome({"exercises": [
                {"prompt": "太阳系有几颗行星？（选一个）", "kind": "choice",
                 "options": ["四颗", "八颗", "十二颗", "这一页没写"],
                 "answer": "八颗", "explanation": "第 1 页写了八颗行星。",
                 "basis_pages": ["第 1 页"]}],
                "uncertain": False, "uncertain_reason": ""})
        if call.name == "mode_judge":
            if self.judge_queue:
                return _Outcome(dict(self.judge_queue.pop(0)))
            return _Outcome({"verdict": "correct", "score_0_1": 1.0, "feedback_md": "对",
                             "better_md": "", "basis_pages": ["第 1 页"]})
        raise AssertionError(f"没预设这个调用点的返回：{call.name}")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate_model_settings(app_client):
    from app import models
    from app.db import SessionLocal

    def _clear() -> None:
        with SessionLocal() as db:
            for key in model_config.KEYS:
                row = db.get(models.AppSetting, key)
                if row is not None:
                    db.delete(row)
            db.commit()
        model_config._MEMORY_KEY = ""

    _clear()
    yield
    _clear()
    app_client.app.dependency_overrides.clear()


def _fake_client(app_client, provider):
    from app.api.deps import get_gateway

    app_client.app.dependency_overrides[get_gateway] = lambda: provider


def _make_mode_subject(app_client, sids, provider, monkeypatch) -> tuple[str, str]:
    """建一个图示教材模式学科：导入 1 页图片 → 采纳 1 个单元 → 返回 (sid, unit_id)。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r56-mode")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: provider)
    sid = make_subject(app_client, sids)
    r = app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                        data={"title": MAT_TITLE},
                        files=[("files", ("p1.png", PNG_1PX, "image/png"))])
    assert r.status_code == 201, r.text
    adopt_outline(app_client, sid, [unit(f"{sid}.u01", "太阳系", section="第 1 页",
                                         material=MAT_TITLE)])
    return sid, f"{sid}.u01"


# ============================================================ 内容生成 + 会话（全 AI 模式）

def test_r56_3_mode_content_is_generated_and_learnable(app_client, sids, monkeypatch):
    """本模式学科 → 单元内容由模型产出（讲解 + `check.mode="ai"` 的题）→ **能进会话学**。"""
    provider = _ModeProvider()
    sid, uid = _make_mode_subject(app_client, sids, provider, monkeypatch)
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: provider)
    res = gen_unit(app_client, sid, uid)
    _fake_client(app_client, provider)      # 会话判题也走假 provider（不触网）
    assert res["status"] == "created", res
    assert "全 AI 模式" in res["note"] and "没有独立的第二次核对" in res["note"], res["note"]
    assert {"mode_lesson", "mode_exercise"} <= set(provider.calls), provider.calls

    # 落盘的文件能被内容库加载；题目是 ai 模式（判对错由模型做）
    from app.content.loader import load_library

    doc = load_library().by_id[uid].doc
    assert doc.exercises, "至少要有一道题"
    assert all(e.check.mode == "ai" for e in doc.exercises), [e.check.mode for e in doc.exercises]
    assert all(e.check.answer for e in doc.exercises)
    assert doc.explanation.body.strip(), "讲解正文非空"

    # **会话**：讲解直接给模型写的正文（不走路径②的"讲解演绎"）
    started = app_client.post("/api/session/start", json={"node_id": uid}).json()
    assert started["step"] == "explain", started["step"]
    assert "太阳系由太阳和八颗行星组成" in str(started["payload"].get("lecture_md") or "")
    assert started["payload"].get("lecture_from") == "all_ai", started["payload"].get("lecture_from")
    assert "mode_qa" not in provider.calls and "explain_node" not in provider.calls, provider.calls

    # 走到练习 → 提交答案（模型判"对"）→ 连对计数照旧由程序推进
    sid_sess = started["session"]["id"]
    for _ in range(2):
        app_client.post("/api/session/step", json={"session_id": sid_sess, "action": "next"})
    step = app_client.get(f"/api/session/{sid_sess}").json()
    assert step["step"] == "practice", step["step"]
    cur = step["payload"]["exercise"]
    submitted = app_client.post("/api/session/step", json={
        "session_id": sid_sess, "action": "submit_exercise",
        "payload": {"exercise_id": cur["exercise_id"], "params_seed": int(cur["seed"]),
                    "user_answer": "八颗"}}).json()
    assert submitted["payload"].get("judged_by") == "model", submitted["payload"]
    assert submitted["payload"].get("verdict") == "correct"
    assert any(e["type"] == "exercise_judged_by_model" for e in submitted["events"]), submitted["events"]


def test_r56_3_mode_session_judging_never_touches_sympy(app_client, sids, monkeypatch):
    """**模式隔离（会话层）**：本模式的提交**不调用** sympy 判题，也**不调用**可答性闸门。"""
    provider = _ModeProvider(judge=[{"verdict": "correct", "score_0_1": 1.0,
                                     "feedback_md": "对", "better_md": "", "basis_pages": []}])
    sid, uid = _make_mode_subject(app_client, sids, provider, monkeypatch)
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: provider)
    assert gen_unit(app_client, sid, uid)["status"] == "created"
    _fake_client(app_client, provider)

    called: list[str] = []

    def _boom(*a, **kw):        # pragma: no cover
        called.append("called")
        raise AssertionError("图示教材模式的会话不许走这条路")

    import app.domain.judge as judge_mod
    from app.content import answerability

    monkeypatch.setattr(judge_mod, "judge", _boom)
    monkeypatch.setattr(answerability, "gate_node", _boom)

    started = app_client.post("/api/session/start", json={"node_id": uid}).json()
    sess = started["session"]["id"]
    for _ in range(2):
        app_client.post("/api/session/step", json={"session_id": sess, "action": "next"})
    step = app_client.get(f"/api/session/{sess}").json()
    cur = step["payload"]["exercise"]
    # **界面要能答题**：选择题的选项必须下发（答案不外泄），并标明"由模型判"
    assert cur.get("options") == ["四颗", "八颗", "十二颗", "这一页没写"], cur
    assert cur.get("answer_kind") == "choice" and cur.get("judged_by") == "model", cur
    assert "answer" not in cur and cur.get("basis_pages") == ["第 1 页"], cur
    out = app_client.post("/api/session/step", json={
        "session_id": sess, "action": "submit_exercise",
        "payload": {"exercise_id": cur["exercise_id"], "params_seed": int(cur["seed"]),
                    "user_answer": "八颗"}}).json()
    assert not called, called
    assert out["payload"]["judged_by"] == "model"
    assert "mode_judge" in provider.calls, provider.calls


def test_r56_3_mode_uncertain_exit_is_visible_and_not_counted(app_client, sids, monkeypatch):
    """**诚实出口（会话层）**：模型说判不了 → 如实显示、**不动进度**、账本有中文记录。"""
    provider = _ModeProvider(judge=[
        {"verdict": "uncertain", "uncertain_reason": "第 1 页是模糊扫描图，读不出题面依据",
         "score_0_1": 0.0, "feedback_md": "这次我读不到依据，先不定你对错。", "better_md": "",
         "basis_pages": ["第 1 页"]}])
    sid, uid = _make_mode_subject(app_client, sids, provider, monkeypatch)
    import app.outline.mode_generate as mg

    monkeypatch.setattr(mg, "_build_provider", lambda db: provider)
    assert gen_unit(app_client, sid, uid)["status"] == "created"
    _fake_client(app_client, provider)

    started = app_client.post("/api/session/start", json={"node_id": uid}).json()
    sess = started["session"]["id"]
    for _ in range(2):
        app_client.post("/api/session/step", json={"session_id": sess, "action": "next"})
    before = app_client.get(f"/api/session/{sess}").json()
    cur = before["payload"]["exercise"]
    out = app_client.post("/api/session/step", json={
        "session_id": sess, "action": "submit_exercise",
        "payload": {"exercise_id": cur["exercise_id"], "params_seed": int(cur["seed"]),
                    "user_answer": "八颗"}}).json()

    assert out["payload"].get("verdict") == "uncertain", out["payload"]
    assert "没判出来" in str(out["payload"].get("reason_zh") or ""), out["payload"]
    assert "读不到" in str(out["payload"].get("feedback_md") or "")
    # **不动进度**：连对还是 0，题还是同一道（不许当成答错换题、也不许当成答对推进）
    assert out["payload"]["progress"]["consecutive_correct"] == 0, out["payload"]["progress"]
    assert any(e["type"] == "judge_uncertain" for e in out["events"]), out["events"]
    after = app_client.get(f"/api/session/{sess}").json()
    assert after["payload"]["exercise"]["exercise_id"] == cur["exercise_id"], "判不了就不换题"
    # 账本里有中文记录（就地提示 + 记录页都能看到）
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    hits = [x for x in rows if (x.get("detail") or {}).get("kind") == "judge_uncertain"]
    assert hits and "没判出来" in hits[0]["reason"], hits


def test_r56_3_ai_exercises_stay_out_of_the_template_gate():
    """本模式的题**不进**路径②的模板闸门（那道闸门用 sympy/引文，本模式没有那些东西）。"""
    from app.content.schemas import (
        CheckDoc, ExerciseDoc, FeynmanDoc, NodeDoc, RubricDoc, RubricDimension,
    )
    from app.content.verify import check_node, gate_errors

    doc = NodeDoc(id="s-x.u01", title="t", level="教材", topic="t",
                  exercises=[ExerciseDoc(id="ai1", kind="fixed", prompt="题目",
                                         check=CheckDoc(mode="ai", answer="答案"))],
                  feynman=FeynmanDoc(task_prompt="讲一遍",
                                     rubric=RubricDoc(dimensions=[
                                         RubricDimension(key="correctness", weight=1.0)])))
    assert check_node(doc) == [] and gate_errors(doc) == []
