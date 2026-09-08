"""阶段 3 子步 10：端到端验收模拟（docs/10 §4）。

离线链路：重置 → 掌握小学锚点至 ≥90% → 反复"下一主题"生成并掌握，直至小学蓝图内容齐且全掌握 →
auto_check 命中跨学段放行（小学全通关）→ 自动生成"初中代数第一批"（middle 蓝图 m03/m04 auto）。
用例结束清理所有生成文件与 DB 行；真实验收仍需用户在浏览器+真模型环境跑一遍。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app import models as m
from app.content import content_root, stages_dir
from app.db import SessionLocal
from app.service import selfextend as se


def _reset_all() -> None:
    from app.db import init_db
    from app.service.library import ensure_user, sync_content

    init_db()
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes", "edges", "ai_logs", "feedback", "nodes", "users"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def _master(db, ids) -> None:
    for nid in ids:
        row = db.get(m.UserNode, ("local", nid))
        if row is None:
            row = m.UserNode(user_id="local", node_id=nid)
            db.add(row)
        row.state = "mastered"
        row.consecutive_correct = 3


def _generated_paths(node_ids) -> list[Path]:
    out: list[Path] = []
    for nid in node_ids:
        fn = f"node_{nid.replace('.', '_')}_auto.md"
        cands = [content_root() / "_drafts" / fn, *(stages_dir().rglob(fn))]
        for c in cands:
            p = Path(c)
            if p.exists() and p not in out:
                out.append(p)
    return out


def _cleanup(node_ids) -> None:
    for p in _generated_paths(node_ids):
        p.unlink(missing_ok=True)
    if not node_ids:
        return
    with SessionLocal() as db:
        db.query(m.Edge).filter(m.Edge.node_id.in_(node_ids) | m.Edge.prereq_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.UserNode).filter(m.UserNode.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.Node).filter(m.Node.id.in_(node_ids)).delete(synchronize_session=False)
        db.commit()
    from app.service.library import refresh_library

    refresh_library()


def test_e2e_complete_primary_then_auto_middle_batch():
    _reset_all()
    all_generated: set[str] = set()
    try:
        # 1) 起点：小学蓝图四个锚点全部掌握（ratio=1）
        with SessionLocal() as db:
            _master(db, ["primary.0101", "primary.0102", "primary.0103", "primary.0104"])
            db.commit()
            assert se.mastered_ratio(db, "local", "primary") >= 1.0

        # 2) 循环："下一主题"生成并掌握，直到小学蓝图内容齐；
        #    小学齐后 extend 自动推进（fallback）生成"初中代数第一批"（middle.m03/m04 auto；m01/m02 锚点覆盖）
        middle_auto: set[str] = set()
        for _ in range(60):
            with SessionLocal() as db:
                res = se.extend(db, "local", level="primary", wait=True)
                db.commit()
            if res.get("generated"):
                ids = set(res["generated"])
                all_generated |= ids
                middle_auto |= {x for x in ids if x.startswith("middle.")}
                with SessionLocal() as db:
                    _master(db, ids)
                    db.commit()
                continue
            assert res["status"] in ("done", "idle"), res
            break

        # 3) 断言：小学有生成内容（自续非空）；"初中代数第一批"已自动解锁并生成（跨学段链路）
        assert all_generated
        assert "middle.m03" in middle_auto and "middle.m04" in middle_auto, middle_auto

        with SessionLocal() as db:
            found = {r[0] for r in db.query(m.Node.id).filter(m.Node.id.in_(all_generated)).all()}
        assert all_generated <= found  # DB 已同步（关卡地图可见）
    finally:
        _cleanup(all_generated)
