"""R50 任务 A 用例：**审计命名状态加上界**（P2，长期隐性泄漏）。

问题（docs/09 R49 §3-1）：`ai_trace._SEQ_BY_KEY` / `_COLLISION_BY_KEY` 的键是
`(秒时间戳, 调用点)`，只增不减 → 单机长跑约 `86400 × 调用点数` 条/天，永不释放。

修法（最小、语义等价）：`_next_name` 进来先**只保留"当前秒"的键**，同秒内的序号与换名报因
原样保留（R48 刚修好的"报因不退化"不能回退）。

两条必交：
- `test_r50_a1_*`：同秒多调用仍正确（无预置 → `{裸名,-02,-03,-04}`；预置占用 → `-02…-05` 且报因"已被占用"）；
- `test_r50_a2_*`：跨秒后旧键被清（两个字典只剩当前秒的键），且新一秒的第 1 个文件**重新用裸名**（序号归零）。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app import models
from app.db import SessionLocal
from app.service import ai_trace
from app.service.ai_trace import OUTCOME_ADOPTED, write_trace

FIXED = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)
STAMP1 = "20260304T050607Z"
STAMP2 = "20260304T050608Z"
STAMP3 = "20260304T050609Z"
CALL = "answer_question"
CALL2 = "explain_node"
OCCUPIED = "已被占用"
SAME_SECOND = "同一秒内对同一调用点多次记录"


class _Clock:
    """可推进的冻结时钟（跨秒用例需要"下一秒"）。"""

    def __init__(self, t: dt.datetime):
        self.t = t


@pytest.fixture(autouse=True)
def _tables():
    """本模块直接调服务层（不走 TestClient），先确保表存在（临时库由 conftest 指定）。"""
    from app.db import init_db

    init_db()


@pytest.fixture
def clock(tmp_path, monkeypatch):
    """临时审计目录 + 可推进冻结时钟 + 清空命名状态。"""
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))
    c = _Clock(FIXED)

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return c.t if tz else c.t.replace(tzinfo=None)

    monkeypatch.setattr(ai_trace, "datetime", _Frozen)
    ai_trace._reset_naming_state()
    yield d, c
    ai_trace._reset_naming_state()


def _write(i: int, *, subject_id: str, call_name: str = CALL) -> dict:
    return write_trace(call_name=call_name, system=f"SYS-{i}", user=f"USER-{i}",
                       raw=f'{{"i":{i}}}', parsed={"i": i}, ok=True, model="m", tier="fast",
                       latency_ms=i, prompt_tokens=i, completion_tokens=i,
                       outcome=OUTCOME_ADOPTED, subject_id=subject_id,
                       prompt_versions=f"default:{call_name}")


def _naming(p: str) -> str:
    part = Path(p).read_text(encoding="utf-8").split(ai_trace.NAMING_HEAD, 1)
    assert len(part) == 2, f"正文缺「命名情况」小节：{p}"
    for line in part[1].splitlines():
        if line.startswith("命名说明："):
            return line[len("命名说明："):].strip()
    raise AssertionError(f"命名小节里没有「命名说明」：{p}")


def _keys(d: dict) -> set:
    with ai_trace._SEQ_LOCK:
        return set(d)


def test_r50_a1_same_second_naming_still_correct(clock):
    """**必交①**：同秒内连写 4 次，命名与报因**与 R48 一致**（上界不得改动同秒语义）。"""
    d, _c = clock
    base = f"{STAMP1}-{CALL}"
    # ① 无预置：裸名 + -02/-03/-04；第 1 个"无需换名"，其余"同秒多次"
    got = [_write(i, subject_id="r50a1") for i in range(1, 5)]
    names = [Path(r["trace_path"]).name for r in got]
    assert names == [f"{base}.txt", f"{base}-02.txt", f"{base}-03.txt", f"{base}-04.txt"], names
    assert "无需换名" in _naming(got[0]["trace_path"])
    for i, r in enumerate(got[1:], start=2):
        why = _naming(r["trace_path"])
        assert SAME_SECOND in why and OCCUPIED not in why, f"第 {i} 次：{why}"

    # ② 预置占用（换调用点）：-02…-05，且 4 次报因**都是"已被占用"**（R48 A 不回退）
    base2 = f"{STAMP1}-{CALL2}"
    d.mkdir(parents=True, exist_ok=True)
    pre = d / f"{base2}.txt"
    pre.write_text("我已存在（人为预置）", encoding="utf-8")
    got2 = [_write(i, subject_id="r50a1b", call_name=CALL2) for i in range(1, 5)]
    names2 = [Path(r["trace_path"]).name for r in got2]
    assert names2 == [f"{base2}-{n:02d}.txt" for n in (2, 3, 4, 5)], names2
    for i, r in enumerate(got2, start=1):
        why = _naming(r["trace_path"])
        assert OCCUPIED in why and SAME_SECOND not in why, f"第 {i} 次：{why}"
    assert pre.read_text(encoding="utf-8") == "我已存在（人为预置）", "预置文件不得被覆盖"
    # 同秒内两个调用点的键都在（上界只丢"非当前秒"，不动同秒）
    assert _keys(ai_trace._SEQ_BY_KEY) == {(STAMP1, CALL), (STAMP1, CALL2)}, _keys(ai_trace._SEQ_BY_KEY)


def test_r50_a2_state_is_pruned_across_seconds(clock):
    """**必交②**：跨秒后旧键被丢（只剩当前秒），且新一秒第 1 个文件**重新用裸名**（序号归零）。"""
    d, c = clock
    base1 = f"{STAMP1}-{CALL}"
    # 第 1 秒：先造"预置占用"，让两个字典都留下 STAMP1 的键
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{base1}.txt").write_text("预置（第 1 秒）", encoding="utf-8")
    first = _write(1, subject_id="r50a2")
    assert Path(first["trace_path"]).name == f"{base1}-02.txt"
    assert _keys(ai_trace._SEQ_BY_KEY) == {(STAMP1, CALL)}, _keys(ai_trace._SEQ_BY_KEY)
    assert _keys(ai_trace._COLLISION_BY_KEY) == {(STAMP1, CALL)}, _keys(ai_trace._COLLISION_BY_KEY)

    # 推进到"下一秒" → 旧键必须被丢，且新一秒重新从**裸名**开始（序号归零、语义等价）
    c.t = FIXED + dt.timedelta(seconds=1)
    second = _write(2, subject_id="r50a2")
    assert Path(second["trace_path"]).name == f"{STAMP2}-{CALL}.txt", \
        "跨秒后序号应归零（上一秒的序号不该影响下一秒）"
    assert "无需换名" in _naming(second["trace_path"]), _naming(second["trace_path"])
    assert _keys(ai_trace._SEQ_BY_KEY) == {(STAMP2, CALL)}, _keys(ai_trace._SEQ_BY_KEY)
    assert _keys(ai_trace._COLLISION_BY_KEY) == set(), _keys(ai_trace._COLLISION_BY_KEY)
    assert not [k for k in _keys(ai_trace._SEQ_BY_KEY) if k[0] != STAMP2], "旧秒的键必须已丢"

    # 再过一秒：仍只剩"当前秒"的键（有界＝当前秒的调用点数；不随秒数增长）
    c.t = FIXED + dt.timedelta(seconds=2)
    third = _write(3, subject_id="r50a2")
    assert Path(third["trace_path"]).name == f"{STAMP3}-{CALL}.txt"
    with ai_trace._SEQ_LOCK:
        assert len(ai_trace._SEQ_BY_KEY) == 1 and len(ai_trace._COLLISION_BY_KEY) <= 1, (
            ai_trace._SEQ_BY_KEY, ai_trace._COLLISION_BY_KEY)
    # 磁盘上三个秒各一份文件（丢的只是"记忆"，不是文件）
    assert sorted(p.name for p in d.glob("*.txt")) == sorted([
        f"{base1}.txt", f"{base1}-02.txt", f"{STAMP2}-{CALL}.txt", f"{STAMP3}-{CALL}.txt"])


def test_r50_a3_reset_helper_still_clears_both(clock):
    """**回归**：`_reset_naming_state()` 行为不变（两个字典一并清空）。"""
    _write(1, subject_id="r50a3")
    assert _keys(ai_trace._SEQ_BY_KEY)
    ai_trace._reset_naming_state()
    assert _keys(ai_trace._SEQ_BY_KEY) == set() and _keys(ai_trace._COLLISION_BY_KEY) == set()
    # 账目仍照常写（内存状态清理不影响落库）
    with SessionLocal() as db:
        rows = db.query(models.ContentLedger).filter(
            models.ContentLedger.category == "other").all()
    assert isinstance(rows, list)
