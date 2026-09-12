"""R52 任务 A 用例：提示词页 **A（默认显示 user 模板）+ C（说清"多处共用同一份"）**。

用户的实际困惑：页面上连点几个调用点，编辑器里都是 system 模板，而 **system 在多个调用点之间
共用同一份文本**（实测：15 个调用点只有 **6** 份不同 system；user 则 15 份互不相同），
于是看着"提示词都是同一个"。

本批：① 默认选 **user 模板**（每个调用点各不相同的那一半）；② 界面上把"共用"直接说白，
   N 由**后端只读字段** `system_shared_with` 给出（算法＝与当前调用点 system 文本完全相同的
   其它调用点数；`user_shared_with` 同法）。
**红线**：只新增只读字段，既有字段/接口结构不变。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PAGE = REPO_ROOT / "frontend" / "src" / "pages" / "PromptsPage.tsx"

# R52 A2 点名的"独有 system"调用点（架构侧清单；实测 system_shared_with == 0）
UNIQUE_SYSTEM_CALLS = ("classify_error", "outline_draft", "unit_content_draft")

_EXISTING_KEYS = (
    "call_name", "label", "purpose", "notes", "system", "default_system", "raw_template",
    "default_raw_template", "system_is_default", "system_diff", "user", "default_user",
    "raw_user_template", "default_raw_user_template", "user_is_default", "user_diff",
    "editable_fields", "is_default", "updated_at", "required_placeholders", "required_tokens",
    "placeholders", "user_required_placeholders", "user_required_tokens",
)


def test_r52_a1_system_shared_count_matches_actual_texts(app_client):
    """**必交②（后端半）**：`system_shared_with` 与"文本完全相同的其它调用点数"逐一吻合，
    且点名的独有 system 调用点为 0。

    **R56 更新**：新增了调用点「读教材页/图」+ 图示教材模式的 8 个环节（工单 §4-B1 要求），
    所以调用点数 15 → **24**、互不相同的 user 数 15 → **24**、互不相同的 system 6 → **15**；
    "最大一组 10 处共用 system"这个分组事实不变——新增那些都是**自带 system** 的独立调用点
    （模式内 8 条共用 `_MODE_COMMON` 前缀但整段文本各不相同）。

    **R67 更新**：新增了调用点「读教材页/图（一次几页）」（一次几页的**批量读**，工单 §6），
    它同样**自带 system 与 user**（一页一条记录的硬口径写在这份提示词里），
    所以调用点数 24 → **25**、互不相同的 user 数 24 → **25**；system 分组事实不变（15 份）。
    """
    data = app_client.get("/api/prompts").json()
    items = data["prompts"]
    assert len(items) == 25, len(items)
    for it in items:
        assert isinstance(it.get("system_shared_with"), int), it.get("call_name")
        assert isinstance(it.get("user_shared_with"), int), it.get("call_name")

    # 与"当前文本"逐一自洽（不依赖注册表内部实现）
    for it in items:
        sys_n = sum(1 for o in items
                    if o["call_name"] != it["call_name"]
                    and o["raw_template"] == it["raw_template"])
        usr_n = sum(1 for o in items
                    if o["call_name"] != it["call_name"]
                    and it["raw_user_template"]
                    and o["raw_user_template"] == it["raw_user_template"])
        assert it["system_shared_with"] == sys_n, (it["call_name"], it["system_shared_with"], sys_n)
        assert it["user_shared_with"] == usr_n, (it["call_name"], it["user_shared_with"], usr_n)

    # 事实锚点（R52 立案实测）：15 个调用点只有 6 份不同 system；最大一组 10 处共用（＝ N=9）
    # **R56 更新**：新增的 9 条（读页 + 模式 8 环节）各自带 system → 不同 system 6 → 15；
    # 共用分组不变（仍是那 10 条路径②调用点共用一份）。
    # **R67 更新**：批量读（一次几页）也自带 system → 不同 system 15 → **16**；共用分组不变。
    assert len({it["raw_template"] for it in items}) == 16
    biggest = max(it["system_shared_with"] for it in items)
    assert biggest == 9, biggest
    assert sum(1 for it in items if it["system_shared_with"] == biggest) == 10
    # user 互不相同 → 每处 user_shared_with 都是 0（界面上"每处都不一样"这句话是真的）
    assert len({it["raw_user_template"] for it in items}) == 25
    assert all(it["user_shared_with"] == 0 for it in items)
    # 独有 system 的调用点（界面应显示"只有这一处在用"）
    for name in UNIQUE_SYSTEM_CALLS + ("read_page", "read_pages", "mode_judge", "mode_lesson",
                                       "mode_outline"):
        hit = next(it for it in items if it["call_name"] == name)
        assert hit["system_shared_with"] == 0, hit["call_name"]


def test_r52_a2_prompts_page_defaults_to_user_and_says_scope(app_client):
    """**必交②（前端半，源码级）**：默认字段是 **user**；system 栏提示写明"共用 N 处"
    且明确"只影响当前调用点"。"""
    src = PROMPTS_PAGE.read_text(encoding="utf-8")
    assert re.search(r'useState<"system" \| "user">\(\s*"user"\s*\)', src), \
        "进入页面应默认选 user 模板（R52 A1）"
    assert "system_shared_with" in src and "user_shared_with" in src
    assert "只影响" in src, "必须写明「在这里改只影响当前调用点」（共用文本 ≠ 改一处全变）"
    assert "共用" in src and "只有这一处在用" in src, "N=0 时要显示「只有这一处在用」（R52 A2）"
    assert "这次具体怎么干活" in src and "角色与总纪律" in src, "两个字段要用大白话标出各自性质（A1）"


def test_r52_a3_existing_contract_untouched(app_client):
    """**红线**：只**新增**两个只读字段——既有字段一个不少、值不变。"""
    data = app_client.get("/api/prompts").json()
    assert set(data) == {"prompts", "count", "changed"}, set(data)
    for it in data["prompts"]:
        missing = [k for k in _EXISTING_KEYS if k not in it]
        assert not missing, (it["call_name"], missing)
    # 只读字段不参与"是否已改"的判定（改提示词不会让 is_default 抖动）
    one = data["prompts"][0]
    assert one["is_default"] is (one["system_is_default"] and one["user_is_default"])
