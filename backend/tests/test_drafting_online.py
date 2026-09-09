"""R13 补记：有 Key 在线出稿接线测试（mock provider / 假工厂，不真调 API）。

覆盖：
- make_ai_drafter 产物经 pipeline 校验后入库（use_ai=True 语义，非 stub 占位）；
- 出稿校验失败 → 自动带错误重试 1 次（二轮合法即 ok，messages 含校验错误）；
- 重试仍失败 → failed，错误带 attempt 标记透传；
- selfextend.extend 在 use_ai=True 时走 AI 分支（make_ai_drafter 命中），产物入库。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.content import content_root, stages_dir
from app.content import pipeline as pl
from app.content.roadmap import load_roadmap
from app.db import SessionLocal


@pytest.fixture(scope="module", autouse=True)
def _db_tables_ready():
    """本模块可能单独运行：先建表，保证 cleanup/DB 同步可用。"""
    from app.db import init_db

    init_db()
    yield


class _FakeOutcome:
    def __init__(self, parsed: dict):
        self.parsed = parsed


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_json(self, call, messages, **kw):
        self.calls.append(list(messages))
        resp = self.responses.pop(0)
        return _FakeOutcome({"draft_md": resp})


class _FakeGateway:
    _p = None

    def __init__(self, provider):
        self._p = provider


def _cleanup(node_ids: set[str]) -> None:
    for nid in node_ids:
        fn = f"node_{nid.replace('.', '_')}_auto.md"
        for cand in [content_root() / "_drafts" / fn, *(stages_dir().rglob(fn))]:
            p = Path(cand)
            if p.exists():
                p.unlink()
    if node_ids:
        from app import models as m

        with SessionLocal() as db:
            db.query(m.Edge).filter(m.Edge.node_id.in_(node_ids) | m.Edge.prereq_id.in_(node_ids)).delete(synchronize_session=False)
            db.query(m.UserNode).filter(m.UserNode.node_id.in_(node_ids)).delete(synchronize_session=False)
            db.query(m.Node).filter(m.Node.id.in_(node_ids)).delete(synchronize_session=False)
            db.commit()
    from app.service.library import refresh_library

    refresh_library()


def _stub_md(entry_id: str) -> str:
    roadmap = load_roadmap("primary")
    return pl.stub_drafter(roadmap.by_id()[entry_id])


def _make_ai_drafter_with(provider):
    """模拟 ai/drafting.make_ai_drafter 的构建：经 fake gateway + provider。"""
    from app.ai.drafting import _draft_messages
    from app.ai.calls import CALL_DRAFT_CONTENT, DraftContentIn

    def drafter(entry, errors=None):
        spec = DraftContentIn(
            spec={
                "level": entry.level,
                "topic": entry.topic,
                "id_hint": entry.id,
                "title": entry.title,
                "objectives": entry.objectives,
                "prereqs": entry.prereqs,
                "difficulty": entry.difficulty,
                "requires_thinking": entry.requires_thinking,
            }
        )
        messages = _draft_messages(spec.spec)
        if errors:
            messages[-1] = {"role": "user", "content": messages[-1]["content"] + "\n\n[上一轮输出未通过自动校验] 校验错误：\n" + "\n".join(errors[:5])}
        out = provider.chat_json(CALL_DRAFT_CONTENT, messages)
        return out.parsed["draft_md"]

    return drafter


def test_ai_drafter_output_ingested_after_validation():
    """合法 AI 输出经 pipeline 校验后入库（front-matter source: auto）。"""
    entry_id = "primary.s01"
    provider = _FakeProvider([_stub_md(entry_id)])
    drafter = _make_ai_drafter_with(provider)
    try:
        results = pl.generate_topic("primary", "数与运算", drafter=drafter, limit=1)
        assert results[0].status == "ok", results[0].errors
        assert results[0].path and "_auto.md" in results[0].path
        text = Path(results[0].path).read_text(encoding="utf-8")
        assert "source: auto" in text
    finally:
        _cleanup({entry_id})


def test_ai_draft_retry_on_validation_failure_with_error_feedback():
    """A2：首轮非法 → 自动重试携带校验错误 → 二轮合法即 ok。"""
    entry_id = "primary.s01"
    provider = _FakeProvider(["这不是合法节点（缺 front-matter）", _stub_md(entry_id)])
    drafter = _make_ai_drafter_with(provider)
    try:
        results = pl.generate_topic("primary", "数与运算", drafter=drafter, limit=1)
        assert results[0].status == "ok", results[0].errors
        assert len(provider.calls) == 2
        second_user = provider.calls[1][-1]["content"]
        assert "校验错误" in second_user  # 校验错误回灌给模型
    finally:
        _cleanup({entry_id})


def test_ai_draft_failed_after_retry_surfaces_errors():
    """A2：重试仍失败 → failed，错误带 attempt 标记透传。"""
    entry_id = "primary.s01"
    provider = _FakeProvider(["bad one", "bad two"])
    drafter = _make_ai_drafter_with(provider)
    results = pl.generate_topic("primary", "数与运算", drafter=drafter, limit=1)
    assert results[0].status == "failed"
    assert any("attempt 1" in e for e in results[0].errors)


def test_ai_draft_with_symbolic_round_rejected():
    """39332ad 复审：模板纪律（禁符号取整）——AI 出稿含 round 表达式的模板题
    必须被 sympy 自检拒绝（status=failed、错误含 broken），绝不入库。"""
    entry_id = "primary.s01"

    def corrupt_drafter(entry, errors=None):  # noqa: ARG001
        md = _stub_md(entry_id)
        # 把答案表达式改为符号取整（round(a/b,2)——violates 模板纪律）
        mutated = md.replace("answer_expr: a + b", "answer_expr: round(a / b, 2)")
        assert mutated != md, "stub 模板应含 answer_expr: a + b（测试前提）"
        return mutated

    result = pl.generate_entry(
        load_roadmap("primary").by_id()[entry_id],
        drafter=corrupt_drafter,
        known_ids=set(),
    )
    assert result.status == "failed"
    assert any("broken" in e for e in result.errors), result.errors
    # 未落盘：目标 id 无对应 auto 文件
    from app.content import content_root

    assert not list((stages_dir() / "primary").rglob(f"node_{entry_id.replace('.', '_')}_auto.md"))
    assert not (content_root() / "_drafts" / f"node_{entry_id.replace('.', '_')}_auto.md").exists()


def test_extend_use_ai_true_takes_ai_drafter(monkeypatch):
    """A1：selfextend 在 use_ai=True（有 key）走 AI 出稿分支（make_ai_drafter 命中），产物入库。"""
    import app.ai.drafting as drafting_mod
    from app.service import selfextend as se

    fake_drafter = pl.stub_drafter  # 假"AI"drafter：产出合法节点（路径选择验证，非 stub 占位语义）
    monkeypatch.setattr(drafting_mod, "make_ai_drafter", lambda settings=None: fake_drafter)
    monkeypatch.setenv("LLM_API_KEY", "sk-test-online")

    from app.db import init_db

    init_db()
    res: dict = {}
    try:
        with SessionLocal() as db:
            res = se.extend(db, "local", level="primary", wait=True)
            db.commit()
        assert res["status"] == "done", res
        assert res["generated"], "use_ai=True 必须走 AI 分支并产出内容"
    finally:
        _cleanup(set(res.get("generated", [])))
