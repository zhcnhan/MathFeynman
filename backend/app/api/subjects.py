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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    from .errors_zh import ensure_zh_message

    return HTTPException(status_code=422, detail={"error": {
        "code": "validation_error", "message": ensure_zh_message(str(e), status_code=422)}})


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
        "enabled": bool(subj.enabled),  # B4：停用标记（列表默认隐藏停用者）
        "removed_at": subj.removed_at.isoformat() if subj.removed_at else None,
        "source_policy": str((subj.meta_json or {}).get("source_policy") or "ai"),  # B3
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


def _require_enabled(db: Session, subject_id: str):
    """学科启用校验（停用学科除 enable/硬删外一律拒绝操作，B4）。"""
    row = outline_store.get_subject(db, subject_id)
    if row is None:
        raise _err(404, "not_found", f"学科不存在: {subject_id}")
    if not row.enabled:
        raise _err(409, "conflict",
                   f"学科「{row.label or subject_id}」已停用；请在学科页「管理已移除」中重新启用后再操作")


@router.get("/subjects")
def list_all(db: Session = Depends(get_db), include_removed: bool = False) -> dict:
    rows = outline_store.list_subjects(db, include_removed=include_removed)
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
    if row is None or not row.enabled:
        raise _err(404, "not_found",
                   f"学科不存在或已停用: {subject_id}（重新启用请见列表「管理已移除」）")
    return _subject_summary(db, row)


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_one(subject_id: str, db: Session = Depends(get_db),
               hard: bool = False) -> None:
    """学科移除（docs/14 §9）：默认停用（enabled=False、隐藏、清进度、文件留盘可恢复）；
    hard=true 仅 custom 连同文件删除（含大纲/内容/材料目录）。math 仅可停用移除。"""
    try:
        outline_store.delete_subject(db, subject_id, hard=hard)
    except OutlineError as e:
        raise _err(409, "conflict", str(e)) from e


@router.post("/subjects/{subject_id}/enable")
def enable_subject(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """重新启用被移除（停用）的学科（大纲/内容文件留盘即恢复）。"""
    try:
        row = outline_store.enable_subject(db, subject_id)
    except OutlineError as e:
        raise _err(409, "conflict", str(e)) from e
    return _subject_summary(db, row)


@router.get("/subjects/{subject_id}/outline")
def get_outline(subject_id: str, db: Session = Depends(get_db)) -> dict:
    _require_enabled(db, subject_id)
    try:
        doc = outline_store.get_outline(subject_id)
    except OutlineError as e:
        raise _err(422, "validation_error", f"大纲文件损坏: {e}") from e
    if doc is None:
        raise _err(404, "not_found", f"学科 {subject_id} 尚无大纲")
    return doc.model_dump(mode="json")


def _unit_payloads(items: list[dict]) -> list[OutlineUnit]:
    from pydantic import ValidationError

    from .errors_zh import pydantic_summary_zh

    units: list[OutlineUnit] = []
    for i, item in enumerate(items):
        try:
            units.append(OutlineUnit(**item))
        except ValidationError as e:
            raise _err(422, "validation_error", f"第 {i + 1} 个单元数据不合法：{pydantic_summary_zh(e)}") from e
        except Exception as e:
            raise _err(422, "validation_error", f"第 {i + 1} 个单元数据不合法，请检查必填项与格式后重试（{type(e).__name__}）") from e
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
        # R36 D3：材料溯源由**服务端**从各单元 materials[].title 反查 material_id（不信客户端自报）；
        # 引用了不存在的材料 → 中文 422（与起草阶段的 D2 校验同一口径）。
        from ..outline import materials as mat

        titles = [str((r or {}).get("title") or "") for u in units for r in (u.materials or [])]
        mat_ids, missing = mat.material_ids_for_titles(db, subject_id, titles)
        if missing:
            raise _err(422, "validation_error",
                       "大纲引用的材料不存在于该学科引用库：" + "、".join(sorted(set(missing)))
                       + "。请先在「学科管理 · 材料」中导入/上传该材料，或移除该单元的溯源引用。")
        # R37 S7：材料是扫描版/未提取到文字 → 不许采纳"没读到书"的大纲（先于溯源逐条校验）
        for m in mat.list_materials(db, subject_id):
            h = m.get("text_health") or {}
            if h.get("checked") and not h.get("healthy"):
                raise _err(422, "validation_error",
                           f"无法采纳大纲：材料《{m['title']}》没有可用的文本层。{h.get('note', '')}")
        # R37 S2：溯源逐条服务端校验并**收敛为教材章节地图的规范标签**（不信客户端自报的文本）
        index = mat._material_index(db, subject_id)
        if index:
            normalized_units = []
            for u in units:
                refs = []
                for r in (u.materials or []):
                    kept, why = mat.check_unit_material(r, index)
                    if kept is None:
                        raise _err(422, "validation_error",
                                   f"单元 {u.id} 的材料溯源不成立：{why}")
                    refs.append(kept)
                normalized_units.append(u.model_copy(update={"materials": refs}))
            units = normalized_units
        # R37 S2：教材全覆盖——地图条目未映射 → 违规（不得悄悄丢章节）
        cov = mat.coverage_problems(units, index)
        if cov:
            raise _err(422, "validation_error", "；".join(cov))
        doc = outline_store.add_outline(
            db, subject_id, units=units, status=body.status, source=body.source,
            note=body.note, known_content_ids=_content_ids(), source_materials=mat_ids,
        )
    except HTTPException:
        raise
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
    # R36 P1：按"将要采纳时的 source"校验（roadmap 派生大纲豁免难度单调硬校验——数据治理项）
    doc = OutlineDoc(subject=subject_id, label=subj.label,
                     source=body.source if body.source in OUTLINE_SOURCES else "manual",
                     units=units)
    problems = outline_store.validate_outline(doc, known_content_ids=_content_ids())
    return {"ok": not problems, "problems": problems, "units": len(units)}


class PatchUnitBody(BaseModel):
    fields: dict


@router.patch("/subjects/{subject_id}/outline/units/{unit_id}")
def patch_unit(subject_id: str, unit_id: str, body: PatchUnitBody,
               db: Session = Depends(get_db)) -> dict:
    _require_enabled(db, subject_id)
    try:
        doc = outline_store.patch_outline_unit(
            db, subject_id, unit_id, fields=body.fields, known_content_ids=_content_ids()
        )
    except OutlineError as e:
        raise _outline_err(e) from e
    concept_svc.sync_outline_registry(db, subject_id, doc)
    return doc.model_dump(mode="json")


@router.post("/subjects/{subject_id}/outline/regenerate")
def regenerate_outline(subject_id: str, db: Session = Depends(get_db),
                       body: DraftOutlineBody | None = None) -> dict:
    """大纲重生成：
    - preset(math)：由 roadmap 派生/再派生（revision+1，概念标签按 unit id 保留）；
    - custom：重新起草候选（source=ai/heuristic，不落盘；用户审阅后 PUT 采纳 revision+1——
      docs/14 §2.1 "丢弃重生成"语义）。"""
    _require_enabled(db, subject_id)
    row = outline_store.get_subject(db, subject_id)
    if row.kind == "preset":
        from ..outline.math_preset import derive_math_outline

        doc = derive_math_outline(db, status="active")
        return doc.model_dump(mode="json")
    from ..outline.draft import draft_outline as _draft

    b = body or DraftOutlineBody()
    try:
        return _draft(subject_id, brief=b.brief, count=b.count, group_hint=b.group_hint,
                      materials=_draft_materials(db, subject_id))
    except OutlineError as e:
        raise _outline_err(e) from e


class DraftOutlineBody(BaseModel):
    brief: str = ""          # 学科简介/用户目标（AI 起草输入）
    count: int = Field(default=6, ge=1, le=30)
    group_hint: str = ""


def _draft_materials(db: Session, subject_id: str) -> dict | None:
    """D1/D4（R36）→ S1/S2/S8（R37）：起草注入包（章→节地图 + 完整正文分批 + 服务端校验索引）。

    预算默认**不限**（``MF_MATERIAL_INJECT_MAX_CHARS=0``）；显式设上限时才走 R36 的截断降级。
    无材料 → None（退化为现状：仅按 brief 起草，并显式标注本内容无教材依据）。
    """
    from ..outline import materials as mat

    pack = mat.draft_materials(db, subject_id)
    return pack if pack.get("count") else None


@router.post("/subjects/{subject_id}/outline/draft")
def draft_outline(subject_id: str, body: DraftOutlineBody, db: Session = Depends(get_db)) -> dict:
    """AI/启发式起草大纲候选（不落盘）→ UI 预览 → PUT 采纳（docs/14 §2.1 · A4）。

    R36 D1/D2 → R37 S1/S2/S8：注入该学科**教材的章 → 节地图 + 完整正文**（默认不设预算，
    书太大时按章/页分批）；**材料可选**——无材料时退化为仅按 brief 起草，不报错（如实标注无教材依据）；
    有材料时要求逐单元 `materials:[{title,section}]` 溯源（服务端校验，不成立则驳回重生成一次），
    并做**全覆盖校验**（未映射的章/节按教材目录补齐并记问题）；教材是扫描版 → 中文 422。
    """
    _require_enabled(db, subject_id)
    row = outline_store.get_subject(db, subject_id)
    if row.kind == "preset":
        raise _err(409, "conflict", "预置学科大纲由课程蓝图（roadmap）治理，请使用派生/再生成接口")
    from ..outline.draft import draft_outline as _draft

    try:
        return _draft(subject_id, brief=body.brief, count=body.count, group_hint=body.group_hint,
                      materials=_draft_materials(db, subject_id))
    except OutlineError as e:
        raise _outline_err(e) from e

@router.post("/subjects/{subject_id}/units/{unit_id}/content")
def generate_unit_content(subject_id: str, unit_id: str, db: Session = Depends(get_db)) -> dict:
    """懒生成单元内容（source:auto 落盘 + 库/DB 同步；幂等；docs/14 §2.3 · A4）。

    预置学科内容由课程蓝图（roadmap）流水线治理 → 本端点仅 custom 学科。
    R37：注入该单元对应的**教材章/节完整正文**并做**教材锚定**（S5）——
    拿不到「逐字出自教材」的事实句 → ``status=uncovered``（中文告知"教材未覆盖此单元"，不落盘）。
    """
    _require_enabled(db, subject_id)
    from ..outline.generate import generate_unit_content as _gen

    try:
        from ..outline import materials as mat

        unit = None
        doc = outline_store.get_outline(subject_id)
        if doc is not None:
            unit = doc.by_id().get(unit_id)
        pack = mat.unit_material_pack(db, subject_id, unit) if unit is not None else None
        return _gen(db, subject_id, unit_id, material_pack=pack)
    except OutlineError as e:
        raise _outline_err(e) from e


@router.get("/subjects/{subject_id}/coverage")
def subject_coverage(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """R37 S6：**覆盖账本**——`已覆盖节 / 总节` + 未覆盖清单 + 每单元来源材料/节标签/覆盖状态。

    数据源＝教材章/节地图（``outline.bookmap``）× 大纲单元溯源 × 单元生成时写回的覆盖状态；
    大纲页与前端复用同一份账（不新建平行机制）。
    """
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    return mat.coverage_ledger(db, subject_id)


# ---------- A2：概念层与进度映射（docs/14 §2.2） ----------
USER = "local"


@router.get("/subjects/{subject_id}/progress")
def get_progress(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """学科进度视图：单元达成/等效（概念命中）/开放；内容节点状态。

    等效达成 = 单元概念标签集 ⊆ 已掌握概念（重生成大纲后"进度不丢"的判定基础）。
    """
    _require_enabled(db, subject_id)
    try:
        return concept_svc.unit_states(db, USER, subject_id)
    except OutlineError as e:
        raise _outline_err(e) from e


@router.post("/subjects/{subject_id}/progress/recompute")
def recompute_progress(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """幂等重算概念掌握证据（= 数学历史掌握迁移入口：user_nodes.mastered → (subject, concept)）。"""
    _require_enabled(db, subject_id)
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
    _require_enabled(db, subject_id)
    try:
        report = concept_svc.reset_subject_progress(db, USER, subject_id)
        db.commit()
        return report
    except OutlineError as e:
        raise _outline_err(e) from e


# ---------- B3：内容来源策略 + 材料层（docs/14 §8） ----------
class PolicyBody(BaseModel):
    source_policy: str = "ai"


@router.get("/subjects/{subject_id}/policy")
def policy_get(subject_id: str, db: Session = Depends(get_db)) -> dict:
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    return {"subject_id": subject_id, "source_policy": mat.get_policy(db, subject_id)}


@router.put("/subjects/{subject_id}/policy")
def policy_put(subject_id: str, body: PolicyBody, db: Session = Depends(get_db)) -> dict:
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    try:
        policy = mat.set_policy(db, subject_id, body.source_policy)
    except OutlineError as e:
        raise _err(422, "validation_error", str(e)) from e
    return {"subject_id": subject_id, "source_policy": policy}


class MaterialUploadBody(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str = "本地导入"
    url: str = ""


@router.post("/subjects/{subject_id}/materials/upload", status_code=201)
def material_upload(subject_id: str, body: MaterialUploadBody,
                    db: Session = Depends(get_db)) -> dict:
    """本地导入（自有/授权 PDF/文本解析为文本后上传，或直接粘贴文本）。"""
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    try:
        entry = mat.add_material(db, subject_id, title=body.title, text=body.text,
                                 source=body.source, url=body.url)
    except OutlineError as e:
        raise _outline_err(e) from e
    return entry


@router.get("/subjects/{subject_id}/materials")
def material_list(subject_id: str, db: Session = Depends(get_db)) -> dict:
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    return {"subject_id": subject_id, "materials": mat.list_materials(db, subject_id)}


@router.delete("/subjects/{subject_id}/materials/{material_id}", status_code=204)
def material_delete(subject_id: str, material_id: str, db: Session = Depends(get_db)) -> None:
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    if not mat.delete_material(db, subject_id, material_id):
        raise _err(404, "not_found", f"材料不存在: {material_id}")


class PdfUploadOut(BaseModel):
    id: str
    title: str
    kind: str
    source: str
    url: str
    file: str
    filename: str
    pages: int | None = None
    chars: int | None = None
    text_health: dict | None = None   # R37 S7：文本层健康度（扫描版 → 中文告知，不静默出稿）


@router.post("/subjects/{subject_id}/materials/upload-pdf", status_code=201)
def material_upload_pdf(
    subject_id: str,
    db: Session = Depends(get_db),
    title: str = Form(""),
    file: UploadFile = File(...),
) -> PdfUploadOut:
    """PDF/文档上传 → 分页/分节文本 → 引用库（kind: pdf · Phase C C2）。

    大文件/非 PDF/解析失败 → 中文 422（docs/13 §2）；粘贴文本入口（materials/upload）保留。
    """
    _require_enabled(db, subject_id)
    from ..outline import materials as mat
    from ..outline.pdfparse import PdfParseError, parse_pdf_bytes

    filename = str(getattr(file, "filename", "") or "")
    data = file.file.read()
    try:
        parsed = parse_pdf_bytes(data, filename=filename)
    except PdfParseError as e:
        raise _err(422, "validation_error", str(e)) from e
    fname_stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    title = (title or "").strip() or fname_stem or "PDF 材料"
    try:
        entry = mat.add_material(
            db, subject_id, title=title, text=parsed["body"],
            source=f"PDF 导入（{filename or '用户上传'}）", url="",
            kind="pdf", filename=filename or fname_stem,
        )
    except OutlineError as e:
        raise _outline_err(e) from e
    return PdfUploadOut(**entry, pages=parsed["pages"], chars=parsed["chars"])

class SearchBody(BaseModel):
    query: str = Field(min_length=1)


@router.post("/subjects/{subject_id}/materials/search")
def material_search(subject_id: str, body: SearchBody, db: Session = Depends(get_db)) -> dict:
    """联网候选清单（外部检索后端 Phase C；离线/未接入返回提示，UI 明示）。"""
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    return mat.search_candidates(db, subject_id, body.query)


class SelectItem(BaseModel):
    title: str = Field(min_length=1)
    url: str = ""
    source: str = ""
    summary: str = Field(min_length=1)
    reason: str = ""
    fetch: bool = False  # Phase C C1：勾选即抓取该公开网页正文入库（大小上限/失败回落摘要）


class SelectBody(BaseModel):
    items: list[SelectItem] = Field(min_length=1)


@router.post("/subjects/{subject_id}/materials/select", status_code=201)
def material_select(subject_id: str, body: SelectBody, db: Session = Depends(get_db)) -> dict:
    """勾选候选 → 本地化引用（摘要入库，来源可追溯；不整本下载）。

    items[].fetch=true（C1：用户勾选动作）→ 抓取 http(s) 公开网页正文入库
    （robots/版权边界：不整本下载书籍、不抓 PDF 二进制；PDF 走 upload-pdf 用户上传）。
    """
    _require_enabled(db, subject_id)
    from ..outline import materials as mat

    items = [it.model_dump() for it in body.items]
    try:
        saved = mat.select_candidates(db, subject_id, items,
                                      fetch_pages=any(it["fetch"] for it in items))
    except OutlineError as e:
        raise _err(422, "validation_error", str(e)) from e
    return {"subject_id": subject_id, "saved": saved}
