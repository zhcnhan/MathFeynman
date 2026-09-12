"""R54 任务 B 用例：**丢弃必须有出路**（P0 · "丢完之后就不管了"）。

分级（阈值与理由见 NOTES §76）：
- **严重 → 内容不可用**：讲解为空 / 事实依据全丢（声明过事实句却一条不剩）/
  没有可用练习（正常文件不可能，见 A5 的防御分支）→ 不许进学习流程 + 一键重新生成 + 覆盖账如实标注；
- **轻微 → 仍可用**：只丢了部分题/事实句 → 单元照常学，但界面**如实提示**丢了几道题。

出路：账本每条"可补救"记录在读取时派生 `action`（一键「重新生成这个单元」）；
重新生成成功后追加一条「已重新生成」记录，并把该单元**此前**的丢弃记录标 `resolved`（历史行不改）。
"""
from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.service import ledger
from r54_support import cleanup_subjects, coverage_unit, gen, make_subject, record_coverage, start


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def test_r54_b1_all_facts_dropped_marks_unit_unusable_with_regenerate(app_client, sids):
    """**B3-①（严重）**：事实句全被丢弃 → 判定**不可用** + 中文说明 + 一键重生成入口。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    # 事实句全丢：文件里一条不剩 + 覆盖记录如实记"丢了 6 条"
    from r54_support import patch_node

    patch_node(sid, unit, lambda m: m.update({"taught_facts": []}))
    record_coverage(sid, unit, {"status": "部分", "material_bound": True, "grounded_facts": 0,
                                "dropped_facts": 6, "dropped_exercises": 0, "sources": []})

    cov = coverage_unit(app_client, sid, unit)

    assert cov["has_content"] is True and cov["usable"] is False, cov
    assert "事实" in cov["content_reason_zh"], cov["content_reason_zh"]
    res = start(app_client, unit)
    assert res["step"] == "content_missing", res["step"]
    assert res["payload"]["content_missing"]["can_generate"] is True
    # 丢弃账目就地可点（"重新生成这个单元"），不是只写"可通过重试补救"
    with SessionLocal() as db:      # 真实丢弃记账（形状与生成路径一致）
        ledger.note(ledger.CAT_GENERATION, f"单元内容（{unit}）· 事实句",
                    "6 条「已声明事实句」因教材原文里找不到对应句子被丢弃",
                    impact=ledger.SCOPE_UNIT, remedy=ledger.REMEDY_RETRY,
                    subject_id=sid, unit_id=unit, detail={"kind": "dropped", "count": 6})
        db.commit()
    entries = app_client.get(f"/api/ledger?subject_id={sid}&category=generation").json()["entries"]
    hit = [e for e in entries if e["unit_id"] == unit]
    assert hit and hit[0]["action"]["kind"] == "regenerate_unit", hit
    assert hit[0]["action"]["label_zh"] and hit[0]["action"]["unit_id"] == unit


def test_r54_b2_one_dropped_exercise_keeps_unit_usable_with_hint(app_client, sids):
    """**B3-②（轻微）**：只丢了 1 道题 → **仍可用** + 界面如实提示（不许一刀切禁用）。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    record_coverage(sid, unit, {"status": "部分", "material_bound": True,
                                "grounded_facts": 3, "dropped_facts": 0,
                                "dropped_exercises": 1, "sources": []})

    cov = coverage_unit(app_client, sid, unit)

    assert cov["usable"] is True and cov["has_content"] is True, cov
    assert cov["dropped_exercises"] == 1, cov      # 界面据此提示"1 道题没采用"
    assert cov["content_reason_zh"] == ""
    res = start(app_client, unit)
    assert res["step"] == "explain", "轻微丢弃不该禁用单元"


def test_r54_b3_regenerate_resolves_old_discard_entries(app_client, sids):
    """**B3-③**：重生成后旧丢弃账目**被标记已解决**（不残留旧失败），且**幂等**。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    with SessionLocal() as db:      # 两条"真实的丢弃账目"（remedy=可补救 + 学科/单元）
        for obj in ("单元内容 · 事实句", "单元内容 · 练习题"):
            ledger.note(ledger.CAT_GENERATION, f"{obj}（{unit}）",
                        "测试：因教材原文里找不到对应句子被丢弃",
                        impact=ledger.SCOPE_UNIT, remedy=ledger.REMEDY_RETRY,
                        subject_id=sid, unit_id=unit, detail={"kind": "dropped", "count": 1})
        db.commit()

    before = app_client.get(f"/api/ledger?subject_id={sid}&category=generation").json()["entries"]
    assert len(before) == 2 and all(not e["resolved"] for e in before)
    assert all(e["action"] and e["action"]["kind"] == "regenerate_unit" for e in before), before

    body = gen(app_client, sid, unit)          # 重新生成（内容已在 → exists 路径也会结算）
    assert body["status"] in ("created", "exists"), body

    after = app_client.get(f"/api/ledger?subject_id={sid}&category=generation").json()["entries"]
    old = [e for e in after if (e.get("detail") or {}).get("kind") == "dropped"]
    assert len(old) == 2 and all(e["resolved"] is True for e in old), old
    marks = [e for e in app_client.get(f"/api/ledger?subject_id={sid}&category=other").json()["entries"]
             if (e.get("detail") or {}).get("kind") == "unit_regenerated"]
    assert marks and marks[0]["unit_id"] == unit
    assert "重新生成" in marks[0]["reason"] and "作废" in marks[0]["reason"]

    gen(app_client, sid, unit)                 # 幂等：不再追加"已重新生成"记录
    marks2 = [e for e in app_client.get(f"/api/ledger?subject_id={sid}&category=other").json()["entries"]
              if (e.get("detail") or {}).get("kind") == "unit_regenerated"]
    assert len(marks2) == len(marks), marks2


def test_r54_b4_ledger_contract_only_added(app_client, sids):
    """**B3-④（回归）**：账本既有字段与类别口径**只增不减**（不改语义）。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"
    led = app_client.get(f"/api/ledger?subject_id={sid}").json()
    labels = {c["key"]: c["label"] for c in led["categories"]}
    assert labels["generation"] == "出题与检查" and labels["other"] == "其它"
    for e in led["entries"]:
        assert {"id", "at", "category", "category_label", "subject_id", "unit_id", "object",
                "reason", "impact", "remedy", "detail"} <= set(e)
        assert isinstance(e["detail"], dict)
        assert "action" in e and "resolved" in e     # R54 B 新增的两个键
