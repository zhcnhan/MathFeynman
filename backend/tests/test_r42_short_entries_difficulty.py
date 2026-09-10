"""R42 · 任务 B1/B2 造错用例：**过短条目不得静默吞掉** + **难度被抬高必须显性**。

来源：docs/09 **R40 §2-4 / §2-5**（R40 五条遗留里未闭的两条高危），NOTES §58-17-⑦。
"""
from __future__ import annotations

import uuid

import pytest

MAT = "教材（伪）"
# 4 章（每章 ≈760 字）——用于 B2 难度单调化
BODY = "".join(
    f"【第 {i} 页】\n第{i}章 主题{i}\n" + f"第{i}章的正文内容与要点。" * 60 + "\n\n"
    for i in range(1, 5)
)
# 1 章正经内容 + 1 条 45 字附录（过短，阈值 200）——用于 B1
SHORT_LABEL = "附录D 元素周期表"
BODY_WITH_SHORT = (
    "【第 1 页】\n第1章 恒星\n" + "恒星是靠内部核聚变发光发热的球状天体。" * 30 + "\n\n"
    "【第 2 页】\n" + SHORT_LABEL + "\n" + "这是附录页，只有一行说明。" + "\n\n"
)


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    def __init__(self, units: list[dict]):
        self.units = list(units)
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))
        return _Outcome({"units": self.units})


@pytest.fixture
def ai_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r42b")


def _install(monkeypatch, units: list[dict]) -> _FakeProvider:
    p = _FakeProvider(units)
    monkeypatch.setattr("app.ai.provider.OpenAICompatibleProvider", lambda **kw: p)
    return p


def _mk(app_client, label: str = "R42 B 学科") -> str:
    sid = f"r42b{uuid.uuid4().hex[:6]}"
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _mat(app_client, sid: str, body: str, title: str = MAT) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload", json={"title": title, "text": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _draft(app_client, sid: str, *, count: int = 4) -> dict:
    d = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": count})
    assert d.status_code == 200, d.text
    return d.json()


# ============================================================ B1 过短条目

def _unit(n: int, *, section: str, title: str, difficulty: int = 1, prereq: str | None = None) -> dict:
    return {"title": title, "objectives": [f"掌握{title}"], "concept_tags": [title],
            "group": "教材", "prereqs": [prereq] if prereq else [], "difficulty": difficulty,
            "materials": [{"title": MAT, "section": section}]}


def test_r42_b1_short_entry_skipped_and_logged_even_with_grounded_neighbour(app_client, monkeypatch, ai_key):
    """**造错 B1-a**：过短附录条目（无单元映射）→ **标为跳过 + 中文记账**；
    即便旁边有"落在这份材料上"的单元，**也不得给它硬塞该条目**（R36 D2 红线：宁缺勿造）。"""
    # 邻单元引用的是"第1章 恒星"（真实章），附录条目没有被任何单元映射 → 跳过
    _install(monkeypatch, [_unit(1, section="第1章 恒星", title="恒星")])
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, BODY_WITH_SHORT)
        body = _draft(app_client, sid, count=1)
        entries = body.get("ledger") or []
        merged = [e for e in entries if (e.get("detail") or {}).get("kind") == "short_entry_merged"]
        skipped = [e for e in entries if (e.get("detail") or {}).get("kind") == "short_entry_skipped"]
        assert skipped, f"过短条目必须被显式处理；账目={[e['object'] for e in entries]}"
        hit = skipped[0]
        assert SHORT_LABEL in str(hit["object"]), hit
        assert "过短" in str(hit["reason"]), hit["reason"]
        assert any("\u4e00" <= ch <= "\u9fff" for ch in str(hit["reason"]))
        assert hit["impact"] and hit["remedy"]
        cov = body["coverage"]
        assert cov["skipped_short"]["count"] >= 1, cov
        assert SHORT_LABEL in cov["skipped_short"]["labels"], cov
        assert SHORT_LABEL not in "、".join(cov["uncovered"]), "过短条目不得计入未覆盖缺口"
        assert not merged, "无单元映射的过短条目不得被硬塞进别的单元"
        assert all(SHORT_LABEL not in [str(r["section"]) for r in (u["materials"] or [])]
                   for u in body["units"]), "不得硬塞伪溯源"
        assert SHORT_LABEL in "；".join(body["problems"]), body["problems"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r42_b1_short_entry_skipped_when_no_grounded_unit_and_logged(app_client, monkeypatch, ai_key):
    """**造错 B1-b**：过短条目 + **没有任何单元落在该节上** → **标为跳过**（不硬塞伪溯源），
    账本中文原因 + 覆盖账 `skipped_short`（**不计入 uncovered 缺口**，可解释）。"""
    # 单元引用的是**另一节**（第1章 恒星），没落在附录那一节 → 短条目不能并入
    _install(monkeypatch, [_unit(1, section="第1章 恒星", title="恒星")])
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, BODY_WITH_SHORT)
        body = _draft(app_client, sid, count=1)
        entries = body.get("ledger") or []
        skipped = [e for e in entries if (e.get("detail") or {}).get("kind") == "short_entry_skipped"]
        assert skipped, ("无可安全并入的单元时必须标跳过并记账；账目="
                         f"{[(e['object'], e['reason'][:40]) for e in entries]}")
        assert SHORT_LABEL in str(skipped[0]["object"])
        assert "已跳过" in str(skipped[0]["reason"]) and "过短" in str(skipped[0]["reason"])
        cov = body["coverage"]
        assert cov["skipped_short"]["count"] >= 1 and SHORT_LABEL in cov["skipped_short"]["labels"], cov
        assert SHORT_LABEL not in "、".join(cov["uncovered"]), "过短条目**不得**计入未覆盖缺口"
        # 不许硬塞：所有单元的溯源里都不得出现该条目标签
        assert all(SHORT_LABEL not in [str(r["section"]) for r in (u["materials"] or [])]
                   for u in body["units"])
        led = app_client.get(f"/api/subjects/{sid}/ledger?category=material").json()["entries"]
        assert any(SHORT_LABEL in str(e["object"]) for e in led), led[:3]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r42_b1_normal_entry_still_becomes_unit(app_client, monkeypatch, ai_key):
    """回归：**非过短**条目（≥200 字）仍按 R37 S2 由教材目录补齐成单元（B1 不改这条口径）。"""
    _install(monkeypatch, [_unit(1, section="第1章 主题1", title="主题1")])
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, BODY)
        body = _draft(app_client, sid, count=1)
        cov = body["coverage"]
        assert cov["total"] == 4, cov
        assert cov["skipped_short"]["count"] == 0, cov
        assert len(body["units"]) == 4, "非过短条目应全部成为单元"
        assert any("教材目录" in x for x in body["problems"]), body["problems"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ============================================================ B2 难度抬高

def test_r42_b2_difficulty_raise_is_logged_and_visible(app_client, monkeypatch, ai_key):
    """**造错 B2**：先修难度高于后继 → 钳制把后继**抬高** → 逐处账本中文原因 + 单元 `meta` 可见。"""
    # 书序 1..4，难度 3,1,1,1 → 钳制后 3,3,3,3（后三个都被抬高）
    units = [_unit(i, section=f"第{i}章 主题{i}", title=f"主题{i}",
                   difficulty=(3 if i == 1 else 1),
                   prereq=(f"u{i - 1:02d}" if i > 1 else None))
             for i in range(1, 5)]
    _install(monkeypatch, units)
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, BODY)
        body = _draft(app_client, sid, count=4)
        entries = body.get("ledger") or []
        gen = [e for e in entries if (e.get("detail") or {}).get("kind") == "difficulty_raised"]
        assert gen, f"难度被抬高必须记账；账目={[(e['category'], e['object']) for e in entries]}"
        assert len(gen) >= 2, gen
        for e in gen:
            assert "抬高" in str(e["reason"]) and "先修单调" in str(e["reason"]), e["reason"]
            assert any("\u4e00" <= ch <= "\u9fff" for ch in str(e["reason"]))
            assert e["impact"] and e["remedy"]
        # 大纲页单元行可见（候选 units[].meta.difficulty_raised）
        raised = [u for u in body["units"] if (u.get("meta") or {}).get("difficulty_raised")]
        assert len(raised) >= 2, body["units"]
        for u in raised:
            dr = u["meta"]["difficulty_raised"]
            assert dr["to"] > dr["from"]
            assert "抬高" in dr["reason_zh"]
        # 候选顶层也直给（便于 UI 一次性取用）
        assert body.get("difficulty_raised"), body.get("difficulty_raised")
        # 难度确实单调非降（钳制仍生效）
        diffs = [u["difficulty"] for u in body["units"]]
        assert diffs == sorted(diffs), diffs
        # 总账里也能查到（离开请求后仍可追溯）
        led = app_client.get(f"/api/subjects/{sid}/ledger?category=generation").json()["entries"]
        assert any("抬高" in str(e["reason"]) for e in led), led[:3]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r42_b2_no_raise_no_ledger_entry(app_client, monkeypatch, ai_key):
    """反向：难度本来就单调（不需抬高）→ **不产生**任何"抬高"账目（不刷噪音）。"""
    units = [_unit(i, section=f"第{i}章 主题{i}", title=f"主题{i}",
                   difficulty=min(3, i), prereq=(f"u{i - 1:02d}" if i > 1 else None))
             for i in range(1, 5)]
    _install(monkeypatch, units)
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, BODY)
        body = _draft(app_client, sid, count=4)
        assert not [e for e in (body.get("ledger") or [])
                    if (e.get("detail") or {}).get("kind") == "difficulty_raised"]
        assert not body.get("difficulty_raised")
        assert all(not (u.get("meta") or {}).get("difficulty_raised") for u in body["units"])
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ============================================================ B4 basis.quote 节级

# 目录级材料：1 章 + 2 节（节名可与单元标题确定性匹配）
TOC_BODY = (
    "目录\n"
    "第1章 恒星物理 1\n"
    "1.1 恒星的能量来源 1\n"
    "1.2 恒星的光度与质量 3\n"
    "【第 1 页】\n"
    "第1章 恒星物理\n"
    "1.1 恒星的能量来源\n"
    "恒星的能量来自核心的核聚变反应，氢聚变为氦并释放能量。\n"
    "1.2 恒星的光度与质量\n"
    "恒星的光度与质量密切相关，质量越大的恒星寿命越短。\n"
)


def test_r42_b4_basis_is_section_level_not_chapter_level(app_client, ai_key):
    """**R42 B4**：目录级材料 → 单元依据细化到**章内该节**（`basis_section` / 逐字 `basis_quote`）。"""
    from app.db import SessionLocal
    from app.outline import materials as mat
    from app.outline.schemas import OutlineUnit

    sid = _mk(app_client)
    try:
        _mat(app_client, sid, TOC_BODY, title="恒星物理（伪教材）")
        with SessionLocal() as db:
            idx = mat._material_index(db, sid)
            unit = OutlineUnit(id=f"{sid}.u01", title="恒星的能量来源", group="教材",
                               concept_tags=["恒星的能量来源"], difficulty=1,
                               materials=[{"title": "恒星物理（伪教材）", "section": "第1章 恒星物理"}])
            pack = mat.unit_material_pack(db, sid, unit)
        assert idx, "材料应被解析"
        assert pack["covered"] is True
        # 章内该节级依据（R40 §2-3）
        assert pack["basis_section"] == "1.1 恒星的能量来源", pack.get("basis_note")
        assert "核聚变" in pack["basis_quote"], pack["basis_quote"]
        # 引文必须是**该节**的逐字片段（不是整章随便一句 / 不是别节那句）
        assert "光度与质量" not in pack["basis_quote"]
        assert pack["basis_quote"] in pack["text"] or pack["basis_quote"] in TOC_BODY
        assert pack["basis_note"] and "章内该节" in pack["basis_note"]
        # 另一节 → 依据随之切换（说明确实"按节"而不是"整章一刀切"）
        with SessionLocal() as db:
            unit2 = OutlineUnit(id=f"{sid}.u02", title="恒星的光度与质量", group="教材",
                                concept_tags=["恒星的光度与质量"], difficulty=2,
                                materials=[{"title": "恒星物理（伪教材）", "section": "第1章 恒星物理"}])
            pack2 = mat.unit_material_pack(db, sid, unit2)
        assert pack2["basis_section"] == "1.2 恒星的光度与质量", pack2.get("basis_note")
        assert "光度" in pack2["basis_quote"] and "核聚变" not in pack2["basis_quote"]
        # 非目录级结构 → 不给（不编造）
        sid2 = _mk(app_client, label="R42 B4 非目录")
        try:
            _mat(app_client, sid2, BODY, title="无目录书")
            with SessionLocal() as db:
                unit3 = OutlineUnit(id=f"{sid2}.u01", title="主题1", group="教材",
                                    concept_tags=["主题1"], difficulty=1,
                                    materials=[{"title": "无目录书", "section": "第1章 主题1"}])
                pack3 = mat.unit_material_pack(db, sid2, unit3)
            assert pack3["basis_section"] == "", "非目录级结构不得编造节级依据"
            assert pack3["basis_quote"] == ""
        finally:
            app_client.delete(f"/api/subjects/{sid2}?hard=true")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")
