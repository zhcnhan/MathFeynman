"""阶段 3 子步 8：内容自续触发测试（docs/10 §2.3）。

离线 stub 出稿验证触发链路：掌握≥90% 蓝图目标 → extend 生成下一主题组 → auto 入库 + DB 同步 →
运行态/比例更新；用例清理生成文件与 DB 行，保持内容库稳定。
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
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes", "edges", "ai_logs", "nodes", "users"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def _set_mastered(db, ids) -> None:
    for nid in ids:
        row = db.get(m.UserNode, ("local", nid))
        if row is None:
            row = m.UserNode(user_id="local", node_id=nid)
            db.add(row)
        row.state = "mastered"


def _generated_paths(node_ids) -> list[Path]:
    out: list[Path] = []
    for nid in node_ids:
        fn = f"node_{nid.replace('.', '_')}_auto.md"
        for cand in [
            content_root() / "_drafts" / fn,
            *(stages_dir().rglob(fn)),
        ]:
            if cand.exists() and cand not in out:
                out.append(Path(cand))
    return out


def _cleanup(node_ids) -> None:
    paths = _generated_paths(node_ids)
    for p in paths:
        p.unlink(missing_ok=True)
    with SessionLocal() as db:
        db.query(m.Edge).filter(m.Edge.node_id.in_(node_ids) | m.Edge.prereq_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.UserNode).filter(m.UserNode.node_id.in_(node_ids)).delete(synchronize_session=False)
        db.query(m.Node).filter(m.Node.id.in_(node_ids)).delete(synchronize_session=False)
        db.commit()
    from app.service.library import refresh_library

    refresh_library()


def test_selfextend_trigger_generates_next_topic():
    _reset_all()
    anchors = ["primary.0101", "primary.0102", "primary.0103", "primary.0104"]
    try:
        with SessionLocal() as db:
            _set_mastered(db, anchors)
            db.commit()
            ratio0 = se.mastered_ratio(db, "local", "primary")
        assert ratio0 >= 0.9, ratio0

        with SessionLocal() as db:
            res = se.extend(db, "local", level="primary", wait=True)
            db.commit()
        assert res["status"] == "done", res
        assert res["generated"], res
        generated = set(res["generated"])
        paths = _generated_paths(generated)
        assert len(paths) == len(generated)

        # DB 已同步：新节点行存在且 content 校验级联成功（通过 load_library 无错误推断）
        with SessionLocal() as db:
            found = {r[0] for r in db.query(m.Node.id).filter(m.Node.id.in_(generated)).all()}
        assert generated <= found

        # 自动探测：新内容未掌握 → 比例回落，不再自动触发
        with SessionLocal() as db2:
            check = se.auto_check(db2, "local")
        assert check["auto"] is False
        st = se.status()
        assert st["last_status"] == "done"
    finally:
        _cleanup(set(generated)) if "generated" in dir() and generated else None


def test_selfextend_manual_run_via_status_flow():
    _reset_all()
    try:
        # 未掌握 → auto_check false，但手动 extend 仍可生成（“继续下一关”）
        with SessionLocal() as db:
            res = se.extend(db, "local", level="primary", wait=True)
            db.commit()
        assert res["status"] == "done", res
        generated = set(res["generated"])
        assert generated
    finally:
        _cleanup(generated) if "generated" in dir() and generated else None
