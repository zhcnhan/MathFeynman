"""R54 任务 C 用例：**「35 个单元只有 2 个有内容」要看得见**（P1）。

- 大纲页/覆盖账必须一眼看出哪些单元**已有内容**、哪些**还没有**（`has_content` / `usable` /
  `content_reason_zh`，由**会话守卫同一实现**给出 → 两处口径不会打架）；
- 点"还没内容"的单元 → **不进空会话**（`/session/start` 回 `content_missing` 卡片：
  中文提示 + 一键生成，而不是 404「节点不存在」）；
- 生成后状态**立即更新**（同一次请求周期内就能看到，不靠缓存过期）。
"""
from __future__ import annotations

import pytest

from r54_support import cleanup_subjects, coverage_unit, gen, make_subject, start


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


def test_r54_c1_unit_without_content_is_visible_and_blocks_empty_session(app_client, sids):
    """**C1-①**：还没内容的单元 → 覆盖账一眼看出 + **不进空会话**（中文提示 + 生成入口）。"""
    sid = make_subject(app_client, sids, count=3)
    unit = f"{sid}.u01"                       # 一个单元都不生成

    cov = coverage_unit(app_client, sid, unit)

    assert cov["has_content"] is False and cov["usable"] is False, cov
    assert cov["content_reason_zh"], cov
    assert cov["exercise_count"] == 0 and "还没有生成内容" in cov["content_reason_zh"]
    res = start(app_client, unit)
    assert res["step"] == "content_missing", res["step"]
    assert res["payload"]["content_missing"]["can_generate"] is True
    assert not res["session"]["id"], "还没内容时不该建会话（不许把人带进空会话）"
    for key in ("lecture_md", "exercise", "task_prompt"):
        assert key not in res["payload"], key


def test_r54_c2_unit_with_content_enters_normally(app_client, sids):
    """**C1-②（回归）**：有内容的单元 → 正常进入学习。"""
    sid = make_subject(app_client, sids)
    unit = f"{sid}.u01"
    assert gen(app_client, sid, unit)["status"] == "created"

    cov = coverage_unit(app_client, sid, unit)

    assert cov["has_content"] is True and cov["usable"] is True, cov
    assert cov["exercise_count"] >= 1 and cov["taught_fact_count"] >= 0
    res = start(app_client, unit)
    assert res["step"] == "explain" and str(res["payload"].get("lecture_md") or "").strip()
    assert res["session"]["id"], "有内容时正常建会话"


def test_r54_c3_status_updates_immediately_after_generate(app_client, sids):
    """**C1-③**：生成后大纲页状态**立即更新**（不需要刷新/重启；与覆盖账同源）。"""
    sid = make_subject(app_client, sids, count=1)
    unit = f"{sid}.u01"
    assert coverage_unit(app_client, sid, unit)["has_content"] is False
    assert start(app_client, unit)["step"] == "content_missing"

    assert gen(app_client, sid, unit)["status"] == "created"

    after = coverage_unit(app_client, sid, unit)
    assert after["has_content"] is True and after["usable"] is True, after
    assert start(app_client, unit)["step"] == "explain"
