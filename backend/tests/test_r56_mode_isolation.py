"""R56 第 3 步用例：**模式选择与隔离**（工单 §3 任务 A）。

口径：
- **显式选择**：材料导入处多一条路「图片为主的教材（全程交给 AI 判断）」，导入的是**页面图片**；
- **前置校验**：没配能读图的模型 → **中文明确拒绝、不落库**（不许静默降级）；
- **落库**：材料上标出"属于哪个模式"（复用既有材料元数据，不新建表）；
- **模式隔离**：本模式的判题/评分走本模式分支，**不碰**文字教材路径的机器（sympy 判题 / 可答性闸门）；
- **回归**：路径②（文字教材）一切照旧。
"""
from __future__ import annotations

import base64

import pytest

from app.service import model_config
from app.service import mode_ai
from r55_support import cleanup_subjects, make_subject, materials, upload_text_material

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeVision:
    """假 provider：读页时回一份固定记录；判题时回预设结论。记录每次调用的调用点名。"""

    def __init__(self, *, page: dict | None = None, judge: dict | None = None):
        self.page = page or {"page_label": "第 1 页", "readable": True,
                             "key_points": ["太阳系由太阳和八颗行星组成"],
                             "visible_text": ["图 1.1 太阳系示意图"],
                             "figures": [{"label": "图 1.1", "kind": "示意图",
                                          "description": "中心是太阳，外围是行星轨道"}],
                             "uncertain": [], "confidence": 0.9}
        self.judge = judge or {"verdict": "correct", "score_0_1": 1.0, "feedback_md": "对",
                               "better_md": "", "basis_pages": ["第 1 页"]}
        self.calls: list[str] = []

    def chat_json(self, call, messages, **kw):        # noqa: ARG002
        self.calls.append(call.name)
        if call.name == "read_page":
            return _Outcome(dict(self.page))
        if call.name == "mode_judge":
            return _Outcome(dict(self.judge))
        raise AssertionError(f"没预设这个调用点的返回：{call.name}")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


@pytest.fixture(autouse=True)
def _isolate_model_settings(app_client):
    """每条用例前后清空模型配置（整轮共用一份临时库）。"""
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


def _upload_pages(app_client, sid: str, *, count: int = 1, title: str = "图片教材"):
    files = [("files", (f"page{i}.png", PNG_1PX, "image/png")) for i in range(1, count + 1)]
    return app_client.post(f"/api/subjects/{sid}/materials/upload-pages",
                           data={"title": title}, files=files)


# ============================================================ A1-① 未配读图模型 → 中文拒绝

def test_r56_3_a1_no_vision_model_is_refused_in_chinese_without_saving(app_client, sids,
                                                                       monkeypatch):
    """没配能读图的模型 → 选这条路被**中文明确拒绝**，且**没有任何东西落库**。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r56-vision")
    sid = make_subject(app_client, sids)
    # 快档模型设成 DeepSeek 的深档（不支持读图）→ 前置校验不过
    app_client.put("/api/settings/model", json={"light": "deepseek-v4-pro"})

    entry = app_client.get(f"/api/subjects/{sid}/mode").json()
    assert entry["vision_ready"] is False, entry
    assert "读图片" in entry["vision_note_zh"] and "deepseek-flash" in entry["vision_note_zh"], \
        entry["vision_note_zh"]    # 诚实边界四条也在入口处给出（导入前就能看到代价）
    assert len(entry["entry_zh"]["costs_zh"]) == 3
    assert "没有独立的第二次核对" in entry["entry_zh"]["costs_zh"][0]
    assert "不比文字教材模式更可靠" in entry["entry_zh"]["not_better_zh"]

    r = _upload_pages(app_client, sid)
    assert r.status_code == 422, r.text
    assert "需要能读图片的模型" in r.text and "设置" in r.text, r.text
    # 不落库：材料列表为空
    assert materials(app_client, sid) == [], "被拒绝的导入不许留下任何材料"

    # 配成能读图的（deepseek-flash 这一档）→ 入口就绪
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    assert app_client.get(f"/api/subjects/{sid}/mode").json()["vision_ready"] is True


# ============================================================ A1-② 配了 → 可上传、落库、标记模式

def test_r56_3_a1_with_vision_model_pages_are_saved_and_marked(app_client, sids, monkeypatch):
    """配了能读图的模型 → 页面图片可导入、材料**标记为全 AI 模式**、读不到的页如实标注。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r56-vision")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    sid = make_subject(app_client, sids)

    fake = _FakeVision()
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)

    r = _upload_pages(app_client, sid, count=2, title="行星科学（扫描页）")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "all_ai" and body["page_count"] == 2
    assert fake.calls.count("read_page") == 2, "每一页都要真的读一次"
    assert body["boundary"]["label"] == "图片为主的教材（全程交给 AI 判断）"

    listed = materials(app_client, sid)
    assert len(listed) == 1, listed
    m0 = listed[0]
    assert m0["mode"] == "all_ai" and m0["page_count"] == 2, m0
    assert "图片为主的教材" in m0["mode_zh"]
    # 学科整体模式也标记成图示教材（界面据此一直显示"当前是哪个模式"）
    view = app_client.get(f"/api/subjects/{sid}/materials").json()
    assert view["mode"] == "all_ai" and "图片为主" in view["mode_label_zh"]

    # 页面记录留档（出题/判题按页取依据）+ 账本有中文说明
    from app.outline import mode_pages

    pages = mode_pages.load_pages(sid, m0["id"])
    assert len(pages) == 2 and pages[0]["page_label"] == "第 1 页"
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    kinds = {(x.get("detail") or {}).get("kind") for x in rows}
    assert "all_ai_pages_imported" in kinds, kinds
    reason = "；".join(x["reason"] for x in rows)
    assert "没有独立的第二次核对" in reason and "更贵" in reason, reason


def test_r56_3_a1_unreadable_page_is_kept_and_marked(app_client, sids, monkeypatch):
    """读不出来的页**照样入库但如实标注**（正文 + 账本），不许当成"这一页没内容"。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r56-vision")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    sid = make_subject(app_client, sids)
    fake = _FakeVision(page={"page_label": "第 1 页", "readable": False,
                             "unreadable_reason": "整页是模糊扫描图，字太小",
                             "key_points": [], "figures": [], "confidence": 0.1})
    import app.outline.mode_pages as mp

    monkeypatch.setattr(mp, "_build_provider", lambda db: fake)
    r = _upload_pages(app_client, sid)
    assert r.status_code == 201, r.text
    assert r.json()["unreadable"] == ["第 1 页"]
    body = app_client.get(f"/api/subjects/{sid}/materials").json()["materials"][0]

    from app.outline import materials as mat
    from app.outline.materials import _parse_entry, materials_dir

    text = ""
    for p in materials_dir(sid).glob("*.md"):
        e = _parse_entry(p)
        if e and e["id"] == body["id"]:
            text = e["body"]
    assert "这一页读不出来" in text and "字太小" in text, text
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    assert any((x.get("detail") or {}).get("kind") == "pages_unreadable" for x in rows), rows
    assert mat.subject_mode(None, sid) == "all_ai"


# ============================================================ A1-③ 模式隔离

def test_r56_3_a1_mode_judging_does_not_touch_book_path_machinery(app_client, sids, monkeypatch):
    """**模式隔离**：本模式的判题走 `mode_ai.judge`，**不调用** sympy 判题与可答性闸门。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r56-vision")
    app_client.put("/api/settings/model", json={"light": "deepseek-flash"})
    sid = make_subject(app_client, sids)

    called: list[str] = []

    def _boom(*a, **kw):        # pragma: no cover - 只要被调用就失败
        called.append("called")
        raise AssertionError("图示教材模式不许走这条路")

    import app.domain.judge as judge_mod
    from app.content import answerability

    monkeypatch.setattr(judge_mod, "judge", _boom)
    monkeypatch.setattr(answerability, "gate_node", _boom)
    monkeypatch.setattr(answerability, "clean_facts", _boom)

    # 1) 判题：模型给"对" → 状态 correct；模型说"判不了" → 诚实出口
    fake = _FakeVision()
    out = mode_ai.judge(fake, mode_ai.ModeJudgeIn(prompt="太阳系有几颗行星？", kind="short",
                                                 reference_answer="八颗", student_answer="八颗"),
                        subject_id=sid, unit_id=f"{sid}.u01",
                        pages=[{"page_label": "第 1 页", "key_points": ["太阳系由太阳和八颗行星组成"]}])
    assert out["status"] == "correct" and not called, called

    fake2 = _FakeVision(judge={"verdict": "uncertain", "uncertain_reason": "页面记录读不出来",
                               "feedback_md": "这次我读不到依据。", "better_md": "",
                               "basis_pages": []})
    out2 = mode_ai.judge(fake2, mode_ai.ModeJudgeIn(prompt="图上第 4 根柱子是多少？",
                                                   student_answer="300"),
                         subject_id=sid, unit_id=f"{sid}.u01")
    assert out2["status"] == "uncertain" and out2["counted"] is False and not called, called
    # 账本里能看到"没判出来"（中文）
    rows = app_client.get(f"/api/ledger?subject_id={sid}").json()["entries"]
    assert any((x.get("detail") or {}).get("kind") == "judge_uncertain" for x in rows), rows
    # 判题用的提示词调用点必须是本模式那一条
    assert "mode_judge" in fake.calls and "mode_judge" in fake2.calls


# ============================================================ A1-④ 路径②回归

def test_r56_3_a1_text_path_is_untouched(app_client, sids):
    """**回归**：文字教材路径照旧——文本材料可上传、模式为空、页面入口提示也如实。"""
    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, "【第 1 页】\n行星是围绕恒星运行的天体。\n" * 3,
                              title="文字教材")
    view = app_client.get(f"/api/subjects/{sid}/materials").json()
    assert view["mode"] == "" and view["mode_label_zh"] == ""
    assert view["materials"][0]["mode"] == "" and view["materials"][0]["mode_zh"] == ""
    assert view["materials"][0]["id"] == up["id"]
    # 入口接口照常可用（只是没配读图模型时 vision_ready 为假——不影响文字路径）
    entry = app_client.get(f"/api/subjects/{sid}/mode").json()
    assert entry["mode"] == "" and isinstance(entry["vision_ready"], bool)
    assert entry["entry_zh"]["need_images_zh"]
