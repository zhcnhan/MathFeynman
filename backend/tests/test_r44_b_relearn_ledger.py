"""R44 任务 B 用例：**回炉在总账（R39 账本）留引用条目**（R41 §3-③ 漏做项）。

口径（单一权威源不改）：
- `relearn_logs` 仍是回炉明细的**唯一真源**；总账只加一条**索引**条目——
  类别 `other`（总账页「其它」）、**中文原因**、`detail.ref="relearn_logs"` + `relearn_id`
  /`ref_key` 指针（问题单要求"不要复制 relearn_logs 内容，避免双源"）；
- **同一次回炉幂等**（重复触发不重复记账）；
- 落库走**调用方事务**（`ledger.write_via`）：回炉发生在 `demote_to_learning` 已 flush 的
  写事务里，独立连接的 `ledger.write` 会自锁（`database is locked`）→ 账目丢失（实测）。

三条必交用例：`b1`（一次回炉 → +1 条中文索引）、`b2`（重复触发 → 幂等）、
`b3`（回归：`relearn_logs` 照常写）；另加 `b4`（会话路径的回炉同样入索引）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.domain.fsrs import RATING_AGAIN
from app.main import app
from app.service import review as review_svc


@pytest.fixture(scope="module")
def client():
    """模块内独立 TestClient：先重置业务数据（跨模块共享同一 sqlite 文件时的顺序隔离）。"""
    _reset_db()
    with TestClient(app) as c:
        yield c


def _reset_db() -> None:
    from sqlalchemy import text

    from app.db import init_db
    from app.service.library import ensure_user, sync_content

    init_db()
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes",
                  "edges", "ai_logs", "nodes", "users", "content_ledger"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def _ledger_rows(*, node_id: str = "", ref: str = "") -> list[dict]:
    """按节点/引用键读账本（新会话，读已提交真相）。"""
    with SessionLocal() as db:
        q = db.query(models.ContentLedger).filter(models.ContentLedger.category == "other")
        if node_id:
            q = q.filter(models.ContentLedger.unit_id == node_id)
        rows = q.order_by(models.ContentLedger.id.desc()).all()
        out = [{"id": int(r.id), "object": r.object or "", "reason": r.reason or "",
                "impact": r.impact or "", "remedy": r.remedy or "",
                "unit_id": r.unit_id or "", "detail": dict(r.detail_json or {})}
               for r in rows]
    if ref:
        out = [r for r in out if r["detail"].get("ref") == ref]
    return out


def _prepare_mastered(node_id: str) -> None:
    """把节点置为"已掌握 + 已排程复习"（回炉前件）。"""
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, node_id)
        row = db.get(models.UserNode, ("local", node_id))
        if row is None:
            row = models.UserNode(user_id="local", node_id=node_id)
            db.add(row)
        row.state = "mastered"
        row.consecutive_correct = 3
        db.flush()
        review_svc.schedule_first(db, "local", node_id)
        db.commit()


def _again_twice(node_id: str) -> dict:
    """两次 `RATING_AGAIN`（lapse 2 → 回炉），返回第二次的提交结果。"""
    with SessionLocal() as db:
        review_svc.submit_review(db, "local", node_id, RATING_AGAIN)
        db.commit()
    with SessionLocal() as db:
        out = review_svc.submit_review(db, "local", node_id, RATING_AGAIN)
        db.commit()
    return out


def test_r44_b1_relearn_writes_one_chinese_index_entry(client):
    """**必交①**：触发一次"again×2 → 回炉" → 账本 +1 条、原因**中文**、
    `detail.ref` 指向 `relearn_logs`；且**只做索引**（不抄明细）。"""
    node = "middle.0102"
    _prepare_mastered(node)
    before = len(_ledger_rows(node_id=node, ref="relearn_logs"))

    out = _again_twice(node)

    assert out["action"] == "relearn", out
    hits = _ledger_rows(node_id=node, ref="relearn_logs")
    assert len(hits) == before + 1, [h["reason"] for h in hits]
    hit = hits[0]
    assert hit["object"] == f"节点 {node} · 回炉", hit["object"]
    reason = hit["reason"]
    assert any("\u4e00" <= ch <= "\u9fff" for ch in reason), reason
    assert "回炉" in reason and "复习记录" in reason, reason
    assert "relearn_logs" in reason, reason
    assert hit["impact"] and hit["remedy"], hit
    # 指针键齐备（可追到 relearn_logs 具体一条）
    with SessionLocal() as db:
        logs = db.query(models.RelearnLog).filter(models.RelearnLog.node_id == node).all()
        assert len(logs) == 1
        log_id = int(logs[0].id)
    assert hit["detail"]["ref"] == "relearn_logs"
    assert int(hit["detail"]["relearn_id"]) == log_id, hit["detail"]
    # 只做索引：detail 不带明细正文
    assert set(hit["detail"]) <= {"ref", "relearn_id", "ref_key", "user_id", "kind"}, hit["detail"]
    assert "reason" not in hit["detail"]
    # 总账页「其它」类别里看得见（界面可见性）
    api = client.get("/api/ledger?category=other").json()
    shown = [e for e in api["entries"] if (e.get("detail") or {}).get("ref") == "relearn_logs"]
    assert shown and shown[0]["category_label"] == "其它", shown[:2]
    assert any("\u4e00" <= ch <= "\u9fff" for ch in shown[0]["reason"])


def test_r44_b2_same_relearn_is_idempotent(client):
    """**必交②**：同一次回炉**重复触发** → **不重复记账**（幂等）；不同次回炉 → 允许新记。"""
    from app.service import progress as progress_svc

    node = "middle.0102"
    with SessionLocal() as db:
        assert progress_svc.note_relearn_in_ledger(
            db, user_id="local", node_id=node, reason="复习 again/hard 累计2次",
            relearn_id=990001) is True
        # 同一个 relearn_id 再来一次（同一次回炉被重复调用）→ 幂等跳过
        assert progress_svc.note_relearn_in_ledger(
            db, user_id="local", node_id=node, reason="复习 again/hard 累计2次",
            relearn_id=990001) is False
        db.commit()
    rows = [r for r in _ledger_rows(node_id=node) if r["detail"].get("relearn_id") == 990001]
    assert len(rows) == 1, f"同一次回炉只应留一条；实际 {len(rows)}"

    # 另一次回炉（新 relearn_id）→ 允许再记一条（不是永久去重）
    with SessionLocal() as db:
        assert progress_svc.note_relearn_in_ledger(
            db, user_id="local", node_id=node, reason="再次回炉", relearn_id=990002) is True
        db.commit()
    got = {r["detail"].get("relearn_id") for r in _ledger_rows(node_id=node)}
    assert {990001, 990002} <= got, got


def test_r44_b3_relearn_logs_is_still_the_single_source(client):
    """**必交③（回归）**：`relearn_logs` 本身**照常写**（单一权威源没被破坏）。"""
    node = "middle.0103"
    _prepare_mastered(node)

    out = _again_twice(node)

    assert out["action"] == "relearn", out
    with SessionLocal() as db:
        logs = db.query(models.RelearnLog).filter(models.RelearnLog.node_id == node).all()
        assert len(logs) == 1, [x.reason for x in logs]
        assert str(logs[0].reason or "").strip(), "relearn_logs 必须照常写（原因非空）"
        row = db.get(models.UserNode, ("local", node))
        assert row.state == "learning", "回炉后节点状态应为 learning"
    hits = _ledger_rows(node_id=node, ref="relearn_logs")
    assert len(hits) == 1, [h["reason"] for h in hits]


def test_r44_b4_session_path_relearn_is_indexed_and_idempotent(client):
    """会话路径的回炉（练习连错 / 费曼额度尽）同样进总账索引；
    幂等键 = 会话 + 节点 + 原因（同一次会话回炉只记一条）。"""
    from app.service import progress as progress_svc

    node = "middle.0104"
    key = "sess-r44:练习连续答错"
    with SessionLocal() as db:
        first = progress_svc.note_relearn_in_ledger(
            db, user_id="local", node_id=node, reason="练习连续答错", extra_key=key)
        again = progress_svc.note_relearn_in_ledger(
            db, user_id="local", node_id=node, reason="练习连续答错", extra_key=key)
        db.commit()
    assert first is True and again is False, (first, again)
    hits = _ledger_rows(node_id=node, ref="relearn_logs")
    assert len(hits) == 1, [h["reason"] for h in hits]
    assert "练习连续答错" in hits[0]["reason"], hits[0]["reason"]
    assert hits[0]["detail"]["ref_key"] == key
    # 就地提示通道：有活跃收集器时同一条也进收集器（不重复落库）
    from app.service import ledger

    with ledger.collector("", "") as acc:
        with SessionLocal() as db:
            progress_svc.note_relearn_in_ledger(
                db, user_id="local", node_id=node, reason="费曼额度尽", extra_key="sess-r44:feynman")
            db.commit()
        assert any(e.detail.get("ref") == "relearn_logs" for e in acc.entries), acc.to_list()
    assert len(_ledger_rows(node_id=node, ref="relearn_logs")) == 2


def test_r44_b5_relearn_index_survives_api_path(client):
    """**端到端（API 口径）**：走 `POST /api/review/submit`（真实请求事务）回炉一次，
    总账索引条目在请求返回后**确实已提交**（不是只在会话内 flush）。"""
    node = "middle.0102"
    with SessionLocal() as db:
        row = db.get(models.UserNode, ("local", node))
        row.state = "mastered"
        row.consecutive_correct = 3
        db.query(models.Review).filter(models.Review.node_id == node).delete()
        db.flush()
        review_svc.schedule_first(db, "local", node)
        db.commit()
    before = len(_ledger_rows(node_id=node, ref="relearn_logs"))
    r1 = client.post("/api/review/submit", json={"node_id": node, "rating": RATING_AGAIN})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/review/submit", json={"node_id": node, "rating": RATING_AGAIN})
    assert r2.status_code == 200, r2.text
    assert r2.json()["action"] == "relearn", r2.json()
    hits = _ledger_rows(node_id=node, ref="relearn_logs")
    assert len(hits) == before + 1, [h["reason"] for h in hits]
    assert hits[0]["detail"]["relearn_id"], hits[0]["detail"]
    api = client.get("/api/ledger?category=other").json()
    assert any((e.get("detail") or {}).get("ref") == "relearn_logs" for e in api["entries"])
    # 复习队列里已无该节点（Review 行被删，与旧行为一致）
    assert not any(x["node_id"] == node for x in client.get("/api/review/queue").json()["due"])
