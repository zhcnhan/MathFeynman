"""app.outline.store：学科注册 + 大纲持久化（docs/14 §1 数据与 docs/14 §2.1）。

数据布局（对齐 docs/14 "大纲文件按 subject/<outline_id>.yaml 存放"）：
    <content>/subjects/                       # 学科大纲数据根（git 管理；loader 不加载）
    <content>/subjects/<subject_id>/outline.yaml   # 当前大纲（revision 递增，原子替换；
                                                # 历史修订由 git 留痕——MVP 无归档副本）

DB（subjects 表）：学科注册（id/label/kind=preset|custom/description/meta）。
- preset math 在启动/ensure 时注册（kind=preset，受代码治理：不得删除、结构编辑受 roadmap 约束）；
- custom 学科由 API 创建（kind=custom，可删除；进度清理语义见 A2 显式重置）。

大纲语义规则（v1）：
- 整份重生成 = 构造新 OutlineDoc → add_outline(revision=当前+1, 原子替换)；
- preset(math) 大纲由 roadmap 派生（source=roadmap）：不允许结构编辑（防大纲与 roadmap 漂移，
  学习引擎仍读 roadmap）；单元级 PATCH 仅允许概念标签等附加字段（A2 起生效）；
- custom 大纲可整体 PUT 采纳 / 单元 PATCH 局部改。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from ..config import REPO_ROOT  # noqa: F401  (类型注释/文档引用)
from ..content import content_root
from .schemas import (
    OUTLINE_SCHEMA_VERSION,
    SUBJECT_ID_RE,
    OutlineDoc,
    OutlineError,
    OutlineUnit,
    load_outline_yaml,
    outline_to_yaml,
    validate_outline_doc,
)

PRESET_MATH = "math"  # 预置学科 id（docs/14 §5：数学 = 第一个 preset）

# preset(math) 大纲中允许通过 PATCH 局部修改的字段（其余结构字段受 roadmap 治理）
_PRESET_PATCHABLE = ("concept_tags", "status", "meta")

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 目录 ----------
def subjects_root() -> Path:
    return content_root() / "subjects"


def subject_dir(subject_id: str) -> Path:
    if not SUBJECT_ID_RE.match(subject_id):
        raise OutlineError(f"学科 id {subject_id!r} 非法（须匹配 {SUBJECT_ID_RE.pattern}）")
    return subjects_root() / subject_id


def _outline_path(subject_id: str) -> Path:
    return subject_dir(subject_id) / "outline.yaml"


# ---------- DB 注册 ----------
def register_subject(
    db: Session,
    *,
    subject_id: str,
    label: str,
    kind: str = "custom",
    description: str = "",
) -> models.Subject:
    """注册学科（幂等：已存在则返回既有行并更新 label/description）。"""
    if kind not in ("preset", "custom"):
        raise OutlineError(f"kind 非法: {kind!r}")
    if subject_id != PRESET_MATH and kind == "preset":
        raise OutlineError(f"preset 学科 id 必须为 {PRESET_MATH!r}")
    row = db.get(models.Subject, subject_id)
    if row is None:
        row = models.Subject(id=subject_id, label=label, kind=kind, description=description)
        db.add(row)
    else:
        row.label = label
        row.description = description or row.description
    db.flush()
    return row


def ensure_math_preset(db: Session) -> models.Subject:
    """启动时注册 math preset（幂等）。"""
    return register_subject(db, subject_id=PRESET_MATH, label="数学", kind="preset",
                            description="预置学科：五学段课程蓝图 + sympy 确定性判题 + 费曼评估（roadmap 治理）")


def get_subject(db: Session, subject_id: str) -> models.Subject | None:
    return db.get(models.Subject, subject_id)


def list_subjects(db: Session, *, include_removed: bool = False) -> list[models.Subject]:
    """学科列表（默认仅启用；include_removed=True 返回全部含停用，供"移除可恢复"管理）。"""
    q = db.query(models.Subject)
    if not include_removed:
        q = q.filter(models.Subject.enabled.is_(True))
    rows = q.all()
    # preset 排前（math），其后按创建时间
    rows.sort(key=lambda r: (0 if r.kind == "preset" else 1, r.created_at or datetime.min))
    return rows


def create_subject(
    db: Session,
    *,
    label: str,
    description: str = "",
    subject_id: str | None = None,
) -> models.Subject:
    """创建自定义学科：注册 DB 行 + 初始化大纲目录（无大纲文件 = 待起草）。"""
    if not label or not label.strip():
        raise OutlineError("学科名称不能为空")
    if subject_id is not None:
        from ..domain.graph import LEVELS

        if subject_id in LEVELS or subject_id == PRESET_MATH:
            raise OutlineError(
                f"学科 id {subject_id!r} 为保留前缀（学段名/math preset），请换名"
            )
    sid = subject_id
    if sid is None:
        sid = _slugify(label)
        if not sid:
            # 中文等无法 ASCII 转写的名称 → 稳定回退 id（s-<label 哈希前 8 位>），
            # 让"中文名学科"无需用户手填英文 id 即可创建
            import hashlib

            sid = "s-" + hashlib.sha1(label.strip().encode("utf-8")).hexdigest()[:8]
    base, n = sid, 1
    while db.get(models.Subject, sid) is not None:
        n += 1
        sid = f"{base}-{n}"
        if n > 1000:  # pragma: no cover - 防御
            raise OutlineError("学科 id 生成冲突过多")
    row = register_subject(db, subject_id=sid, label=label.strip(), kind="custom",
                           description=description.strip())
    d = subject_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    db.commit()
    return row


def _slugify(label: str) -> str:
    """ASCII 化学科 id 草稿：仅保留 a-z0-9 与连字符（允许数字开头，5b49a8a 语义）。

    中文字符直接剥离（中文/纯符号名称 → 空 → 调用方走稳定 s-<hash> 回退）。
    """
    s = re.sub(r"[^0-9a-z]+", "-", label.strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", s or "-"):
        return ""
    return s[:32]


def delete_subject(db: Session, subject_id: str, *, hard: bool = False) -> models.Subject:
    """学科移除（docs/14 §9"移除可恢复"，B4）。

    - hard=False（默认）＝**停用移除**：任何学科（含 preset math）——从列表隐藏（enabled=False）、
      清除该学科内容节点的 user_nodes/reviews 与 (subject) user_concepts 概念证据；
      **大纲/内容文件与（math）roadmap 留盘**，可随时 enable_subject 恢复；启动不复活已移除
      math（ensure_math_preset 不翻转 enabled）。
    - hard=True＝**连同文件删除**（仅 custom）：物理移除内容文件（stages/<sid>/ 与大纲/材料目录）
      + Node 行禁用 + 注册行删除；preset（math）roadmap 受治理不支持 hard（抛 OutlineError）。
    attempts/sessions 审计留痕不删（A2 重置口径）。
    """
    row = db.get(models.Subject, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    if hard and row.kind == "preset":
        raise OutlineError("预置学科不支持'连同文件删除'（roadmap/大纲受治理留盘；可停用移除）")

    # 0) 大纲单元（+本学科前缀锚点）→ 内容节点 id 集（进度清理基准；soft 时文件保留）
    outline = get_outline(subject_id)
    unit_ids: set[str] = set()
    if outline is not None:
        unit_ids = {u.id for u in outline.units}
        unit_ids |= {a for u in outline.units for a in u.anchors if a.startswith(f"{subject_id}.")}

    if hard:
        # hard：物理移除内容文件（stages/<sid>/ 懒生成产物）
        from ..content import stages_dir

        content_dir = stages_dir() / subject_id
        if content_dir.exists():
            for p in content_dir.rglob("*.md"):
                p.unlink(missing_ok=True)
            try:
                content_dir.rmdir()
            except OSError:
                pass
            from ..service.library import refresh_library, sync_content

            refresh_library()
            sync_content(db)  # Node 行转 disabled

    # 进度/概念证据清理（soft 与 hard 都做；概念注册表 soft 保留可恢复，hard 清除）
    if unit_ids:
        db.query(models.UserNode).filter(
            models.UserNode.node_id.in_(unit_ids),
        ).delete(synchronize_session=False)
        db.query(models.Review).filter(
            models.Review.node_id.in_(unit_ids),
        ).delete(synchronize_session=False)
    db.query(models.UserConcept).filter(
        models.UserConcept.subject_id == subject_id
    ).delete(synchronize_session=False)
    if hard:
        db.query(models.Concept).filter(models.Concept.subject_id == subject_id).delete(
            synchronize_session=False
        )

    if hard:
        # 大纲文件 + 材料目录 + 注册行
        d = subject_dir(subject_id)
        if d.exists():
            for p in d.rglob("*.yaml"):
                p.unlink(missing_ok=True)
            for p in d.rglob("*.md"):
                p.unlink(missing_ok=True)
            try:
                for sub in list(d.rglob("*"))[::-1]:
                    sub.rmdir()
            except OSError:
                pass
            try:
                d.rmdir()
            except OSError:
                pass
        db.delete(row)
    else:
        row.enabled = False
        row.removed_at = datetime.now(timezone.utc)
    db.commit()
    return row


def enable_subject(db: Session, subject_id: str) -> models.Subject:
    """重新启用被移除的学科（大纲/内容文件留盘即恢复；无大纲者恢复为空待起草）。"""
    row = db.get(models.Subject, subject_id)
    if row is None:
        raise OutlineError(f"学科不存在: {subject_id}")
    row.enabled = True
    row.removed_at = None
    db.commit()
    return row


def is_subject_enabled(db: Session, subject_id: str) -> bool:
    """学科是否启用（缺省 True：行不存在视为不阻塞；用于会话/门禁分流）。"""
    row = db.get(models.Subject, subject_id)
    return row is None or bool(row.enabled)


# ---------- 大纲持久化 ----------
def _subject_must_exist(db: Session, subject_id: str) -> models.Subject:
    row = get_subject(db, subject_id)
    if row is None:
        raise OutlineError(f"学科未注册: {subject_id}")
    return row


def _check_unit_namespace(subject_id: str, units: list[OutlineUnit]) -> None:
    """自定义学科单元 id 必须带 `<subject>.` 前缀（内容节点全局唯一命名空间约定）。

    math preset 单元 id 复用既有命名（primary.s01/锚点节点），不走本检查（A3 派生路径）。
    """
    bad = [u.id for u in units if not u.id.startswith(f"{subject_id}.")]
    if bad:
        raise OutlineError(
            f"单元 id 必须带学科前缀 <{subject_id}>.：{bad}（内容节点全局唯一命名空间约定）"
        )


def get_outline(subject_id: str) -> OutlineDoc | None:
    """读取当前大纲文件（不存在 → None；结构损坏 → OutlineError）。"""
    p = _outline_path(subject_id)
    if not p.exists():
        return None
    with _lock:
        return load_outline_yaml(p.read_text(encoding="utf-8"))


def save_outline(subject_id: str, doc: OutlineDoc) -> None:
    """大纲落盘（原子替换：同目录临时文件 + os.replace）。"""
    d = subject_dir(subject_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".outline.yaml.tmp"
    tmp.write_text(outline_to_yaml(doc), encoding="utf-8")
    tmp.replace(_outline_path(subject_id))


def validate_outline(doc: OutlineDoc, *, known_content_ids: set[str] | None = None) -> list[str]:
    """校验包装（供 API/测试统一调用）。"""
    return validate_outline_doc(doc, known_content_ids=known_content_ids)


def add_outline(
    db: Session,
    subject_id: str,
    *,
    units: list[OutlineUnit] | None = None,
    data: dict | None = None,
    status: str = "draft",
    source: str = "manual",
    note: str = "",
    known_content_ids: set[str] | None = None,
) -> OutlineDoc:
    """创建或整份重生成大纲（revision 递增；源=roadmap 的 preset 大纲不经此路径编辑）。

    units 或 data 二选一（data 为完整 OutlineDoc dict；units 为解析后的单元列表）。
    custom 学科首个大纲：revision=1, status=传入（默认 draft，采纳时 active）。
    再次调用 = 重生成：revision+1（原子替换旧文件，版本递增语义）。
    """
    subj = _subject_must_exist(db, subject_id)
    if subj.kind == "preset":
        raise OutlineError(
            "预置学科大纲由 roadmap 派生治理（docs/14 §5），禁止直接 PUT；"
            "请用派生入口 regenerate_math_outline()"
        )
    if source not in ("ai", "heuristic", "manual", "hybrid"):
        raise OutlineError(f"自定义学科大纲 source 非法: {source!r}")
    prev = get_outline(subject_id)
    revision = (prev.revision + 1) if prev else 1
    doc: OutlineDoc
    if data is not None:
        doc = OutlineDoc(**data)
        if doc.subject != subject_id:
            raise OutlineError(f"大纲 subject 字段 {doc.subject!r} 与学科 {subject_id!r} 不符")
        _check_unit_namespace(subject_id, doc.units)
    else:
        doc = OutlineDoc(subject=subject_id, label=subj.label, units=list(units or []))
        _check_unit_namespace(subject_id, doc.units)
    doc.label = doc.label or subj.label
    doc.revision = revision
    doc.status = status if status in ("draft", "active") else "draft"
    doc.source = source
    doc.note = note or doc.note
    doc.schema_version = OUTLINE_SCHEMA_VERSION
    doc.unit_id_scope = "subject"
    doc.updated_at = _now_iso()
    if revision == 1:
        doc.generated_at = _now_iso()
    problems = validate_outline(doc, known_content_ids=known_content_ids)
    if problems:
        raise OutlineError("大纲校验未通过：" + "；".join(problems))
    save_outline(subject_id, doc)
    db.commit()
    return doc


def patch_outline_unit(
    db: Session,
    subject_id: str,
    unit_id: str,
    *,
    fields: dict,
    known_content_ids: set[str] | None = None,
) -> OutlineDoc:
    """单元局部改（审阅修订）：custom 任意白名单字段；preset(math) 仅附加字段。

    fields: {field: value}（title/objectives/concept_tags/prereqs/…）；
    结构字段（id/group 移动）需整份 PUT/roadmap 治理。
    """
    subj = _subject_must_exist(db, subject_id)
    doc = get_outline(subject_id)
    if doc is None:
        raise OutlineError(f"学科 {subject_id} 尚无大纲")
    byid = doc.by_id()
    unit = byid.get(unit_id)
    if unit is None:
        raise OutlineError(f"单元不存在: {unit_id}")
    allowed = set(OutlineUnit.model_fields.keys()) - {"id", "group"}
    if subj.kind == "preset":
        allowed &= set(_PRESET_PATCHABLE)  # preset 结构受 roadmap 治理
    unknown = set(fields) - allowed
    if unknown:
        raise OutlineError(f"不允许修改字段: {sorted(unknown)}")
    if subj.kind == "preset" and fields:
        pass  # concept_tags/status/meta 允许（A2 起生效；当前 preset 大纲尚未派生）
    # 逐字段重建（pydantic 校验由 OutlineUnit 承担）
    new_fields = {f: getattr(unit, f) for f in allowed}
    new_fields.update(fields)
    try:
        new_unit = OutlineUnit(id=unit.id, group=unit.group, **new_fields)
    except Exception as e:
        raise OutlineError(f"单元 {unit_id} 字段非法: {e}") from e
    idx = doc.units.index(unit)
    doc.units[idx] = new_unit
    problems = validate_outline(doc, known_content_ids=known_content_ids)
    if problems:
        raise OutlineError("修订后大纲校验未通过：" + "；".join(problems))
    doc.updated_at = _now_iso()
    save_outline(subject_id, doc)
    db.commit()
    return doc


def delete_outline(db: Session, subject_id: str) -> None:
    """删除大纲文件（学科保留）。preset 不可删大纲。"""
    subj = _subject_must_exist(db, subject_id)
    if subj.kind == "preset":
        raise OutlineError("预置学科大纲不可删除")
    _outline_path(subject_id).unlink(missing_ok=True)
    db.commit()


__all__ = [
    "PRESET_MATH",
    "subjects_root",
    "subject_dir",
    "register_subject",
    "ensure_math_preset",
    "get_subject",
    "list_subjects",
    "create_subject",
    "delete_subject",
    "enable_subject",
    "is_subject_enabled",
    "get_outline",
    "save_outline",
    "validate_outline",
    "add_outline",
    "patch_outline_unit",
    "delete_outline",
]
