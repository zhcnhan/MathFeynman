"""R37 教材真源化（Source-First）回归用例：S1/S2/S5/S6/S7 造错必报（全离线）。

覆盖（每条新增行为都有"造错必报"用例）：
- **S5 教材锚定（本批核心）**：事实句不在教材 → 整单元失败（uncovered，不落盘）；
  题目引文不在教材 → **丢弃该题**（其余保留，覆盖状态=部分）；引文/事实句在教材里查得到 → 放行；
- **S1 不省成本**：默认（0）注入量随书规模增长且不截断；显式设上限时才走 R36 截断口径；
  书太大 → 按章/页**结构化分批**（不"前 N 字"），各批正文完整、并集＝全书；
- **S2 大纲＝书的目录**：章节地图派生单元 → 未映射 → 中文违规（PUT 422）；
  模型没映射的条目按**教材目录**补齐（记问题，不悄悄丢章节）；
- **S6 覆盖账本**：`GET /coverage` 给出 `已覆盖节/总节` + 未覆盖清单 + 每单元来源/状态；
- **S7 扫描版诚实边界**：无文本层材料 → 中文告知，起草/采纳都**拒绝**（不静默出稿）；
- 引文尺子加固：全角数字/私用区字形折算（教材原文常见排版），单一实现不变。

全部**离线**：AI 路径用假 provider（monkeypatch ``app.ai.provider.OpenAICompatibleProvider``）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

MAT_TITLE = "行星科学（伪教材）"
# 两章结构（页首章标题 → bookmap 的 heading 路径；不依赖目录导引线字形）
CHAPTER_1 = "第1章 恒星"
CHAPTER_2 = "第2章 行星"
MAT_BODY = (
    "【第 1 页】\n"
    f"{CHAPTER_1}\n"
    "恒星是靠内部核聚变发光发热的球状天体，太阳就是一颗恒星。\n"
    "恒星内部的氢在高温高压下聚变为氦，并释放出巨大的能量。\n"
    "我们看到的星光就是这些能量穿过太空到达地球的结果。\n\n"
    "【第 2 页】\n"
    "恒星的光度与质量密切相关，质量越大的恒星寿命越短。\n"
    "恒星的光谱类型可以按表面温度从高到低排列为 O、B、A、F、G、K、M 七类。\n"
    "太阳属于 G 型恒星，它的表面温度约为 5500 摄氏度。\n\n"
    "【第 3 页】\n"
    f"{CHAPTER_2}\n"
    "行星自身不发光，沿着近似椭圆的轨道围绕恒星运行。\n"
    "行星的质量远小于恒星，因此它不能像恒星那样点燃核心的核聚变。\n"
    "行星靠反射恒星的光而被我们看见，这也是它看起来明亮的原因。\n\n"
    "【第 4 页】\n"
    "行星的质量远小于恒星，太阳系有八颗行星。\n"
    "八颗行星按距离太阳由近到远依次是水星、金星、地球、火星、木星、土星、天王星和海王星。\n"
    "其中木星的质量最大，约占太阳系全部行星质量总和的三分之二。\n"
)
FACT1 = "恒星是靠内部核聚变发光发热的球状天体"
FACT2 = "行星自身不发光，沿着近似椭圆的轨道围绕恒星运行"


class _Outcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    """假 provider：按序吐预设响应；记录 messages 供 prompt 断言。"""

    def __init__(self, responses: list[dict | Exception]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):  # noqa: ARG002
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("假 provider 收到了超出预设次数的调用（可能触发了非预期重试）")
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
    """开启"有 key"并替换 provider 工厂；返回安装函数。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r37")
    holder: dict = {}

    def _install(responses: list[dict | Exception]) -> _FakeProvider:
        p = _FakeProvider(responses)
        holder["p"] = p
        import app.ai.provider as prov

        monkeypatch.setattr(prov, "OpenAICompatibleProvider", lambda **kw: p)
        return p

    return _install


def _sid(prefix: str = "r37") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _mk_subject(app_client, label: str = "R37 教材学科") -> str:
    sid = _sid()
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _add_material(app_client, sid: str, *, title: str = MAT_TITLE, text: str = MAT_BODY) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                        json={"title": title, "text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _put_outline(app_client, sid: str, units: list[dict], *, source: str = "manual"):
    return app_client.put(f"/api/subjects/{sid}/outline",
                          json={"units": units, "status": "active", "source": source})


def _unit(sid: str, n: int, *, section: str, title: str, prereq: str | None = None,
          difficulty: int = 1, material: str = MAT_TITLE) -> dict:
    return {
        "id": f"{sid}.u{n:02d}", "title": title, "group": "教材", "objectives": [f"掌握{title}"],
        "concept_tags": [title], "difficulty": difficulty,
        "prereqs": [prereq] if prereq else [],
        "materials": [{"title": material, "section": section}],
    }


def _lecture():
    return f"{FACT1}。\n恒星的光度与质量密切相关。\n{FACT2}。"


def _unit_payload(*, facts: list[dict], exercises: list[dict], asks: list[dict] | None = None):
    return {
        "lecture": _lecture(),
        "feynman_task": "请讲清教材里这两章的要点。",
        "taught_facts": facts,
        "derivable": [],
        "worked_examples": [{"prompt": "例：恒星为什么会发光？", "solution_steps": ["因为它内部核聚变"]}],
        "asks": asks or [],
        "exercises": exercises,
    }


def _ex(i: int, quote: str, *, kind: str = "boolean") -> dict:
    spec = {"kind": kind, "prompt": f"练习题 {i}：{'判断' if kind == 'boolean' else '填空'}陈述 {i}。",
            "basis": {"fact_ids": ["f1"], "quote": quote}}
    if kind == "boolean":
        spec["answer_bool"] = True
    elif kind == "fill":
        spec["expected"] = "恒星"
    return spec


# ---------- 引文尺子加固（教材原文的全角/私用区排版） ----------

def test_r37_citation_ruler_folds_fullwidth_and_private_use():
    from app.content import citations as cit

    assert cit.is_valid("1995年以来", "自 １ ９ ９ ５年 以来")        # 全角数字 + 拆字空格
    assert cit.is_valid("行星科学教材", "􀅰行 星 科 学􀅰教材")        # 私用区装饰字形
    assert cit.is_valid("太阳是一颗恒星", "􀅰１􀅰 第１章 绪 论 太阳是一颗恒星。")
    assert not cit.is_valid("这句话教材里没有", MAT_BODY)


# ---------- S1：不省成本 / 结构化分段 ----------

def test_r37_s1_injection_defaults_to_unlimited_and_grows_with_book(app_client):
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title="小册子", text="【第 1 页】\n短材料。" * 3)
        big = "".join(f"【第 {i} 页】\n" + "正文内容。" * 40 + "\n\n" for i in range(1, 13))
        _add_material(app_client, sid, title="大部头", text=big)
        with SessionLocal() as db:
            pack = mat.draft_materials(db, sid)  # 默认（未设 MF_MATERIAL_INJECT_MAX_CHARS）
        assert pack["inject_max_chars"] == 0, "R37 默认必须是不限（0）"
        assert pack["truncated"] is False and pack["dropped"] == []
        # 注入量＝两本书的章/节正文之和（随书规模增长，不是"每份前 220 字"）
        assert pack["used_chars"] > len(big)
        assert pack["used_chars"] >= sum(e.chars for m in pack["index"]
                                         for e in m["structure"]["entries"])
        # 显式调小**单次调用预算（滑块 A）** → 分批，**不丢章节**（R37/R38 §3 ＋ R39 铁则）
        # ⚠️ R42 A：`max_chars=`/`inject_max_chars=` 现在是**总注入上限（滑块 B，真硬上限）**，
        # 语义不同（会真的少注入后段章节）；"调小不丢章节"的承诺归属**滑块 A**＝`batch_chars=`。
        with SessionLocal() as db:
            capped = mat.draft_materials(db, sid, batch_chars=500)
        assert capped["per_call_chars"] == 500
        assert capped["dropped"] == [] and capped["truncated"] is False
        assert capped["batch_count"] >= 2
        assert capped["usage"]["inject_cap"]["skipped_count"] == 0, "滑块 A 不得跳过任何章节"
        from app.content import citations

        flat = lambda p: "\n".join(b["text"] for b in p["batches"])  # noqa: E731
        assert citations.normalize(flat(capped)) == citations.normalize(flat(pack)), \
            "调小单次预算不得减少总注入内容"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s1_large_book_is_batched_by_structure(app_client, monkeypatch):
    """书太大 → 按章/页分批（每批正文完整，并集＝全书），不是"前 N 字"。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    monkeypatch.setenv("MF_MATERIAL_BATCH_CHARS", "1500")
    body = ""
    for ch in range(1, 4):
        body += f"【第 {ch} 页】\n第{ch}章 主题{ch}\n" + f"第{ch}章的正文。" * 100 + "\n\n"
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid, title="三章书", text=body)
        with SessionLocal() as db:
            pack = mat.draft_materials(db, sid, batch_chars=1500)
        assert len(pack["batches"]) >= 2, "超过分段阈值必须分批"
        labels = [lb for b in pack["batches"] for lb in b["labels"]]
        assert len(labels) == 3 and len(set(labels)) == 3, labels
        joined = "\n".join(b["text"] for b in pack["batches"])
        for ch in range(1, 4):
            assert f"第{ch}章的正文。" in joined, f"第 {ch} 章正文被截断（分批不得丢正文）"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s1_small_budget_still_covers_every_chapter(app_client, monkeypatch):
    """**R38 §3 共存口径**：把**单次调用预算（滑块 A）**调小 → 只改"每次喂多少"，
    **章节一个不丢**（覆盖账不变）。⚠️ R42 A：`max_chars=` 已是**总上限（滑块 B，真硬上限）**，
    语义不同；"不丢章节"的承诺归属 `batch_chars=`。"""
    from app.db import SessionLocal
    from app.outline import materials as mat

    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)                      # 两章伪教材
        with SessionLocal() as db:
            unlimited = mat.draft_materials(db, sid, batch_chars=0)
            tight = mat.draft_materials(db, sid, batch_chars=60)   # 远小于单章字数
        assert tight["dropped"] == [] and tight["truncated"] is False
        assert tight["per_call_chars"] == 60
        assert tight["batch_count"] >= 2
        assert tight["usage"]["inject_cap"]["skipped_count"] == 0, "滑块 A 不得跳过任何章节"
        flat = lambda p: "\n".join(b["text"] for b in p["batches"])  # noqa: E731
        assert CHAPTER_1 in flat(tight) and CHAPTER_2 in flat(tight), "预算调小不得丢章节"
        from app.content import citations

        assert (citations.normalize(flat(tight)) == citations.normalize(flat(unlimited)),
                "分批不改变注入正文内容（只改每批装多少）")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- S2：大纲＝书的目录（全覆盖 / 未映射必报违规） ----------

def test_r37_s2_draft_units_cover_every_chapter(app_client, ai_provider):
    p = ai_provider([
        {"units": [{"title": "恒星：靠核聚变发光", "objectives": ["说出恒星发光的原因"],
                    "concept_tags": ["恒星", "核聚变"], "difficulty": 1,
                    "materials": [{"title": MAT_TITLE, "section": CHAPTER_1}]},
                   {"title": "行星：不发光的天体", "objectives": ["说出行星为何不发光"],
                    "concept_tags": ["行星", "轨道"], "difficulty": 2,
                    "materials": [{"title": MAT_TITLE, "section": CHAPTER_2}]}],
         "ok": True},
    ])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        # R42 B1：coverage 增 `skipped_short`（过短条目，不计入未覆盖缺口）——断言改为逐字段核对（不减弱）
        cov = body["coverage"]
        assert cov["total"] == 2 and cov["covered"] == 2 and cov["uncovered"] == [], cov
        assert cov["skipped_short"]["count"] == 0, cov
        # 注入的是**整章完整正文**（不是 220 字摘要）
        assert FACT1 in p.user_text and FACT2 in p.user_text
        assert "教材章节地图" in p.user_text and CHAPTER_1 in p.user_text
        # 教材＝真源的硬约束写进了起草 prompt（S2/S8 接线锁）
        assert "教材＝权威真源" in p.system_text
        assert "section **必须逐字复制**" in p.system_text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s2_unmapped_chapter_is_filled_from_book_toc_and_reported(app_client, ai_provider):
    """模型只映射了第 1 章 → 第 2 章按**教材目录**补齐并记问题（不得悄悄丢章节）。"""
    ai_provider([
        {"units": [{"title": "恒星", "objectives": ["目标"], "concept_tags": ["恒星"],
                    "difficulty": 1,
                    "materials": [{"title": MAT_TITLE, "section": CHAPTER_1}]}]},
    ])
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 1})
        body = r.json()
        assert body["coverage"]["uncovered"] == [], "补齐后不得再有未映射章节"
        assert body["coverage"]["total"] == 2
        assert any("教材目录" in x for x in body["problems"]), body["problems"]
        titles = [u["title"] for u in body["units"]]
        assert CHAPTER_2 in titles, titles
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s2_put_outline_rejects_unmapped_chapter_zh(app_client):
    """造错必报：手工大纲漏掉第 2 章 → 中文 422（覆盖率违规）。"""
    sid = _mk_subject(app_client)
    try:
        _add_material(app_client, sid)
        only_first = [_unit(sid, 1, section=CHAPTER_1, title="恒星")]
        r = _put_outline(app_client, sid, only_first)
        assert r.status_code == 422, r.text
        msg = r.json()["detail"]["error"]["message"]
        assert "教材覆盖不全" in msg and CHAPTER_2 in msg
        full = only_first + [_unit(sid, 2, section=CHAPTER_2, title="行星", prereq=f"{sid}.u01")]
        r = _put_outline(app_client, sid, full)
        assert r.status_code == 200, r.text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- S5：教材锚定（三档） ----------

def _seed_subject_with_outline(app_client) -> str:
    sid = _mk_subject(app_client)
    _add_material(app_client, sid)
    r = _put_outline(app_client, sid, [
        _unit(sid, 1, section=CHAPTER_1, title="恒星"),
        _unit(sid, 2, section=CHAPTER_2, title="行星", prereq=f"{sid}.u01", difficulty=2),
    ])
    assert r.status_code == 200, r.text
    return sid


def test_r37_s5_fact_not_in_material_fails_whole_unit(app_client, ai_provider):
    """造错必报（第 3 档）：事实句只在讲解里、**教材里没有** → 整单元失败，不落盘。"""
    invented = "恒星的寿命取决于它的质量与金属丰度"
    payload = {
        "lecture": f"{FACT1}。\n{invented}。",
        "feynman_task": "讲清教材内容和它的推论。",
        "taught_facts": [{"id": "f1", "text": invented}],   # 讲解里有、教材里没有
        "derivable": [],
        "worked_examples": [{"prompt": "例：恒星为什么会发光？", "solution_steps": ["内部核聚变"]}],
        "asks": [],
        "exercises": [_ex(1, invented), _ex(2, invented, kind="fill"), _ex(3, invented)],
    }
    ai_provider([payload, payload])  # 两轮都不行 → 整单元失败
    sid = _seed_subject_with_outline(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "uncovered", body
        assert "教材未覆盖此单元" in body["note"]
        stage = Path(app_content_root()) / "stages" / sid
        assert not stage.exists() or not list(stage.glob("*.md")), "失败不得落盘"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s5_exercise_quote_not_in_material_is_dropped(app_client, ai_provider):
    """造错必报（第 2 档）：事实句都在教材里，但某题引文只在讲解里 → **丢弃该题**，其余保留。"""
    invented = "行星的轨道半径与它的公转周期成三次方正比"
    payload = _unit_payload(
        facts=[{"id": "f1", "text": FACT1}],
        exercises=[
            _ex(1, FACT1),
            _ex(2, invented),                       # 讲解里有、教材里没有 → 丢弃
            _ex(3, FACT2, kind="fill"),
            _ex(4, FACT2),
        ],
    )
    payload["lecture"] = _lecture() + f"\n{invented}。"
    ai_provider([payload])
    sid = _seed_subject_with_outline(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "created", body
        assert body["coverage"]["status"] == "部分", body["coverage"]
        assert body["coverage"]["dropped_exercises"] == 1
        text = (Path(app_content_root()) / "stages" / sid / f"node_{sid}.u01_auto.md").read_text(
            encoding="utf-8")
        assert FACT1 in text and FACT2 in text
        assert "练习题 1" in text, "有据的题必须保留"
        assert "练习题 2" not in text, "教材里没有依据的题必须被丢弃"
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r37_s5_grounded_unit_is_kept_whole(app_client, ai_provider):
    """正例：事实句与引文都逐字出自教材 → 整单元放行，覆盖状态=完整。"""
    payload = _unit_payload(
        facts=[{"id": "f1", "text": FACT1}, {"id": "f2", "text": "恒星的光度与质量密切相关"}],
        exercises=[_ex(1, FACT1), _ex(2, "恒星的光度与质量密切相关"),
                   _ex(3, FACT1, kind="fill")],
        asks=[{"ask": "恒星为什么发光？", "basis": {"fact_ids": ["f1"], "quote": FACT1}}],
    )
    p = ai_provider([payload])
    sid = _seed_subject_with_outline(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "created" and body["coverage"]["status"] == "完整", body
        assert body["coverage"]["grounded_facts"] == 2
        # S3：单元出稿注入的是**整章完整正文**（含该章两页），并要求逐字摘录
        assert CHAPTER_1 in p.user_text and "恒星的光度与质量密切相关" in p.user_text
        assert "教材锚定硬要求" in p.system_text
        assert "逐字摘录自教材段落原文" in p.system_text
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- S6：覆盖账本 ----------

def test_r37_s6_coverage_ledger_api(app_client, ai_provider):
    payload = _unit_payload(facts=[{"id": "f1", "text": FACT1}],
                            exercises=[_ex(1, FACT1), _ex(2, FACT1, kind="fill")])
    ai_provider([payload])
    sid = _seed_subject_with_outline(app_client)
    try:
        app_client.post(f"/api/subjects/{sid}/units/{sid}.u01/content")
        r = app_client.get(f"/api/subjects/{sid}/coverage")
        assert r.status_code == 200, r.text
        cov = r.json()
        assert cov["total"] == 2 and cov["covered"] == 2 and cov["uncovered"] == []
        # 每单元记录：来源材料 + 节标签 + 覆盖状态（S6）
        row = next(u for u in cov["units"] if u["unit_id"] == f"{sid}.u01")
        assert row["sources"] and row["sources"][0]["section"] == CHAPTER_1
        assert row["status"] in ("完整", "部分", "未覆盖", "未知")
        assert row["note"], "覆盖状态必须带中文说明"
        entry = next(e for e in cov["entries"] if e["label"] == CHAPTER_1)
        assert entry["covered"] is True and f"{sid}.u01" in entry["units"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


# ---------- S7：扫描/图片版 PDF 的诚实边界 ----------

SCANNED = "".join(f"【第 {i} 页】\n\n" for i in range(1, 11)) + "abc"


def test_r37_s7_scanned_material_reported_and_refused(app_client, ai_provider):
    ai_provider([{"units": []}])
    sid = _mk_subject(app_client)
    try:
        r = app_client.post(f"/api/subjects/{sid}/materials/upload",
                            json={"title": "扫描版教材", "text": SCANNED})
        assert r.status_code == 201, r.text
        h = r.json()["text_health"]
        assert h["checked"] is True and h["healthy"] is False
        assert "扫描" in h["note"] and "OCR" in h["note"]
        # 起草：拒绝并中文告知（不得静默生成"没读到书的大纲"）
        r = app_client.post(f"/api/subjects/{sid}/outline/draft", json={"count": 3})
        assert r.status_code == 422, r.text
        assert "扫描" in r.json()["detail"]["error"]["message"]
        # 采纳：同样拒绝
        r = _put_outline(app_client, sid, [
            _unit(sid, 1, section="第 1 页（扫描）", title="恒星", material="扫描版教材")])
        assert r.status_code == 422, r.text
        assert "文本层" in r.json()["detail"]["error"]["message"]
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def app_content_root() -> str:
    from app.content import content_root

    return str(content_root())
