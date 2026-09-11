"""R48 任务 A 用例：**换名报因不再退化**（P1，R47 §3 架构侧独立复现）。

现象（修复前）：预置一个裸名文件 `<stamp>-<call_name>.txt` 后连写 4 次 —— 文件确实落成
`-02/-03/-04/-05`（无覆盖、序号不重复，三层防护有效），但**只有第 1 次**说得出
"目标文件名已被占用（…人为预置）"，第 2–4 次退化成通用文案"同一秒内对同一调用点多次记录"。

根因：`_next_name` 只在 `seq == 0` 时算出"被占用"的 `why`，**没有把它记在该秒该调用点上** →
第 2 次进来 `seq != 0` → `why` 为空 → 退化成兜底文案。

修法（R48 A，不改编排）：确认"被占用"时**先置位并记住报因**（`_SEQ_BY_KEY` + `_COLLISION_BY_KEY`），
本秒后续每次换名沿用同一原因；"取候选名 → 原子独占 `open(x)` → 失败换名"三层防护原样不动。

三条必交：
- `test_r48_a1_*`：预置裸名 + 连写 4 次 → **4 次的正文与账目都含「已被占用」**；
- `test_r48_a2_*`（回归）：无预置连写 4 次 → 仍全是「**同秒多次**」、**都不含「已被占用」**；
- `test_r48_a3_*`（回归）：文件集合与序号连续、无重复，预置内容原封不动。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app import models
from app.db import SessionLocal
from app.service import ai_trace
from app.service.ai_trace import OUTCOME_ADOPTED, write_trace

# 冻结时钟：所有写入落在**同一秒**（严格复现"同秒"前件）
FIXED = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)
STAMP = "20260304T050607Z"
# 每个用例用**不同调用点**：账目按 base_name 过滤时天然互不串（临时库跨用例共享）
CALL = "challenge_exercise"
CALL_NOPRE = "feynman_evaluate"
CALL_SEQ = "unit_content_draft"
CALL_SEQ2 = "explain_node"
BASE = f"{STAMP}-{CALL}"
OCCUPIED = "已被占用"
SAME_SECOND = "同一秒内对同一调用点多次记录"


@pytest.fixture(autouse=True)
def _tables():
    """本模块直接调服务层（不走 TestClient），先确保表存在（临时库由 conftest 指定）。"""
    from app.db import init_db

    init_db()


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """临时审计目录 + 冻结时钟 + 清空"同秒序号 / 换名报因"记忆。"""
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return FIXED if tz else FIXED.replace(tzinfo=None)

    monkeypatch.setattr(ai_trace, "datetime", _Frozen)
    ai_trace._reset_naming_state()
    yield d
    ai_trace._reset_naming_state()


def _write(i: int, *, subject_id: str, call_name: str = CALL) -> dict:
    return write_trace(call_name=call_name, system=f"SYS-{i}", user=f"USER-{i}",
                       raw=f'{{"i":{i}}}', parsed={"i": i}, ok=True, model="m", tier="fast",
                       latency_ms=i, prompt_tokens=i, completion_tokens=i,
                       outcome=OUTCOME_ADOPTED, subject_id=subject_id,
                       prompt_versions=f"default:{call_name}")


def _naming(p: str) -> str:
    """取正文「命名情况」小节里的那一句 `命名说明`。"""
    part = Path(p).read_text(encoding="utf-8").split(ai_trace.NAMING_HEAD, 1)
    assert len(part) == 2, f"正文缺「命名情况」小节：{p}"
    for line in part[1].splitlines():
        if line.startswith("命名说明："):
            return line[len("命名说明："):].strip()
    raise AssertionError(f"命名小节里没有「命名说明」：{p}")


def _ledger_renames(call_name: str) -> list[dict]:
    """某调用点的换名账目（按 base_name 过滤，天然与其它用例隔离）。"""
    base = f"{STAMP}-{call_name}.txt"
    with SessionLocal() as db:
        rows = (db.query(models.ContentLedger)
                .filter(models.ContentLedger.category == "other")
                .order_by(models.ContentLedger.id.desc()).all())
    return [{"id": int(r.id), "reason": r.reason or "", "detail": dict(r.detail_json or {})}
            for r in rows if (r.detail_json or {}).get("kind") == "trace_name_renamed"
            and (r.detail_json or {}).get("base_name") == base]


def test_r48_a1_every_write_reports_occupied_when_bare_name_preexists(trace_dir):
    """**必交①**：预置裸名 + 连写 4 次 → **4 次的正文与账目都含「已被占用」**（不再退化）。"""
    trace_dir.mkdir(parents=True, exist_ok=True)
    base = trace_dir / f"{BASE}.txt"
    base.write_text("我已存在（人为预置）", encoding="utf-8")

    results = [_write(i, subject_id="r48a1") for i in range(1, 5)]

    names = [Path(r["trace_path"]).name for r in results]
    assert names == [f"{BASE}-{n:02d}.txt" for n in (2, 3, 4, 5)], names
    for i, r in enumerate(results, start=1):
        why = _naming(r["trace_path"])
        assert OCCUPIED in why, f"第 {i} 次正文丢了占用原因：{why}"
        assert SAME_SECOND not in why, f"第 {i} 次退化成通用文案：{why}"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in why)
    # 账目同理：4 条都是「已被占用」
    renames = _ledger_renames(CALL)
    assert len(renames) == 4, [r["reason"] for r in renames]
    for r in renames:
        assert OCCUPIED in r["reason"], r["reason"]
        assert SAME_SECOND not in r["reason"], r["reason"]
    # 正文与账目仍是**同一句**文案（R46 A 的单源约定没被破坏）
    assert any(_naming(results[0]["trace_path"]) in r["reason"] for r in renames)


def test_r48_a2_pure_same_second_still_reports_same_second(trace_dir):
    """**必交②（回归）**：无预置连写 4 次 → 仍全是「**同秒多次**」、**都不含「已被占用」**。"""
    base = f"{STAMP}-{CALL_NOPRE}"
    results = [_write(i, subject_id="r48a2", call_name=CALL_NOPRE) for i in range(1, 5)]

    names = [Path(r["trace_path"]).name for r in results]
    assert names == [f"{base}.txt", f"{base}-02.txt", f"{base}-03.txt", f"{base}-04.txt"], names
    first_why = _naming(results[0]["trace_path"])
    assert "无需换名" in first_why, f"第 1 个未换名 → 应写「无需换名」：{first_why}"
    for i, r in enumerate(results[1:], start=2):
        why = _naming(r["trace_path"])
        assert SAME_SECOND in why, f"第 {i} 次应为「同秒多次」：{why}"
        assert OCCUPIED not in why, f"第 {i} 次不涉及占用，不许写「已被占用」：{why}"
    assert not [1 for r in results if OCCUPIED in _naming(r["trace_path"])], \
        "本期**没有**占用，一律不得提「已被占用」"
    renames = _ledger_renames(CALL_NOPRE)
    assert len(renames) == 3, [r["reason"] for r in renames]
    for r in renames:
        assert SAME_SECOND in r["reason"] and OCCUPIED not in r["reason"], r["reason"]


def test_r48_a3_file_set_and_sequence_stay_contiguous(trace_dir):
    """**必交③（回归）**：文件集合恰为 `{裸名, -02, -03, -04}`（连续、无重复）；
    预置场景下裸名内容**原封不动**、新增文件为 `-02…-05`。"""
    base1 = f"{STAMP}-{CALL_SEQ}"
    base2 = f"{STAMP}-{CALL_SEQ2}"
    # ① 无预置：4 次 → 裸名 + -02/-03/-04（序号连续、无重复）
    results = [_write(i, subject_id="r48a3", call_name=CALL_SEQ) for i in range(1, 5)]
    got = [Path(r["trace_path"]).name for r in results]
    assert set(got) == {f"{base1}.txt", f"{base1}-02.txt", f"{base1}-03.txt", f"{base1}-04.txt"}, got
    assert len(set(got)) == 4, "序号不得重复"

    # ② 预置裸名（换一个调用点，避免与 ① 的同秒记忆纠缠）：内容原封不动，新增 -02…-05
    pre = trace_dir / f"{base2}.txt"
    pre.write_text("预置内容：不得改动", encoding="utf-8")
    again = [_write(i, subject_id="r48a3b", call_name=CALL_SEQ2) for i in range(1, 5)]
    got2 = sorted(Path(r["trace_path"]).name for r in again)
    assert got2 == sorted([f"{base2}-{n:02d}.txt" for n in (2, 3, 4, 5)]), got2
    assert pre.read_text(encoding="utf-8") == "预置内容：不得改动", "预置文件被覆盖/改动了"
    # 目录内容恰为「① 的 4 个 + ② 的 4 个 + ② 的预置裸名」
    assert sorted(p.name for p in trace_dir.glob("*.txt")) == sorted(
        got + got2 + [f"{base2}.txt"]), sorted(p.name for p in trace_dir.glob("*.txt"))
