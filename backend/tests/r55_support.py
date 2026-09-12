"""R55 A/B/C 共用工具：造材料 / 造内容单元 / 读口径。

（与 `order_support.py`、`r54_support.py` 同一套路：支撑代码独立成模块。）
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app import models
from app.db import SessionLocal


def new_sid() -> str:
    return f"r55{uuid.uuid4().hex[:6]}"


def cleanup_subjects(sids: list[str]) -> None:
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
            # 材料文件（含 *.raw.txt）也清掉
            from app.content import content_root

            for d in (content_root() / "subjects" / sid,):
                if d.exists():
                    for p in sorted(d.rglob("*")):
                        if p.is_file():
                            p.unlink(missing_ok=True)
        db.commit()


def make_subject(app_client, sids: list[str], *, label: str = "R55 测试学科") -> str:
    sid = new_sid()
    r = app_client.post("/api/subjects", json={"label": label, "subject_id": sid})
    assert r.status_code == 201, r.text
    sids.append(sid)
    return sid


def upload_text_material(app_client, sid: str, text: str, *, title: str = "测试教材",
                         raw_text: str = "", source: str = "本地导入") -> dict:
    payload = {"title": title, "text": text, "source": source}
    if raw_text:
        payload["raw_text"] = raw_text
    r = app_client.post(f"/api/subjects/{sid}/materials/upload", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def materials(app_client, sid: str) -> list[dict]:
    return app_client.get(f"/api/subjects/{sid}/materials").json()["materials"]


def material_body(sid: str, mid: str) -> str:
    from app.outline.materials import materials_dir, _parse_entry

    for p in materials_dir(sid).glob("*.md"):
        e = _parse_entry(p)
        if e and e["id"] == mid:
            return e["body"]
    raise AssertionError(f"材料不存在: {mid}")


def adopt_outline(app_client, sid: str, units: list[dict]) -> dict:
    r = app_client.put(f"/api/subjects/{sid}/outline",
                       json={"units": units, "status": "active", "source": "heuristic"})
    assert r.status_code == 200, r.text
    return r.json()


def unit(uid: str, title: str, *, section: str, prereqs: list[str] | None = None,
         material: str = "测试教材") -> dict:
    return {"id": uid, "title": title, "objectives": [f"掌握{title}"], "concept_tags": [title],
            "group": "教材", "prereqs": prereqs or [], "difficulty": 1,
            "materials": [{"title": material, "section": section}]}


def draft_pack(sid: str) -> dict:
    """走**真实入口**读一次材料（`draft_materials`）→ 触发材料级记账（图示不可用等）。"""
    from app.outline import materials as mat

    with SessionLocal() as db:
        return mat.draft_materials(db, sid)


def gen_unit(app_client, sid: str, uid: str) -> dict:
    r = app_client.post(f"/api/subjects/{sid}/units/{uid}/content")
    assert r.status_code == 200, r.text
    return r.json()


def ledger_entries(app_client, sid: str, *, category: str = "", kind: str = "") -> list[dict]:
    q = f"/api/ledger?subject_id={sid}" + (f"&category={category}" if category else "")
    rows = app_client.get(q).json()["entries"]
    if kind:
        rows = [e for e in rows if (e.get("detail") or {}).get("kind") == kind]
    return rows


def material_path(sid: str, mid: str) -> Path:
    from app.outline.materials import materials_dir, _parse_entry

    for p in materials_dir(sid).glob("*.md"):
        e = _parse_entry(p)
        if e and e["id"] == mid:
            return p
    raise AssertionError(f"材料不存在: {mid}")
