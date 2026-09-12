"""service.ledger：**「一切显性」铁则**的唯一记账入口（docs/09 R39 §1）。

> 铁则：程序任何时候"没有按用户以为的方式使用他的输入/产出"，都必须被记录、并可见。

本模块是**唯一入口**：所有"丢弃 / 截断 / 跳过 / 降级 / 失败 / 重试 / 替代"都必须经
``service.ledger`` 记账——**禁止**各处自行 ``print``，**禁止**只在 prompt 尾部提一句。
覆盖范围**不限于材料**：材料吸纳 / 生成与校验 / 模型调用 / 覆盖 / 其它（学科停用、
内容被纠错替换、复习降级回炉、提示词改动、审计清理…）。

两条可见通道（docs/09 R39 §1"两处可见"）：

1. **就地提示**——调用方拿 ``Accumulator``（``collector()`` 上下文）记账，
   结束时 ``to_dict()`` 随 API 响应下发，材料页/大纲页/单元页就地显示"本次丢弃了 X，原因…"；
2. **总账页**——``write()`` 同时落 ``content_ledger`` 表，``list_entries()`` 供
   ``GET /ledger`` 一处看全部（可按学科/类别筛）。

设计约束：
- **不阻塞主流程**：任何写库异常都被吞掉（只返回 id），绝不让"记账"把业务弄挂；
  **但"记账自己失败"不许静默**（R42 D1）：写库异常会打一行 stderr 兜底日志 ``[ledger] 记账失败: …``；
- **并发隔离**（R42 D2）：当前收集器用 ``contextvars.ContextVar``（不是模块级 list）——
  FastAPI 线程池/异步下并发请求**不会串账**；
- **中文原因**：``reason`` 必须是中文人话（验收口径：账本有中文原因）；
- **可判定**：每条"静默路径"都要有账本写入 + 用例（"造错必报"同款口径）。
"""
from __future__ import annotations

import contextvars
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

# ---------------------------------------------------------------------------
# 类别（docs/09 R39 §1 的完整清单；新增类别必须同时加到这里与 ``CATEGORY_LABELS_ZH``）
# ---------------------------------------------------------------------------
CAT_MATERIAL = "material"        # 材料吸纳（注入了多少 / 哪些没纳入 / 哪节被截断）
CAT_GENERATION = "generation"    # 生成与校验（重试 / 题与事实被丢弃 / 单元失败 / 降级启发式）
CAT_MODEL_CALL = "model_call"    # 模型调用（超时/报错/日限额拦截/降档/离线兜底）
CAT_COVERAGE = "coverage"        # 覆盖（教材哪些章节还没内容）
CAT_OTHER = "other"              # 其它（学科停用 / 内容被纠错替换 / 复习降级回炉 / 提示词改动…）

CATEGORIES = (CAT_MATERIAL, CAT_GENERATION, CAT_MODEL_CALL, CAT_COVERAGE, CAT_OTHER)

CATEGORY_LABELS_ZH: dict[str, str] = {
    # **R52 B**：类别名改成用户一眼能懂的（界面上直接显示这些字）
    CAT_MATERIAL: "读书情况",
    CAT_GENERATION: "出题与检查",
    CAT_MODEL_CALL: "问 AI 的情况",
    CAT_COVERAGE: "章节进度",
    CAT_OTHER: "其它",
}

# 影响面 / 可否补救 的规范化取值（中文，直接可渲染）
SCOPE_THIS_RUN = "本次操作"
SCOPE_UNIT = "该单元"
SCOPE_SUBJECT = "该学科"
SCOPE_GLOBAL = "全局"

REMEDY_YES = "可补救"
REMEDY_NO = "不可补救"
REMEDY_RETRY = "可通过重试/重新生成补救"
REMEDY_CONFIRM = "需用户确认后补救"


def category_label(cat: str) -> str:
    return CATEGORY_LABELS_ZH.get(str(cat or ""), "未分类")


# ---------------------------------------------------------------------------
# 数据形状
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# **R54 B**：账目的"出路"（丢弃不能只写"可通过重试补救"却不给入口）
# ---------------------------------------------------------------------------
def action_for(*, remedy: str, subject_id: str, unit_id: str) -> dict | None:
    """一条账目的**可操作出路**（给界面渲染成按钮）。

    - ``remedy == 可补救（重试/重新生成）`` 且知道是哪个学科/单元 → 一键「重新生成这个单元」；
    - 其它（不可补救 / 只做记录）→ ``None``（界面不给按钮，不给假希望）。

    **只读派生**：不改任何既有字段语义，只在读取时多带一个 ``action`` 键。
    """
    if not unit_id or not subject_id or remedy != REMEDY_RETRY:
        return None
    return {"kind": "regenerate_unit", "label_zh": "重新生成这个单元",
            "subject_id": subject_id, "unit_id": unit_id}


def resolve_unit_discards(subject_id: str, unit_id: str) -> int:
    """单元**重新生成成功后**，把该单元此前的"丢弃/失败"账目标记为已解决（**追加一条解决记录**，不改历史行）。

    - 账本仍**只增不改**（历史行保留原样，便于追溯"当时发生了什么"）；
    - 读取时（``list_entries``）凡在解决记录**之前**、同单元的"可补救"账目 → 标 ``resolved: true``；
    - **幂等**：该单元没有"尚未被解决"的丢弃账目时不写任何东西（不留噪音）。

    返回本次"解决掉"的账目条数（0 = 无需处理）。
    """
    from sqlalchemy import select

    from ..db import SessionLocal
    from .. import models

    if not unit_id or not subject_id:
        return 0
    try:
        with SessionLocal() as db:
            rows = list(db.execute(
                select(models.ContentLedger)
                .where(models.ContentLedger.unit_id == unit_id)
                .order_by(models.ContentLedger.id.asc())
            ).scalars())
            marks = _resolution_ids(rows)
            open_rows = [r for r in rows
                         if _is_resolvable(r) and not _resolved_by(int(r.id), marks)]
            if not open_rows:
                return 0
            write(Entry(category=CAT_OTHER, object=f"单元内容（{unit_id}）· 已重新生成",
                        reason=(f"这个单元已经重新生成好了：此前 {len(open_rows)} 条"
                                "「因为依据不足被丢弃 / 没出稿」的记录都作废了（明细保留可追溯）"),
                        impact=SCOPE_UNIT, remedy=REMEDY_NO, subject_id=subject_id,
                        unit_id=unit_id,
                        detail={"kind": "unit_regenerated", "unit_id": unit_id,
                                "subject_id": subject_id, "resolved_count": len(open_rows)},
                        created_at=_now_iso()))
            return len(open_rows)
    except Exception as e:  # 记账失败不阻塞生成（铁则：不阻塞主流程）
        _log_failure(e, Entry(category=CAT_OTHER, object=f"单元内容（{unit_id}）· 已重新生成",
                              reason="标记旧丢弃账目为已解决"))
        return 0


def _is_resolvable(row) -> bool:
    """该账目是不是"丢弃/失败、可重试"那一类（＝重新生成后应当作废的）。"""
    if str(getattr(row, "remedy", "") or "") != REMEDY_RETRY:
        return False
    return str((getattr(row, "detail_json", None) or {}).get("kind") or "") != "unit_regenerated"


def _resolution_ids(rows) -> list[int]:
    """一组账目里"已重新生成"记录的 id（按单元判定用；读取与写入共用同一口径）。"""
    return [int(r.id) for r in rows
            if str((getattr(r, "detail_json", None) or {}).get("kind") or "") == "unit_regenerated"]


def _resolved_by(entry_id: int, marks: list[int]) -> bool:
    """该账目是否被**之后**的"已重新生成"记录作废。"""
    return any(m > entry_id for m in marks)


@dataclass
class Entry:
    """一条账目（docs/09 R39 §1 要求的最小字段集）。"""

    category: str
    object: str                 # 对象（材料/单元/题号…）
    reason: str                 # 原因（**中文**）
    impact: str = ""            # 影响面
    remedy: str = ""            # 可否补救
    subject_id: str = ""
    unit_id: str = ""
    detail: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": None,
            "at": self.created_at,
            "category": self.category,
            "category_label": category_label(self.category),
            "subject_id": self.subject_id,
            "object": self.object,
            "reason": self.reason,
            "impact": self.impact,
            "remedy": self.remedy,
            "unit_id": self.unit_id,
            "detail": dict(self.detail or {}),
            # R54 B：可操作出路（丢什么 → 就地一键重新生成该单元）
            "action": action_for(remedy=self.remedy, subject_id=self.subject_id,
                                 unit_id=self.unit_id),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 单次操作的收集器（**就地提示**通道）
# ---------------------------------------------------------------------------
class Accumulator:
    """一次操作（起草/出稿/生成/调用）内的账目收集器。

    ``record()`` 既收进内存（供 API 就地回显），也**立即落库**（总账页可见）。
    """

    def __init__(self, *, subject_id: str = "", unit_id: str = "", persist: bool = True):
        self.subject_id = subject_id
        self.unit_id = unit_id
        self.persist = persist
        self.entries: list[Entry] = []

    def record(self, category: str, object: str, reason: str, *,
               impact: str = "", remedy: str = "", unit_id: str = "",
               subject_id: str = "", detail: dict | None = None,
               persist: bool = True) -> Entry:
        """记一条账目；``persist=False`` ＝ 只进内存（就地提示），**不落库**
        （R44 B：调用方已用 `write_via` 在同一事务里落过库时，避免二次落库/写锁自锁）。"""
        e = Entry(category=str(category), object=str(object or ""), reason=str(reason or ""),
                  impact=str(impact or ""), remedy=str(remedy or ""),
                  subject_id=subject_id or self.subject_id, unit_id=unit_id or self.unit_id,
                  detail=dict(detail or {}), created_at=_now_iso())
        self.entries.append(e)
        if self.persist and persist:
            write(e)
        return e

    # 便捷包装（覆盖清单里的高频类别；调用点不必记类别常量）
    def material(self, object: str, reason: str, **kw) -> Entry:
        kw.setdefault("impact", SCOPE_THIS_RUN)
        return self.record(CAT_MATERIAL, object, reason, **kw)

    def generation(self, object: str, reason: str, **kw) -> Entry:
        kw.setdefault("impact", SCOPE_UNIT)
        return self.record(CAT_GENERATION, object, reason, **kw)

    def model_call(self, object: str, reason: str, **kw) -> Entry:
        kw.setdefault("impact", SCOPE_THIS_RUN)
        return self.record(CAT_MODEL_CALL, object, reason, **kw)

    def coverage(self, object: str, reason: str, **kw) -> Entry:
        kw.setdefault("impact", SCOPE_SUBJECT)
        return self.record(CAT_COVERAGE, object, reason, **kw)

    def other(self, object: str, reason: str, **kw) -> Entry:
        return self.record(CAT_OTHER, object, reason, **kw)

    def has_entries(self) -> bool:
        return bool(self.entries)

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self.entries]

    def summary_zh(self) -> str:
        if not self.entries:
            return ""
        return "；".join(f"{category_label(e.category)}：{e.object}——{e.reason}"
                         for e in self.entries[:5])


# 当前调用链的"隐含收集器"（API 层建，深层函数无需层层传参即可记账）。
# **R42 D2**：用 ``contextvars.ContextVar``（**不是模块级 list**）——
# FastAPI 线程池/异步下并发请求各有自己的上下文，**不会串账**；
# 同一上下文内可**嵌套**（内层 collector 覆盖外层，退出后自动还原）。
_CURRENT: contextvars.ContextVar[Accumulator | None] = contextvars.ContextVar(
    "yanhui_ledger_current", default=None)


@contextmanager
def collector(subject_id: str = "", unit_id: str = "", *, persist: bool = True) -> Iterator[Accumulator]:
    """建立一次操作的收集器上下文：``with ledger.collector(sid, uid) as acc: ...``。

    可嵌套（内层生效，退出后还原外层）；**线程/任务隔离**（ContextVar 语义）。
    """
    acc = Accumulator(subject_id=subject_id, unit_id=unit_id, persist=persist)
    token = _CURRENT.set(acc)
    try:
        yield acc
    finally:
        _CURRENT.reset(token)


def current() -> Accumulator | None:
    """当前收集器（无则 None）；供深层调用点"顺手记账"而不必改所有签名。"""
    return _CURRENT.get()


def note(category: str, object: str, reason: str, *, impact: str = "", remedy: str = "",
         subject_id: str = "", unit_id: str = "", detail: dict | None = None) -> Entry | None:
    """向当前收集器记一条；**没有收集器时也落库**（总账页仍可见，绝不静默）。

    这是给"深层代码"用的轻入口：``ledger.note(ledger.CAT_MODEL_CALL, "费曼评分", "超时", …)``。
    """
    acc = current()
    if acc is not None:
        return acc.record(category, object, reason, impact=impact, remedy=remedy,
                          subject_id=subject_id, unit_id=unit_id, detail=detail)
    e = Entry(category=str(category), object=str(object or ""), reason=str(reason or ""),
              impact=str(impact or ""), remedy=str(remedy or ""),
              subject_id=str(subject_id or ""), unit_id=str(unit_id or ""),
              detail=dict(detail or {}), created_at=_now_iso())
    write(e)
    return e


# ---------------------------------------------------------------------------
# 落库 + 查询（**总账页**通道）
# ---------------------------------------------------------------------------
def _log_failure(e: Exception, entry: Entry) -> None:
    """记账失败时的 stderr 兜底（**不静默**；连日志都写不出去也不能炸）。"""
    try:
        print(f"[ledger] 记账失败: {type(e).__name__}: {e}"
              f"（类别={entry.category} 对象={entry.object} 原因={entry.reason[:80]}）",
              file=sys.stderr)
    except Exception:
        pass


def _row_of(entry: Entry):
    from .. import models

    return models.ContentLedger(
        subject_id=entry.subject_id, unit_id=entry.unit_id, category=entry.category,
        object=entry.object, reason=entry.reason, impact=entry.impact,
        remedy=entry.remedy, detail_json=dict(entry.detail or {}),
    )


def write(entry: Entry) -> int | None:
    """把一条账目写入 ``content_ledger`` 表；失败**不影响主流程**（返回 None）。

    **R42 D1**：保持"不阻塞主流程"不变（**不抛异常**），但**加一道进程日志兜底**
    （stderr，形如 ``[ledger] 记账失败: …``）——让"记账自己失败"**不静默**
    （架构侧 R41 §5 观察项 1）。
    """
    try:
        from ..db import SessionLocal

        with SessionLocal() as db:
            row = _row_of(entry)
            db.add(row)
            db.commit()
            return int(row.id or 0) or None
    except Exception as e:  # 记账失败绝不影响业务（铁则要求"不阻塞主流程"）
        _log_failure(e, entry)
        return None


def write_via(db, entry: Entry) -> int | None:
    """把一条账目落进**调用方现有事务**（与调用方一起提交 / 一起回滚）。

    **R44 B 引入的唯一理由**：调用方**已持有写事务**时（例：回炉 —— `demote_to_learning`
    刚 flush 过 `user_nodes`/`relearn_logs`），若仍走 `write()` 的**独立连接**，SQLite 会
    **自锁**（外连接等内连接、内连接又在等外连接提交 → `database is locked`），账目**静默丢失**。
    这里改用调用方会话落库（`flush` 后本会话与后续读取都能看到），**仍是同一份账本**
    （`content_ledger` 表 + 本模块唯一入口，不新建第二套账）。

    口径：账目与调用方**同生共死**——回炉被回滚，则它的索引条目一并回滚（这正是要的语义：
    索引指向的那次回炉确实存在）。
    """
    try:
        row = _row_of(entry)
        db.add(row)
        db.flush()
        return int(row.id or 0) or None
    except Exception as e:
        _log_failure(e, entry)
        return None


def list_entries(db, *, subject_id: str = "", category: str = "", limit: int = 200,
                 offset: int = 0) -> dict:
    """总账页数据源：按学科/类别筛，时间倒序。

    **R54 B**：每条带 ``action``（丢弃 → 就地一键「重新生成这个单元」）与 ``resolved``
    （该单元后来已重新生成 → 此条旧丢弃记录已作废，界面不应再当作"当前问题"）。
    """
    from sqlalchemy import select

    from .. import models

    stmt = select(models.ContentLedger)
    if subject_id:
        stmt = stmt.where(models.ContentLedger.subject_id == subject_id)
    if category:
        stmt = stmt.where(models.ContentLedger.category == category)
    stmt = stmt.order_by(models.ContentLedger.id.desc()).offset(max(0, offset)).limit(
        max(1, min(int(limit or 200), 500)))
    rows = list(db.execute(stmt).scalars())
    # 解决标记：{unit_id: [「已重新生成」记录 id…]}（全表扫，量级小；只读不改历史行）
    marks: dict[str, list[int]] = {}
    for r in db.execute(select(models.ContentLedger).where(
            models.ContentLedger.category == CAT_OTHER)).scalars():
        if str((r.detail_json or {}).get("kind") or "") != "unit_regenerated":
            continue
        uid = str(r.unit_id or "")
        if uid:
            marks.setdefault(uid, []).append(int(r.id))
    items = []
    for r in rows:
        detail = dict(r.detail_json or {})
        remedy = r.remedy or ""
        uid = r.unit_id or ""
        items.append({
            "id": int(r.id),
            "at": _to_iso(r.created_at),
            "category": r.category or CAT_OTHER,
            "category_label": category_label(r.category or CAT_OTHER),
            "subject_id": r.subject_id or "",
            "unit_id": uid,
            "object": r.object or "",
            "reason": r.reason or "",
            "impact": r.impact or "",
            "remedy": remedy,
            "detail": detail,
            # R54 B：出路与是否已被后续重生成作废
            "action": action_for(remedy=remedy, subject_id=r.subject_id or "", unit_id=uid),
            "resolved": bool(detail.get("kind") != "unit_regenerated" and uid
                             and _resolved_by(int(r.id), marks.get(uid, []))),
        })
    return {
        "entries": items,
        "count": len(items),
        "categories": [{"key": k, "label": CATEGORY_LABELS_ZH[k]} for k in CATEGORIES],
        "filter": {"subject_id": subject_id, "category": category},
    }


def counts_by_category(db, *, subject_id: str = "") -> list[dict]:
    """类别计数（供总账页做筛选项徽标）。"""
    from sqlalchemy import func, select

    from .. import models

    stmt = select(models.ContentLedger.category, func.count()).group_by(models.ContentLedger.category)
    if subject_id:
        stmt = stmt.where(models.ContentLedger.subject_id == subject_id)
    got = {str(c or CAT_OTHER): int(n) for c, n in db.execute(stmt).all()}
    return [{"key": k, "label": CATEGORY_LABELS_ZH[k], "count": got.get(k, 0)} for k in CATEGORIES]


def _to_iso(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


__all__ = [
    "CATEGORIES", "CATEGORY_LABELS_ZH", "CAT_MATERIAL", "CAT_GENERATION", "CAT_MODEL_CALL",
    "CAT_COVERAGE", "CAT_OTHER", "SCOPE_THIS_RUN", "SCOPE_UNIT", "SCOPE_SUBJECT", "SCOPE_GLOBAL",
    "REMEDY_YES", "REMEDY_NO", "REMEDY_RETRY", "REMEDY_CONFIRM",
    "Entry", "Accumulator", "category_label", "collector", "current", "note", "write",
    "write_via",
    "action_for", "resolve_unit_discards",
    "list_entries", "counts_by_category",
]
