"""service.feedback：内容纠错反馈闭环（docs/10 §3、docs/11 子步 9、工单 B 段）。

管线（工单 B 段，真正"重生成替换"）：
- 记录（record）：反馈入表 status=pending；**auto 节点**由调用方在提交后触发
  `spawn_auto_regen` → 后台线程执行重生成；**人工锚点**停留在复核队列（regenerate 端点对其只标 reviewed）。
- 重生成（`regenerate` / `_regenerate_node_now`）：auto 节点 → status=regenerating →
  复用 ai/drafting 的 AI 出稿器（未配 LLM_API_KEY → 记 failed、保留原内容待人工，**不回落 stub 占位**）→
  pipeline 自动校验（结构/sympy broken=0）→ 通过则**原子替换**内容文件（同目录临时文件 + os.replace）
  + refresh_library + sync_content（库内节点/边/掌握度随内容刷新）→ 该节点未处置反馈 pending/failed
  全部清零记 regenerated；失败（≤2 稿）→ status=failed + result 记录原因、原文件与库内节点保留。
- 并发：同一节点同时只允许一个重生成在飞（模块级活跃集合，防并行重复替换）。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .library import refresh_library, sync_content

KINDS = ("lecture", "exercise", "content", "answerability")
# R35 S7：kind=answerability = "这题我没法答（讲解里没有）" 的可答性投诉——**同表同闭环**，
# 不新建表；它同时进 guardrails 问题率（内容缺陷信号）并触发 auto 节点重生成。
# 未处置 = pending | regenerating | failed（regenerated/reviewed 视为已处置）
UNRESOLVED = ("pending", "regenerating", "failed")

_regen_lock = threading.Lock()
_regen_active: set[str] = set()


def node_source(node_id: str) -> str:
    """节点来源：auto（流水线生成）| human（人工/锚点）。读原始文件 front-matter source。"""
    from ..content.loader import load_library, parse_node_text

    try:
        lib = load_library()
        loaded = lib.by_id.get(node_id)
        if loaded is None:
            return "unknown"
        meta, _ = parse_node_text(loaded.raw_text)
        return meta.get("source", "human")
    except Exception:
        return "human"


def record(db: Session, user_id: str, *, node_id: str, kind: str, message: str, exercise_id: str | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS}")
    if not message.strip():
        raise ValueError("反馈内容不能为空")
    row = models.Feedback(
        user_id=user_id,
        node_id=node_id,
        kind=kind,
        exercise_id=exercise_id,
        message=message.strip(),
        status="pending",
        result="",
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "node_id": row.node_id,
        "kind": row.kind,
        "status": row.status,
        "source": node_source(node_id),
    }


def list_feedback(db: Session, user_id: str, *, status: str | None = None, node_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(models.Feedback).filter(models.Feedback.user_id == user_id)
    if status:
        q = q.filter(models.Feedback.status == status)
    if node_id:
        q = q.filter(models.Feedback.node_id == node_id)
    out = []
    for row in q.order_by(models.Feedback.id.desc()).limit(200).all():
        node = db.get(models.Node, row.node_id)
        out.append(
            {
                "id": row.id,
                "node_id": row.node_id,
                "node_title": node.title if node else row.node_id,
                "kind": row.kind,
                "exercise_id": row.exercise_id,
                "message": row.message,
                "status": row.status,
                "result": row.result,
                "source": node_source(row.node_id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return out


def _feedback_rows(db: Session, user_id: str, node_id: str) -> list:
    """该节点未处置（pending/failed）反馈行（重生成成功后全部清零；failed 允许重试）。"""
    return (
        db.query(models.Feedback)
        .filter(
            models.Feedback.user_id == user_id,
            models.Feedback.node_id == node_id,
            models.Feedback.status.in_(("pending", "failed")),
        )
        .all()
    )


def _atomic_replace(path: Path, raw_md: str) -> None:
    """原子替换内容文件：同目录临时文件 + os.replace。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(raw_md, encoding="utf-8")
    os.replace(tmp, path)


def _node_file_and_entry(node_id: str) -> tuple[Path | None, dict | None]:
    """返回 (文件路径, front-matter meta)。节点必须在内容库（stages）且来源 auto。"""
    from ..content.loader import load_library, parse_node_text

    lib = load_library()
    loaded = lib.by_id.get(node_id)
    if loaded is None:
        return None, None
    path = Path(loaded.path)
    meta, _ = parse_node_text(path.read_text(encoding="utf-8"))
    if meta.get("source", "human") != "auto":
        return None, None
    return path, meta


def regenerate(db: Session, user_id: str, feedback_id: int, *, wait: bool = False, drafter=None) -> dict[str, Any]:
    """显式重生成（复核动作）：
    - 人工锚点（source≠auto）：仅标 reviewed，不替换；
    - auto 节点：wait=True 同步执行（测试/脚本）；wait=False 起后台线程（API 默认），
      返回 regenerating；pending/failed 均可触发（regenerating 在飞时返回 already）。
    """
    row = db.get(models.Feedback, feedback_id)
    if row is None or row.user_id != user_id:
        raise KeyError(f"反馈不存在: {feedback_id}")
    src = node_source(row.node_id)
    if src != "auto":
        row.status = "reviewed"
        row.result = "人工节点：仅标记复核，不自动替换（人工修订）。"
        db.flush()
        return {
            "action": "manual_only",
            "node_id": row.node_id,
            "status": "reviewed",
            "message": row.result,
        }
    return _start_or_run_regen(db, user_id, row.node_id, wait=wait, drafter=drafter)


def spawn_auto_regen(node_id: str, user_id: str = "local") -> dict[str, Any]:
    """提交反馈后由 API 调用的自动触发入口（auto 节点；人工节点由调用方自行判断）。"""
    with _regen_lock:
        if node_id in _regen_active:
            return {"action": "regenerating", "node_id": node_id, "message": "该节点重生成已在后台进行中"}
    threading.Thread(target=_worker, args=(node_id, user_id), daemon=True).start()
    return {"action": "regenerating", "node_id": node_id, "message": "已提交复核；auto 内容将自动重生成替换（完成后可查看处理结果）"}


def _fail_node_feedback(node_id: str, user_id: str, err: Exception) -> None:
    """后台异常兜底：把该节点 pending/regenerating 反馈标为 failed 并写原因（杜绝无限待复核）。"""
    try:
        from .. import models
        from ..db import SessionLocal

        with SessionLocal() as db:
            rows = (
                db.query(models.Feedback)
                .filter(
                    models.Feedback.node_id == node_id,
                    models.Feedback.user_id == user_id,
                    models.Feedback.status.in_(("pending", "regenerating")),
                )
                .all()
            )
            reason = f"自动重生成异常：{type(err).__name__}: {str(err)[:200]}"
            for r in rows:
                r.status = "failed"
                r.result = reason
            db.commit()
    except Exception:
        pass


def _worker(node_id: str, user_id: str) -> None:
    from ..db import SessionLocal

    try:
        with SessionLocal() as wdb:
            _regenerate_node_now(wdb, user_id, node_id, drafter=None)
            wdb.commit()
    except Exception as e:  # 后台失败：标记 failed 留痕（不静默吞掉导致无限 pending）
        _fail_node_feedback(node_id, user_id, e)


def _start_or_run_regen(db: Session, user_id: str, node_id: str, *, wait: bool, drafter) -> dict[str, Any]:
    rows = _feedback_rows(db, user_id, node_id)
    if not rows:
        return {"action": "nothing", "node_id": node_id, "message": "该节点无未处置的反馈。"}
    if wait:
        return _regenerate_node_now(db, user_id, node_id, drafter=drafter)
    with _regen_lock:
        if node_id in _regen_active:
            return {"action": "already", "node_id": node_id, "message": "该节点重生成已在后台进行中"}
    # 后台线程在独立会话执行同一核心；核心内部自取活跃锁（防重复执行）
    def _run() -> None:
        from ..db import SessionLocal

        try:
            with SessionLocal() as wdb:
                _regenerate_node_now(wdb, user_id, node_id, drafter=drafter)
                wdb.commit()
        except Exception as e:  # 后台失败：标记 failed 留痕
            _fail_node_feedback(node_id, user_id, e)

    threading.Thread(target=_run, daemon=True).start()
    return {"action": "regenerating", "node_id": node_id, "message": "已启动后台重生成替换（完成后可在复核队列查看结果）"}


def _mark(db: Session, rows: list, status: str, result: str) -> None:
    for r in rows:
        r.status = status
        r.result = result


def _regenerate_node_now(db: Session, user_id: str, node_id: str, *, drafter=None) -> dict[str, Any]:
    """同步核心：出稿 → 自动校验 → 原子替换 + 库刷新同步 + 反馈清零。测试/脚本走 wait=True 同此路径。"""
    rows = _feedback_rows(db, user_id, node_id)
    if not rows:
        return {"action": "nothing", "node_id": node_id, "message": "该节点无未处置的反馈。"}
    with _regen_lock:
        if node_id in _regen_active:
            return {"action": "already", "node_id": node_id, "message": "该节点重生成已在后台进行中"}
        _regen_active.add(node_id)
    try:
        _mark(db, rows, "regenerating", "正在自动重生成替换…")
        db.flush()
        path, meta = _node_file_and_entry(node_id)
        if path is None or meta is None:
            _mark(db, rows, "failed", "节点不在内容库或非 auto 来源（保留原内容，请人工处理）。")
            db.flush()
            return {"action": "failed", "node_id": node_id, "message": "节点不可自动重生成（非 auto/不存在）。"}

        from ..domain.graph import LEVELS

        # R26：自定义学科（非数学 preset）内容重生成 = 学科化单元出稿
        # （group 名作层级，不走数学 roadmap 学段校验——修 RoadmapEntry level 校验炸）
        prefix = node_id.split(".", 1)[0]
        is_generic = prefix not in LEVELS
        if is_generic:
            from ..outline import generate as ogen

            try:
                res = ogen.generate_unit_content(db, prefix, node_id, force=True)
            except Exception as e:
                _mark(db, rows, "failed", f"自动重生成异常（通用学科）：{type(e).__name__}: {str(e)[:200]}")
                db.flush()
                return {"action": "failed", "node_id": node_id, "message": "通用学科重生成失败，保留原内容。"}
            if res.get("status") in ("created", "exists"):
                _invalidate_stale_practice(db, node_id)
                _mark(db, rows, "regenerated", res.get("note") or "已自动重生成替换（通用学科）。")
                db.flush()
                return {"action": "regenerated", "node_id": node_id,
                        "message": f"已自动重生成替换该单元（{len(rows)} 条反馈清零）。"}
            _mark(db, rows, "failed", res.get("note") or "重生成失败（保留原内容）。")
            db.flush()
            return {"action": "failed", "node_id": node_id, "message": res.get("note") or "重生成失败。"}

        from ..content import pipeline as pl
        from ..content.loader import load_library
        from ..content.roadmap import RoadmapEntry

        # 由现有文件 front-matter 重建蓝图条目（prereqs 已是落地后的真实引用）
        entry = RoadmapEntry(
            id=meta["id"],
            title=meta.get("title", node_id),
            level=meta.get("level", "primary"),
            topic=meta.get("topic", ""),
            objectives=list(meta.get("objectives") or []),
            prereqs=list(meta.get("prereqs") or []),
            difficulty=int(meta.get("difficulty", 2)),
            requires_thinking=bool(meta.get("requires_thinking", False)),
        )
        known_ids = set(load_library().by_id)
        user_notes = [f"用户纠错反馈：{r.message.strip()}" for r in rows if r.message.strip()][:3]

        if drafter is None:
            from ..ai.drafting import make_ai_drafter

            drafter = make_ai_drafter()
        if drafter is None:
            _mark(db, rows, "failed", "未配置 LLM_API_KEY：无法 AI 重生成（保留原内容待人工；配置 key 后重试可自动替换）。")
            db.flush()
            return {"action": "failed", "node_id": node_id, "message": "未配置 LLM_API_KEY，保留原内容待人工。"}

        attempts: list[str] = []
        raw_md: str | None = None
        last_errs: list[str] = []
        for attempt in range(1, 3):
            errors_arg = list(attempts) or list(user_notes)
            try:
                raw_md = drafter(entry, errors_arg or None)
            except Exception as e:  # 出稿器异常（DraftingError 等）
                attempts.append(f"[attempt {attempt}] 出稿器异常: {e}")
                raw_md = None
                continue
            errs = pl.validate_candidate(raw_md, known_ids)
            if not errs:
                # 出稿必须保持同一节点 id（防串位覆盖）
                try:
                    from ..content.loader import parse_node_text

                    new_meta, _ = parse_node_text(raw_md)
                    if new_meta.get("id") != node_id:
                        errs.append(f"重生成节点 id 应为 {node_id}，实得 {new_meta.get('id')!r}")
                except Exception as e:
                    errs.append(f"重生成产物解析失败: {e}")
            if not errs:
                break
            attempts.extend(f"[attempt {attempt}] {e}" for e in errs[:3])
            last_errs = errs
            raw_md = None

        if raw_md is None:
            detail = "; ".join((attempts or last_errs or ["未知"])[:4])
            _mark(db, rows, "failed", f"自动重生成失败（原内容保留）：{detail[:400]}")
            db.flush()
            return {"action": "failed", "node_id": node_id, "message": "重生成未通过校验，保留原内容（详见 result）。", "errors": attempts[:4]}

        _atomic_replace(path, raw_md)
        refresh_library()
        report = sync_content(db)
        if not report.ok:
            _mark(db, rows, "failed", f"内容文件已替换但库同步失败：{report.errors[:2]}（请重启服务或人工复核）")
            db.flush()
            return {"action": "failed", "node_id": node_id, "message": "库同步失败，请人工复核。"}
        _invalidate_stale_practice(db, node_id)  # R25：换题后清掉指向旧题目 id 的进行中练习
        _mark(db, rows, "regenerated", f"已自动重生成替换（第 {len([a for a in attempts if '[attempt' in a]) + 1} 稿通过自动校验；{len(rows)} 条反馈清零）。")
        db.flush()
        return {
            "action": "regenerated",
            "node_id": node_id,
            "message": f"已自动重生成替换该节点（{len(rows)} 条反馈清零）。",
        }
    finally:
        with _regen_lock:
            _regen_active.discard(node_id)


def _invalidate_stale_practice(db, node_id: str) -> None:
    """R25：内容自动替换后，清掉该节点会话里指向"旧题 id"的进行中练习，
    使其重新抽到新题（避免渲染不存在题目 id 报错 / 用户看到永不更新的旧题）。"""
    from sqlalchemy.orm.attributes import flag_modified

    from .. import models
    from ..content.loader import load_library

    lib = load_library()
    loaded = lib.by_id.get(node_id)
    node_doc = getattr(loaded, "doc", loaded) if loaded else None
    new_ids = {e.id for e in node_doc.exercises} if node_doc else set()
    rows = (
        db.query(models.Session)
        .filter(models.Session.node_id == node_id, models.Session.state == "learning")
        .all()
    )
    for s in rows:
        flow = s.flow_json
        if not flow:
            continue
        p = flow.get("practice") or {}
        if flow.get("stage") != "practice" or p.get("passed"):
            continue
        cur = p.get("current") or {}
        if cur.get("exercise_id") and cur["exercise_id"] not in new_ids:
            p["current"] = None
            p["attempts_this"] = 0
            p["hints_this"] = 0
            flow["practice"] = p
            s.flow_json = dict(flow)
            flag_modified(s, "flow_json")
    db.flush()


__all__ = [
    "record",
    "list_feedback",
    "regenerate",
    "spawn_auto_regen",
    "node_source",
    "KINDS",
    "UNRESOLVED",
]
