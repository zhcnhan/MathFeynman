"""docs/12 P4：high+ 自动入库 + 纠错召回熔断护栏测试。

覆盖：
- high 学段生成**默认自动入库**（stages/<level>/，front-matter source: auto）——替代旧的 high+→_drafts 强制人审；
- 主题问题率（未处置纠错反馈节点 / 已入库 auto 节点）超阈值 → guardrails 判定熔断；
- selfextend 接线：熔断主题生成转 _drafts 待检（summary/guardrail 字段可见）；pending 清零 → 自动恢复。
用例自清理生成文件与 DB 行，保持内容库稳定。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app import models as m
from app.content import content_root, stages_dir
from app.content import pipeline as pl
from app.content.loader import load_library
from app.db import SessionLocal, init_db
from app.service import guardrails as gr
from app.service import selfextend as se
from app.service.library import refresh_library


def _generated_paths(node_ids) -> list[Path]:
    out: list[Path] = []
    for nid in node_ids:
        fn = f"node_{nid.replace('.', '_')}_auto.md"
        for cand in [content_root() / "_drafts" / fn, *(stages_dir().rglob(fn))]:
            if cand.exists() and cand not in out:
                out.append(Path(cand))
    return out


def _cleanup(node_ids) -> None:
    for p in _generated_paths(node_ids):
        p.unlink(missing_ok=True)
    if not node_ids:
        return
    with SessionLocal() as db:
        db.query(m.Feedback).filter(m.Feedback.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.Edge).filter(m.Edge.node_id.in_(node_ids) | m.Edge.prereq_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.UserNode).filter(m.UserNode.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.Node).filter(m.Node.id.in_(node_ids)).delete(synchronize_session=False)
        db.commit()
    refresh_library()


def test_high_generation_defaults_to_auto_stages():
    """P4：high 默认自动入库（不再是 _drafts 强制人审）。"""
    init_db()
    results = pl.generate_topic("high", "集合与常用逻辑", limit=3)
    ok = {r.entry_id: r.path for r in results if r.status == "ok"}
    assert ok, [r.status for r in results]
    try:
        for nid, path in ok.items():
            assert path and "stages" in path and "_drafts" not in path, path
            text_ = Path(path).read_text(encoding="utf-8")
            assert "source: auto" in text_  # 入库标注 auto
    finally:
        _cleanup(set(ok))


def test_meltdown_force_draft_then_release_after_handled():
    """P4：主题问题率超阈值 → 生成转 _drafts；pending 清零 → 恢复自动入库。"""
    init_db()
    landed: set[str] = set()
    draft_ids: set[str] = set()
    try:
        # 1) 数与运算主题先生成 4 条 auto 入库（s01–s04）
        res1 = pl.generate_topic("primary", "数与运算", limit=4)
        landed = {r.entry_id for r in res1 if r.status == "ok"}
        assert len(landed) >= 4, [r.status for r in res1]
        refresh_library()  # loader 可见新入库节点（guardrails 分母口径）

        # 2) 其中 2 条被"未处置"纠错反馈命中 → 问题率 2/4 = 0.5 > 阈值 → 熔断
        with SessionLocal() as db:
            for nid in list(landed)[:2]:
                db.add(m.Feedback(user_id="local", node_id=nid, kind="content", message="内容有误", status="pending"))
            db.commit()
            stats = gr.topic_problem_stats(db, "primary", "数与运算")
        assert stats == {"landed": 4, "problems": 2, "ratio": 0.5, "tripped": True}, stats

        # 3) selfextend 接线：该主题剩余条目生成 → _drafts 待检
        with SessionLocal() as db:
            res = se.extend(db, "local", level="primary", wait=True)
            db.commit()
        assert res["status"] == "done", res
        assert res.get("guardrail", {}).get("tripped") is True, res
        assert "熔断" in res["summary"], res["summary"]
        draft_ids = {x for x in res.get("generated", [])}
        if draft_ids:
            for p in _generated_paths(draft_ids):
                assert "_drafts" in str(p) and "stages" not in str(p), p

        # 4) 处置（复核/重生成后 pending 清零）→ 自动恢复（不再熔断）
        with SessionLocal() as db:
            db.query(m.Feedback).filter(m.Feedback.status == "pending").update(
                {"status": "reviewed"}, synchronize_session=False
            )
            db.commit()
            stats2 = gr.topic_problem_stats(db, "primary", "数与运算")
        assert stats2["tripped"] is False, stats2
    finally:
        _cleanup(landed | draft_ids)
