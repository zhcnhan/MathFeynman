"""R42 · 任务 A 造错用例（**六条，缺一条不验收**）：滑块 B「总注入上限」＝**真硬上限**。

架构侧裁决 docs/09 **R41 §3-①**：
- **滑块 A（单次调用预算）**：调小 → 只是分更多批，**绝不丢章节**；
- **滑块 B（总注入上限）**：**是真上限** —— 超了**真的不再注入**，但**每一处未注入都必须
  在账本里有中文原因 + 覆盖账按材料分组显式列出**。

一句话：**A 管"每次喂多少"，B 管"总共最多喂多少，超了明说哪些没喂"。**

六条：
1. `test_r42_a1_cap_stops_at_section_boundary_and_later_chapters_absent` —— B 设小 → 后段确实未注入；
2. `test_r42_a2_every_skipped_chapter_has_zh_ledger_reason` —— 每一章都有中文账目（逐章核对）；
3. `test_r42_a3_coverage_and_budget_view_report_the_loss_truthfully` —— 覆盖账如实降；
4. `test_r42_a4_never_truncates_mid_sentence` —— 绝不在句中截断；
5. `test_r42_a5_slider_a_still_never_drops_chapters` —— A 调小仍不丢章节（原承诺不被破坏）；
6. `test_r42_a6_default_unlimited_is_byte_identical` —— B=0 行为与 R38 逐字一致。
"""
from __future__ import annotations

import uuid

import pytest

from app.service import ledger as ledger_svc


@pytest.fixture
def ai_key(monkeypatch):
    """有教材时必须配 key（R40 §2-1：有教材 + 无模型 → 拒绝出稿）。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r42")


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """最小假 provider：返回一份能过覆盖校验的单元（起草候选）。"""

    def __init__(self, units: list[dict]):
        self.units = units

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        return _Outcome({"units": list(self.units)})


def _units() -> list[dict]:
    return [{"title": CHAPTERS[0], "objectives": ["掌握"], "concept_tags": ["主题1"],
             "group": "教材", "prereqs": [], "difficulty": 1,
             "materials": [{"title": MAT, "section": CHAPTERS[0]}]}]


@pytest.fixture
def ai_provider(monkeypatch, ai_key):
    monkeypatch.setattr("app.ai.provider.OpenAICompatibleProvider",
                        lambda **kw: _FakeProvider(_units()))


def _collect(fn):
    """在账本收集器里跑（就地账目随返回值回传，与 API 路径同源）。"""
    with ledger_svc.collector("", "") as acc:
        out = fn()
        out["ledger"] = acc.to_list()
        return out


MAT = "四章教材（伪）"
# 4 章 × 每章 ≈760 字（含块头）→ 单章整块约 760 字，便于精确落在章边界
BODY = "".join(
    f"【第 {i} 页】\n第{i}章 主题{i}\n" + f"第{i}章的正文内容与要点。" * 60 + "\n\n"
    for i in range(1, 5)
)
CHAPTERS = [f"第{i}章 主题{i}" for i in range(1, 5)]


def _sid(prefix: str = "r42") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk(app_client) -> str:
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": "R42 总上限学科", "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _mat(app_client, sid: str, body: str = BODY, title: str = MAT) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload", json={"title": title, "text": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _draft(app_client, sid: str, **patch) -> dict:
    """设预算（若有）→ 起草 → 返回候选（含 material_usage / ledger）。"""
    if patch:
        r = app_client.put(f"/api/subjects/{sid}/budget", json=patch)
        assert r.status_code == 200, r.text
    d = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 2})
    assert d.status_code == 200, d.text
    return d.json()


def _flat(pack_or_usage: dict) -> str:
    return "\n".join(b["text"] for b in (pack_or_usage.get("batches") or []))


def _draft_materials(db, sid: str, **kw) -> dict:
    """`draft_materials` + 就地账目（测试直读服务层时也要能看账本）。"""
    from app.outline import materials as mat

    return _collect(lambda: mat.draft_materials(db, sid, **kw))


# ---------------------------------------------------------------- 1. 后段确实未注入

def test_r42_a1_cap_stops_at_section_boundary_and_later_chapters_absent(app_client, ai_provider):
    """**造错①**：B 设小 → 前面的章节在、**后面的章节确实不在**（逐章核对，走 API 路径）。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        body = _draft(app_client, sid, batch_chars=60000, inject_max_chars=2000)
        usage = body["material_usage"]
        assert usage["inject_cap"]["configured"] is True
        assert usage["inject_cap"]["cap"] == 2000
        skipped = usage["inject_cap"]["skipped_labels"]
        assert skipped, "B 设小必须真的跳过章节"
        assert CHAPTERS[-1] in skipped, "最后一章必须被明确列出未注入"
        assert usage["batches"] >= 1
        # 界面数据源同步如实
        view = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert view["inject_cap"]["skipped_count"] == usage["inject_cap"]["skipped_count"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r42_a1b_cap_prefix_is_exact_and_later_chapters_absent(app_client, ai_key):
    """**造错①（主体）**：注入内容＝**前若干章**（完整块），后面的章节一个字都不在。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        with SessionLocal() as db:
            full = _draft_materials(db, sid, batch_chars=60000, inject_max_chars=2000)
        assert full["inject_max_chars"] == 2000
        cap = full["usage"]["inject_cap"]
        assert cap["configured"] is True and cap["cap"] == 2000
        injected_text = _flat(full)
        labels_in = [lb for b in full["batches"] for lb in b["labels"]]
        # 前段在
        assert CHAPTERS[0] in injected_text and CHAPTERS[0] in labels_in
        # 后段确实不在
        skipped_labels = cap["skipped_labels"]
        assert skipped_labels, "必须报告因总上限未注入的章节"
        assert CHAPTERS[-1] in skipped_labels, "最后一章必须被明确列出未注入"
        for lab in skipped_labels:
            assert lab not in labels_in, f"{lab} 既在批里又被报未注入（自相矛盾）"
            assert f"{lab}\n" not in injected_text, f"{lab} 的正文不得出现在注入内容里"
        # 剩余量如实
        assert cap["used_chars"] <= cap["cap"] or cap["first_batch_over_cap"] is True
        assert cap["remaining"] >= 0 or cap["first_batch_over_cap"] is True
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 2. 每章都有中文账目

def test_r42_a2_every_skipped_chapter_has_zh_ledger_reason(app_client, ai_provider):
    """**造错②**：未注入的**每一章**都在账本里，且**原因是中文**（不是一条汇总了事）。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        body = _draft(app_client, sid, batch_chars=60000, inject_max_chars=2000)
        usage = body["material_usage"]
        skipped = usage["inject_cap"]["skipped_labels"]
        assert len(skipped) >= 2, f"本样本应跳过 ≥2 章，实际 {skipped}"
        entries = body.get("ledger") or []
        mat_entries = [e for e in entries if e["category"] == "material"]
        assert mat_entries, "材料吸纳必须有账目"
        # 逐章核对：每章在账目里都有一条，且对象含该章标签
        for lab in skipped:
            hits = [e for e in mat_entries if lab in str(e.get("object") or "")]
            assert hits, f"未注入的章节「{lab}」在账本里没有条目；实际账目对象={[e['object'] for e in mat_entries]}"
            assert any("总注入上限" in str(e["reason"]) for e in hits), hits
            for e in hits:
                assert any("\u4e00" <= ch <= "\u9fff" for ch in str(e["reason"])), "原因必须中文"
                assert e["impact"] and e["remedy"], "账本必须写明影响面与可否补救"
        # 也落进总账（离开本次请求后仍可查）
        led = app_client.get(f"/api/subjects/{sid}/ledger?category=material").json()["entries"]
        for lab in skipped:
            assert any(lab in str(e.get("object") or "") for e in led), f"{lab} 未进总账"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 3. 覆盖账如实降

def test_r42_a3b_coverage_ledger_explains_where_skipped_chapters_went(app_client, ai_key):
    """**造错③（覆盖账）**：`/coverage` 里 `not_injected` 标出「总注入上限」，
    `inject_cap.skipped_count > 0`，逐条 `entries[].reason_zh` 能解释"这条去哪了"。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        r = app_client.put(f"/api/subjects/{sid}/budget",
                           json={"batch_chars": 60000, "inject_max_chars": 2000})
        assert r.status_code == 200, r.text
        cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
        assert cov["inject_cap"]["skipped_count"] >= 1, "覆盖账必须报告因总上限未注入的章节数"
        assert cov["inject_cap"]["skipped_labels"]
        cap_items = [x for x in cov["not_injected"] if x.get("reason") == "总注入上限"]
        assert cap_items, "覆盖账的 not_injected 必须标出「总注入上限」"
        for x in cap_items:
            assert x["material"] == MAT and x["label"] in CHAPTERS
        # 逐条可解释（不是凭空消失）
        by_label = {e["label"]: e for e in cov["entries"]}
        for lab in cov["inject_cap"]["skipped_labels"]:
            e = by_label[lab]
            assert e["covered"] is False
            # R52 B：文案改人话（机器可读的 reason 仍是"总注入上限"，只有给用户看的 reason_zh 变了）
            assert e["not_injected_reason"] == "到总量上限了"
            assert "设了总量上限" in e["reason_zh"] and "没读" in e["reason_zh"]
        # 逐材料分组也带该信息
        bm = cov["by_material"][0]
        assert bm["cap_skipped_count"] >= 1 and bm["cap_skipped"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r42_a3_coverage_and_budget_view_report_the_loss_truthfully(app_client, ai_key):
    """**造错③**：`not_injected` 非空、按材料分组；预算视图显示"因总上限未注入的章节数"。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        body = _draft(app_client, sid, batch_chars=60000, inject_max_chars=2000)
        usage = body["material_usage"]
        assert usage["not_injected"], "not_injected 必须非空（如实降）"
        cap_items = [x for x in usage["not_injected"] if x.get("reason") == "总注入上限"]
        assert cap_items, ("必须按原因标出「总注入上限」；实际 not_injected="
                          f"{[(x.get('material'), x.get('label'), x.get('reason')) for x in usage['not_injected']]}")
        assert all(x["material"] == MAT for x in cap_items), "必须按材料分组（带材料名）"
        assert usage["dropped"] == [], "dropped 仍只表示『异常丢弃』（恒空），未注入走 not_injected"
        by_mat = usage["inject_cap"]["skipped_by_material"]
        assert by_mat and by_mat[0]["title"] == MAT and by_mat[0]["items"]

        # 预算视图（界面数据源）
        view = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert view["inject_cap"]["skipped_count"] == usage["inject_cap"]["skipped_count"]
        assert view["last_usage"]["cap_skipped_count"] == usage["inject_cap"]["skipped_count"]
        assert view["last_usage"]["cap_skipped_count"] > 0
        assert "没读" in view["last_usage"]["cap_note_zh"] and "总量" in view["last_usage"]["cap_note_zh"]
        assert view["not_injected"], "预算视图也要给未纳入清单"
        assert view["last_usage"]["per_material"][0]["cap_skipped_count"] > 0, "逐材料也要能看出被跳过"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 4. 绝不在句中截断

def test_r42_a4_never_truncates_mid_sentence(app_client, ai_key):
    """**造错④**：最后装入的那一批正文必须是**完整块边界**（不是句子被切断）。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        with SessionLocal() as db:
            index = mat._material_index(db, sid)
            blocks = mat._full_blocks(index)
            full = _draft_materials(db, sid, batch_chars=60000, inject_max_chars=2000)
        kept_text = [b["text"] for b in full["batches"]]
        assert kept_text, "至少要装入首批"
        # 每个注入批次的正文，必须**逐字等于**若干完整块的拼接（前缀连续）
        remaining = [b["text"] for b in blocks]
        rebuilt: list[str] = []
        for t in kept_text:
            # 逐块贪心还原：该批文本 = 连续若干块用 "\n\n" 连接
            acc = ""
            while remaining:
                nxt = remaining[0] if not acc else acc + "\n\n" + remaining[0]
                if t == nxt:
                    acc = nxt
                    remaining.pop(0)
                    break
                if t.startswith(nxt):
                    acc = nxt
                    remaining.pop(0)
                    continue
                break
            rebuilt.append(acc)
            assert acc == t, ("注入批次不是完整的章/节边界拼接（可能被句中截断）\n"
                              f"批次前 120 字={t[:120]!r}\n还原={acc[:120]!r}")
        # 每章正文的关键句完整（不是半句）
        joined = "\n".join(kept_text)
        for lab in [lb for b in full["batches"] for lb in b["labels"]]:
            assert f"{lab}\n" in joined
        # 未被注入的章节，其正文**一个字都不该出现**（不是"只出现前半句"）
        for lab in full["usage"]["inject_cap"]["skipped_labels"]:
            assert lab not in joined
            assert f"{lab}的正文内容与要点。" not in joined, f"{lab} 有正文片段泄漏进注入内容"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 5. A 调小仍不丢章节

def test_r42_a5_slider_a_still_never_drops_chapters(app_client, ai_key):
    """**造错⑤**：B 不限、A 从 60000 调到 300 → 只分更多批，**章节一个不丢**（原承诺不破）。"""
    from app.content import citations
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        with SessionLocal() as db:
            wide = _draft_materials(db, sid, batch_chars=60000, inject_max_chars=0)
            tight = _draft_materials(db, sid, batch_chars=300, inject_max_chars=0)
        assert wide["usage"]["inject_cap"]["skipped_count"] == 0
        assert tight["usage"]["inject_cap"]["skipped_count"] == 0, "A 调小不得跳过任何章节"
        assert tight["dropped"] == [] and tight["truncated"] is False
        assert tight["batch_count"] > wide["batch_count"], "调小 A 必须表现为分更多批"
        assert citations.normalize(_flat(tight) or "\n".join(b["text"] for b in tight["batches"])) == \
            citations.normalize("\n".join(b["text"] for b in wide["batches"])), \
            "A 调小不得改变总注入内容"
        injected = "\n".join(b["text"] for b in tight["batches"])
        for lab in CHAPTERS:
            assert lab in injected, f"A 调小导致「{lab}」丢失（造错必报）"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 6. B=0 逐字不变

def test_r42_a6_default_unlimited_is_byte_identical(app_client, ai_key):
    """**造错⑥（回归）**：B = 0（不限，默认）→ 行为与"未设预算"**逐字一致**。"""
    from app.content import citations
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        with SessionLocal() as db:
            default = mat.draft_materials(db, sid)                        # 未设任何预算
            explicit = _draft_materials(db, sid, batch_chars=60000, inject_max_chars=0)
        assert default["usage"]["inject_cap"]["configured"] is False
        assert explicit["usage"]["inject_cap"]["configured"] is False
        assert default["usage"]["inject_cap"]["skipped_count"] == 0
        assert default["batch_count"] == explicit["batch_count"]
        assert default["used_chars"] == explicit["used_chars"]
        assert citations.normalize("\n".join(b["text"] for b in default["batches"])) == \
            citations.normalize("\n".join(b["text"] for b in explicit["batches"]))
        assert default["usage"]["not_injected"] == []
        assert default["dropped"] == [] and default["truncated"] is False
        # 默认档位与内置值不变（R38 口径）
        view = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert view["batch_chars"]["value"] == 60000
        assert view["inject_max_chars"]["value"] == 0
        assert view["inject_cap"]["configured"] is False
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------------------------------------------------------------- 边界：上限小于单章

def test_r42_a_first_batch_over_cap_is_reported_not_silent(app_client, ai_key):
    """边界：B 小于**单章**本身 → 仍整章注入（不截断），并**明确记账**超出多少。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk(app_client)
    try:
        _mat(app_client, sid)
        with SessionLocal() as db:
            pack = _draft_materials(db, sid, batch_chars=60000, inject_max_chars=100)
        cap = pack["usage"]["inject_cap"]
        assert cap["first_batch_over_cap"] is True
        assert cap["used_chars"] > cap["cap"], "首批整章注入（宁可不截断）"
        assert pack["batch_count"] == 1
        assert all(CHAPTERS[0] in b["text"] for b in pack["batches"])
        reasons = "；".join(str(e.get("reason", "")) for e in (pack.get("ledger") or []))
        assert "小于第一章" in reasons and "整章注入" in reasons, reasons
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")
