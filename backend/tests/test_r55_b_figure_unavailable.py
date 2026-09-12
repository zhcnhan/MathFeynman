"""R55 任务 B 用例：**图示不可用要显式认输**（本轮最重要的一条）。

用户原话（R55 立案）：系统读不到图片，却照样出内容/出题——"它没说它读不到图"。
口径：
- 正文里**指向图/表**的段落 → ① 注入文本里就地加中文标注 ② 记一条中文账（材料/节级）
  ③ 覆盖账里可见（界面能看见）④ **不许**被当成事实句/题目依据（只落在图段里的引用一律丢弃）；
- **整节内容都在图里** → **不出内容**，并用中文说清原因（宁缺勿造，不猜图里画的是什么）；
- 误判防护：孤立的"图"字（地图/图书/图解）、参考文献行里的"图"**不算**指代。
"""
from __future__ import annotations

import pytest

from app.content import content_root
from app.db import SessionLocal
from app.outline import materials as mat
from app.outline import store as outline_store
from r55_support import (
    adopt_outline, cleanup_subjects, draft_pack, gen_unit, ledger_entries, make_subject,
    material_body, materials, unit, upload_text_material,
)

MAT = "带图的教材"

FIG_PARA = "如图 1.1 所示，恒星从内到外分为核心、辐射层和对流层。"
TBL_PARA = "见下表 1-1，各层的温度与密度差别很大。"
CLEAN_PARA = "行星是围绕恒星运行的天体，自身不发光。"
CLEAN_PARA2 = "阳光从太阳到地球大约需要八分钟。"
CLEAN3 = "小行星带位于火星与木星轨道之间。"
FIG3 = "如图 3.2 所示，小行星的形状大多不规则。"
NO_FIG_PARA = "地图与图书里也能看到图解，但这里只是在说书名《图解天文》。"

CH1 = "第1章 恒星的内部"
CH2 = "第2章 行星"
CH3 = "第3章 小行星"
PLAIN_CH = "第1章 地图与图书"

# 三章材料（B1 主用例：既有"整章靠图"，也有"干净章"）。
# ⚠️ 必须带 `【第 N 页】`：只有这样章节地图才会按"页首章标题"认出 3 章
# （真实材料就是这种结构；没有页标记 → 退化成"第 1 段"整块，测不到章级口径）。
FIG_BODY = (f"【第 1 页】\n{CH1}\n{FIG_PARA}\n\n{TBL_PARA}\n\n"
            f"【第 2 页】\n{CH2}\n{CLEAN_PARA}\n\n{CLEAN_PARA2}\n\n"
            f"【第 3 页】\n{CH3}\n{CLEAN3}\n\n{FIG3}\n")
# 单章材料（各自只覆盖一个章/节条目：大纲校验要求"教材条目全部有单元对应"）
PURE_FIG_BODY = f"【第 1 页】\n{CH1}\n{FIG_PARA}\n\n{TBL_PARA}\n"
MIXED_BODY = f"【第 1 页】\n{CH3}\n{CLEAN3}\n\n{FIG3}\n"
PLAIN_BODY = (f"【第 1 页】\n{PLAIN_CH}\n{NO_FIG_PARA}\n\n{CLEAN_PARA}\n\n"
              "[12] 图解天文学. 科学出版社, 1999.\n")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def _has_zh(s: str) -> bool:
    return bool(s) and any("\u4e00" <= c <= "\u9fff" for c in s)


def _pack(sid: str, uid: str) -> dict:
    with SessionLocal() as db:
        doc = outline_store.get_outline(sid)
        return mat.unit_material_pack(db, sid, doc.by_id()[uid])


# ============================================================ B1 标注 + 记账 + 可见

def test_r55_b1_figure_paragraphs_are_marked_and_kept_verbatim():
    """**B-①**：图段在注入文本里就地标注（中文），且**原文一字不删**。"""
    from app.outline.materials import annotated_entry_text

    text = f"{CH1}\n{FIG_PARA}\n\n{NO_FIG_PARA}\n\n{CLEAN_PARA}"
    annotated, refs, marked = annotated_entry_text(text)
    assert marked == 1 and "图 1.1" in refs, (marked, refs)
    assert "【图示不可用" in annotated and "不要据此编造" in annotated
    for para in (FIG_PARA, NO_FIG_PARA, CLEAN_PARA):
        assert para in annotated, "标注只能加，不许删改正文"
    assert annotated.count("【图示不可用") == 1, "只有引用图/表的段落才标注（不许到处贴）"


def test_r55_b1_figure_unit_is_marked_ledgered_and_visible(app_client, sids):
    """**B-①**：材料级记账（中文）＋ 注入文本标注 ＋ 覆盖账里可见（三处一致）。"""
    sid = make_subject(app_client, sids)
    mid = upload_text_material(app_client, sid, FIG_BODY, title=MAT)["id"]

    # 真实入口：读一次材料（`draft_materials`，与起草大纲同一条路）→ 材料级记账
    draft_pack(sid)
    rows = ledger_entries(app_client, sid, kind="figure_unavailable")
    mat_rows = [r for r in rows if "材料" in str(r.get("object") or "")]
    assert mat_rows, f"材料里引用了图表就必须记账；实际：{rows}"
    text = f"{mat_rows[0].get('object','')}{mat_rows[0].get('reason','')}"
    assert "图示不可用" in text and _has_zh(text), text
    assert "读不到" in text or "只能读文字" in text, text

    # ① 注入文本：图段标注、原文保留
    adopt_outline(app_client, sid, [
        unit(f"{sid}.u01", "恒星的内部", section=FIG_PARA, material=MAT),
        unit(f"{sid}.u02", "行星", section=CLEAN_PARA, prereqs=[f"{sid}.u01"], material=MAT),
        unit(f"{sid}.u03", "小行星", section=CLEAN3, prereqs=[f"{sid}.u02"], material=MAT),
    ])
    p1 = _pack(sid, f"{sid}.u01")
    assert "【图示不可用" in p1["text"] and "不要据此编造" in p1["text"]
    assert FIG_PARA in p1["text"] and TBL_PARA in p1["text"], "标注不许删正文"
    assert set(p1["figure_refs"]) >= {"图 1.1", "表 1-1"}, p1["figure_refs"]
    assert p1["figure_marked"] == 2 and p1["figure_only"] is True, p1["figure_marked"]
    assert FIG_PARA not in p1["clean_text"] and TBL_PARA not in p1["clean_text"]

    # ③ 生成"整章靠图"的单元 → 不出内容 + 中文说明 + 覆盖账可见
    res = gen_unit(app_client, sid, f"{sid}.u01")
    assert res["status"] == "uncovered", res
    node = content_root() / "stages" / sid / f"node_{sid}.u01_auto.md"
    assert not node.exists(), "整章靠图 → 不许落盘任何内容（不猜图里画的是什么）"
    assert _has_zh(res["note"]) and "图" in res["note"], res["note"]

    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    bm = [x for x in cov["by_material"] if x["material_id"] == mid][0]
    assert bm["figure_unavailable_count"] >= 2, bm
    assert {CH1, CH3} <= set(bm["figure_unavailable"]), bm
    u01 = [x for x in cov["units"] if x["unit_id"] == f"{sid}.u01"][0]
    assert u01["figure_unavailable"] is True and u01["has_content"] is False, u01
    assert "图" in u01["note"] and _has_zh(u01["note"]), u01["note"]
    # 单元级也有账（账本里能看到"为什么没出稿"）
    assert [r for r in ledger_entries(app_client, sid, kind="figure_unavailable")
            if r.get("unit_id") == f"{sid}.u01"], "未出稿必须记账"


def test_r55_b1_figure_unit_explains_in_chinese_at_the_session_entry(app_client, sids):
    """**B-①（续）**：点进学习时说的是"读不到图"，不是含糊的"还没有内容"。"""
    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, PURE_FIG_BODY, title=MAT)
    adopt_outline(app_client, sid, [unit(f"{sid}.u01", "恒星的内部",
                                         section=FIG_PARA, material=MAT)])
    res = gen_unit(app_client, sid, f"{sid}.u01")
    assert res["status"] == "uncovered" and "图" in str(res["note"]), res["note"]

    started = app_client.post("/api/session/start", json={"node_id": f"{sid}.u01"}).json()
    assert started["step"] == "content_missing", started["step"]
    info = started["payload"]["content_missing"]
    assert info["missing"] == "content" and _has_zh(info["reason_zh"]), info
    assert "图" in info["reason_zh"] and "读不到" in info["reason_zh"], info["reason_zh"]


def test_r55_b1_mixed_entry_is_not_refused_but_figure_part_is_stripped(app_client, sids):
    """**B-①（边界）**：一节里**只有一段**是图 → 照常出稿，但图段仍不进"可当依据"的正文。"""
    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, MIXED_BODY, title=MAT)
    adopt_outline(app_client, sid, [unit(f"{sid}.u03", "小行星", section=CLEAN3, material=MAT)])
    p3 = _pack(sid, f"{sid}.u03")
    assert p3["figure_marked"] == 1 and p3["figure_only"] is False, \
        (p3["figure_marked"], p3["figure_only"])
    assert CLEAN3 in p3["clean_text"] and FIG3 not in p3["clean_text"]
    assert FIG3 in p3["figure_text"]
    # ⚠️ **不许把整章当图段**：同一章里没引用图的那段**不算**图段
    # （否则这章里正常的正文也会被当成"读不到图" → 好内容被误丢）
    assert CLEAN3 not in p3["figure_text"], "figure_text 必须停在句子级，不是整章/整页"
    res = gen_unit(app_client, sid, f"{sid}.u03")
    assert res["status"] == "created", res


def test_r55_b1_same_paragraph_clean_sentence_survives_a_figure_sentence():
    """**B-①（粒度）**：同一段里，**没引用图的那句**照旧能当依据；引用图的那句才丢。

    为什么不用"整段"当硬边界：真实教材一"段"常常是**整页**（页内没有空行）——
    段落级实测会误丢 17 条事实句里的 10 条（见 NOTES §77 的实测对比），所以：
    **可见标注＝段落级**（段前加中文警告），**"不许当依据"＝句子级**（引用句 + 紧随其后 1 句）。
    """
    from app.content import answerability
    from app.outline.materials import figure_text_of, non_figure_text

    clean_s = "月球是地球唯一的天然卫星。"
    fig_s = "如图 9.1 所示，卫星表面的陨石坑分布不均。"
    text = f"第9章 卫星\n{clean_s} {fig_s}"

    assert clean_s.strip() in non_figure_text(text) and clean_s not in figure_text_of(text)
    assert fig_s in figure_text_of(text)
    material = f"【第 1 页】\n{text}\n"
    kept, _problems, dropped = answerability.clean_facts(
        [{"id": "f1", "text": clean_s, "quote": clean_s},
         {"id": "f2", "text": "卫星表面的陨石坑分布不均。", "quote": fig_s}],
        text, material=material, figure_text=figure_text_of(text))
    assert [f.id for f in kept] == ["f1"], [f.id for f in kept]
    assert [d.get("drop_kind") for d in dropped] == ["figure_unavailable"], dropped

    # 紧随引用句之后的那一句也按"可能是在讲这张图"处理（窗口＝2 句，宁可保守；实测不误伤）
    tail = f"第9章 卫星\n{fig_s} 坑的密度随纬度变化。"
    assert "坑的密度随纬度变化。" in figure_text_of(tail)


def test_r55_b1_fact_from_clean_paragraph_survives_a_figure_in_the_same_chapter():
    """**B-①（不许误伤）**：同章另一段没引用图 → 那段的事实句/引文**必须留下**。"""
    from app.content import answerability

    material = MIXED_BODY
    figure_text = FIG3                       # 只有"如图 3.2…"那一句
    lecture = f"{CLEAN3}\n{FIG3}"
    kept, problems, dropped = answerability.clean_facts(
        [{"id": "f1", "text": CLEAN3, "quote": CLEAN3},
         {"id": "f2", "text": "小行星的形状大多不规则。", "quote": FIG3}],
        lecture, material=material, figure_text=figure_text)
    assert [f.id for f in kept] == ["f1"], [f.id for f in kept]
    assert [d.get("drop_kind") for d in dropped] == ["figure_unavailable"], dropped
    ok, why = answerability.check_basis({"fact_ids": ["f1"], "quote": CLEAN3},
                                        lecture=lecture, fact_ids={"f1"},
                                        material=material, figure_text=figure_text)
    assert ok, why          # 同章干净段的引文照样成立


# ============================================================ B2 不许误判

def test_r55_b2_plain_words_about_maps_and_books_are_not_figure_refs(app_client, sids):
    """**B-②**：孤立的"图"字（地图/图书/图解/书名）与参考文献行**不算**指代——不许到处报警。"""
    assert mat.figure_refs(NO_FIG_PARA) == []
    assert mat.figure_refs("这本书的图书编号是 3。") == []
    assert mat.figure_refs("[12] 图解天文学. 科学出版社, 1999.") == []
    assert mat.figure_refs("见 https://example.org/tu 里的说明") == []
    # 真指代仍然要认出来（别把尺子调松到"什么都不认"）
    assert mat.figure_refs(FIG_PARA) and mat.figure_refs("见下表 1-1，各层不同。")
    assert mat.figure_refs("Fig. 4 shows the layers.") and mat.figure_refs("Table 5 lists them.")

    sid = make_subject(app_client, sids)
    upload_text_material(app_client, sid, PLAIN_BODY, title=MAT)
    adopt_outline(app_client, sid, [unit(f"{sid}.u01", "地图与图书",
                                         section=CLEAN_PARA, material=MAT)])
    res = gen_unit(app_client, sid, f"{sid}.u01")

    assert res["status"] == "created", res
    assert not ledger_entries(app_client, sid, kind="figure_unavailable"), "误报会产生假账"
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    assert cov["by_material"][0]["figure_unavailable_count"] == 0, cov["by_material"][0]


# ============================================================ B3 图段不许当依据

def test_r55_b3_facts_and_basis_from_figure_paragraphs_are_dropped():
    """**B-③**：只落在图段里的引用 → **丢弃**（事实句与题目依据都不许来自图段）。"""
    from app.content import answerability

    material = FIG_BODY
    figure_text = f"{FIG_PARA}\n{TBL_PARA}\n{FIG3}"
    lecture = f"{CLEAN_PARA}\n{FIG_PARA}\n{TBL_PARA}"
    facts = [
        {"id": "f1", "text": "恒星从内到外分为核心、辐射层和对流层。", "quote": FIG_PARA},
        {"id": "f2", "text": "行星是围绕恒星运行的天体，自身不发光。", "quote": CLEAN_PARA},
    ]
    kept, problems, dropped = answerability.clean_facts(
        facts, lecture, material=material, figure_text=figure_text)
    assert [f.id for f in kept] == ["f2"], [f.id for f in kept]
    assert dropped and dropped[0].get("drop_kind") == "figure_unavailable", dropped
    assert "图" in dropped[0]["reason"] and "读不到图片" in dropped[0]["reason"], dropped[0]

    # 题目依据同理：引文只出现在图段 → 不许作为依据
    ok, why = answerability.check_basis({"fact_ids": ["f2"], "quote": CLEAN_PARA},
                                        lecture=lecture, fact_ids={"f2"},
                                        material=material, figure_text=figure_text)
    assert ok, why
    ok2, why2 = answerability.check_basis({"fact_ids": ["f2"], "quote": TBL_PARA},
                                          lecture=lecture, fact_ids={"f2"},
                                          material=material, figure_text=figure_text)
    assert not ok2, f"图段的引文不该通过依据校验：{why2}"
    assert "图" in why2 or "读不到" in why2, why2


def test_r55_b3_material_body_is_never_rewritten_by_marking(app_client, sids):
    """**B-③（续）**：标注只发生在**注入副本**里，材料文件本体原样不动（可复核）。"""
    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, FIG_BODY, title=MAT)
    listed = [m for m in materials(app_client, sid) if m["id"] == up["id"]][0]
    assert listed["kind"] == "local" and listed["text_health"]["grade"] == "好"
    adopt_outline(app_client, sid, [
        unit(f"{sid}.u01", "恒星的内部", section=FIG_PARA, material=MAT),
        unit(f"{sid}.u02", "行星", section=CLEAN_PARA, prereqs=[f"{sid}.u01"], material=MAT),
        unit(f"{sid}.u03", "小行星", section=CLEAN3, prereqs=[f"{sid}.u02"], material=MAT),
    ])
    gen_unit(app_client, sid, f"{sid}.u01")
    gen_unit(app_client, sid, f"{sid}.u02")          # 干净单元照常出稿（不殃及无关单元）
    body = material_body(sid, up["id"])
    assert FIG_PARA in body and TBL_PARA in body and "【图示不可用" not in body
    assert (content_root() / "stages" / sid / f"node_{sid}.u02_auto.md").exists()
