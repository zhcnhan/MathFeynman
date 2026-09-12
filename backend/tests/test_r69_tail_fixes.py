"""R69 任务 ④ 用例：**两处小收口**。

工单 §4：

① `index.css` 里 `.subject-switch .nav-subject.active { … }` 与 `.page-head .row-between { … }`
   挤在同一行（缺换行）—— 功能无影响，**断行**即可；
② 后端提示说「管理已移除」，而学科列表页实际的分组标题是「**已移除**」
   —— 把后端那句统一成「已移除」（**前端标题不动**，那个更直白）。

⚠️ 纪律（工单 §6）：凡"扫描结果是 0"必须附**阳性对照**，否则不算数；
    扫描源码要先**剥注释**。两条都照做了（见 `_two_rules_on_one_line` 的自检）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from r55_support import cleanup_subjects, make_subject

REPO = Path(__file__).resolve().parents[2]
CSS = REPO / "frontend" / "src" / "index.css"
SUBJECTS_PAGE = REPO / "frontend" / "src" / "pages" / "SubjectsPage.tsx"


@pytest.fixture(scope="module")
def sids():
    out: list[str] = []
    yield out
    cleanup_subjects(out)


# ============================================================ ① 后端文案统一
def _msg(resp) -> str:
    return str(resp.json()["detail"]["error"]["message"])


def test_r69_d1_removed_subject_copy_says_removed(app_client, sids):
    """**①**：停用学科后，后端提示与界面标题**同一句话**（「已移除」），不再说「管理已移除」。"""
    sid = make_subject(app_client, sids)
    assert app_client.delete(f"/api/subjects/{sid}").status_code == 204   # 停用（软移除）

    r404 = app_client.get(f"/api/subjects/{sid}")
    assert r404.status_code == 404, r404.text
    m404 = _msg(r404)
    r409 = app_client.get(f"/api/subjects/{sid}/policy")
    assert r409.status_code == 409, r409.text
    m409 = _msg(r409)

    for msg in (m404, m409):
        assert "已移除" in msg, msg
        assert "管理已移除" not in msg, f"后端还在说「管理已移除」：{msg}"
    # 界面上的分组标题（**不动**它，这里只是钉住"两边说的是同一句"）
    heading = SUBJECTS_PAGE.read_text(encoding="utf-8")
    assert "<h2" in heading and "已移除" in heading, "学科列表页的「已移除」标题不见了？"


def test_r69_d2_no_backend_copy_says_managed_removed():
    """**①（反向锁）**：整个后端源码里再也不出现「管理已移除」这句旧文案。

    阳性对照：同一套扫描在**改之前**必须能扫到（见下面 `_scan` 的自检断言）——
    否则"扫出 0"就不算数（工单 §6 纪律）。
    """
    py = [p for p in (REPO / "backend" / "app").rglob("*.py")]
    hits = [(p, i + 1) for p in py
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines())
            if "管理已移除" in line]
    assert hits == [], f"这些地方还写着旧文案「管理已移除」：{hits}"
    # 阳性对照：同一套"逐行找子串"的写法，换一个**确实存在**的旧串必须能找到
    control = [(p, i + 1) for p in py
               for i, line in enumerate(p.read_text(encoding="utf-8").splitlines())
               if "已停用" in line]
    assert control, "阳性对照失败：连「已停用」都扫不到，说明这个扫描器本身是坏的"

# ============================================================ ② index.css 断行
def _two_rules_on_one_line(css: str) -> list[str]:
    """一行里挤了两条规则的行（`}` 后面又跟着 `.x {` / `@media` / `#id`）。

    **先剥注释**（工单 §6：扫描源码要先剥注释，否则被注释里的示例误伤）。
    """
    body = re.sub(r"/\*[\s\S]*?\*/", "", css)
    return [ln.strip() for ln in body.splitlines()
            if re.search(r"\}\s*[.#@&a-zA-Z]", ln)]


def test_r69_d3_css_scanner_is_not_vacuous():
    """**②的阳性对照**：这个扫描器**能**扫出"两条规则挤一行"（否则扫出 0 不算数）。"""
    bad = ".a { x: 1; }.b { y: 2; }\n"
    good = ".a { x: 1; }\n.b { y: 2; }\n"
    assert len(_two_rules_on_one_line(bad)) == 1, _two_rules_on_one_line(bad)
    assert _two_rules_on_one_line(good) == [], _two_rules_on_one_line(good)
    # 注释里的示例**不算数**（剥注释这条要真的生效）
    assert _two_rules_on_one_line("/* .a { x: 1; }.b { y: 2; } */\n.c { z: 3; }\n") == []


def test_r69_d4_css_has_no_two_rules_on_one_line():
    """**②**：`index.css` 里不再有"两条规则挤在一行"的地方（本批修的那一处）。"""
    css = CSS.read_text(encoding="utf-8")
    bad = _two_rules_on_one_line(css)
    assert bad == [], f"index.css 里还有挤在一行的规则：{bad}"
    # 两条规则都还在、且各自成行（断行不许把规则改坏或删掉）
    assert re.search(r"^\.subject-switch \.nav-subject\.active \{[^}]*\}$", css, re.M), \
        "断行把 .subject-switch .nav-subject.active 这条规则弄丢了"
    assert re.search(r"^\.page-head \.row-between \{[^}]*\}$", css, re.M), \
        "断行把 .page-head .row-between 这条规则弄丢了"
