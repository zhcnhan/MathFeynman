"""R54 任务 A 用例：**没看到讲解，不许进"讲解环节"**（P0 · 用户实测痛点）。

用户原话：「我打开一章他直接让我讲，我都没看过他的讲解我讲什么。」
口径：内容不足以学（讲解为空 / 还没内容 / （防御）题没了 / 事实依据全丢）→ 状态机只下发
`content_missing` 卡片（中文说明 + 一键生成），**不下发学习步骤、不下发作答入口**；
"已展示过讲解"用 `flow.explained_seen` 记（explain 阶段正常下发讲解正文后置位），
进费曼前必须为真——老会话/历史数据默认 False → **退回讲解**并说明（不报错、不留在半步）。
"""
from __future__ import annotations

import pytest

from app.service import outline_gate
from r54_support import (
    answer_of, cleanup_subjects, gen, get_session, make_subject, patch_node,
    remove_node_file, session_flow, set_flow, start,
)


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def _assert_no_learning_steps(payload: dict) -> None:
    for key in ("lecture_md", "exercise", "task_prompt", "rubric"):
        assert key not in payload, key


def test_r54_a1_missing_explanation_blocks_learning_and_offers_generate(app_client, sids):
    """**A3-①**：内容文件没有讲解正文 → **不许进 explain/Feynman**；给中文说明 + 一键生成入口。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    patch_node(sid, unit, lambda m: m["explanation"].update({"body": ""}))

    res = start(app_client, unit)

    assert res["step"] == "content_missing", res["step"]
    info = res["payload"]["content_missing"]
    assert info["missing"] == "explanation", info
    assert "讲解" in info["reason_zh"] and any("\u4e00" <= c <= "\u9fff" for c in info["reason_zh"])
    assert info["can_generate"] is True and info["subject_id"] == sid and info["unit_id"] == unit
    _assert_no_learning_steps(res["payload"])


def test_r54_a2_explanation_not_shown_cannot_jump_to_feynman(app_client, sids):
    """**A3-②（用户撞到的场景）**：讲解存在但**这轮没展示过** → 不许直接进 Feynman；退回讲解并说明。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    res = start(app_client, unit)
    session_id = res["session"]["id"]
    assert res["step"] == "explain"          # 正常入口：先讲
    assert str(res["payload"].get("lecture_md") or "").strip(), "讲解正文必须真的有内容"

    # 模拟"历史会话"：练习已过、被推到费曼，但这一轮压根没看过讲解
    set_flow(session_id, lambda f: (f.update({"stage": "feynman", "explained_seen": False}),
                                    f["practice"].update({"passed": True})))

    # ① 直接调费曼提交也拦得住（不报错，把人送回讲解并说明）——这正是用户撞到的那一步
    forced = app_client.post("/api/session/step", json={
        "session_id": session_id, "action": "feynman_submit",
        "payload": {"transcript": "我直接讲一遍试试"}}).json()
    assert forced["step"] == "explain", f"没看过讲解不许进费曼；实际 {forced['step']}"
    assert forced["payload"].get("rewound_zh"), "必须给中文说明（不是静默退回）"
    assert "讲解" in forced["payload"]["rewound_zh"]
    assert not forced["payload"].get("task_prompt"), "不许下发'请你讲一遍'的任务"
    assert str(forced["payload"].get("lecture_md") or "").strip(), "退回讲解就要把讲解给出来"
    assert session_flow(session_id)["stage"] == "explain"

    # ② 正常打开（恢复）也停在讲解，不会跳到费曼
    back = get_session(app_client, session_id)
    assert back["step"] == "explain"
    assert str(back["payload"].get("lecture_md") or "").strip()
    assert not back["payload"].get("task_prompt")


def test_r54_a3_explanation_shown_then_practice_leads_to_feynman(app_client, sids):
    """**A3-③（回归）**：讲解正常展示过 → 练习达标后**可以**进 Feynman（不许把正常路径堵死）。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    res = start(app_client, unit)
    session_id = res["session"]["id"]
    assert res["step"] == "explain" and str(res["payload"].get("lecture_md") or "").strip()
    assert session_flow(session_id)["explained_seen"] is True   # 展示过 → 置位

    step = app_client.post("/api/session/step",
                           json={"session_id": session_id, "action": "next"}).json()
    assert step["step"] == "example"
    step = app_client.post("/api/session/step",
                           json={"session_id": session_id, "action": "next"}).json()
    assert step["step"] == "practice"

    for _ in range(6):                       # 真答对 3 题（canonical 答案；判题仍走 L1 判题器）
        cur = step["payload"].get("exercise")
        if not cur:
            break
        ans = answer_of(unit, cur["exercise_id"], int(cur["seed"]))
        step = app_client.post("/api/session/step", json={
            "session_id": session_id, "action": "submit_exercise",
            "payload": {"exercise_id": cur["exercise_id"], "params_seed": int(cur["seed"]),
                        "user_answer": ans}}).json()
        if step["step"] == "feynman":
            break
    assert step["step"] == "feynman", f"讲解看过 + 练习达标应进费曼；实际 {step['step']}"
    assert step["payload"].get("task_prompt")


def test_r54_a4_resume_after_content_removed_rewinds_with_zh_note(app_client, sids):
    """**A3-④**：内容文件被删后恢复旧会话 → **退回可进行状态 + 中文说明**，不卡半步（不 404/409）。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    res = start(app_client, unit)
    session_id = res["session"]["id"]
    app_client.post("/api/session/step", json={"session_id": session_id, "action": "next"})

    remove_node_file(sid, unit)              # 内容被移除/被替换

    back = get_session(app_client, session_id)

    assert back["step"] == "content_missing", back["step"]
    info = back["payload"]["content_missing"]
    assert info["reason_zh"] and "内容" in info["reason_zh"], info
    assert info["can_generate"] is True and info["unit_id"] == unit
    _assert_no_learning_steps(back["payload"])
    nxt = app_client.post("/api/session/step",
                          json={"session_id": session_id, "action": "next"}).json()
    assert nxt["step"] == "content_missing", nxt["step"]


def test_r54_a5_no_exercises_blocks_practice(monkeypatch, app_client, sids):
    """**A3-⑤**：练习前必须有题（**防御分支**：正常内容文件不可能 0 题——加载校验
    `每个节点至少 1 道练习` 会先挡住；这里直接施加"0 题"状态验证守卫本身）。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    real = outline_gate.unit_content_status

    def fake(node_id: str) -> dict:
        st = dict(real(node_id))
        if node_id == unit:
            st.update({"usable": False, "exists": True, "missing": "exercise", "exercises": 0,
                       "reason_zh": "这个单元还没有可用的练习题，重新生成后才能开始练习"})
        return st

    monkeypatch.setattr(outline_gate, "unit_content_status", fake)

    res = start(app_client, unit)

    assert res["step"] == "content_missing", res["step"]
    info = res["payload"]["content_missing"]
    assert info["missing"] == "exercise" and "练习" in info["reason_zh"]
    assert info["can_generate"] is True
