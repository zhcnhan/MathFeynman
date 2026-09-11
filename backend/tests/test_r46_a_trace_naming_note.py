"""R46 任务 A 用例：**审计换名说明写进文件正文**（R45 §3-1 裁定）。

背景：R44 已修掉"同秒同名静默覆盖"（三层防护）。但"为什么会有 `-02` 文件"这件事只写在总账里，
而**换名记账走独立连接**——调用方持有 SQLite 写事务时账目可能只落到 stderr 兜底（§58-18-①）。
架构侧 R45 §3-1 裁定：**不要求改连接口径**（审计**绝不能**改成持写事务，否则记审计会变成主流程
死锁源），**改用文件正文自证**"原拟名 / 实际名 / 原因"；**总账那条仍保留**（第二道可见性，
不是替代品）。

三条必交：
- `test_r46_a1_*`：同秒同调用点 5 次 → 第 1 个文件写明"无需换名"；`-02` 文件写明原拟名 + 实际名（中文）；
- `test_r46_a2_*`：人为预置同名 → 新文件正文写明"目标文件名已被占用、已换名"；
- `test_r46_a3_*`：**回归** —— `/api/ai-traces/{id}` 详情里 `full.system`/`full.user` 仍完整（新增小节不破坏分段）。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app import models
from app.db import SessionLocal
from app.service import ai_trace
from app.service.ai_trace import OUTCOME_ADOPTED, write_trace

# 冻结时钟：所有审计写入落在**同一秒**（严格复现"同秒"前件，不受机器快慢影响）
FIXED = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)
STAMP = "20260304T050607Z"
BASE = f"{STAMP}-answer_question"


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """审计全文目录指向临时目录 + 冻结时钟 + 清空同秒序号（不碰真实 `.runtime/ai_trace`）。"""
    d = tmp_path / "ai_trace"
    monkeypatch.setenv("MF_AI_TRACE_DIR", str(d))

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return FIXED if tz else FIXED.replace(tzinfo=None)

    monkeypatch.setattr(ai_trace, "datetime", _Frozen)
    ai_trace._reset_naming_state()   # R48 A：序号 + 换名报因一并清（否则跨用例互相污染）
    yield d
    ai_trace._reset_naming_state()


def _write(i: int, *, subject_id: str) -> dict:
    return write_trace(
        call_name="answer_question", system=f"SYS-{i}", user=f"USER-{i}",
        raw=f'{{"i":{i}}}', parsed={"i": i}, ok=True, model="m", tier="fast",
        latency_ms=i, prompt_tokens=i, completion_tokens=i, outcome=OUTCOME_ADOPTED,
        subject_id=subject_id, prompt_versions="default:answer_question")


def _body(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _naming_lines(path: str) -> dict:
    """把正文里的「命名情况」一节解析成 {实际名, 原拟名, 说明}。"""
    body = _body(path)
    assert ai_trace.NAMING_HEAD in body, f"正文缺「命名情况」小节：{path}"
    seg = body.split(ai_trace.NAMING_HEAD, 1)[1]
    out = {}
    for line in seg.splitlines():
        for key in ("本文件实际文件名：", "原拟文件名：", "命名说明："):
            if line.startswith(key):
                out[key.rstrip("：")] = line[len(key):].strip()
    return out


def _ledger_renames(*, subject_id: str = "") -> list[dict]:
    """换名账目；``subject_id`` 给了就只取该学科的。

    **R48 A 补**：R44 A 的同期用例与本模块**共用同一个冻结时间戳与调用点**
    （`20260304T050607Z-answer_question`），只按 `kind` 过滤会**跨用例串账** →
    单文件/部分选择运行时计数会虚高（全量套件里因为 `test_r44_b_*` 的库重置而侥幸通过）。
    账目上带了 `subject_id`，按它过滤即可精确隔离。
    """
    with SessionLocal() as db:
        q = db.query(models.ContentLedger).filter(models.ContentLedger.category == "other")
        if subject_id:
            q = q.filter(models.ContentLedger.subject_id == subject_id)
        rows = q.order_by(models.ContentLedger.id.desc()).all()
        return [{"id": int(r.id), "reason": r.reason or "", "detail": dict(r.detail_json or {})}
                for r in rows if (r.detail_json or {}).get("kind") == "trace_name_renamed"]


def test_r46_a1_first_file_says_no_rename_second_says_original_and_actual(app_client, trace_dir):
    """**必交①**：同秒同调用点 5 次 → 第 1 个文件"无需换名"；`-02` 文件写明**原拟名 + 实际名**（中文）。"""
    first = _write(1, subject_id="r46a1")
    second = _write(2, subject_id="r46a1")

    # 第 1 个：明确写"无需换名"，且**不含**换名字样
    n1 = _naming_lines(first["trace_path"])
    assert n1["本文件实际文件名"] == f"{BASE}.txt", n1
    assert n1["原拟文件名"] == f"{BASE}.txt", n1
    assert "无需换名" in n1["命名说明"], n1
    assert "第 1 个" in n1["命名说明"], n1
    assert "已改名" not in n1["命名说明"], n1

    # 第 2 个（-02）：原拟名 + 实际名 + 中文原因，都在**正文**里（不依赖数据库）
    n2 = _naming_lines(second["trace_path"])
    assert n2["本文件实际文件名"] == f"{BASE}-02.txt", n2
    assert n2["原拟文件名"] == f"{BASE}.txt", n2
    assert "已改名" in n2["命名说明"] and "不被覆盖" in n2["命名说明"], n2
    assert any("\u4e00" <= ch <= "\u9fff" for ch in n2["命名说明"])

    # 续写至 5 次：每次换名都要在正文自证
    rest = [_write(i, subject_id="r46a1") for i in (3, 4, 5)]
    assert [Path(r["trace_path"]).name for r in rest] == [
        f"{BASE}-03.txt", f"{BASE}-04.txt", f"{BASE}-05.txt"]
    for i, r in enumerate(rest, start=3):
        n = _naming_lines(r["trace_path"])
        assert n["本文件实际文件名"] == f"{BASE}-{i:02d}.txt", n
        assert n["原拟文件名"] == f"{BASE}.txt", n
        assert "已改名" in n["命名说明"], n
    # **总账那条仍保留**（文件正文是第二道可见性，不是替代品），且文案同源
    renames = _ledger_renames(subject_id="r46a1")
    assert len(renames) == 4, [r["reason"] for r in renames]
    assert all(r["detail"].get("reason_in_body") is True for r in renames)
    assert any(_naming_lines(second["trace_path"])["命名说明"] in r["reason"] for r in renames), \
        "总账原因与文件正文说明应同源（同一句文案）"
    assert "SYS-2" in _body(second["trace_path"]) and "USER-2" in _body(second["trace_path"])


def test_r46_a2_preexisting_file_note_says_occupied(app_client, trace_dir):
    """**必交②**：人为预置同名 → 新文件**正文**写明"目标文件名已被占用、已换名"。"""
    trace_dir.mkdir(parents=True, exist_ok=True)
    base = trace_dir / f"{BASE}.txt"
    base.write_text("我已存在（人为预置）", encoding="utf-8")

    res = _write(9, subject_id="r46a2")

    assert base.read_text(encoding="utf-8") == "我已存在（人为预置）", "预置文件不得被覆盖"
    n = _naming_lines(res["trace_path"])
    assert n["本文件实际文件名"] == f"{BASE}-02.txt", n
    assert n["原拟文件名"] == f"{BASE}.txt", n
    assert "已被占用" in n["命名说明"], n
    assert "人为预置" in n["命名说明"] or "另一进程" in n["命名说明"], n
    assert "已换名" in n["命名说明"] or "已改名" in n["命名说明"], n
    # 正文里的命名说明**独立于数据库**：清空账本后依然能从文件读到原因
    with SessionLocal() as db:
        db.query(models.ContentLedger).filter(
            models.ContentLedger.category == "other").delete()
        db.commit()
    assert "已被占用" in _naming_lines(res["trace_path"])["命名说明"], "文件正文必须自证（不依赖账本）"


def test_r46_a3_detail_segments_still_intact(app_client, trace_dir):
    """**必交③（回归）**：新增小节**不得**破坏 `_split_trace` 分段——
    `/api/ai-traces/{id}` 详情里 `full.system` / `full.user` / `full.response` 仍能**完整**取出。"""
    res = _write(7, subject_id="r46a3")
    _write(8, subject_id="r46a3")  # 让本次记录带上换名说明，进一步确认不干扰分段

    row = app_client.get("/api/ai-traces?subject_id=r46a3").json()["items"]
    target = next(r for r in row if r["trace_path"] == res["trace_path"])
    detail = app_client.get(f"/api/ai-traces/{target['id']}").json()
    full = detail["full"]
    assert full["system"] == "SYS-7", full["system"]
    assert full["user"] == "USER-7", full["user"]
    assert full["response"] == '{"i":7}', full["response"]
    assert detail["file_exists"] is True
    # 命名小节落在 meta（system 段之前），且**不**混进 system/user/response
    assert ai_trace.NAMING_HEAD in full["meta"], full["meta"][:200]
    for seg in ("system", "user", "response"):
        assert ai_trace.NAMING_HEAD not in full[seg], seg
        assert "命名说明" not in full[seg], seg
    # 三段内容长度与写入时一致（分段没有多吃/少吃）
    assert len(full["system"]) == len("SYS-7") and len(full["user"]) == len("USER-7")
