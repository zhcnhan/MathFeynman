"""R36 任务 D（大纲起草读材料 D1–D5）＋任务 P（由易到难 P1–P4）回归用例。

全部**离线**：AI 路径用假 provider 注入（monkeypatch ``app.ai.provider.OpenAICompatibleProvider``），
不触真模型。覆盖：
- D1 注入：有材料 → prompt 含分节摘要；**无材料 → 退化为现状、不报错**（两情形都 200）；
- D2 逐单元溯源：真实章节名 / 逐字引文 → 保留；编造 → **驳回重生成一次**；仍不成立 → 剔除并记问题；
- D3 大纲层溯源：采纳时**服务端**反查 source_materials；引用不存在的材料 → 中文 422；
- D4 预算：注入量受字符上限约束（截断留痕，不整本塞入）；
- P1 由易到难：难度倒置 → 候选 problems + PUT 校验 422（**造错必报**）；
- P2/P3/P4：写进起草 prompt（机器校验待 R35 的 taught_facts/derivable，见 NOTES §60）；
- 引文尺子单一来源：``content.citations`` 与 ``service.feynman_ledger``（R30 F5 口径）同源。
"""
from __future__ import annotations

import uuid

import pytest

MAT_TITLE = "天文学导论"
MAT_BODY = (
    "【第 1 页】\n"
    "天文学研究地球之外的一切天体。太阳是一颗恒星，它是太阳系唯一的恒星。\n\n"
    "【第 2 页】\n"
    "类木行星的体积远大于类地行星，其中木星的体积在八大行星里最大。\n"
)
PAGE2_QUOTE = "类木行星的体积远大于类地行星"


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider：按序吐出预设响应；记录每次调用的 messages（供 prompt 断言）。"""

    def __init__(self, responses: list[dict | Exception]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return _Outcome(resp)

    # 断言辅助
    @property
    def system_text(self) -> str:
        return self.calls[0][0]["content"]

    @property
    def user_text(self) -> str:
        return self.calls[0][-1]["content"]


@pytest.fixture
def ai_provider(monkeypatch):
    """开启"有 key"并替换 provider 工厂；返回 (provider, 装配函数)。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r36")
    holder: dict = {}

    def _install(responses: list[dict | Exception]) -> _FakeProvider:
        p = _FakeProvider(responses)
        holder["p"] = p
        import app.ai.provider as prov

        monkeypatch.setattr(prov, "OpenAICompatibleProvider", lambda **kw: p)
        return p

    return _install


def _sid(prefix: str = "r36") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label: str = "R36 走查学科") -> str:
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _add_material(app_client, sid: str, *, title: str = MAT_TITLE, text: str = MAT_BODY) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                        json={"title": title, "text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _units(n: int = 3, *, sid: str | None = None, materials_for=None) -> list[dict]:
    """合法的起草候选单元（难度非降：1,2,2,3…；线性前置）。

    ``sid=None`` → 前置用**起草本地编号**（``u01``，起草收尾时映射为 <sid>.uNN）；
    给了 sid → 直接用完整单元 id 与完整前置 id（PUT 采纳路径需要）。
    """
    out = []
    for i in range(1, n + 1):
        uid = f"{sid}.u{i:02d}" if sid else f"u{i:02d}"
        prev = (f"{sid}.u{i - 1:02d}" if sid else f"u{i - 1:02d}") if i > 1 else None
        u = {
            "id": uid,
            "title": f"第 {i} 单元",
            "objectives": [f"掌握第 {i} 单元要点"],
            "concept_tags": [f"概念{i}"],
            "group": "主线",
            "prereqs": [prev] if prev else [],
            "difficulty": min(3, 1 + (i - 1) // 2),
        }
        if materials_for is not None:
            u["materials"] = materials_for(i)
        out.append(u)
    return out


# ---------- D1：注入与退化 ----------

def test_d1_draft_without_materials_degrades_but_succeeds(app_client, ai_provider):
    """无材料 → 不报错，退化为仅按 brief 起草（D1）；material_usage 计数为 0。"""
    p = ai_provider([{"units": _units(3)}])
    sid = _mk_subject(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/outline/draft",
                            json={"brief": "零基础天文学", "count": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True, body["problems"]
        assert len(body["units"]) == 3
        assert body["material_usage"]["count"] == 0
        assert body["source_materials"] == []
        assert all(u["materials"] == [] for u in body["units"])
        assert p.calls, "AI 路径应被调用"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_d1_draft_injects_material_sections_into_prompt(app_client, ai_provider):
    """有材料 → prompt 里出现材料标题与分节内容（D1 注入证据）。"""
    p = ai_provider([{"units": _units(2)}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["material_usage"]["count"] == 1
        assert MAT_TITLE in p.system_text + p.user_text
        assert "【第 1 页】" in p.user_text or "第 1 页" in p.user_text
        assert "第 2 页" in p.user_text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- D2：逐单元溯源 ----------

def test_d2_valid_section_and_verbatim_quote_are_kept(app_client, ai_provider):
    """真实章节名（第 N 页）与逐字引文（≥6 字）都算合法溯源，写回单元。"""
    def mats(i: int):
        if i == 1:
            return [{"title": MAT_TITLE, "section": "第 1 页"}]
        return [{"title": MAT_TITLE, "section": PAGE2_QUOTE}]

    ai_provider([{"units": _units(2, materials_for=mats)}])
    sid = _mk_subject(app_client)
    try:
        mid = _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["problems"] == [], body["problems"]
        assert body["ok"] is True
        assert body["units"][0]["materials"] == [{"title": MAT_TITLE, "section": "第 1 页"}]
        assert body["units"][1]["materials"] == [{"title": MAT_TITLE, "section": PAGE2_QUOTE}]
        assert body["source_materials"] == [mid]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_d2_bogus_citation_rejected_then_regenerated(app_client, ai_provider):
    """编造的溯源 → 驳回并**重生成一次**（错误回灌），二轮合法则通过。"""
    bad = lambda i: [{"title": "不存在的书", "section": "第 1 页"}]  # noqa: E731
    good = lambda i: [{"title": MAT_TITLE, "section": "第 1 页"}]   # noqa: E731
    p = ai_provider([{"units": _units(1, materials_for=bad)},
                     {"units": _units(1, materials_for=good)}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(p.calls) == 2, "首次引用不成立应触发一次重生成"
        assert "引用库" in p.calls[1][-1]["content"], "重生成应回灌中文校验原因"
        assert body["units"][0]["materials"] == [{"title": MAT_TITLE, "section": "第 1 页"}]
        assert any("驳回重生成" in x for x in body["problems"])
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_d2_citation_stripped_when_regeneration_also_fails(app_client, ai_provider):
    """两轮都不成立 → 剔除该引用 + 记问题（不硬塞伪溯源；接口仍 200 不炸）。

    R37 S2 扩展（2026-09-10）：教材＝真源后，**章节不得因溯源不成立而悄悄消失**——
    被剔除引用的单元保持"无溯源"（宁缺勿造的口径不变），同时该章由**教材目录**补齐一个单元并记问题。
    """
    bad = lambda i: [{"title": MAT_TITLE, "section": "这句话不在材料正文里出现过的引文"}]  # noqa: E731
    p = ai_provider([{"units": _units(1, materials_for=bad)},
                     {"units": _units(1, materials_for=bad)}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(p.calls) == 2
        stripped = [u for u in body["units"] if u["title"] == "第 1 单元"]
        assert stripped and stripped[0]["materials"] == [], "不得硬塞伪溯源"
        assert any("溯源不成立" in x for x in body["problems"]), body["problems"]
        assert any("教材目录" in x for x in body["problems"]), body["problems"]
        assert body["ok"] is False  # 有问题必须如实上报（供 UI 提示）
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- D3：大纲层溯源 ----------

def test_d3_put_outline_records_source_materials_server_side(app_client):
    """采纳时服务端按 units[].materials[].title 反查 material_id（不信客户端自报）。"""
    sid = _mk_subject(app_client)
    try:
        mid = _add_material(app_client, sid)
        units = _units(2, sid=sid, materials_for=lambda i: [{"title": MAT_TITLE, "section": "第 1 页"}])
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": units, "status": "active", "source": "ai"})
        assert r.status_code == 200, r.text
        assert r.json()["source_materials"] == [mid]
        got = app_client.get(f"/api/subjects/{sid}/outline").json()
        assert got["source_materials"] == [mid]
        assert got["units"][0]["materials"][0]["title"] == MAT_TITLE
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_d3_put_outline_rejects_unknown_material_zh(app_client):
    """采纳时引用了不存在的材料 → 中文 422（提示去材料区导入）。"""
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        units = _units(1, sid=sid, materials_for=lambda i: [{"title": "没有这本书", "section": "第 1 页"}])
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": units, "status": "active", "source": "ai"})
        assert r.status_code == 422, r.text
        msg = r.json()["detail"]["error"]["message"]
        assert "引用库" in msg and "材料" in msg
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- D4：注入预算 ----------

def test_d4_injection_respects_char_budget(app_client, ai_provider, monkeypatch):
    """整本材料不得整份塞入：总注入量受 MF_OUTLINE_MATERIAL_MAX_CHARS 约束并留截断痕迹。"""
    monkeypatch.setenv("MF_OUTLINE_MATERIAL_MAX_CHARS", "800")
    long_body = "".join(
        f"【第 {i} 页】\n这是第 {i} 页的正文内容，用于验证注入预算会截断超量材料。" + "填充" * 60 + "\n\n"
        for i in range(1, 21)
    )
    p = ai_provider([{"units": _units(1)}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title="大部头", text=long_body)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        assert r.status_code == 200, r.text
        usage = r.json()["material_usage"]
        assert usage["truncated"] is True
        assert usage["used_chars"] <= 800
        # prompt 里含开头几页、不含最后一页（未被塞满整本）
        assert "第 1 页" in p.user_text
        assert "第 20 页" not in p.user_text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_d4_material_over_budget_is_reported_dropped(app_client, ai_provider, monkeypatch):
    """极小预算时材料整体未注入 → dropped 留痕（不静默）。"""
    monkeypatch.setenv("MF_OUTLINE_MATERIAL_MAX_CHARS", "80")
    p = ai_provider([{"units": _units(1)}])
    sid = _mk_subject(app_client)
    try:
        # 首页正文极长 → 标题+首节都放不进 80 字预算
        _add_material(app_client, sid, text="【第 1 页】\n" + "很长的一段正文。" * 40)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        assert r.status_code == 200, r.text
        usage = r.json()["material_usage"]
        assert usage["dropped"] == [MAT_TITLE]
        assert usage["used_chars"] == 0
        assert "超出本次注入预算" in p.user_text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- P1：由易到难（造错必报） ----------

def _inverted_units(sid: str) -> list[dict]:
    """故意造错：u01 难度 3 → u02 难度 1（先修比后继难）。"""
    return [
        {"id": f"{sid}.u01", "title": "难的第一讲", "group": "主线",
         "objectives": ["目标"], "concept_tags": ["甲"], "difficulty": 3},
        {"id": f"{sid}.u02", "title": "简单的第二讲", "group": "主线",
         "objectives": ["目标"], "concept_tags": ["乙"], "prereqs": [f"{sid}.u01"], "difficulty": 1},
    ]


def test_p1_validate_reports_difficulty_inversion(app_client):
    """P1 造错必报：难度倒置 → /outline/validate 明确报「由易到难」。"""
    sid = _mk_subject(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/outline/validate",
                            json={"units": _inverted_units(sid), "status": "draft", "source": "ai"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert any("由易到难" in p for p in body["problems"]), body["problems"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_p1_put_outline_rejects_difficulty_inversion_zh(app_client):
    """P1：不够"由易到难"的大纲**不许采纳**（中文 422）。"""
    sid = _mk_subject(app_client)
    try:
        r = app_client.put(f"/api/subjects/{sid}/outline",
                           json={"units": _inverted_units(sid), "status": "active", "source": "ai"})
        assert r.status_code == 422, r.text
        assert "由易到难" in r.json()["detail"]["error"]["message"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_p1_monotonic_ok_and_roadmap_exempt(app_client):
    """非降难度 → 通过；roadmap 派生大纲（math preset）豁免该硬校验（数据治理项见 NOTES §60）。"""
    sid = _mk_subject(app_client)
    try:
        units = [
            {"id": f"{sid}.u01", "title": "第一讲", "group": "主线", "objectives": ["目标"],
             "concept_tags": ["甲"], "difficulty": 1},
            {"id": f"{sid}.u02", "title": "第二讲", "group": "主线", "objectives": ["目标"],
             "concept_tags": ["乙"], "prereqs": [f"{sid}.u01"], "difficulty": 2},
        ]
        r = app_client.post(f"/api/subjects/{sid}/outline/validate",
                            json={"units": units, "status": "draft", "source": "ai"})
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        # roadmap 源：同样倒置的数据不报（豁免口径）
        r = app_client.post(f"/api/subjects/{sid}/outline/validate",
                            json={"units": _inverted_units(sid), "status": "active", "source": "roadmap"})
        assert r.status_code == 200
        assert not any("由易到难" in p for p in r.json()["problems"])
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- P2/P3/P4：写进 prompt ----------

def test_p2_p3_p4_constraints_are_in_draft_prompt(app_client, ai_provider):
    """零基础起点 / 由易到难 / 难度只能靠已教事实累积 → 必须出现在起草 prompt 里。"""
    p = ai_provider([{"units": _units(2)}])
    sid = _mk_subject(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 2})
        assert r.status_code == 200
        sys_text = p.system_text
        assert "零基础" in sys_text          # P2
        assert "由易到难" in sys_text        # P1/P3
        assert "group" in sys_text           # P3：分组表达章/阶段层次
        assert "已讲" in sys_text or "已教" in sys_text  # P4（prompt 约束，机器校验待 R35）
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- 接线加固：AI 输出 schema 必须携带 materials ----------

def test_outline_draft_call_schema_carries_material_citations():
    """R36 D2 接线锁：``CALL_OUTLINE_DRAFT`` 的**输出 schema 必须声明 materials**。

    背景（活体冒烟 2026-09-10 实测踩到）：provider 用 ``model_validate`` 校验输出，
    pydantic 默认**丢弃未声明字段** —— schema 漏声明时"模型给了引用、服务端收到空数组"，
    溯源链路静默失效（假 provider 的单测**测不出**这一类接线缺口，故单独立锁）。
    """
    from app.ai.calls import CALL_OUTLINE_DRAFT

    parsed = CALL_OUTLINE_DRAFT.output_schema.model_validate({
        "units": [{"title": "第一讲", "difficulty": 1,
                   "materials": [{"title": "天文学入门讲义", "section": "第 1 页"}]}],
    })
    unit = parsed.units[0]
    assert unit.materials, "输出 schema 丢失了 materials —— D2 溯源链路会静默失效"
    assert unit.materials[0].title == "天文学入门讲义"
    assert unit.materials[0].section == "第 1 页"


# ---------- 引文尺子单一来源 ----------

def test_citation_ruler_is_shared_with_feynman_evidence():
    """``content.citations`` 与 ``service.feynman_ledger``（R30 F5）必须同一把尺子。"""
    from app.content import citations as cit
    from app.service import feynman_ledger as fl

    assert cit.MIN_QUOTE_CHARS == 6 == fl.MIN_EVIDENCE_CHARS
    text = "方程是含有未知数的等式"
    cases = [("方程", False), ("方程是含有", False), ("方程是含有未", True),
             ("完全不在这段话里的句子", False), ("方 程，是 含 有 未", True)]
    for quote, expect in cases:
        assert fl.quote_valid(quote, text) is expect
        assert cit.is_valid(quote, text) is expect
    assert fl.quote_invalid_reason("方程", text) == cit.invalid_reason("方程", text, where="本轮提交文本")
    assert "过短" in fl.quote_invalid_reason("方程", text)
    assert "不在本轮提交文本中" in fl.quote_invalid_reason("完全不在这段话里的句子", text)
