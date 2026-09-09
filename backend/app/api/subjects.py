"""app.api.subjects：学科注册与大纲管理端点（docs/14 Phase A A1）。

- GET/POST /subjects                 学科列表 / 创建自定义学科
- GET/DELETE /subjects/{sid}         学科详情（含大纲摘要）/ 删除自定义学科
- GET /subjects/{sid}/outline        当前大纲全文（审阅）
- POST /subjects/{sid}/outline/validate   校验大纲候选（提交前预览；UI A4 用）
- PUT /subjects/{sid}/outline        采纳/整份重生成大纲（custom；revision 递增）
- PATCH /subjects/{sid}/outline/units/{uid}   单元局部改（审阅修订）
- POST /subjects/{sid}/outline/regenerate     （A4 开放：AI 重起草；当前 501 占位）

错误约定：{error:{code,message}}；code ∈ not_found/validation_error/conflict。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..content.loader import load_library
from ..outline import OutlineDoc, OutlineError, OutlineUnit
from ..outline import concepts as concept_svc
from ..outline.schemas import OUTLINE_SOURCES, OUTLINE_STATUSES, SUBJECT_ID_RE
from ..outline import store as outline_store
from .deps import get_db

router = APIRouter(tags=["subjects"])


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


def _outline_err(e: OutlineError) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": {"code": "validation_error", "message": str(e)}})


def _subject_summary(db: Session, subj) -> dict:
    doc = None
    try:
        doc = outline_store.get_outline(subj.id)
    except OutlineError:
        pass  # 损坏大纲在详情/校验处报错；列表容错
    return {
        "id": subj.id,
        "label": subj.label,
        "kind": subj.kind,
        "description": subj.description,
        "outline": (
            None
            if doc is None
            else {
                "exists": True,
                "revision": doc.revision,
                "status": doc.status,
                "source": doc.source,
                "schema_version": doc.schema_version,
                "units": len(doc.units),
                "groups": doc.groups(),
                "updated_at": doc.updated_at,
            }
        ),
    }


def _content_ids() -> set[str]:
    lib = load_library()
    return {n.id for n in lib.nodes}


@router.get("/subjects")
def list_all(db: Session = Depends(get_db)) -> dict:
    rows = outline_store.list_subjects(db)
    return {"subjects": [_subject_summary(db, r) for r in rows]}


class CreateSubjectBody(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    description: str = ""
    subject_id: str | None = Field(default=None, max_length=32)


@router.post("/subjects", status_code=201)
def create_subject(body: CreateSubjectBody, db: Session = Depends(get_db)) -> dict:
    sid = body.subject_id
    if sid is not None and not SUBJECT_ID_RE.match(sid):
        raise _err(422, "validation_error",
                   f"学科 id 非法（须匹配 {SUBJECT_ID_RE.pattern}）")
    try:
        row = outline_store.create_subject(db, label=body.label, description=body.description,
                                           subject_id=sid)
    except OutlineError as e:
        raise _err(422, "validation_error", str(e)) from e
    return _subject_summary(db, row)


@router.get("/subjects/{subject_id}")
def get_one(subject_id: str, db: Session = Depends(get_db)) -> dict:
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    return _subject_summary(db, row)


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_one(subject_id: str, db: Session = Depends(get_db)) -> None:
    try:
        outline_store.delete_subject(db, subject_id)
    except OutlineError as e:
        raise _err(409, "conflict", str(e)) from e


@router.get("/subjects/{subject_id}/outline")
def get_outline(subject_id: str, db: Session = Depends(get_db)) -> dict:
    if outline_store.get_subject(db, subject_id) is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    try:
        doc = outline_store.get_outline(subject_id)
    except OutlineError as e:
        raise _err(422, "validation_error", f"大纲文件损坏: {e}") from e
    if doc is None:
        raise _err(404, "not_found", f"学科 {subject_id} 尚无大纲")
    return doc.model_dump(mode="json")


def _unit_payloads(items: list[dict]) -> list[OutlineUnit]:
    units: list[OutlineUnit] = []
    for i, item in enumerate(items):
        try:
            units.append(OutlineUnit(**item))
        except Exception as e:
            raise _err(422, "validation_error", f"单元[{i}] 非法: {e}") from e
    return units


class PutOutlineBody(BaseModel):
    units: list[dict]
    status: str = "draft"
    source: str = "manual"
    note: str = ""
    label: str | None = None


@router.put("/subjects/{subject_id}/outline")
def put_outline(subject_id: str, body: PutOutlineBody, db: Session = Depends(get_db)) -> dict:
    if body.status not in OUTLINE_STATUSES:
        raise _err(422, "validation_error", f"status 非法: {body.status!r}")
    if body.source not in OUTLINE_SOURCES or body.source == "roadmap":
        raise _err(422, "validation_error", f"自定义大纲 source 非法: {body.source!r}")
    try:
        units = _unit_payloads(body.units)
        doc = outline_store.add_outline(
            db, subject_id, units=units, status=body.status, source=body.source,
            note=body.note, known_content_ids=_content_ids(),
        )
    except OutlineError as e:
        raise _outline_err(e) from e
    concept_svc.sync_outline_registry(db, subject_id, doc)
    return doc.model_dump(mode="json")


@router.post("/subjects/{subject_id}/outline/validate")
def validate_candidate(subject_id: str, body: PutOutlineBody,
                       db: Session = Depends(get_db)) -> dict:
    """校验大纲候选（不落盘）：依赖无环/标签/引用存在性报告，供 UI 预览。"""
    try:
        units = _unit_payloads(body.units)
    except HTTPException:
        raise
    subj = outline_store.get_subject(db, subject_id)
    if subj is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    doc = OutlineDoc(subject=subject_id, label=subj.label, units=units)
    problems = outline_store.validate_outline(doc, known_content_ids=_content_ids())
    return {"ok": not problems, "problems": problems, "units": len(units)}


class PatchUnitBody(BaseModel):
    fields: dict


@router.patch("/subjects/{subject_id}/outline/units/{unit_id}")
def patch_unit(subject_id: str, unit_id: str, body: PatchUnitBody,
               db: Session = Depends(get_db)) -> dict:
    if outline_store.get_subject(db, subject_id) is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    try:
        doc = outline_store.patch_outline_unit(
            db, subject_id, unit_id, fields=body.fields, known_content_ids=_content_ids()
        )
    except OutlineError as e:
        raise _outline_err(e) from e
    concept_svc.sync_outline_registry(db, subject_id, doc)
    return doc.model_dump(mode="json")


@router.post("/subjects/{subject_id}/outline/regenerate")
def regenerate_outline(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """大纲重生成：preset(math) = 由 roadmap 派生/再派生（revision+1，概念标签按 unit id 保留）；
    通用学科 AI 起草/重生成在 Phase A4 开放。"""
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    if row.kind == "preset":
        from ..outline.math_preset import derive_math_outline

        doc = derive_math_outline(db, status="active")
        return doc.model_dump(mode="json")
    raise _err(501, "not_implemented",
               f"通用学科大纲 AI 起草/重生成在 Phase A4 开放（当前为 custom 学科 {subject_id}）")


# ---------- A2：概念层与进度映射（docs/14 §2.2） ----------
USER = "local"


@router.get("/subjects/{subject_id}/progress")
def get_progress(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """学科进度视图：单元达成/等效（概念命中）/开放；内容节点状态。

    等效达成 = 单元概念标签集 ⊆ 已掌握概念（重生成大纲后"进度不丢"的判定基础）。
    """
    if outline_store.get_subject(db, subject_id) is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    try:
        return concept_svc.unit_states(db, USER, subject_id)
    except OutlineError as e:
        raise _outline_err(e) from e


@router.post("/subjects/{subject_id}/progress/recompute")
def recompute_progress(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """幂等重算概念掌握证据（= 数学历史掌握迁移入口：user_nodes.mastered → (subject, concept)）。"""
    if outline_store.get_subject(db, subject_id) is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    try:
        report = concept_svc.recompute_subject_concepts(db, USER, subject_id)
        db.commit()
        return report
    except OutlineError as e:
        raise _outline_err(e) from e


class ResetProgressBody(BaseModel):
    mode: str = "all"  # all=清概念层+学科内容掌握（显式重置）


@router.post("/subjects/{subject_id}/progress/reset")
def reset_progress(subject_id: str, body: ResetProgressBody,
                   db: Session = Depends(get_db)) -> dict:
    """显式重置学科进度（docs/14 §2.2/§0.4）：清概念证据 + 学科内容节点掌握降回 available。"""
    if outline_store.get_subject(db, subject_id) is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    try:
        report = concept_svc.reset_subject_progress(db, USER, subject_id)
        db.commit()
        return report
    except OutlineError as e:
        raise _outline_err(e) from e
