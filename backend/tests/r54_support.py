"""R54 用例共用工具：建自定义学科 → 采纳大纲 → 生成单元内容 → 改内容文件 / 造会话状态。

（与既有 `order_support.py` 同一套路：把测试支撑代码独立成模块，三个任务用例各自 import。）
"""
from __future__ import annotations

import uuid
from pathlib import Path

import yaml

from app import models
from app.content import content_root
from app.content.loader import parse_node_text
from app.content.templates import render_exercise
from app.db import SessionLocal
from app.service import outline_gate
from app.service.library import get_library, refresh_library, sync_content


def new_sid() -> str:
    return f"r54{uuid.uuid4().hex[:6]}"


def cleanup_subjects(sids: list[str]) -> None:
    """模块结束清理本模块建的学科（DB 行；内容 *_auto 文件由 conftest 模块钩子清）。"""
    with SessionLocal() as db:
        for sid in sids:
            node_ids = {nid for (nid,) in db.query(models.Node.id)
                        .filter(models.Node.id.like(f"{sid}.%")).all()}
            if node_ids:
                for table in (models.UserConcept, models.Review, models.UserNode, models.Session):
                    col = getattr(table, "node_id", None)
                    if col is not None:
                        db.query(table).filter(col.in_(node_ids)).delete(synchronize_session=False)
                db.query(models.ContentLedger).filter(
                    models.ContentLedger.unit_id.in_(node_ids)).delete(synchronize_session=False)
                db.query(models.Node).filter(models.Node.id.in_(node_ids)).delete(
                    synchronize_session=False)
            db.query(models.ContentLedger).filter(
                models.ContentLedger.subject_id == sid).delete(synchronize_session=False)
            subj = db.get(models.Subject, sid)
            if subj is not None:
                db.delete(subj)
        db.commit()


def make_subject(app_client, sids: list[str], *, count: int = 3) -> str:
    """建自定义学科 + 采纳一份启发式大纲（不依赖真模型）。"""
    sid = new_sid()
    r = app_client.post("/api/subjects", json={"label": "R54 测试学科", "subject_id": sid})
    assert r.status_code == 201, r.text
    sids.append(sid)
    d = app_client.post(f"/api/subjects/{sid}/outline/draft",
                        json={"brief": "零基础入门", "count": count, "group_hint": "主线"})
    assert d.status_code == 200, d.text
    a = app_client.put(f"/api/subjects/{sid}/outline",
                       json={"units": d.json()["units"], "status": "active", "source": "heuristic"})
    assert a.status_code == 200, a.text
    return sid


def gen(app_client, sid: str, unit: str) -> dict:
    r = app_client.post(f"/api/subjects/{sid}/units/{unit}/content")
    assert r.status_code == 200, r.text
    return r.json()


def node_file(sid: str, unit: str) -> Path:
    return content_root() / "stages" / sid / f"node_{unit}_auto.md"


def refresh() -> None:
    refresh_library()
    outline_gate.clear_outline_cache()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()


def patch_node(sid: str, unit: str, mutate) -> None:
    """改**测试内容副本**里的节点文件（真实仓库与用户文件不受影响），再刷新库与 DB。

    注意：`exercises` 不能改成空数组——NodeDoc 有「每个节点至少 1 道练习」的校验（学习闭环需要判题），
    所以"题全没了"在真实世界里表现为**内容文件根本没生成**（走 `missing="content"` 分支）。
    """
    p = node_file(sid, unit)
    assert p.exists(), f"内容文件不存在：{p}"
    meta, body = parse_node_text(p.read_text(encoding="utf-8"))
    meta = dict(meta)
    mutate(meta)
    p.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                 + "---\n" + str(body or meta.get("body_md") or ""), encoding="utf-8", newline="\n")
    refresh()


def remove_node_file(sid: str, unit: str) -> None:
    node_file(sid, unit).unlink()
    refresh()


def record_coverage(sid: str, unit: str, cov: dict) -> None:
    """走**真实写入口**记录覆盖状态（模拟"生成时丢了 N 条"）。"""
    from app.outline.generate import _record_coverage as record

    with SessionLocal() as db:
        record(db, sid, unit, cov)
        db.commit()
    outline_gate.clear_outline_cache()


def coverage_unit(app_client, sid: str, unit: str) -> dict:
    cov = app_client.get(f"/api/subjects/{sid}/coverage").json()
    hits = [u for u in (cov.get("units") or []) if u["unit_id"] == unit]
    assert hits, f"覆盖账里没有单元 {unit}"
    return hits[0]


def start(app_client, unit: str) -> dict:
    r = app_client.post("/api/session/start", json={"node_id": unit})
    assert r.status_code == 200, r.text
    return r.json()


def get_session(app_client, session_id: str) -> dict:
    r = app_client.get(f"/api/session/{session_id}")
    assert r.status_code == 200, r.text
    return r.json()


def session_flow(session_id: str) -> dict:
    with SessionLocal() as db:
        sess = db.get(models.Session, session_id)
        assert sess is not None
        return dict(sess.flow_json or {})


def set_flow(session_id: str, mutate) -> None:
    """改会话 flow（模拟"历史会话/上一版留下的状态"）。"""
    from sqlalchemy.orm.attributes import flag_modified

    with SessionLocal() as db:
        sess = db.get(models.Session, session_id)
        flow = dict(sess.flow_json or {})
        mutate(flow)
        sess.flow_json = flow
        flag_modified(sess, "flow_json")
        db.commit()


def answer_of(node_id: str, exercise_id: str, seed: int) -> str:
    """服务端 canonical 答案（判题仍走 L1 判题器，测试不绕过）。"""
    doc = get_library().by_id[node_id].doc
    ex = next(e for e in doc.exercises if e.id == exercise_id)
    return render_exercise(node_id, ex, seed).canonical_answer
