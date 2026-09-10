"""R39 回归用例：**「一切显性」铁则** + **提示词可改可恢复** + **AI 对话审计**（全离线）。

覆盖（逐条对应 docs/09 R39 §5 验收）：
- **铁则 ≥5 类造错**（每类：账本有中文原因 + 界面/接口可见）：
  ① 材料吸纳（材料被挡下/未纳入）② 生成与校验（题/事实句被丢弃）③ 生成失败降级（AI 失败 → 启发式）
  ④ 模型调用（日限额拦截）⑤ 覆盖（单元未出稿/教材未覆盖）；另附：提示词改动、审计失败与清理；
- **提示词**：改一条 → **生成确实用了新版**（审计全文可对照）；单条/全部恢复默认可用；
  删掉必填占位符/硬约束 → **中文拒存**；模板语法错（裸花括号）→ 中文拒存；
- **审计**：每次调用一条（真 provider 路径，httpx MockTransport）；prompt 与 response **都能完整展开**；
  **无 API Key 泄漏**；失败/丢弃在列表**置顶**；**非流式**（一次返回完整 JSON）。
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

MAT_TITLE = "行星科学（伪教材）"
MAT_BODY = (
    "【第 1 页】\n第1章 恒星\n"
    "恒星是靠内部核聚变发光发热的球状天体，太阳就是一颗恒星。\n"
    "恒星内部的氢在高温高压下聚变为氦，并释放出巨大的能量。\n"
    "我们看到的星光就是这些能量穿过太空到达地球的结果。\n\n"
    "【第 2 页】\n第2章 行星\n"
    "行星自身不发光，沿着近似椭圆的轨道围绕恒星运行。\n"
    "行星的质量远小于恒星，因此它不能像恒星那样点燃核心的核聚变。\n"
    "行星靠反射恒星的光而被我们看见，这也是它看起来明亮的原因。\n"
)
FACT1 = "恒星是靠内部核聚变发光发热的球状天体"
FACT2 = "行星自身不发光，沿着近似椭圆的轨道围绕恒星运行"


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider（记录 audit 参数，便于断言"哪次生成用的哪版提示词"）。"""

    def __init__(self, responses: list[dict | Exception]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.audits: list[dict] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))
        self.audits.append(dict(kw.get("audit") or {}))
        if not self.responses:
            raise AssertionError("假 provider 收到了超出预设次数的调用")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return _Outcome(resp)

    @property
    def system_text(self) -> str:
        return "\n".join(m[0]["content"] for m in self.calls)

    @property
    def user_text(self) -> str:
        return "\n".join(m[-1]["content"] for m in self.calls)


@pytest.fixture
def ai_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r39")

    def _install(responses: list[dict | Exception]) -> _FakeProvider:
        p = _FakeProvider(responses)
        import app.ai.provider as prov

        monkeypatch.setattr(prov, "OpenAICompatibleProvider", lambda **kw: p)
        return p

    return _install


def _mock_transport(payload: dict | str, *, status: int = 200):
    """httpx MockTransport：真 provider 路径（会走审计写入）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return httpx.Response(
            status,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22},
            },
        )

    return httpx.MockTransport(handler)


def _sid(prefix: str = "r39") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label: str = "R39 铁则学科") -> str:
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _add_material(app_client, sid: str, *, title: str = MAT_TITLE, text: str = MAT_BODY) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                        json={"title": title, "text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _unit(sid: str, n: int, *, section: str, title: str, prereq: str | None = None) -> dict:
    return {
        "id": f"{sid}.u{n:02d}", "title": title, "group": "教材", "objectives": [f"掌握{title}"],
        "concept_tags": [title], "difficulty": 1,
        "prereqs": [prereq] if prereq else [],
        "materials": [{"title": MAT_TITLE, "section": section}],
    }


def _seed_outline(app_client, sid: str) -> None:
    r = app_client.put(f"/api/subjects/{sid}/outline", json={
        "units": [_unit(sid, 1, section="第1章 恒星", title="恒星"),
                  _unit(sid, 2, section="第2章 行星", title="行星", prereq=f"{sid}.u01")],
        "status": "active", "source": "manual",
    })
    assert r.status_code == 200, r.text


def _ledger(app_client, sid: str = "", category: str = "") -> list[dict]:
    q = "?" + "&".join(x for x in (f"subject_id={sid}" if sid else "",
                                   f"category={category}" if category else "") if x)
    r = app_client.get(f"/api/ledger{q}")
    assert r.status_code == 200, r.text
    return r.json()["entries"]


# ===========================================================================
# 一、铁则：≥5 类"静默路径"都要有账本写入 + 中文原因
# ===========================================================================

def test_r39_ironclad_1_material_not_absorbed_is_in_ledger(app_client, ai_provider):
    """① 材料吸纳：扫描版材料**整份未纳入** → 账本有中文原因（不是只在 prompt 尾部提一句）。"""
    # 有教材 ⇒ 必须有可用模型（R40 §2-1：有教材 + 无模型 → 拒绝出稿）
    ai_provider([{"units": [{"title": "第1章 恒星", "objectives": ["掌握"],
                            "concept_tags": ["恒星"], "group": "教材", "prereqs": [],
                            "difficulty": 1,
                            "materials": [{"title": MAT_TITLE, "section": "第1章 恒星"}]}]}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_TITLE, text=MAT_BODY)
        app_client.post(f"/api/subjects/{sid}/materials/upload",
                        json={"title": "扫描版", "text": "".join(f"【第 {i} 页】\n\n\n" for i in range(1, 31))})
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 3})
        assert r.status_code == 200
        entries = r.json().get("ledger") or []
        hits = [e for e in entries if e["category"] == "material"]
        assert hits, "材料未纳入必须在就近账目里可见"
        assert any("未被注入" in e["reason"] and "健康度" in e["reason"] for e in hits), hits
        assert all(e["category_label"] == "材料吸纳" for e in hits)
        # 总账页通道同样能看见
        assert _ledger(app_client, sid, "material"), "总账页必须能筛到材料吸纳类别"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_ironclad_2_dropped_exercise_is_in_ledger(app_client, ai_provider):
    """② 生成与校验：**题被校验丢弃** → 账本（中文原因）+ 覆盖状态如实记"部分"。"""
    ai_provider([
        {
            "lecture": FACT1 + "。" + FACT2 + "。",
            "taught_facts": [{"id": "f1", "text": FACT1}, {"id": "f2", "text": FACT2}],
            "derivable": [], "worked_examples": [{"prompt": "例", "solution_steps": ["步"]}],
            "asks": [{"ask": "恒星靠什么发光？", "basis": {"fact_ids": ["f1"], "quote": FACT1}}],
            "feynman_task": "用自己的话讲讲恒星与行星。",
            "exercises": [
                {"kind": "boolean", "prompt": f"判断：{FACT1}。", "answer_bool": True,
                 "basis": {"fact_ids": ["f1"], "quote": FACT1}},
                {"kind": "boolean", "prompt": "判断：行星会发光。", "answer_bool": False,
                 "basis": {"fact_ids": ["f9"], "quote": "这句话只在我的讲解里，不在教材里。"}},
                {"kind": "fill", "prompt": "填空：行星沿着什么轨道运行？", "expected": "椭圆",
                 "basis": {"fact_ids": ["f2"], "quote": FACT2}},
                {"kind": "boolean", "prompt": "判断：行星围绕恒星运行。", "answer_bool": True,
                 "basis": {"fact_ids": ["f2"], "quote": FACT2}},
            ],
        },
    ])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        _seed_outline(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] in ("created", "uncovered"), body
        entries = body.get("ledger") or []
        gen = [e for e in entries if e["category"] == "generation"]
        assert gen, "题/事实句被丢弃必须在就近账目里可见"
        assert any("丢弃" in e["reason"] for e in gen), gen
        assert any(e["remedy"] for e in gen), "账本必须写明可否补救"
        if body["status"] == "created":
            assert body["coverage"]["status"] == "部分"
        assert _ledger(app_client, sid, "generation")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_ironclad_3_ai_failure_degrade_is_in_ledger(app_client, ai_provider, monkeypatch):
    """③ 生成失败降级：AI 起草整体失败 → **降级启发式**必须显性（不许静默换内容来源）。"""
    ai_provider([RuntimeError("上游 502 Bad Gateway")])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "heuristic"
        entries = body.get("ledger") or []
        hits = [e for e in entries if e["category"] == "model_call"]
        assert hits and any("降级" in e["reason"] and "启发式" in e["reason"] for e in hits), entries
        assert any("502" in json.dumps(e.get("detail") or {}, ensure_ascii=False) for e in hits)
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_ironclad_4_daily_token_cap_blocked_is_in_ledger(app_client, monkeypatch):
    """④ 模型调用：**日限额拦截** → 账本（中文原因）+ 审计各一条（绝不静默不调用模型）。"""
    monkeypatch.setenv("LLM_MAX_TOKENS_PER_DAY", "10")
    sid = _mk_subject(app_client)
    try:
        from app import models
        from app.ai.calls import CALL_CLASSIFY_ERROR, ClassifyErrorIn
        from app.ai.gateway import OpenAICompatibleGateway
        from app.ai.provider import OpenAICompatibleProvider
        from app.db import SessionLocal

        # 先造"今天已用满"的事实（否则拦截条件不成立）
        with SessionLocal() as db:
            db.add(models.AiLog(call_name="seed", model="m", tier="light", prompt_tokens=9,
                                completion_tokens=9, ok=True, outcome="adopted"))
            db.commit()

        p = OpenAICompatibleProvider(api_key="sk-x", base_url="http://127.0.0.1:1/v1",
                                     model_heavy="m", model_light="m",
                                     transport=_mock_transport({"error_type": "unknown"}))
        assert p.tokens_used_today() >= 10, "前置：今日已用应超过上限"
        gw = OpenAICompatibleGateway(p)
        with pytest.raises(Exception) as ei:
            gw.classify_error(ClassifyErrorIn(node_id=f"{sid}.u01", prompt="题",
                                              correct_solution="答", user_answer="错"))
        assert "额度" in str(ei.value)
        entries = _ledger(app_client, sid, "model_call")
        assert entries, "日限额拦截必须进账本"
        assert any("额度已用尽" in e["reason"] for e in entries), entries
        tr = app_client.get(f"/api/ai-traces?subject_id={sid}").json()
        assert tr["total"] >= 1
        assert any(t["outcome"] == "failed" for t in tr["items"])
        assert CALL_CLASSIFY_ERROR.name == "classify_error"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_ironclad_5_uncovered_unit_is_in_ledger(app_client, ai_provider):
    """⑤ 覆盖：教材未覆盖/无字面接地 → 整单元未出稿 → 账本 + 覆盖账"未覆盖"（双向可见）。"""
    ai_provider([
        {
            "lecture": "这是一段与教材无关的自撰讲解。",
            "taught_facts": [{"id": "f1", "text": "这句话教材里根本没有，纯属编造。"}],
            "derivable": [], "worked_examples": [{"prompt": "例", "solution_steps": ["步"]}],
            "asks": [],
            "feynman_task": "讲讲。",
            "exercises": [{"kind": "boolean", "prompt": "编造题", "answer_bool": True,
                           "basis": {"fact_ids": ["f1"], "quote": "这句话教材里根本没有，纯属编造。"}}],
        },
        {
            "lecture": "还是一段与教材无关的自撰讲解。",
            "taught_facts": [{"id": "f1", "text": "依然编造的事实句。"}],
            "derivable": [], "worked_examples": [{"prompt": "例", "solution_steps": ["步"]}],
            "asks": [],
            "feynman_task": "讲讲。",
            "exercises": [{"kind": "boolean", "prompt": "编造题", "answer_bool": True,
                           "basis": {"fact_ids": ["f1"], "quote": "依然编造的事实句。"}}],
        },
    ])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        _seed_outline(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "uncovered", body
        assert "教材未覆盖此单元" in body["note"]
        entries = body.get("ledger") or []
        assert any(e["category"] == "coverage" for e in entries), entries
        assert any("未覆盖" in e["reason"] for e in entries)
        cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
        u01 = next(u for u in cov["units"] if u["unit_id"] == f"{sid}.u01")
        assert u01["status"] == "未覆盖"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_ironclad_6_prompt_change_and_audit_cleanup_are_logged(app_client):
    """附：**提示词改动**与**审计清理**也走同一账本（铁则范围不限于材料）。"""
    r = app_client.put("/api/prompts/classify_error", json={
        "system": "你是学习系统的错因分类器。\n"
                  '[输出纪律] 只输出 JSON：{{"error_type": "<枚举>"}}。\n'
                  "枚举：arithmetic_slip | sign_error | concept_confusion | step_omission | "
                  "procedure_misuse | notation_error | unknown（无法归类时用 unknown）。\n"
                  "（R39 测试：额外一句叮嘱，保持全部硬约束不变）"
    })
    try:
        assert r.status_code == 200, r.text
        allc = _ledger(app_client, "", "other")
        assert any("提示词" in e["object"] and "修改" in e["reason"] for e in allc), allc[:3]
        c = app_client.post("/api/ai-traces/cleanup", json={"keep_days": 3650})
        assert c.status_code == 200
        allc2 = _ledger(app_client, "", "other")
        assert any("审计文件" in e["object"] for e in allc2) or c.json()["count"] == 0
    finally:
        app_client.post("/api/prompts/reset-all")


def test_r39_audit_write_failure_is_logged(app_client, monkeypatch):
    """附：**审计写入失败**必须记账（不许静默丢证据）。"""
    from app.service import ai_trace

    def boom(*a, **kw):
        raise OSError("模拟磁盘写入失败")

    monkeypatch.setattr(ai_trace, "_write_file", boom)
    res = ai_trace.write_trace(call_name="explain_node", system="s", user="u", raw="{}",
                               parsed={}, prompt_versions="default:explain_node")
    assert res["wrote_file"] is False
    entries = _ledger(app_client, "", "other")
    assert any("审计全文写入失败" in e["reason"] for e in entries), entries[:3]


def test_r39_ledger_total_page_filters(app_client):
    """总账页：一处看全部 + 可按学科/类别筛；类别非法 → 中文提示（不 500）。"""
    sid = _mk_subject(app_client)
    try:
        r = app_client.get(f"/api/ledger?subject_id={sid}")
        assert r.status_code == 200
        body = r.json()
        assert {c["key"] for c in body["categories"]} == {
            "material", "generation", "model_call", "coverage", "other"}
        assert all("label" in c for c in body["categories"])
        assert "counts" in body
        bad = app_client.get("/api/ledger?category=不存在").json()
        assert bad["count"] == 0 and "非法" in bad["note"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ===========================================================================
# 二、提示词：改一条 → 生成确实用了新版；恢复默认；必填缺失 → 中文拒存
# ===========================================================================

def test_r39_prompt_edit_takes_effect_and_is_visible_in_audit(app_client, monkeypatch):
    """改一条提示词 → **生成确实用了新版**，且审计全文能对照（真 provider + MockTransport）。"""
    marker = "R39-自定义标记-请只输出 JSON"
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r39")   # 有 key 才走 AI 路径（否则离线启发式）
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        base = app_client.get("/api/prompts/outline_draft").json()
        assert base["is_default"] is True and base["system_is_default"] is True
        assert base["required_placeholders"], "必须声明必填占位符（删掉要拒存）"
        edited = base["default_raw_template"] + "\n" + marker
        r = app_client.put("/api/prompts/outline_draft", json={"system": edited})
        assert r.status_code == 200, r.text
        after = app_client.get("/api/prompts/outline_draft").json()
        assert after["is_default"] is False and after["system_diff"], "必须给出与默认的差异"
        assert after["updated_at"], "必须显示上次修改时间"

        from app.ai.provider import OpenAICompatibleProvider

        payload = {"units": [{"title": "第1章 恒星", "objectives": ["掌握"],
                              "concept_tags": ["恒星"], "group": "教材",
                              "prereqs": [], "difficulty": 1,
                              "materials": [{"title": MAT_TITLE, "section": "第1章 恒星"}]}]}
        import app.ai.provider as prov

        orig = prov.OpenAICompatibleProvider

        def _factory(**kw):
            return orig(**{**kw, "transport": _mock_transport(payload)})

        prov.OpenAICompatibleProvider = _factory
        try:
            d = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        finally:
            prov.OpenAICompatibleProvider = orig
        assert d.status_code == 200, d.text

        traces = app_client.get("/api/ai-traces?call_name=outline_draft").json()
        if not traces["items"]:
            allt = app_client.get("/api/ai-traces?limit=20").json()
            raise AssertionError(
                "每次调用必须有一条审计；实际记录：" + repr([(t["call_name"], t["subject_id"], t["outcome"])
                                                     for t in allt["items"]])
                + f"；draft={d.status_code} body={d.text[:300]}")
        hit = traces["items"][0]
        assert "custom:outline_draft@" in hit["prompt_versions"], hit["prompt_versions"]
        detail = app_client.get(f"/api/ai-traces/{hit['id']}").json()
        assert marker in detail["full"]["system"], "生成必须使用改后的提示词（审计全文可对照）"
        assert detail["full"]["user"], "审计里能完整展开 user"
        assert "第1章 恒星" in detail["full"]["user"]
        assert OpenAICompatibleProvider  # noqa: B018  说明：上面用真 provider 路径
    finally:
        app_client.post("/api/prompts/reset-all")
        app_client.delete(f"/api/subjects/{sid}?hard=true")


@pytest.mark.parametrize("drop", ["{material_discipline}", "输出 JSON", "materials", "concept_tags"])
def test_r39_prompt_missing_required_is_rejected_zh(app_client, drop):
    """删掉**必填占位符/硬约束** → **中文报错并拒绝保存**（否则功能会静默失效）。"""
    base = app_client.get("/api/prompts/outline_draft").json()
    broken = base["default_raw_template"].replace(drop, "")
    assert broken != base["default_raw_template"]
    r = app_client.put("/api/prompts/outline_draft", json={"system": broken})
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["error"]["message"]
    assert "拒绝保存" in msg and "必须保留" in msg, msg
    assert app_client.get("/api/prompts/outline_draft").json()["is_default"] is True
    app_client.post("/api/prompts/reset-all")


def test_r39_prompt_bad_template_syntax_is_rejected_zh(app_client):
    """模板语法错（裸花括号，如 JSON 示例没转义）→ 中文拒存并教怎么写。"""
    base = app_client.get("/api/prompts/outline_draft").json()
    broken = base["default_raw_template"] + '\n输出示例：{"units":[]}'   # 裸花括号
    r = app_client.put("/api/prompts/outline_draft", json={"system": broken})
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["error"]["message"]
    assert "花括号" in msg and "双花括号" in msg, msg
    app_client.post("/api/prompts/reset-all")


def test_r39_prompt_reset_one_and_all(app_client):
    """单条恢复默认 + 全部恢复默认（都可用，且不被拒存规则挡住）。"""
    base = app_client.get("/api/prompts/explain_node").json()
    edited = base["default_raw_template"] + "\n（测试追加一行）"
    assert app_client.put("/api/prompts/explain_node", json={"system": edited}).status_code == 200
    assert app_client.get("/api/prompts/explain_node").json()["is_default"] is False

    r1 = app_client.post("/api/prompts/explain_node/reset", json={})
    assert r1.status_code == 200 and r1.json()["is_default"] is True

    app_client.put("/api/prompts/explain_node", json={"system": edited})
    hb = app_client.get("/api/prompts/hint_on_error").json()
    app_client.put("/api/prompts/hint_on_error", json={"system": hb["default_raw_template"] + "\n（x）"})
    r2 = app_client.post("/api/prompts/reset-all")
    assert r2.status_code == 200 and r2.json()["count"] >= 2
    lst = app_client.get("/api/prompts").json()
    assert lst["changed"] == [], "全部恢复默认后不应还有自定义"
    bad = app_client.put("/api/prompts/not_a_call", json={"system": "x"})
    assert bad.status_code == 422 and "未收录" in bad.json()["detail"]["error"]["message"]


def test_r39_all_call_sites_are_editable(app_client):
    """**所有**发往模型的提示词模板一处不漏：注册表 = ai.calls.CALLS，每个都可读可改。"""
    from app.ai.calls import CALLS

    r = app_client.get("/api/prompts")
    assert r.status_code == 200
    listed = {p["call_name"] for p in r.json()["prompts"]}
    assert listed == set(CALLS), f"注册表与调用点清单不一致：{listed ^ set(CALLS)}"
    for name in sorted(listed):
        one = app_client.get(f"/api/prompts/{name}")
        assert one.status_code == 200, name
        body = one.json()
        assert body["label"] and body["purpose"], name
        assert body["default_raw_template"].strip(), name
        assert body["default_system"].strip(), name


# ===========================================================================
# 三、AI 对话审计（提示词监听）
# ===========================================================================

def test_r39_audit_one_record_per_call_with_full_expand(app_client):
    """每次调用一条审计；prompt 与 response **都能完整展开**（真 provider 路径 + 读全文文件）。"""
    from app.ai.calls import AnswerQuestionIn, CALL_ANSWER_QUESTION
    from app.ai.gateway import OpenAICompatibleGateway
    from app.ai.provider import OpenAICompatibleProvider

    sid = _mk_subject(app_client)
    try:
        payload = {"reply_md": "恒星靠核聚变发光。", "needs_more_info": False, "out_of_scope": False}
        p = OpenAICompatibleProvider(api_key="sk-test-abc", base_url="http://mock.local/v1",
                                     model_heavy="mh", model_light="ml",
                                     transport=_mock_transport(payload))
        gw = OpenAICompatibleGateway(p)
        out = gw.answer_question(AnswerQuestionIn(
            session_id="s1", node_id=f"{sid}.u01", node_title="恒星", level="middle",
            explanation_body="恒星靠核聚变发光。", whitelist=["恒星"],
            student_question="恒星为什么发光？"), strategy="fast")
        assert out.reply_md

        lst = app_client.get(f"/api/ai-traces?subject_id={sid}&call_name=answer_question").json()
        assert lst["total"] == 1, "每次调用一条记录"
        one = lst["items"][0]
        assert one["ok"] is True and one["outcome"] == "adopted"
        assert one["prompt_tokens"] == 11 and one["completion_tokens"] == 22
        assert one["trace_path"] and one["trace_chars"] > 0
        d = app_client.get(f"/api/ai-traces/{one['id']}").json()
        assert "恒星靠核聚变发光。" in d["full"]["system"], "讲解稿在 system（教学内容真源）"
        assert "恒星为什么发光？" in d["full"]["user"]
        assert CALL_ANSWER_QUESTION.name == "answer_question"
        assert json.loads(d["full"]["response"])["reply_md"].startswith("恒星靠核聚变")
        assert d["file_exists"] is True
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_audit_failed_call_records_retries_and_ranking(app_client):
    """失败调用：**重试次数**与失败结局入审计；列表**失败置顶**；接口**非流式**。"""
    from app.ai.calls import CALL_CLASSIFY_ERROR, ClassifyErrorIn
    from app.ai.gateway import OpenAICompatibleGateway
    from app.ai.provider import OpenAICompatibleProvider

    sid = _mk_subject(app_client)
    try:
        # 永远返回非法 JSON → provider 重试耗尽 → AiCallError（审计一条，retries=2）
        p = OpenAICompatibleProvider(api_key="sk-test-abc", base_url="http://mock.local/v1",
                                     model_heavy="mh", model_light="ml",
                                     transport=_mock_transport("这不是 JSON"))
        gw = OpenAICompatibleGateway(p)
        with pytest.raises(Exception):
            gw.classify_error(ClassifyErrorIn(node_id=f"{sid}.u01", prompt="1+1=?",
                                              correct_solution="2", user_answer="3"))
        lst = app_client.get(f"/api/ai-traces?subject_id={sid}").json()
        assert lst["total"] == 1
        fail = lst["items"][0]
        assert fail["ok"] is False and fail["outcome"] == "failed"
        assert fail["retries"] == 2 and fail["is_failure"] is True
        assert fail["error"]
        # 再写一条成功记录（另一个学科）→ 失败项仍置顶
        p2 = OpenAICompatibleProvider(api_key="sk-test-abc", base_url="http://mock.local/v1",
                                      model_heavy="mh", model_light="ml",
                                      transport=_mock_transport({"error_type": "unknown"}))
        OpenAICompatibleGateway(p2).classify_error(ClassifyErrorIn(
            node_id=f"{sid}.u02", prompt="x", correct_solution="y", user_answer="z"))
        allx = app_client.get("/api/ai-traces?limit=5").json()
        assert allx["items"][0]["is_failure"] is True, "失败项必须置顶"
        only = app_client.get("/api/ai-traces?only_failed=true").json()
        assert all(t["is_failure"] for t in only["items"])
        r = app_client.get("/api/ai-traces?limit=1")
        assert "text/event-stream" not in r.headers.get("content-type", "")
        assert "application/json" in r.headers.get("content-type", "")
        assert CALL_CLASSIFY_ERROR.name == "classify_error"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_audit_no_api_key_leak(app_client):
    """红线：审计全文**不得**出现 API Key（写文件前遮蔽）。"""
    from pathlib import Path

    from app.config import REPO_ROOT
    from app.ai.calls import AnswerQuestionIn
    from app.ai.gateway import OpenAICompatibleGateway
    from app.ai.provider import OpenAICompatibleProvider
    from app.service.ai_trace import redact

    assert "sk-" not in redact("Authorization: Bearer sk-abcdef1234567890")
    sid = _mk_subject(app_client)
    try:
        # 模型"返回"里夹带密钥（模拟上游回显）→ 审计文件必须已遮蔽
        p = OpenAICompatibleProvider(api_key="sk-REALSECRET123456", base_url="http://mock.local/v1",
                                     model_heavy="mh", model_light="ml",
                                     transport=_mock_transport(
                                         '{"reply_md":"key=sk-LEAKED9999999999"}'))
        OpenAICompatibleGateway(p).answer_question(AnswerQuestionIn(
            session_id="s", node_id=f"{sid}.u01", node_title="t", level="middle",
            explanation_body="e", whitelist=[], student_question="q"))
        lst = app_client.get(f"/api/ai-traces?subject_id={sid}").json()
        path = Path(lst["items"][0]["trace_path"])
        path = path if path.is_absolute() else REPO_ROOT / path
        text = path.read_text(encoding="utf-8")
        assert "sk-LEAKED9999999999" not in text and "sk-REALSECRET" not in text
        assert "[已隐去]" in text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r39_audit_long_prompt_is_served_whole_but_ui_caps_render(app_client):
    """>10 万字的 prompt：**接口给全文**（可完整展开），前端按折叠 + 渲染上限处理（不卡界面）。"""
    from app.service import ai_trace

    big = "长" * 120000
    res = ai_trace.write_trace(call_name="unit_content_draft", system=big, user="u",
                               raw='{"lecture":"x"}', parsed={"lecture": "x"},
                               prompt_versions="default:unit_content_draft")
    assert res["trace_chars"] > 120000
    lst = app_client.get("/api/ai-traces?call_name=unit_content_draft&limit=1").json()
    d = app_client.get(f"/api/ai-traces/{lst['items'][0]['id']}").json()
    assert len(d["full"]["system"]) == 120000, "接口必须能给出全文（界面负责折叠/截断渲染）"
    # 列表里只给预览（防库爆/防一次渲染几十万字）
    assert len(lst["items"][0]["system_preview"]) < 1000


def test_r39_audit_missing_file_is_reported_not_silent(app_client):
    """审计全文文件缺失（被清理/落盘失败）→ 如实说明 + 库内预览兜底（不静默失败）。"""
    from app import models
    from app.db import SessionLocal
    from app.service import ai_trace

    res = ai_trace.write_trace(call_name="explain_node", system="s", user="u", raw="{}",
                               parsed={}, prompt_versions="default:explain_node")
    with SessionLocal() as db:
        row = db.query(models.AiLog).order_by(models.AiLog.id.desc()).first()
        assert row is not None
        rid = row.id
    from pathlib import Path

    from app.config import REPO_ROOT

    p = Path(res["trace_path"])
    p = p if p.is_absolute() else REPO_ROOT / p
    p.unlink(missing_ok=True)
    d = app_client.get(f"/api/ai-traces/{rid}").json()
    assert d["file_exists"] is False
    assert "预览" in d["note"] or "读取失败" in d["note"], d["note"]
    assert app_client.get("/api/ai-traces/999999").status_code == 404
