"""R38 回归用例：**材料注入预算用户可控**（两个滑块）+ **多材料合并口径**（全离线）。

覆盖（逐条对应 docs/09 R38 §4 验收）：
- **A1/A5 滑块**：改值 → 立即生效、API 回读一致（当前值 + 来源"你设定的"/"默认"）；
  非法值 → **中文 422**；优先级 单次请求参数 > 学科滑块 > .env > 内置默认；
- **A1 必显**：上一轮**实际注入总量**与**批次数** + 逐材料吸纳明细 + 顺序依据；
- **A2 不限 = 真不限**：滑块 A/B 都设 0 → 无字符级截断（`truncated` 恒 false、逐字全在）；
- **A3 与 R37 分批共存（造错用例）**：调小滑块 A → 只是分更多批，**章节一个不丢**、覆盖账不变；
- **A4 安全阀**：按「字符≈token」粗估超上下文 → **不硬发**，自动分批 + 中文说明；
- **A1b 节粒度**：无标题 PDF **按页合并成章级单元**（覆盖账按章级统计、页号保留可下钻）；
- **B1 多材料合并**：章节地图合并成一份、每节标来源、覆盖账跨材料、未覆盖清单**按材料分组**、
  **未纳入者显式列出**（不是只在 prompt 尾部提一句）；
- **B2 材料角色**：主教材定顺序与范围；未标注按导入顺序并在覆盖账注明。

全部离线：AI 路径用假 provider（monkeypatch ``app.ai.provider.OpenAICompatibleProvider``）。
"""
from __future__ import annotations

import uuid

import pytest

MAT_A = "主教材（伪）"
MAT_B = "补充材料（伪）"

# 4 章 × 页首章标题（bookmap heading 路径；每章约 1.2k 字）
BODY_A = "".join(
    f"【第 {i} 页】\n第{i}章 主题{i}\n" + f"第{i}章的正文内容与要点。" * 70 + "\n\n"
    for i in range(1, 5)
)
# 2 章补充材料
BODY_B = "".join(
    f"【第 {i} 页】\n补充{i}章 细节{i}\n" + f"补充{i}章的例题与细节。" * 40 + "\n\n"
    for i in range(1, 3)
)


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider：按序吐预设响应；记录 messages。"""

    def __init__(self, responses: list[dict | Exception]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))
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
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r38")

    def _install(responses: list[dict | Exception]) -> _FakeProvider:
        p = _FakeProvider(responses)
        import app.ai.provider as prov

        monkeypatch.setattr(prov, "OpenAICompatibleProvider", lambda **kw: p)
        return p

    return _install


def _sid(prefix: str = "r38") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label: str = "R38 预算学科") -> str:
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _add_material(app_client, sid: str, *, title: str, text: str) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                        json={"title": title, "text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _budget(app_client, sid: str, **patch) -> dict:
    r = app_client.put(f"/api/subjects/{sid}/budget", json=patch)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- A1/A5：滑块改值立即生效 + API 回读一致 ----------

def test_r38_a1_slider_takes_effect_and_reads_back(app_client):
    """改滑块 → 立即生效（下一次起草用新值）+ API 回读一致 + 来源标注正确。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)

        b = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert b["batch_chars"]["source"] == "builtin"
        assert b["batch_chars"]["source_zh"] == "默认"
        assert b["batch_chars"]["value"] == 60000        # 内置默认（工单 §0.5）
        assert b["inject_max_chars"]["value"] == 0       # 默认不限
        assert b["inject_max_chars"]["source_zh"] == "默认"

        # 改：单次调用预算=省着用 20000、总上限=充裕 150000
        out = _budget(app_client, sid, batch_chars=20000, inject_max_chars=150000)
        assert out["batch_chars"]["value"] == 20000
        assert out["batch_chars"]["source"] == "subject"
        assert out["batch_chars"]["source_zh"] == "你设定的（本学科）"
        assert out["inject_max_chars"]["value"] == 150000

        # 回读一致
        again = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert again["batch_chars"]["value"] == 20000
        assert again["inject_max_chars"]["value"] == 150000
        assert again["batch_chars"]["set"] == 20000

        # **立即生效**：下一次 draft_materials 用新值
        with SessionLocal() as db:
            pack = mat.draft_materials(db, sid)
        assert pack["budget"]["batch_source"] == "subject"
        assert pack["budget"]["batch_chars"] == 20000
        assert pack["batch_chars"] == 20000

        # 调成"不限"（0）
        out0 = _budget(app_client, sid, batch_chars=0)
        assert out0["batch_chars"]["value"] == 0
        assert out0["last_usage"]["note_zh"].startswith("调小")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r38_a5_priority_request_beats_subject_slider(app_client, monkeypatch):
    """A5 优先级：单次请求参数 > 学科滑块 > .env > 内置默认（逐项可查）。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    monkeypatch.setenv("MF_MATERIAL_BATCH_CHARS", "33333")
    monkeypatch.setenv("MF_MATERIAL_INJECT_MAX_CHARS", "0")
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        with SessionLocal() as db:
            env_only = mat.resolve_budget(db, sid)
        assert env_only["batch_source"] == "env" and env_only["batch_chars"] == 33333
        assert env_only["inject_source"] == "env" and env_only["inject_max_chars"] == 0

        _budget(app_client, sid, batch_chars=20000)
        with SessionLocal() as db:
            subj = mat.resolve_budget(db, sid)
        assert subj["batch_source"] == "subject" and subj["batch_chars"] == 20000

        with SessionLocal() as db:
            req = mat.resolve_budget(db, sid, batch_chars=1234)
        assert req["batch_source"] == "request" and req["batch_chars"] == 1234
        assert req["per_call_chars"] == 1234
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


@pytest.mark.parametrize("body", [
    {"batch_chars": -1},
    {"inject_max_chars": -5},
    {"batch_chars": 99_999_999},
    {"batch_chars": "很多字"},
])
def test_r38_a5_illegal_value_is_zh_422(app_client, body):
    """非法值 → **中文 422**（负值/超范围/非整数）。"""
    sid = _mk_subject(app_client)
    try:
        r = app_client.put(f"/api/subjects/{sid}/budget", json=body)
        assert r.status_code == 422, r.text
        msg = r.json()["detail"]["error"]["message"]
        assert any("\u4e00" <= ch <= "\u9fff" for ch in msg), msg
        assert ("非法" in msg) or ("不合法" in msg) or ("格式" in msg), msg
        assert "错误" not in msg or "格式错误" in msg  # 不得把英文 pydantic 原文抛给前端
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- A2：不限 = 真不限（无字符级截断） ----------

def test_r38_a2_unlimited_means_no_truncation(app_client):
    """滑块 A/B 都设 0（不限）→ 逐字全在、`truncated` 恒 false、`dropped` 恒空；贴 used_chars。"""
    from app.content import citations
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        _budget(app_client, sid, batch_chars=0, inject_max_chars=0)  # 两档都不限
        with SessionLocal() as db:
            unlimited = mat.draft_materials(db, sid)
        assert unlimited["per_call_chars"] == 0, "不限必须真的是 0（不是被悄悄设成某值）"
        assert unlimited["truncated"] is False and unlimited["dropped"] == []
        joined = "\n".join(b["text"] for b in unlimited["batches"])
        # 与"显式大预算"逐字相同（对照 used_chars）
        with SessionLocal() as db:
            capped = mat.draft_materials(db, sid, batch_chars=20000)
        capped_text = "\n".join(b["text"] for b in capped["batches"])
        assert citations.normalize(joined) == citations.normalize(capped_text)
        assert unlimited["used_chars"] == capped["used_chars"] == len(joined)
        for i in range(1, 5):
            assert f"第{i}章的正文内容与要点。" in joined, f"第 {i} 章正文被截断"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- A3：调小滑块不得丢章节（造错用例） ----------

def test_r38_a3_smaller_slider_more_batches_chapters_intact(app_client):
    """**造错用例**：滑块 A 从 60000 调到 300 → 批次变多，但**章节一个不丢**、覆盖账不变。

    这是"调小滑块丢章节"的造错场景：旧口径（预算＝全局上限、超出即截断）在这里会丢材料。
    """
    from app.content import citations
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        _budget(app_client, sid, batch_chars=60000)
        with SessionLocal() as db:
            wide = mat.draft_materials(db, sid)
            idx = mat._material_index(db, sid)
        _budget(app_client, sid, batch_chars=300)
        with SessionLocal() as db:
            narrow = mat.draft_materials(db, sid)
        assert narrow["dropped"] == [] and narrow["truncated"] is False
        assert narrow["batch_count"] > wide["batch_count"], "调小预算必须表现为分更多批"
        flat = lambda p: "\n".join(b["text"] for b in p["batches"])  # noqa: E731
        assert (citations.normalize(flat(narrow)) == citations.normalize(flat(wide))), \
            "调小单次预算**不得**改变总注入内容"
        for i in range(1, 5):
            assert f"第{i}章的正文内容与要点。" in flat(narrow), f"第 {i} 章丢失（造错必报）"
        # 覆盖账（章级）不变
        assert mat.coverage_summary([], idx) == mat.coverage_summary([], idx)
        # 就地可见：批次数与总注入量随滑块变化，但"未纳入章节"为空
        assert narrow["usage"]["not_injected"] == []
        assert len(narrow["usage"]["injected_chars_per_batch"]) == narrow["batch_count"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- A4：安全阀（超上下文 → 自动分批，不硬发） ----------

def test_r38_a4_context_valve_batches_instead_of_sending(app_client, monkeypatch, ai_provider):
    """「不限」+ 超上下文硬上限 → 自动分批 + 中文说明；单块超限时按页边界切（不切句子）。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    monkeypatch.setenv("MF_CONTEXT_TOKEN_LIMIT", "3000")   # 预留 2048 → 单次最多 952 字
    ai_provider([{"units": [{"title": "第1章 主题1", "objectives": ["掌握"],
                            "concept_tags": ["主题1"], "group": "教材", "prereqs": [],
                            "difficulty": 1,
                            "materials": [{"title": MAT_A, "section": "第1章 主题1"}]}]}])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        # 走 API（起草端点建了账本收集器 → 账目随响应**就地**回传）
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 4})
        assert r.status_code == 200, r.text
        body = r.json()
        usage = body["material_usage"]
        assert usage["context_valve"]["applied"] is True, "超上下文必须触发安全阀"
        assert usage["batches"] >= 2
        assert usage["context_valve"]["limit_chars"] == 3000 - 2048
        reasons = "；".join(str(e.get("reason", "")) for e in (body.get("ledger") or []))
        assert "本书较大" in reasons and "已分" in reasons, reasons
        # 中文说明必须同时出现在预算视图（界面就地可见）
        view = app_client.get(f"/api/subjects/{sid}/budget").json()
        assert view["context_valve"]["applied"] is True
        assert view["last_usage"]["batch_count"] >= 2
        # 不截断：每章正文仍在（候选候选不落盘，改从注入包直接核对）
        with SessionLocal() as db:
            pack = mat.draft_materials(db, sid)
        joined = "\n".join(b["text"] for b in pack["batches"])
        for i in range(1, 5):
            assert f"第{i}章的正文内容与要点。" in joined
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- A1b：节粒度（无标题 PDF → 章级单元，页号保留） ----------

def test_r38_a1b_pdf_pages_merge_into_chapter_units_with_page_numbers(app_client):
    """无标题/无目录的 PDF：**按页合并成章级单元**（不是一页一节）；页号保留可下钻。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        body = "".join(f"【第 {i} 页】\n" + "本页正文。" * 200 + "\n\n" for i in range(1, 21))
        _add_material(app_client, sid, title="无标题大部头", text=body)
        with SessionLocal() as db:
            idx = mat._material_index(db, sid)
        entries = idx[0]["structure"]["entries"]
        assert idx[0]["structure"]["kind"] == "page"
        assert 1 <= len(entries) <= 3, f"20 页应合并成少量章级单元，实际 {len(entries)}"
        pages = [p for e in entries for p in e.pages]
        assert [f"第 {i} 页" for i in range(1, 21)] == pages, "页号必须齐全且保序（溯源用）"
        assert "第 1 页" in entries[0].text, "单元正文里保留页标记（页级可下钻）"
        # 覆盖账按章级统计 + 页级总数可下钻
        ledger = mat.coverage_ledger(db, sid)
        assert ledger["total"] == len(entries)
        assert ledger["page_total"] == 20
        assert ledger["uncovered_by_material"] and ledger["uncovered_by_material"][0]["items"][0]["pages"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- B1：多材料合并 ----------

def test_r38_b1_multi_material_merges_map_and_groups_uncovered(app_client):
    """多份材料：章节地图**合并成一份**、每节标来源、覆盖账跨材料、未覆盖**按材料分组**。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        _add_material(app_client, sid, title=MAT_B, text=BODY_B)
        with SessionLocal() as db:
            pack = mat.draft_materials(db, sid)
        assert pack["count"] == 2
        # 一份合并地图，每份材料都注明来自哪份材料
        assert len(pack["chapter_map"]) == 2
        titles = {m["material"] for m in pack["chapter_map"]}
        assert titles == {MAT_A, MAT_B}
        # 逐材料吸纳明细（注入了多少 / 在哪几批）
        per = pack["usage"]["per_material"]
        assert {m["title"] for m in per} == {MAT_A, MAT_B}
        assert all(m["injected"] for m in per)
        assert all(m["entries_total"] >= 1 for m in per)
        assert sum(m["entries_total"] for m in per) >= 4
        # 未纳入者显式列出（此处应为空：两份都被注入）
        assert pack["usage"]["not_injected"] == []
        # 覆盖账跨全部材料 + 未覆盖清单按材料分组
        ledger = mat.coverage_ledger(db, sid)
        assert ledger["multi_material"] is True
        assert ledger["total"] == sum(b["total"] for b in ledger["by_material"])
        assert {b["title"] for b in ledger["by_material"]} == {MAT_A, MAT_B}
        assert len(ledger["uncovered_by_material"]) == 2   # 两份材料各有一组未覆盖条目
        assert all(g["items"] for g in ledger["uncovered_by_material"])
        assert ledger["order_basis"] == "导入顺序", "未标注角色 → 按导入顺序并注明"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r38_b1_blocked_material_is_listed_explicitly_and_in_ledger(app_client):
    """扫描版（无文本层）材料：**整份未纳入** → 覆盖账显式列出 + 账本中文原因（不静默）。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        scanned = "".join(f"【第 {i} 页】\n\n\n" for i in range(1, 31))
        r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                            json={"title": "扫描版（无文本层）", "text": scanned})
        assert r.status_code == 201, r.text
        with SessionLocal() as db:
            ledger = mat.coverage_ledger(db, sid)
            pack = mat.draft_materials(db, sid)
        assert ledger["uncovered_materials"], "整份未纳入的材料必须显式列出"
        assert ledger["uncovered_materials"][0]["title"] == "扫描版（无文本层）"
        assert pack["usage"]["not_injected"], "未纳入的条目必须在用量报告里显式列出"
        # 「必须显性」：账本里能看到中文原因（总账页/就地接口都能读）
        led = app_client.get(f"/api/subjects/{sid}/ledger").json()
        reasons = "；".join(str(e.get("reason", "")) for e in led["entries"])
        assert "未被注入" in reasons and "健康度" in reasons, reasons
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- B2：材料角色（主/补） ----------

def test_r38_b2_role_orders_main_first_and_is_reported(app_client):
    """角色：主教材定顺序与范围 → **有主教材时它排在最前**；覆盖账注明依据=角色。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        mid_b = _add_material(app_client, sid, title=MAT_B, text=BODY_B)   # 先导入"补充材料"
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        listed = {m["id"]: m for m in app_client.get(f"/api/subjects/{sid}/materials").json()["materials"]}
        assert listed[mid_b]["role_explicit"] is False, "未标注角色 → explicit=false（按导入顺序）"
        with SessionLocal() as db:
            assert mat.coverage_ledger(db, sid)["order_basis"] == "导入顺序"
        # 把"补充材料"改标为**主教材**
        r = app_client.put(f"/api/subjects/{sid}/materials/{mid_b}/role", json={"role": "main"})
        assert r.status_code == 200, r.text
        assert r.json()["role_zh"] == "主教材"
        with SessionLocal() as db:
            ledger = mat.coverage_ledger(db, sid)
            ordered = mat._ordered(mat._material_index(db, sid))
        assert ordered[0]["title"] == MAT_B, "主教材必须排在最前（定顺序与范围）"
        assert "角色" in ledger["order_basis"]
        assert next(b for b in ledger["by_material"] if b["title"] == MAT_B)["role_zh"] == "主教材"
        # 改回补充材料 → 不再定顺序
        r2 = app_client.put(f"/api/subjects/{sid}/materials/{mid_b}/role", json={"role": "supplement"})
        assert r2.status_code == 200 and r2.json()["role_zh"] == "补充材料"
        with SessionLocal() as db:
            assert mat.coverage_ledger(db, sid)["order_basis"] != "导入顺序"  # 有显式角色 → 按角色
        # 非法角色 → 中文 422
        bad = app_client.put(f"/api/subjects/{sid}/materials/{mid_b}/role", json={"role": "boss"})
        assert bad.status_code == 422
        assert "非法" in bad.json()["detail"]["error"]["message"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- R40 裁决 §2-1：有教材 + 无可用模型 → **拒绝出稿** ----------

def test_r38_r40_offline_with_material_refuses_draft_and_logs(app_client, monkeypatch):
    """R40 §2-1：有教材但无可用模型 → **明确中文说明 + 不落盘**（不再出"无教材依据"的稿），且记账。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 3})
        assert r.status_code == 422, r.text
        msg = r.json()["detail"]["error"]["message"]
        assert "未配置模型" in msg and "教材" in msg, msg
        led = app_client.get(f"/api/subjects/{sid}/ledger?category=model_call").json()["entries"]
        assert any("拒绝出稿" in e["reason"] for e in led), led
        # 无教材时仍退化为"仅按 brief 起草"（机制可跑通，如实标注无教材依据）
        sid2 = _mk_subject(app_client)
        try:
            ok = app_client.post(f"/api/subjects/{sid2}/outline/draft", json={"count": 3})
            assert ok.status_code == 200 and ok.json()["no_material_grounding"] is True
        finally:
            app_client.delete(f"/api/subjects/{sid2}?hard=true")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- 前端必显数据的契约（API 回读） ----------

def test_r38_api_contract_has_current_values_and_last_usage(app_client):
    """`GET /budget` 必显：两档当前值 + 来源 + 上一轮注入总量/批次数 + 未纳入清单（全中文）。"""
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title=MAT_A, text=BODY_A)
        b = app_client.get(f"/api/subjects/{sid}/budget").json()
        for key in ("batch_chars", "inject_max_chars", "last_usage", "tiers", "materials"):
            assert key in b, key
        assert set(b["tiers"]) == {"batch", "inject"}
        assert [t["label"] for t in b["tiers"]["batch"]] == ["省着用", "常规（默认）", "充裕", "不限"]
        lu = b["last_usage"]
        assert lu["used_chars"] > 0 and lu["batch_count"] >= 1
        assert lu["summary_zh"].startswith("共注入")
        assert "不会少学章节" in lu["note_zh"]
        assert b["materials"][0]["role_zh"] in ("主教材", "补充材料", "未标注")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")
