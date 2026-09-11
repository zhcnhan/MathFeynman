"""R52 任务 B 用例：**界面文案守卫**（"给用户看的东西一律说人话"）。

来源：用户当面对话（2026-09-11）——"整个程序给用户看的文案要说人话、简洁"；
硬性禁令（工单 §3-B1）：界面上不得出现**内部编号**（`R38`/`§2`/`docs/…`/`Phase X`）、
**字段名/文件名**（`schema`/`batch_chars`/`inject_max_chars`/`trace_path`/`MF_*`），
以及术语表点名的工程黑话（注入/预算/吸纳/落库/降级/丢弃/截断/幂等/溯源/闸门/总账/账本/节点…）。

做法（前端没有测试运行器 → 按工单 §5-1 授权做**源码级**扫描）：见 `ui_copy_guard.py`——
去掉注释后抽"含中文的字符串字面量 + JSX 文本"，逐条查禁用模式。

另：**后端**里"会渲染到界面"的那部分（类别名 / 两个滑块的承诺 / 覆盖账原因 / 提示词页说明）
也一并锁死；后端的中文还有大量是**账目记录与 docstring**，不属本用例守备范围（见 NOTES §75）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui_copy_guard as g  # noqa: E402


def test_r52_b1_frontend_user_text_has_no_internal_ids_or_jargon():
    """**必交①**：前端**所有**会渲染的中文文本里，没有内部编号 / 字段名 / 工程黑话。"""
    findings = g.scan_frontend()
    assert not findings, (
        "界面文案里仍有内部说法（工单 §3-B1/B2 禁用）：\n"
        + "\n".join(str(f) for f in findings[:40])
        + (f"\n…共 {len(findings)} 处" if len(findings) > 40 else ""))


def test_r52_b2_frontend_named_places_use_plain_wording():
    """**必交（点名位置，源码级）**：用户点名的几处确实换成了人话。

    注：**注释**里允许保留技术说法（工单 §1：注释不算"给用户看的东西"），
    故"不许再出现旧说法"这类**否定**断言一律在**去注释后**的源码上做。
    """
    def raw(rel: str) -> str:
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def code(rel: str) -> str:
        return g.strip_comments(raw(rel))

    budget = code("frontend/src/components/MaterialBudgetPanel.tsx")
    assert "读多少书（本学科单独设）" in budget
    assert "每次读多少" in budget and "这本书最多读多少" in budget
    assert "调小只是分成几次读，一章都不会少" in budget
    assert "读到上限就停" in budget and "哪几章没读" in budget
    assert "上次读了" in budget and "万字" in budget
    assert "材料注入预算" not in budget and "承诺不一样" not in budget

    ledger = code("frontend/src/pages/LedgerPage.tsx")
    assert "记录（它做了什么、为什么）" in ledger
    assert "读书情况" in ledger and "出题与检查" in ledger and "问 AI 的情况" in ledger
    assert "章节进度" in ledger

    settings = code("frontend/src/pages/SettingsPage.tsx")
    assert "提示词（可以自己改）" in settings
    assert "高级：查看 AI 对话记录" in settings
    assert "（R39" not in settings and "（R12）" not in settings

    subjects = code("frontend/src/pages/SubjectsPage.tsx")
    assert "新建学科" in subjects and "docs/14" not in subjects

    trace = code("frontend/src/pages/AiTracePage.tsx")
    assert "这一次的完整对话" in trace
    assert "审计文件：" not in trace


def test_r52_b3_backend_ui_labels_are_plain(app_client):
    """**必交（后端直出、前端原样渲染的那部分）**：类别名 / 承诺 / 覆盖原因都是人话。"""
    cats = app_client.get("/api/ledger/cats").json()["categories"]
    labels = [c["label"] for c in cats]
    assert labels == ["读书情况", "出题与检查", "问 AI 的情况", "章节进度", "其它"], labels

    # 两个滑块的承诺（前端直接渲染，见 MaterialBudgetPanel）
    b = app_client.get("/api/subjects/math/budget").json()
    prom = b["promises_zh"]
    assert "一章都不会少" in prom["batch_chars"], prom
    assert "读到上限就停" in prom["inject_max_chars"], prom
    assert "注入" not in prom["batch_chars"] + prom["inject_max_chars"]
    assert b["last_usage"]["summary_zh"].startswith("共读了") or \
        b["last_usage"]["summary_zh"] == "还没有可读的教材"
    assert "一章都不会少" in b["last_usage"]["note_zh"]

    # 提示词页的说明文字（标签/用途/提示）
    items = app_client.get("/api/prompts").json()["prompts"]
    joined = " ".join(f"{i['label']} {i['purpose']} {i.get('notes') or ''}" for i in items)
    for bad in ("R35", "R36", "R37", "R39", "docs/", "§", "溯源", "MVP", "rubric"):
        assert bad not in joined, (bad, joined[:200])
