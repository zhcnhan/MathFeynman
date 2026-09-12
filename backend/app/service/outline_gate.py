"""service.outline_gate：通用学科的大纲门禁（docs/14 §2.2/§6 · Phase A A4）。

数学 = subject=math 的学习顺序由 roadmap 权威总序引擎（service/path，R18）驱动；
**通用学科（custom）**的内容节点学习顺序由各自 **Outline 大纲**权威驱动（概念层映射）：

- 节点 → 所属 (subject, unit)：内容节点 id == 大纲单元 id（通用学科内容按单元生成，
  单元 id 强制 `<subject>.` 前缀）；math 内容节点（level ∈ LEVELS）不经过本门禁；
- 单元满足（satisfied）= 覆盖内容节点 mastered 或 **概念等效已掌握**
  （concept_tags ⊆ (subject) 已掌握概念，A2）；学习中另有 learning 行；
- 单元开放（open）= 未满足 且 全部大纲前置单元已满足（等效即达成——"跳过/快速过"
  不卡后链）；
- 节点可学（allowed）= 其单元 satisfied（复习/快速过）或 open；否则 locked/409。

纯 DB+大纲文件计算：无 LLM/UI 依赖；大纲读取带**进程级 mtime/revision 指纹缓存**
（R19 块 3：多学科大量节点时避免每次按 node 重读大纲文件；文件变更后指纹失效自动重读）。
"""
from __future__ import annotations

import threading
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .. import models
from ..domain.graph import LEVELS
from ..outline import concepts as concept_svc
from ..outline import store as outline_store
from ..outline.schemas import OutlineDoc, OutlineError

# 课程内容节点的 subject 前缀 = 学段名的（math）不路由本门禁
_MATH_PREFIXES = set(LEVELS)

# 进程级大纲缓存：subject_id -> (指纹, OutlineDoc|None)
# 指纹 = outline.yaml 的 (mtime_ns,size)——文件被原子替换后指纹变化即重读；
# 显式清空入口 clear_outline_cache() 供长驻进程内外部变更后使用。
_cache_lock = threading.Lock()
_outline_cache: dict[str, tuple[str, OutlineDoc | None]] = {}


def _outline_path_of(subject_id: str):
    try:
        return outline_store.subject_dir(subject_id) / "outline.yaml"
    except Exception:
        return None


def _fingerprint(path) -> str:
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return ""


def clear_outline_cache(subject_id: str | None = None) -> None:
    """清空大纲进程缓存（subject_id 为空 = 全清；测试/外部文件变更后调用）。"""
    with _cache_lock:
        if subject_id is None:
            _outline_cache.clear()
        else:
            _outline_cache.pop(subject_id, None)


def _cached_outline(subject_id: str) -> OutlineDoc | None:
    """读大纲（进程缓存；指纹 = 文件 mtime_ns+size，变更自动重读）。"""
    path = _outline_path_of(subject_id)
    fp = _fingerprint(path) if path is not None else ""
    if not fp:
        with _cache_lock:
            _outline_cache.pop(subject_id, None)
        return None
    with _cache_lock:
        cached = _outline_cache.get(subject_id)
        if cached is not None and cached[0] == fp:
            return cached[1]
    doc: OutlineDoc | None = None
    try:
        doc = outline_store.get_outline(subject_id)
    except OutlineError:
        doc = None
    with _cache_lock:
        _outline_cache[subject_id] = (fp, doc)
    return doc


def _subject_ids(db: Session, *, include_removed: bool = False) -> set[str]:
    """学科 id 集（默认仅启用；include_removed=True 用于停用学科的内容识别/门禁分流）。"""
    q = db.query(models.Subject.id)
    if not include_removed:
        q = q.filter(models.Subject.enabled.is_(True))
    return {r[0] for r in q.all()}


def subject_of_node(db: Session, node_id: str) -> str | None:
    """节点 → 所属 subject（math=学段前缀；通用=学科前缀（含已停用））。None=未知。"""
    head, sep, _ = node_id.partition(".")
    if not sep or not head:
        return None
    if head in _MATH_PREFIXES:
        return "math"
    if head in _subject_ids(db, include_removed=True):
        return head
    return None


def disabled_subject_ids(db: Session) -> set[str]:
    """已停用学科 id 集（含 math——其内容以学段前缀标识，C3）。"""
    return {r[0] for r in db.query(models.Subject.id).filter(models.Subject.enabled.is_(False)).all()}


def is_node_subject_disabled(db: Session, node_id: str) -> bool:
    """节点所属学科是否停用（停用 → 视觉层/引擎一致隐藏；docs/14 §9 · C3）。"""
    head, sep, _ = node_id.partition(".")
    if not sep or not head:
        return False
    if head in _MATH_PREFIXES:
        return "math" in disabled_subject_ids(db)
    return head in disabled_subject_ids(db)


def visible_node_ids(db: Session, node_ids: Iterable[str]) -> list[str]:
    """按 subject.enabled 过滤内容节点（停用学科节点在仪表盘/图谱/推荐/复习一律隐藏）。"""
    disabled = disabled_subject_ids(db)
    if not disabled:
        return list(node_ids)
    out: list[str] = []
    for nid in node_ids:
        head, sep, _ = nid.partition(".")
        if not sep:  # 无学科前缀的孤立 id → 可视（不归属任何已停用学科）
            out.append(nid)
            continue
        if head in _MATH_PREFIXES:
            if "math" not in disabled:
                out.append(nid)
        elif head not in disabled:
            out.append(nid)
    return out


def is_subject_disabled(db: Session, subject_id: str) -> bool:
    return not outline_store.is_subject_enabled(db, subject_id)


def resolve_subject_unit(db: Session, node_id: str) -> tuple[str, str] | None:
    """内容节点 → (subject_id, unit_id)。math / 未知节点 → None（走 roadmap/内容前置兜底）。"""
    head, sep, _ = node_id.partition(".")
    if not sep or not head or head in _MATH_PREFIXES:
        return None
    subjects = _subject_ids(db)
    if head not in subjects:
        return None
    outline = _cached_outline(head)
    if outline is None or node_id not in outline.by_id():
        return None
    return head, node_id


def _outline_of(subject_id: str) -> OutlineDoc | None:
    return _cached_outline(subject_id)


def _node_states(db: Session, user_id: str, node_ids: set[str]) -> dict[str, str]:
    rows = (
        db.query(models.UserNode.node_id, models.UserNode.state)
        .filter(models.UserNode.user_id == user_id, models.UserNode.node_id.in_(node_ids))
    )
    return {nid: st for nid, st in rows}


def _satisfaction(
    db: Session,
    user_id: str,
    subject_id: str,
    outline: OutlineDoc,
    node_states: dict[str, str],
) -> tuple[dict[str, str], set[str]]:
    """{unit_id: satisfied|learning|todo} + 已掌握概念集。

    satisfied：单元覆盖节点 mastered；否则 concept_tags（非空）⊆ 已掌握概念 → equivalent 达成。
    """
    mastered_concepts = concept_svc.mastered_concepts(db, user_id, subject_id)
    sat: dict[str, str] = {}
    for u in outline.units:
        ns = node_states.get(u.id)
        if ns == "mastered":
            sat[u.id] = "satisfied"
        elif ns == "learning":
            sat[u.id] = "learning"
        else:
            tags = {concept_svc.normalize_tag(t) for t in u.concept_tags if concept_svc.normalize_tag(t)}
            if tags and tags <= mastered_concepts:
                sat[u.id] = "satisfied"  # 概念等效已掌握
            else:
                sat[u.id] = "todo"
    return sat, mastered_concepts


def unit_allowed(
    db: Session,
    user_id: str,
    subject_id: str,
    unit_id: str,
    outline: OutlineDoc | None = None,
) -> tuple[bool, list[str]]:
    """大纲单元是否可学：(已满足 或 前置全满足)。返回 (ok, 未满足前置标题列表)。"""
    outline = outline or _outline_of(subject_id)
    if outline is None:
        return False, [f"学科 {subject_id} 尚无大纲"]
    byid = outline.by_id()
    unit = byid.get(unit_id)
    if unit is None:
        return False, [f"单元不在大纲中: {unit_id}"]
    node_states = _node_states(db, user_id, {u.id for u in outline.units})
    sat, _ = _satisfaction(db, user_id, subject_id, outline, node_states)
    if sat.get(unit_id) == "satisfied":
        return True, []
    if sat.get(unit_id) == "learning":
        return True, []
    missing: list[str] = []
    for p in unit.prereqs:
        if p in byid:
            if sat.get(p) != "satisfied":
                missing.append(byid[p].title)
    if missing:
        return False, [f"请先完成：{'、'.join(missing[:5])}"]
    return True, []


def node_allowed(db: Session, user_id: str, node_id: str) -> tuple[bool, list[str]]:
    """内容节点门禁（通用学科）。math/未注册 → (False,[]) 由调用方走 roadmap 引擎。"""
    res = resolve_subject_unit(db, node_id)
    if res is None:
        return False, []
    subject_id, unit_id = res
    outline = _outline_of(subject_id)
    ok, missing = unit_allowed(db, user_id, subject_id, unit_id, outline)
    if ok:
        return True, []
    if not missing:
        missing = [f"当前节点尚未解锁（须按学科大纲顺序先学前置：{unit_id}）"]
    return False, missing


def refresh_concept_evidence(db: Session, user_id: str, node_id: str) -> dict | None:
    """节点掌握状态变化后同步刷新其学科概念证据（使大纲等效判定实时成立）。

    仅对通用学科（custom，大纲解析可命中）生效；math 走 roadmap 门禁，等效判定不依赖
    实时概念证据（数学迁移/查看经显式 recompute）。返回 recompute 报告或 None。
    """
    res = resolve_subject_unit(db, node_id)
    if res is None:
        return None
    from ..outline.concepts import recompute_subject_concepts

    return recompute_subject_concepts(db, user_id, res[0])


def subject_node_allowed(db: Session, user_id: str, node_id: str) -> bool:
    """快速判定节点归属通用学科大纲（供调用方分流）。"""
    return resolve_subject_unit(db, node_id) is not None


# ---------------------------------------------------------------------------
# **R54**：单元内容状态（**唯一口径**：会话守卫 / 大纲页 / 覆盖账同源）
# ---------------------------------------------------------------------------
# 可用线（阈值与理由见 NOTES §76 / 工单汇报）：
#   - 讲解正文非空：费曼环节要求学生"讲"，没有讲解＝没得可讲（用户实测撞到的正是这个）；
#   - 至少 1 道练习：练不成闭环就永远是半步。
# 注意：**这不是放松 R37 锚定**——丢弃记录照样如实记；这里只回答"丢完之后还能不能学"。
MIN_EXERCISES = 1
MIN_EXPLANATION_CHARS = 1


def unit_content_status(node_id: str) -> dict:
    """单元内容可用性（内容文件口径；不读账本、不猜）。

    返回：``exists`` 内容是否已生成；``usable`` 能否走完学习闭环；
    ``reason_zh`` 中文原因（可用时为空串）；``missing`` ∈ ``""|"content"|"explanation"|"exercise"``；
    以及 ``explanation_chars/exercises/taught_facts/asks/dropped_exercises`` 计数。

    ``dropped_exercises`` 取自大纲单元的覆盖记录（与覆盖账**同源**，不另算一套）。
    """
    from .library import get_library

    out = {"exists": False, "usable": False, "reason_zh": "这个单元还没有生成内容",
           "missing": "content", "explanation_chars": 0, "exercises": 0, "taught_facts": 0,
           "asks": 0, "dropped_exercises": 0, "title": ""}
    loaded = get_library().by_id.get(node_id)
    if loaded is None:
        return out
    doc = loaded.doc
    explanation = ""
    if getattr(doc, "explanation", None) is not None:
        explanation = str(getattr(doc.explanation, "body", "") or "").strip()
    exercises = len(list(getattr(doc, "exercises", None) or []))
    facts = len(list(getattr(doc, "taught_facts", None) or []))
    asks = len(list(getattr(doc, "asks", None) or []))
    out.update({"exists": True, "title": str(getattr(doc, "title", "") or ""),
                "explanation_chars": len(explanation), "exercises": exercises,
                "taught_facts": facts, "asks": asks})
    # 丢弃计数（同源：大纲单元的覆盖记录）
    subject_id = None
    head, sep, _ = str(node_id).partition(".")
    if sep:
        subject_id = head
    if subject_id:
        outline = _outline_of(subject_id)
        unit = (outline.by_id().get(node_id) if outline is not None else None)
        if unit is not None:
            cov = dict((getattr(unit, "meta", None) or {}).get("coverage") or {})
            out["dropped_exercises"] = int(cov.get("dropped_exercises") or 0)
            out["dropped_facts"] = int(cov.get("dropped_facts") or 0)
    dropped_facts = int(out.get("dropped_facts") or 0)
    if not explanation and not exercises:
        out.update({"missing": "content", "reason_zh": "这个单元还没有讲解和练习，先生成内容才能开始学"})
    elif not explanation:
        out.update({"missing": "explanation", "reason_zh": "这个单元还没有讲解正文，先生成讲解才能开始学"})
    elif exercises < MIN_EXERCISES:
        out.update({"missing": "exercise",
                    "reason_zh": "这个单元还没有可用的练习题（题目可能因为找不到教材依据被丢弃了），"
                                 "重新生成后才能开始练习"})
    elif facts == 0 and dropped_facts > 0:
        # 声明过事实句却一条都没留下：讲解的每句话都失去了教材依据（R35 S6/R37 的死结），
        # 这种单元**不可用**——宁可不学，也不编造。
        out.update({"missing": "facts",
                    "reason_zh": f"这个单元的事实依据全被丢弃了（{dropped_facts} 条在教材里找不到对应原文），"
                                 "重新生成后才能学"})
    else:
        out.update({"usable": True, "missing": "", "reason_zh": ""})
    return out


__all__ = [
    "resolve_subject_unit",
    "unit_allowed",
    "node_allowed",
    "subject_node_allowed",
    "refresh_concept_evidence",
    "clear_outline_cache",
    "_cached_outline",
    "subject_of_node",
    "is_subject_disabled",
    "disabled_subject_ids",
    "is_node_subject_disabled",
    "visible_node_ids",
    "unit_content_status",
    "MIN_EXERCISES",
]
