"""R46 任务 C 用例：**节级依据支持中文序数节名**（§58-17-⑤，P2）。

现状（R42 B4）：节名匹配＝"归一化后相等或互相包含（≥4 字）+ **行首编号节名**兜底"
（``1.1 太阳系的组成``）。教材若用 ``第一节 恒星`` / ``第二讲 …`` 这类**中文序数**节名 →
匹配不到 → 不给依据（宁缺勿造，本身没错）。

本批扩到中文序数（``第<一~九十九>[节讲课篇]``），**仍不放宽到模糊匹配**：
匹配不到就不给。定位改为**空白弹性**（全角空格/多空格都认），归一化照旧。

三条必交：
- `test_r46_c1_*`：``第一节 …`` / ``第二节 …`` 的教材 → `basis_section`/`basis_quote` **取到且逐字出自该节**；
- `test_r46_c2_*`：``恒星概述`` 这类匹配不到的节名 → **不给**（既有行为回归）；
- `test_r46_c3_*`：归一化仍在（全角/半角、空白）。
"""
from __future__ import annotations

import uuid

import pytest

MAT = "恒星物理（伪教材）"

# 章正文用**中文序数**节名（R46 C 的靶子）：每节正文都够长（引文门槛：归一化 ≥20 字）
ZH_BODY = (
    "【第 1 页】\n"
    "第1章 恒星物理\n"
    "第一节 恒星的能量来源\n"
    "恒星的能量来自核心的核聚变反应，氢原子核聚变为氦原子核并释放出巨大的能量。\n"
    "第二节 恒星的光度与质量\n"
    "恒星的光度与质量密切相关，质量越大的恒星其寿命反而越短促。\n"
)
# 全角空格（U+3000）+ 全角数字章号：确认"空白弹性 + 归一化"仍在
ZH_BODY_WIDE = (
    "【第 1 页】\n"
    "第１章 恒星物理\n"
    "第一节\u3000恒星的能量来源\n"
    "恒星的能量来自核心的核聚变反应，氢原子核聚变为氦原子核并释放出巨大的能量。\n"
    "第二节\u3000恒星的光度与质量\n"
    "恒星的光度与质量密切相关，质量越大的恒星其寿命反而越短促。\n"
)


@pytest.fixture
def ai_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-r46c")


def _mk(app_client, label: str = "R46 C 学科") -> str:
    sid = f"r46c{uuid.uuid4().hex[:6]}"
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    return sid


def _mat(app_client, sid: str, body: str, title: str = MAT) -> str:
    r = app_client.post(f"/api/subjects/{sid}/materials/upload", json={"title": title, "text": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _pack(sid: str, *, title: str, section: str) -> dict:
    from app.db import SessionLocal
    from app.outline import materials as mat
    from app.outline.schemas import OutlineUnit

    with SessionLocal() as db:
        unit = OutlineUnit(id=f"{sid}.u01", title=title, group="教材",
                           concept_tags=[title], difficulty=1,
                           materials=[{"title": MAT, "section": section}])
        return mat.unit_material_pack(db, sid, unit)


def test_r46_c1_zh_ordinal_section_names_give_section_level_basis(app_client, ai_key):
    """**必交①**：``第一节 …`` / ``第二节 …`` → `basis_section`/`basis_quote` **取到且逐字出自该节**。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, ZH_BODY)
        pack1 = _pack(sid, title="恒星的能量来源", section="第1章 恒星物理")
        assert pack1["basis_section"] == "第一节 恒星的能量来源", pack1.get("basis_note")
        assert "核聚变" in pack1["basis_quote"], pack1["basis_quote"]
        assert "光度与质量" not in pack1["basis_quote"], "引文必须只出自本节的正文"
        assert pack1["basis_note"] and "章内该节" in pack1["basis_note"], pack1["basis_note"]

        pack2 = _pack(sid, title="恒星的光度与质量", section="第1章 恒星物理")
        assert pack2["basis_section"] == "第二节 恒星的光度与质量", pack2.get("basis_note")
        assert "光度" in pack2["basis_quote"] and "核聚变" not in pack2["basis_quote"]
        # 引文**逐字**出自教材原文（归一化子串包含，复用同一把尺子）
        from app.content import citations

        assert citations.normalize(pack2["basis_quote"]) in citations.normalize(ZH_BODY)
        # 第二讲 也认（同一套形态）
        body_jiang = ZH_BODY.replace("第一节", "第一讲").replace("第二节", "第二讲")
        sid2 = _mk(app_client, label="R46 C 讲次")
        try:
            _mat(app_client, sid2, body_jiang)
            pack3 = _pack(sid2, title="恒星的能量来源", section="第1章 恒星物理")
            assert pack3["basis_section"] == "第一讲 恒星的能量来源", pack3.get("basis_note")
            assert "核聚变" in pack3["basis_quote"]
        finally:
            app_client.delete(f"/api/subjects/{sid2}?hard=true")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r46_c2_unmatched_section_name_still_gives_nothing(app_client, ai_key):
    """**必交②（回归·宁缺勿造）**：节名匹配不到（``恒星概述``）→ **不给**依据，不得模糊放宽。"""
    sid = _mk(app_client)
    try:
        # 正文里压根没有"恒星概述"这一节名 → 不许硬凑
        _mat(app_client, sid, ZH_BODY)
        pack = _pack(sid, title="恒星概述", section="第1章 恒星物理")
        assert pack["basis_section"] == "", pack.get("basis_section")
        assert pack["basis_quote"] == "", pack.get("basis_quote")
        assert pack["covered"] is True, "不给依据 ≠ 没覆盖：材料仍算覆盖（只是不给节级依据）"
        # 反向：节名存在但单元标题与它无关（既非相等也非包含）→ 也不给
        pack2 = _pack(sid, title="行星轨道", section="第1章 恒星物理")
        assert pack2["basis_section"] == "", pack2.get("basis_section")
        assert pack2["basis_quote"] == ""
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r46_c3_normalization_still_holds_fullwidth_and_whitespace(app_client, ai_key):
    """**必交③**：归一化仍在——全角空格（U+3000）/全角数字章号也照样取到节级依据。"""
    sid = _mk(app_client)
    try:
        _mat(app_client, sid, ZH_BODY_WIDE)
        pack = _pack(sid, title="恒星的能量来源", section="第1章 恒星物理")
        assert pack["basis_section"] == "第一节 恒星的能量来源", pack.get("basis_note")
        assert "核聚变" in pack["basis_quote"], pack["basis_quote"]
        assert "光度与质量" not in pack["basis_quote"]
        # 单元标题用**全角**写法也能匹配（normalize 折算全角 ASCII）
        pack2 = _pack(sid, title="恒星的能量来源", section="第１章 恒星物理")
        assert pack2["basis_section"] == "第一节 恒星的能量来源", pack2.get("basis_note")
    finally:
        app_client.delete(f"/api/subjects/{sid}?hard=true")


def test_r46_c4_section_text_slices_only_that_section():
    """定位与切片是**同一套形态**：切出的"该节正文"含本节内容、不含下一节内容。"""
    from app.outline import materials as mat

    sec = "第一节 恒星的能量来源"
    body = mat._section_text(ZH_BODY, sec)
    assert "核聚变" in body, body
    assert "光度与质量" not in body, "切到下一节标题前就该停（不得跨节）"
    # 全角空格版本同样切得对
    body2 = mat._section_text(ZH_BODY_WIDE, sec)
    assert "核聚变" in body2 and "光度与质量" not in body2, body2
    # 节名不在正文里 → 空串（不编造）
    assert mat._section_text(ZH_BODY, "恒星概述") == ""
    # 行首节标题识别：编号 + 中文序数都认，普通正文行不认
    heads = mat._body_section_headings(ZH_BODY)
    assert heads == ["第一节 恒星的能量来源", "第二节 恒星的光度与质量"], heads
    assert mat._body_section_headings("恒星概述\n这是一段普通正文，不该被当成节标题。") == []
