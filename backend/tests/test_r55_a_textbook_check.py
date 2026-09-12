"""R55 任务 A 用例：**教材体检**（导入时就把"这本书抽得好不好"讲成人话）。

口径（实现见 `outline/pdfparse.py::extract_quality` ＋ `outline/materials.py::text_health`）：
- 四个指标：认不出字符占比 / 被空格拆开的行占比 / 公式符号数 / 图片数；
- 三档 **好 / 一般 / 差** + 一句"所以会怎样"（**只给数字不算体检结论**）；
- 体检在**原始抽取文本**上算——即使用户后来拿了修正后的文本，也如实说"这份 PDF 抽出来有多脏"；
- 图片数**只影响那句说明**（"有 N 张图读不到"），不参与判档；
- R37 的扫描版诚实边界（`healthy/note`）**原样保留**，没有被 R55 覆盖掉。
"""
from __future__ import annotations

import pytest

from app.outline.materials import text_health
from app.outline.pdfparse import _clean, extract_quality
from r55_support import cleanup_subjects, make_subject, materials, upload_text_material

PUA_UNKNOWN = "\U000f0001"      # 私用区、不在已知表里（真实材料里的"认不出"就是这类字形）
BAD_CHAR = "\ufffd"             # 替换字符（另一种"认不出"）

# 内部字段名/编号**不许**出现在给用户看的文案里（docs/13 §2：说人话）
_JARGON = ("ratio", "unrecognized", "broken_space", "grade", "MF_", "§", "docs/", "schema",
           "extract", "token", "R55")


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def _assert_plain_chinese(summary: str) -> None:
    """体检摘要是**人话**：有汉字、有句号、不夹内部字段名，也不是"光甩数字"。"""
    assert summary and any("\u4e00" <= c <= "\u9fff" for c in summary), summary
    assert "。" in summary, summary
    for bad in _JARGON:
        assert bad not in summary, f"体检文案里不该出现内部字样 {bad!r}：{summary}"


# ============================================================ A1 干净材料 → 好

def test_r55_a1_clean_material_grades_good_and_says_it_in_plain_chinese(app_client, sids):
    """**A-①**：干净材料 → 三档为「好」，并且有一句"所以会怎样"（不是只给数字）。"""
    body = ("【第 1 页】\n行星是围绕恒星运行的天体，自身不发光，靠反射恒星的光被我们看见。\n"
            "【第 2 页】\n阳光从太阳到地球大约需要八分钟，所以我们看到的太阳是八分钟前的太阳。\n"
            "【第 3 页】\n恒星的光度与质量密切相关，质量越大的恒星通常越亮，寿命也越短。\n"
            "【第 4 页】\n行星之间的距离远大于行星本身的大小，所以太阳系的图大多不按比例画。\n"
            "【第 5 页】\n小行星带位于火星与木星轨道之间，那里有大量形状不规则的岩石天体。\n")
    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, body, title="干净教材")
    health = up["text_health"]

    assert health["grade"] == "好", health
    _assert_plain_chinese(health["summary_zh"])
    assert "直接用" in health["summary_zh"], health["summary_zh"]
    # 四个指标都在（用户想知道"读了多干净"，但结论是那句人话）
    ex = health["extract"]
    for key in ("unrecognized_ratio", "broken_space_ratio", "formula_symbols",
                "images", "image_pages"):
        assert key in ex, key
    assert ex["unrecognized_ratio"] < 0.005 and ex["images"] == 0
    # 列表接口口径一致（两处同源，不各说一套）
    listed = [m for m in materials(app_client, sid) if m["id"] == up["id"]][0]
    assert listed["text_health"]["grade"] == "好"
    assert listed["text_health"]["summary_zh"] == health["summary_zh"]


# ============================================================ A2 脏材料 → 差 + 为什么

def test_r55_a2_polluted_extract_grades_bad_and_still_reports_after_fix(app_client, sids):
    """**A-②**：抽得脏（认不出 ≥5%）→ 判「差」并说清后果；
    **即使已经把文本修好了**，体检仍如实反映"这份 PDF 抽出来有多脏"。"""
    clean_body = "【第 1 页】\n" + "太阳系由太阳和八大行星组成，行星沿椭圆轨道运行。" * 12
    raw = clean_body + PUA_UNKNOWN * 60          # 真实材料同款：私用区字形 → 认不出
    fixed = _clean(raw)
    assert PUA_UNKNOWN not in fixed, "抽取修正应该已经把这批认不出的字形处理掉"

    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, fixed, title="抽得脏的教材", raw_text=raw)
    health = up["text_health"]

    assert health["grade"] == "差", health          # 体检照**原始抽取**算
    assert health["extract"]["unrecognized"] >= 60
    assert health["fixed"] is True                  # 同时如实说"已做抽取修正"
    _assert_plain_chinese(health["summary_zh"])
    assert "认不出" in health["summary_zh"] and "%" in health["summary_zh"], health["summary_zh"]
    assert any(k in health["summary_zh"] for k in ("建议", "换", "文字识别")), health["summary_zh"]


# ============================================================ A3 扫描版老口径不许被覆盖

def test_r55_a3_scanned_material_keeps_r37_honest_path(app_client, sids):
    """**A-③**：几乎没读到文字的材料 → R37 的"扫描件"结论原样保留（体检不掩盖它）。"""
    thin = "".join(f"【第 {i} 页】\n几。\n" for i in range(1, 7))
    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, thin, title="扫描版教材")
    health = up["text_health"]

    for key in ("pages", "chars", "chars_per_page", "text_page_ratio", "healthy", "checked",
                "note", "extract", "grade", "summary_zh"):
        assert key in health, key
    assert health["healthy"] is False and health["checked"] is True
    assert "扫描" in health["note"] and "OCR" in health["note"], health["note"]
    assert "文字识别" in health["summary_zh"] or "OCR" in health["summary_zh"], health["summary_zh"]
    _assert_plain_chinese(health["summary_zh"])
    # 页数太少的粘贴文本仍按老口径"未判定"（不许把短材料写成扫描件）
    short = upload_text_material(app_client, sid, "一句话的材料。", title="短材料")["text_health"]
    assert short["checked"] is False and short["healthy"] is True


# ============================================================ A4 判档阈值 + 图片不改档

def test_r55_a4_grade_thresholds_are_where_we_say_they_are():
    """**A-④**：三档的分界线（写成测试，别只写在文档里）。"""
    ok = extract_quality("甲" * 1000, pages=10, images=0, image_pages=0)
    assert ok["grade"] == "好", ok
    # 认不出 0.4% → 仍是好；0.5% → 一般；6% → 差
    warn_line = extract_quality("甲" * 996 + BAD_CHAR * 4, pages=10, images=0, image_pages=0)
    assert warn_line["grade"] == "好", warn_line
    warn = extract_quality("甲" * 995 + BAD_CHAR * 5, pages=10, images=0, image_pages=0)
    assert warn["grade"] == "一般", warn
    bad = extract_quality("甲" * 940 + BAD_CHAR * 60, pages=10, images=0, image_pages=0)
    assert bad["grade"] == "差", bad
    # 拆字空格：**判档用的是"拆得厉害的行"占比**（一行 ≥3 处），偶尔一处不判低
    # （真实材料：3,621/4,664 行有拆字（77.6%），其中拆得厉害的 3,055 行（65.5%）→ 判「一般」）
    heavy_lines = ["行 星 科 学 与 太 阳 系" if i < 6 else "行星科学与太阳系" for i in range(10)]
    heavy = extract_quality("\n".join(heavy_lines), pages=10, images=0, image_pages=0)
    assert heavy["broken_space_heavy_ratio"] == 0.6 and heavy["grade"] == "一般", heavy
    light = extract_quality("\n".join(["行 星 科 学 与 太 阳 系" if i < 2 else "行星科学与太阳系"
                                       for i in range(10)]), pages=10, images=0, image_pages=0)
    assert light["broken_space_heavy_ratio"] == 0.2 and light["grade"] == "一般", light
    fewer = extract_quality("\n".join(["行 星 科 学 与 太 阳 系" if i < 1 else "行星科学与太阳系"
                                       for i in range(10)]), pages=10, images=0, image_pages=0)
    assert fewer["broken_space_heavy_ratio"] == 0.1 and fewer["grade"] == "好", fewer


def test_r55_a4_images_never_change_the_grade_only_add_a_sentence():
    """**A-④**：图片数**不参与判档**，只让体检多说一句"这些图我读不到"。"""
    text = "【第 1 页】\n行星是围绕恒星运行的天体。\n"
    without = text_health(text)
    with_images = text_health(text, quality=extract_quality(text, pages=1, images=47,
                                                            image_pages=20))
    assert without["grade"] == with_images["grade"] == "好"
    assert with_images["extract"]["images"] == 47 and with_images["extract"]["image_pages"] == 20
    assert "47 张图" in with_images["summary_zh"], with_images["summary_zh"]
    assert "读不到" in with_images["summary_zh"], with_images["summary_zh"]
    _assert_plain_chinese(with_images["summary_zh"])


def test_r55_a4_metrics_are_stable_on_repeated_reads(app_client, sids):
    """**A-④**：同一份材料反复体检 → 数字与结论一字不变（体检不写状态、不带时间戳）。"""
    sid = make_subject(app_client, sids)
    up = upload_text_material(app_client, sid, "【第 1 页】\n行星在运行。\n" * 3, title="稳定教材")
    h1 = [m for m in materials(app_client, sid) if m["id"] == up["id"]][0]["text_health"]
    h2 = [m for m in materials(app_client, sid) if m["id"] == up["id"]][0]["text_health"]
    assert h1 == h2, (h1, h2)
