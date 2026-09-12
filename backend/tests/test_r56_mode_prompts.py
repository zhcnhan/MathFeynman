"""R56 第 2 步用例：**提示词全套**（工单 §4 任务 B）＋ **判题/评分的诚实出口**（§5 任务 C）。

口径：
- 每个环节都是**独立提示词调用点**（可读、可改、可恢复默认），schema + prompt + 用例三处同改；
- 提示词里必须写进四条硬约束（只用给到的内容 / 读不到就明说 / 依据指到页·图号 / 拿不准给出口）；
- 改一条提示词 → 本模式下对应产出**下一次就用新版**（用 AI 对话审计对照）；
- **诚实出口**：模型说判不了 → 不打分、不计掌握、界面如实显示、账本有中文记录，**不许静默当对/当错**。
"""
from __future__ import annotations

import json

import pytest

from app.ai.calls import CALLS, ModeJudgeIn
from app.ai.prompt_templates import PROMPTS, UI_PLACEHOLDER_DEFAULTS, render
from app.service import mode_ai
from r55_support import cleanup_subjects, make_subject

MODE_CALLS = ("read_page", "mode_outline", "mode_lesson", "mode_exercise", "mode_judge",
              "mode_feynman", "mode_followup", "mode_gap_check", "mode_qa")


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider：回预设结构化结果，并记下**发给它的提示词**（用于核对"改了就生效"）。"""

    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls: list[list[dict]] = []
        self.seen_kwargs: list[dict] = []

    def chat_json(self, call, messages, **kw):
        self.calls.append([dict(m) for m in messages])
        self.seen_kwargs.append({"call": call.name, **kw})
        if not self.payloads:
            raise AssertionError("假 provider 收到了超出预设次数的调用")
        return _Outcome(self.payloads.pop(0))

    @property
    def system_text(self) -> str:
        return "\n".join(str(m[0]["content"]) for m in self.calls)

    @property
    def user_text(self) -> str:
        return "\n".join(str(m[-1]["content"]) for m in self.calls)


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def _pages() -> list[dict]:
    return [{"page_label": "第 12 页", "readable": True,
             "key_points": ["太阳系由太阳和八颗行星组成"],
             "visible_text": ["图 1.1 太阳系示意图"],
             "figures": [{"label": "图 1.1", "kind": "示意图", "description": "中心是太阳"}],
             "uncertain": ["右下角小字看不清"], "confidence": 0.8},
            {"page_label": "第 13 页", "readable": False,
             "unreadable_reason": "整页是模糊扫描图，字太小", "figures": [], "confidence": 0.1}]


# ============================================================ B3-① 每个调用点都注册进提示词表

def test_r56_2_all_mode_call_points_are_registered_and_editable(app_client):
    """**B3-①**：本模式的每个环节都有独立调用点，能在提示词接口里读、能改、能恢复默认。"""
    for name in MODE_CALLS:
        assert name in CALLS, f"调用点没注册：{name}"
        assert name in PROMPTS, f"提示词没注册：{name}"
    data = app_client.get("/api/prompts").json()
    got = {it["call_name"]: it for it in data["prompts"]}
    for name in MODE_CALLS:
        assert name in got, f"提示词接口里看不到：{name}"
        item = got[name]
        assert item["is_default"] is True
        assert str(item["system"]).strip() and str(item["user"]).strip()
        # 每个占位符都有界面预览默认值（编辑页不会因缺值渲染崩）
        for ph in item["placeholders"]:
            assert ph in UI_PLACEHOLDER_DEFAULTS, (name, ph)
    # 9 个环节各自独立：user 模板互不相同
    users = [got[n]["raw_user_template"] for n in MODE_CALLS]
    assert len(set(users)) == len(users), "模式内各环节的提示词必须各自独立（不许共用一份）"

    # 能改 + 能恢复默认（拿最关键的那条：判对错）
    changed = app_client.put(
        "/api/prompts/mode_judge",
        json={"user": got["mode_judge"]["raw_user_template"] + "\n[我的要求] 每题都要讲清依据。"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["is_default"] is False
    back = app_client.post("/api/prompts/mode_judge/reset", json={"field": "user"})
    assert back.status_code == 200 and back.json()["is_default"] is True, back.text


def test_r56_2_mode_prompts_carry_the_four_hard_constraints():
    """提示词里必须写进四条硬约束（这是本模式的诚实性所在，不是可选文案）。"""
    common = render(PROMPTS["mode_judge"].system, **UI_PLACEHOLDER_DEFAULTS)
    for token in ("只用给到你的内容", "读不到就明说", "依据指到页/图号", "拿不准给出口"):
        assert token in common, token
    # 判/评类调用点必须把「不确定」写进提示词与输出字段
    for name in ("mode_judge", "mode_feynman", "mode_gap_check"):
        spec = PROMPTS[name]
        body = render(spec.system, **UI_PLACEHOLDER_DEFAULTS) + render(
            spec.user, **UI_PLACEHOLDER_DEFAULTS)
        assert "uncertain" in body, name
    # 判题：明确写了"不许硬判"与"部分对也要给 partial"
    judge = render(PROMPTS["mode_judge"].system, **UI_PLACEHOLDER_DEFAULTS)
    assert "不要硬判" in judge and "partial" in judge
    # 评分：要求逐字引用学生原话；追问：引不出来就 reteach
    assert "evidence_quote" in render(PROMPTS["mode_feynman"].system, **UI_PLACEHOLDER_DEFAULTS)
    assert "reteach" in render(PROMPTS["mode_followup"].system, **UI_PLACEHOLDER_DEFAULTS)


def test_r56_2_deleting_a_required_token_is_rejected_in_chinese(app_client):
    """**B3-②**：删掉"必须保留"的硬约束/占位符 → **中文拒存**（沿用既有机制）。"""
    data = app_client.get("/api/prompts").json()
    judge = next(it for it in data["prompts"] if it["call_name"] == "mode_judge")
    # 删掉硬约束词（uncertain）→ 拒绝（改的是**原始模板**，接口按 raw 校验并保存）
    bad = app_client.put("/api/prompts/mode_judge",
                         json={"system": str(judge["raw_template"]).replace("uncertain", "结果")})
    assert bad.status_code == 422, bad.text
    assert "必须" in bad.text or "保留" in bad.text, bad.text
    # 删掉必填占位符（pages_digest）→ 拒绝
    bad2 = app_client.put("/api/prompts/mode_judge",
                          json={"user": str(judge["raw_user_template"]).replace("{pages_digest}", "")})
    assert bad2.status_code == 422 and "pages_digest" in bad2.text, bad2.text
    # 别把拒存留在库里
    app_client.post("/api/prompts/mode_judge/reset", json={"field": "system"})
    assert app_client.get("/api/prompts").json()["prompts"]
    assert next(it for it in app_client.get("/api/prompts").json()["prompts"]
                if it["call_name"] == "mode_judge")["is_default"] is True


# ============================================================ B3-③ 改提示词 → 下一次产出即用新版

def test_r56_2_edited_prompt_takes_effect_next_call(app_client, monkeypatch):
    """**B3-③**：改一条提示词 → 本模式下对应产出**下一次就用新版**（审计里能看到新文本）。"""
    marker = "[本次特别要求] 判题时先复述学生答案，再下结论。"
    data = app_client.get("/api/prompts").json()
    judge = next(it for it in data["prompts"] if it["call_name"] == "mode_judge")
    r = app_client.put("/api/prompts/mode_judge",
                       json={"system": str(judge["raw_template"]) + "\n" + marker})
    assert r.status_code == 200, r.text
    try:
        fake = _FakeProvider([{"verdict": "correct", "score_0_1": 1.0,
                               "feedback_md": "对", "better_md": "", "basis_pages": ["第 12 页"]}])
        out = mode_ai.judge(fake, ModeJudgeIn(prompt="太阳系有几颗行星？", kind="short",
                                              reference_answer="八颗", student_answer="八颗"),
                            subject_id="s-r56", unit_id="s-r56.u01", pages=_pages())
        assert out["status"] == "correct"
        assert marker in fake.system_text, "改过的提示词没有生效"
        # 审计元数据带上提示词版本（能对照"这次用的是哪一版"）
        assert fake.seen_kwargs[-1]["call"] == "mode_judge"
        assert fake.seen_kwargs[-1]["audit"]["prompt_versions"], fake.seen_kwargs[-1]
        # 页面记录（含"读不出来"的那页）如实进了提示词
        assert "第 12 页" in fake.user_text and "第 13 页" in fake.user_text
    finally:
        app_client.post("/api/prompts/mode_judge/reset", json={"field": "system"})


# ============================================================ C1 诚实出口（P0）

def test_r56_2_c1_judge_uncertain_is_honest_and_ledgered(app_client, sids):
    """**C1-①**：造一份"图读不出来"的样本 → 判题走**诚实出口**：不打分、账本有中文记录。"""
    sid = make_subject(app_client, sids)
    fake = _FakeProvider([{"verdict": "uncertain",
                           "uncertain_reason": "相关页面（第 13 页）是模糊扫描图，读不出题面依据，判不了",
                           "score_0_1": 0.0, "feedback_md": "这次我读不到依据，先不定你对错。",
                           "better_md": "", "basis_pages": ["第 13 页"]}])
    out = mode_ai.judge(fake, ModeJudgeIn(prompt="柱状图里第 4 根柱子是多少？", kind="short",
                                          reference_answer="300", student_answer="300",
                                          pages_digest=""),
                        subject_id=sid, unit_id=f"{sid}.u01", pages=_pages())

    assert out["status"] == "uncertain" and out["verdict"] == "uncertain", out
    assert out["counted"] is False, "判不出来就不许计入掌握"
    assert out["score_0_1"] == 0.0
    assert "没判出来" in out["reason_zh"] and "不算对也不算错" in out["reason_zh"], out["reason_zh"]
    assert "读不到" in out["feedback_md"] or "读不到" in out["reason_zh"]

    # 账本：一条中文记录（就地提示 + 记录页都能看到）
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    hits = [x for x in rows if (x.get("detail") or {}).get("kind") == "judge_uncertain"]
    assert hits, rows
    text = f"{hits[0]['object']}{hits[0]['reason']}"
    assert "判题" in text and "没判出来" in text and "读" in text, text
    assert hits[0]["impact"] == "该单元" and hits[0]["remedy"], hits[0]
    # 界面（接口）能拿到同一句中文说明：`reason_zh` 就是给它用的
    assert out["reason_zh"]


def test_r56_2_c1_never_silently_treated_as_wrong_or_right(app_client, sids):
    """**C1-②**：判不出来时**没有**任何"静默当错/当对"的痕迹（既不计分也不判掌握）。"""
    sid = make_subject(app_client, sids)
    fake = _FakeProvider([{"verdict": "uncertain", "uncertain_reason": "题目本身有歧义",
                           "score_0_1": 0.0, "feedback_md": "这题问得不清，我不判。",
                           "better_md": "", "basis_pages": []}])
    out = mode_ai.judge(fake, ModeJudgeIn(prompt="下图说明了什么？", kind="short",
                                          reference_answer="", student_answer="说明了温度变化"),
                        subject_id=sid, unit_id=f"{sid}.u01")
    assert out["status"] not in ("correct", "partial", "wrong"), out
    assert out["counted"] is False and out["score_0_1"] == 0.0
    # 账目里必须写明"不算对也不算错"（不给学习者扣分，也不给他虚假的通过）
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    reason = "；".join(x["reason"] for x in rows)
    assert "不算对也不算错" in reason, reason
    assert "答对了" not in reason and "答错了" not in reason, reason

    # 费曼评分同理：评不出来 → 不通过也不判失败（verdict=uncertain，维度分不落）
    fake2 = _FakeProvider([{"dimension_scores": [{"key": "correctness", "score": 0.9,
                                                  "evidence_quote": "太阳是恒星", "comment": "好"}],
                            "overall_note": "讲得不错", "verdict": "uncertain",
                            "uncertain_reason": "页面记录读不出来，无法核对内容对错",
                            "confidence": 0.2}])
    fey = mode_ai.feynman(fake2, mode_ai.ModeFeynmanIn(
        task_prompt="讲一遍", dimensions=["correctness"], transcript="太阳是恒星"),
        subject_id=sid, unit_id=f"{sid}.u01")
    assert fey.verdict == "uncertain"
    assert fey.dimension_scores == [], "判不出来时不许留下「看起来给了分」的维度分"
    assert "评不了" in fey.overall_note
    rows2 = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    assert any((x.get("detail") or {}).get("kind") == "feynman_uncertain" for x in rows2), rows2


def test_r56_2_mode_service_does_not_import_book_path_machinery():
    """模式分支**不许**偷偷用文字教材路径的机器（sympy 判题 / 可答性 / 引文比对 / 会话守卫）。

    只看**实际 import**（模块文档里写着"不用它们"是说明，不是机制）。
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(mode_ai.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[-1])
            imported |= {a.name for a in node.names}
    for banned in ("sympy", "answerability", "citations", "judge", "judge_exercise",
                   "outline_gate", "answerability_gate"):
        assert banned not in imported, f"图示教材模式里 import 了文字路径的机器：{banned}"
    # 判题结果里的分**原样**来自模型（服务端不改分）：故意让模型给 0.37，看是否被改成 0/1
    fake = _FakeProvider([{"verdict": "partial", "score_0_1": 0.37, "feedback_md": "对一半",
                           "better_md": "", "basis_pages": []}])
    out = mode_ai.judge(fake, ModeJudgeIn(prompt="p", student_answer="a"))
    assert out["score_0_1"] == 0.37, "服务端不许用规则改模型给的分"
    assert json.dumps(out, ensure_ascii=False)
