"""R44 任务 A 用例：**审计全文文件名防碰撞**（R43 §3 揪出的真缺陷）。

缺陷：`service/ai_trace.py::_write_file` 旧实现用 `abs(hash((call_name, at)))` 当唯一后缀——
同一秒内同一调用点 hash 完全相同 → 同名 → `write_text` **静默覆盖**，前几次调用的
完整 prompt/response **永久丢失**（违反 R39 §3「展开即完整」）。

本文件四条必交用例：
- **①同秒同调用点 5 次** → 5 个文件，内容不串、都不丢（`test_r44_a1_*`）；
- **②同秒不同调用点 3 个** → 3 个文件（回归，`test_r44_a2_*`）；
- **③重试场景**（`test_r44_a3_*`）：本批口径＝**每次尝试各留一个完整文件**，
  不覆盖已落的失败痕迹、也不合并（provider 对重试循环合成一条审计，多次 `write_trace`
  只可能来自不同调用/不同重试轮，合并会再次丢证据）；
- **④预置同名文件** → **不被静默覆盖**（换名 + 中文账目，`test_r44_a4_*`）。
另加：同秒换名也要记账（`a5`）、`ai_logs` 契约不变（`a6`）。
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from app.service import ai_trace
from app.service.ai_trace import OUTCOME_ADOPTED, OUTCOME_FAILED, write_trace

# 冻结时钟：所有审计写入落在**同一秒**（严格复现"同秒"前件，不受机器快慢影响）
FIXED = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)
STAMP = "20260304T050607Z"
NAME_RE = re.compile(r"^\d{8}T\d{6}Z-[\w_]+(-\d{2,4})?\.txt$")


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """审计全文目录指向临时目录（不碰真实 `.runtime/ai_trace`）＋ 冻结时钟 ＋ 清空同秒序号。"""
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return FIXED if tz else FIXED.replace(tzinfo=None)

    monkeypatch.setattr(ai_trace, "datetime", _Frozen)
    with ai_trace._SEQ_LOCK:
        ai_trace._SEQ_BY_KEY.clear()
    yield d
    with ai_trace._SEQ_LOCK:
        ai_trace._SEQ_BY_KEY.clear()


def _write(call_name: str, i: int, *, subject_id: str = "r44", **kw) -> dict:
    """一次 `write_trace`（走默认 sink → 真落 `ai_logs` 元数据）。"""
    return write_trace(
        call_name=call_name, system=f"SYS-{i}", user=f"USER-{i}", raw=f'{{"i":{i}}}',
        parsed={"i": i}, ok=True, model="m", tier="fast", latency_ms=i * 10,
        prompt_tokens=i, completion_tokens=i, outcome=OUTCOME_ADOPTED,
        subject_id=subject_id, prompt_versions=f"default:{call_name}", **kw)


def _body(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _user_segment(body: str) -> str:
    head = "==== 发给 AI 的完整内容 · user ====\n"
    i = body.find(head)
    assert i >= 0, body[:300]
    return body[i + len(head):].split("\n\n====", 1)[0]


def _names(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("*.txt"))


def _ledger_rows(*, kind: str = "") -> list[dict]:
    """读账本（新会话，读已提交真相）。"""
    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        rows = (db.query(models.ContentLedger)
                .filter(models.ContentLedger.category == "other")
                .order_by(models.ContentLedger.id.desc()).all())
        out = [{"id": int(r.id), "object": r.object or "", "reason": r.reason or "",
                "detail": dict(r.detail_json or {})} for r in rows]
    if kind:
        out = [r for r in out if r["detail"].get("kind") == kind]
    return out


def test_r44_a1_same_second_same_call_site_five_calls_five_files(app_client, trace_dir):
    """**必交①**：同秒内同一调用点连调 5 次 → **5 个文件**，文件名可读且**内容不串、都不丢**。"""
    results = [_write("answer_question", i, subject_id="r44a1") for i in range(1, 6)]

    names = _names(trace_dir)
    want = [f"{STAMP}-answer_question.txt"] + [
        f"{STAMP}-answer_question-{n:02d}.txt" for n in range(2, 6)]
    assert names == sorted(want), f"同秒 5 次应落 5 个可读文件名；实际 {names}"
    assert all(NAME_RE.match(n) for n in names), names

    paths = [r["trace_path"] for r in results]
    assert len(set(paths)) == 5, f"5 次返回的文件路径必须互不相同；实际 {paths}"
    assert all(r["wrote_file"] for r in results)

    # 每次写入的内容必须落在**自己**的文件里（不串、不丢）
    for i, r in enumerate(results, start=1):
        body = _body(r["trace_path"])
        assert f"SYS-{i}" in body, f"第 {i} 次的 system 丢了：{r['trace_path']}"
        assert _user_segment(body) == f"USER-{i}", f"第 {i} 次内容串了：{r['trace_path']}"
        assert f'{{"i":{i}}}' in body, f"第 {i} 次的原始返回丢了"
        assert body.count("==== 解析/校验结果 ====") == 1

    # DB 侧（`ai_logs` 契约不变）：5 条记录各自指向自己的文件，逐个都真实存在
    rows = app_client.get("/api/ai-traces?subject_id=r44a1").json()["items"]
    assert len(rows) == 5, [r["trace_path"] for r in rows]
    assert len({r["trace_path"] for r in rows}) == 5, [r["trace_path"] for r in rows]
    for r in rows:
        assert r["trace_path"] and Path(r["trace_path"]).exists()
    # 旧缺陷形状（`hash()` 后缀 = 6 位数字）不再出现
    assert not [n for n in names if re.search(r"-\d{6,}\.txt$", n)], names


def test_r44_a2_same_second_three_call_sites_three_files(app_client, trace_dir):
    """**必交②（回归）**：同秒内**不同调用点**各落一个文件（原行为不被改坏，且不误加序号）。"""
    a = _write("answer_question", 1, subject_id="r44a2")
    b = _write("feynman_evaluate", 2, subject_id="r44a2")
    c = _write("challenge_exercise", 3, subject_id="r44a2")

    names = _names(trace_dir)
    assert names == sorted([f"{STAMP}-answer_question.txt", f"{STAMP}-feynman_evaluate.txt",
                            f"{STAMP}-challenge_exercise.txt"]), names
    assert len({Path(r["trace_path"]).name for r in (a, b, c)}) == 3
    for want_user, label, r in (("USER-1", "answer_question", a),
                                ("USER-2", "feynman_evaluate", b),
                                ("USER-3", "challenge_exercise", c)):
        assert label in Path(r["trace_path"]).name, r["trace_path"]
        assert _user_segment(_body(r["trace_path"])) == want_user, r["trace_path"]
    rows = app_client.get("/api/ai-traces?subject_id=r44a2").json()["items"]
    assert len(rows) == 3 and len({r["trace_path"] for r in rows}) == 3


def test_r44_a3_retry_attempts_are_kept_separately(app_client, trace_dir):
    """**必交③ 重试场景（本批口径）**：同一次逻辑调用的**每次尝试各留一个完整文件**，
    **既不覆盖**已落的失败痕迹、**也不合并**成一条—— provider 对重试循环合成一条审计
    （R39 §3），故多次 `write_trace` 只可能来自不同调用/不同重试轮，合并会再次丢证据。
    """
    fail1 = write_trace(call_name="unit_content_draft", system="S", user="尝试1",
                        raw="这不是 JSON", parsed=None,
                        parse_error="输出校验失败: JSON 解析失败", retries=0, ok=False,
                        outcome=OUTCOME_FAILED, subject_id="r44a3",
                        prompt_versions="default:unit_content_draft")
    fail2 = write_trace(call_name="unit_content_draft", system="S", user="尝试2",
                        raw="仍不是 JSON", parsed=None,
                        parse_error="输出校验失败: JSON 解析失败", retries=1, ok=False,
                        outcome=OUTCOME_FAILED, subject_id="r44a3",
                        prompt_versions="default:unit_content_draft")
    ok = write_trace(call_name="unit_content_draft", system="S", user="尝试3",
                     raw='{"lecture":"x"}', parsed={"lecture": "x"}, retries=2, ok=True,
                     outcome=OUTCOME_ADOPTED, subject_id="r44a3",
                     prompt_versions="default:unit_content_draft")

    names = _names(trace_dir)
    assert names == sorted([f"{STAMP}-unit_content_draft.txt"] +
                           [f"{STAMP}-unit_content_draft-{n:02d}.txt" for n in (2, 3)]), names
    # 三次尝试各留一份，失败痕迹与最终成功**都在**
    for r, want_user in ((fail1, "尝试1"), (fail2, "尝试2"), (ok, "尝试3")):
        assert _user_segment(_body(r["trace_path"])) == want_user, r["trace_path"]
    assert "结局：失败" in _body(fail1["trace_path"])
    assert "结局：失败" in _body(fail2["trace_path"])
    assert "结局：采纳" in _body(ok["trace_path"])
    assert "重试次数：2" in _body(ok["trace_path"])
    rows = app_client.get("/api/ai-traces?subject_id=r44a3").json()["items"]
    assert len(rows) == 3 and len({r["trace_path"] for r in rows}) == 3
    assert sum(1 for r in rows if r["outcome"] == OUTCOME_FAILED) == 2


def test_r44_a4_preexisting_same_name_not_silently_overwritten(app_client, trace_dir):
    """**必交④**：人为预置同名文件 → **不被静默覆盖**（换名写新文件 + 中文账目说明）。"""
    trace_dir.mkdir(parents=True, exist_ok=True)
    base = trace_dir / f"{STAMP}-answer_question.txt"
    base.write_text("我已存在（人为预置，不得被覆盖）", encoding="utf-8")

    res = _write("answer_question", 9, subject_id="r44a4")

    assert base.read_text(encoding="utf-8") == "我已存在（人为预置，不得被覆盖）", \
        "预置文件被覆盖了（静默覆盖 = 缺陷）"
    final = Path(res["trace_path"])
    assert final.name != base.name, "目标名被占用时必须换名"
    assert final.exists() and _user_segment(_body(str(final))) == "USER-9"
    assert final.name == f"{STAMP}-answer_question-02.txt", final.name
    # 账本必须留一条**中文**原因（换名以免覆盖），detail 可追溯
    hit = _ledger_rows(kind="trace_name_renamed")
    assert hit, "换名必须记账（不许静默）"
    row = hit[0]
    assert "已被占用" in row["reason"] and "换名" in row["reason"], row["reason"]
    assert "人为预置" in row["reason"] or "另一进程" in row["reason"], row["reason"]
    assert any("\u4e00" <= ch <= "\u9fff" for ch in row["reason"])
    assert row["detail"]["final_name"] == final.name
    assert row["detail"]["base_name"] == base.name
    # 总账页「其它」类别里看得见
    api = app_client.get("/api/ledger?category=other").json()
    assert any((e.get("detail") or {}).get("kind") == "trace_name_renamed"
               for e in api["entries"]), api["entries"][:3]


def test_r44_a5_same_second_rename_is_also_accounted(app_client, trace_dir):
    """同秒第 2 次写入（正常换名）**也要记账**：写明"同一秒/不被覆盖"，不是静默改名。"""
    _write("explain_node", 1, subject_id="r44a5")
    _write("explain_node", 2, subject_id="r44a5")
    hit = _ledger_rows(kind="trace_name_renamed")
    assert hit, [(r["object"], r["reason"][:40]) for r in _ledger_rows()[:3]]
    assert "同一秒" in hit[0]["reason"] and "不被覆盖" in hit[0]["reason"], hit[0]["reason"]
    assert hit[0]["detail"]["final_name"].endswith("-02.txt")


def test_r44_a6_db_contract_unchanged(app_client, trace_dir):
    """**别动 DB 契约**：`/ai-traces` 列表与详情的响应形状不变，详情仍能展开全文。"""
    res = _write("answer_question", 7, subject_id="r44a6")
    lst = app_client.get("/api/ai-traces?subject_id=r44a6").json()
    for key in ("items", "count", "total", "call_sites", "outcomes", "trace_dir", "keep_days"):
        assert key in lst, key
    row = lst["items"][0]
    for key in ("id", "at", "call_name", "subject_id", "unit_id", "tier", "model", "ok",
                "outcome", "retries", "trace_path", "trace_chars", "system_preview",
                "user_preview", "response_preview", "parse_result", "prompt_versions"):
        assert key in row, key
    assert row["trace_path"] == res["trace_path"] and row["trace_chars"] == res["trace_chars"]
    detail = app_client.get(f"/api/ai-traces/{row['id']}").json()
    assert detail["file_exists"] is True
    assert detail["full"]["user"] == "USER-7"
    assert detail["full"]["system"] == "SYS-7"
    assert detail["note"] == ""
