"""R18 阶段 3：总序门禁测试矩阵（docs/09 R18 验收：任何学段"后学先可学"=未通过）。

覆盖：
- 五学段抽样链：未达前置 / 学段未解锁 start → 409 invalid_state；依序达成 → 200；
- 分数红线：乘法口诀(s03)在百以内加减(s02)后、分数意义锚(0102/s06)在因数倍数(s27)后；
- boss 前锁后开（middle.0199 = 蓝图组全达成）；
- 跨学段：primary 通关前 middle 内容 409 → 通关后 200（含 high.0201 学段预修孤儿）；
- fresh-run 单调推进：master 前缀后下一环解锁断言。
（内容：hermetic 副本 seed primary s01–s04；链上缺失 auto 由 order_support.unlock_until 现场生成）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app


@pytest.fixture(scope="module")
def client():
    _reset_db()
    _seed_primary_head()
    with TestClient(app) as c:
        yield c


def _reset_db() -> None:
    from sqlalchemy import text

    from app.db import init_db
    from app.service.library import ensure_user, sync_content

    init_db()
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes", "edges", "ai_logs", "feedback", "nodes", "users"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        sync_content(db)
        db.commit()


def _seed_primary_head() -> None:
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap
    from app.service.library import refresh_library, sync_content

    pl.generate_sequence(load_roadmap("primary"), ["primary.s01", "primary.s02", "primary.s03", "primary.s04"])
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()


def fresh_user() -> None:
    """每测试独立起点：清用户进度态（内容/Nodes 保留；副本模块内共享）。"""
    from sqlalchemy import text

    from app.db import init_db
    from app.service.library import ensure_user

    init_db()
    with SessionLocal() as db:
        for t in ("attempts", "reviews", "sessions", "relearn_logs", "user_nodes"):
            db.execute(text(f"DELETE FROM {t}"))
        ensure_user(db)
        db.commit()


def start(client, node_id: str) -> tuple[int, dict]:
    r = client.post("/api/session/start", json={"node_id": node_id})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"text": r.text}


def _assert_409(status: int, body: dict) -> None:
    assert status == 409, (status, body)
    assert body.get("detail", {}).get("error", {}).get("code") == "invalid_state", body


def _assert_200(status: int) -> None:
    assert status == 200, status


# ---------------------------------------------------------------------------
# primary：链式 409 → 依序解锁；分数红线（口诀/因数倍数在前）
# ---------------------------------------------------------------------------
def test_primary_chain_409_then_sequential_unlock(client):
    fresh_user()
    # 根可学
    s, _ = start(client, "primary.s01")
    _assert_200(s)
    # s02 需 s01 达成 → 409
    _assert_409(*start(client, "primary.s02"))
    from order_support import master

    with SessionLocal() as db:
        master(db, ["primary.s01"])
        db.commit()
    _assert_200(start(client, "primary.s02")[0])
    # s03（乘法口诀）仍锁：需 s02
    _assert_409(*start(client, "primary.s03"))
    with SessionLocal() as db:
        master(db, ["primary.s02", "primary.s03"])
        db.commit()
    _assert_200(start(client, "primary.s04")[0])


def test_primary_score_line_after_multiplication_and_lcm(client):
    """红线：分数意义(0102/s06)不可先于因数倍数(s27)；口诀(s03)不可先于加减(s02)。"""
    fresh_user()
    from order_support import master, unlock_until

    # 0 掌握：0101(s05 四则) 也锁
    _assert_409(*start(client, "primary.0101"))
    with SessionLocal() as db:
        unlock_until(db, "primary.0101")
        db.commit()
    _assert_200(start(client, "primary.0101")[0])
    # 0101 mastered（s05 达成）后：0102(s06) 仍需 s27（因数倍数）→ 409
    with SessionLocal() as db:
        master(db, ["primary.0101"])
        db.commit()
    _assert_409(*start(client, "primary.0102"))
    with SessionLocal() as db:
        unlock_until(db, "primary.0102")
        db.commit()
    _assert_200(start(client, "primary.0102")[0])


# ---------------------------------------------------------------------------
# middle / high / college / ai：跨学段门禁与抽样链
# ---------------------------------------------------------------------------
def test_middle_cross_level_lock_then_unlock(client):
    fresh_user()
    # middle 内容在 primary 通关前全部 409（跨学段总序）
    _assert_409(*start(client, "middle.0101"))
    from order_support import master, unlock_until

    with SessionLocal() as db:
        unlock_until(db, "middle.0101")
        db.commit()
    # 达成概念(0101) → 等式性质(0104)解锁；解方程(0102)仍锁（须先 0104）
    with SessionLocal() as db:
        master(db, ["middle.0101"])
        db.commit()
    _assert_200(start(client, "middle.0104")[0])
    _assert_409(*start(client, "middle.0102"))
    # 达成 0104 → 0102 解锁
    with SessionLocal() as db:
        master(db, ["middle.0104"])
        db.commit()
    _assert_200(start(client, "middle.0102")[0])


def test_high_orphan_prereq_gate(client):
    fresh_user()
    _assert_409(*start(client, "high.0201"))  # primary/middle 未通关
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, "high.0201")  # 孤儿：前序学段通关即可（内容 prereq 空）
        db.commit()
    _assert_200(start(client, "high.0201")[0])


def test_college_chain_gate_with_seeded_content(client):
    """college：seed c01 auto → 未解锁 409 → 前序（primary/middle/high）通关 → 200。"""
    fresh_user()
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap
    from app.service.library import refresh_library, sync_content

    pl.generate_sequence(load_roadmap("college"), ["college.c01"])
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()
    _assert_409(*start(client, "college.c01"))
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, "college.c01")
        db.commit()
    _assert_200(start(client, "college.c01")[0])


def test_ai_chain_gate_with_seeded_content(client):
    fresh_user()
    from app.content import pipeline as pl
    from app.content.roadmap import load_roadmap
    from app.service.library import refresh_library, sync_content

    pl.generate_sequence(load_roadmap("ai"), ["ai.a01"])
    refresh_library()
    with SessionLocal() as db:
        sync_content(db)
        db.commit()
    _assert_409(*start(client, "ai.a01"))
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, "ai.a01")
        db.commit()
    _assert_200(start(client, "ai.a01")[0])


# ---------------------------------------------------------------------------
# boss 门禁 / 允许集 / fresh-run 单调
# ---------------------------------------------------------------------------
def test_boss_locked_until_group_complete(client):
    fresh_user()
    _assert_409(*start(client, "middle.0199"))  # 组未全达成
    from order_support import unlock_until

    with SessionLocal() as db:
        unlock_until(db, "middle.0199")  # 归属组（蓝图 m11–m19）全达成
        db.commit()
    _assert_200(start(client, "middle.0199")[0])


def test_graph_available_is_total_order_allowed(client):
    """图谱 available 集 = 总序允许集：available 中抽样 start 200；locked 抽样 409。"""
    fresh_user()
    g = client.get("/api/graph").json()
    states = {n["id"]: n["state"] for n in g["nodes"]}
    avail = [nid for nid, st in states.items() if st == "available"]
    locked = [nid for nid, st in states.items() if st == "locked"]
    assert avail, "seed 后 primary.s01 应 available"
    _assert_200(start(client, avail[0])[0])
    if locked:
        _assert_409(*start(client, locked[0]))


def test_fresh_run_monotonic_progress_e2e(client):
    """fresh-run：0 掌握 → 从 s01 依序推进（每掌握一环解锁下一环，绝不错位）。"""
    fresh_user()
    from order_support import master

    seq = ["primary.s01", "primary.s02", "primary.s03", "primary.s04"]
    for i, nid in enumerate(seq):
        # 已掌握前 i 个：第 i+1 个可学、之后的不行
        ok_status, _ = start(client, nid)
        _assert_200(ok_status)
        if i + 1 < len(seq):
            _assert_409(*start(client, seq[i + 1]))
        with SessionLocal() as db:
            master(db, [nid])
            db.commit()
    # 前缀全掌握 → 0101(四则混合锚 s05) 解锁；分数意义(0102)仍锁（缺因数倍数 s27）
    _assert_200(start(client, "primary.0101")[0])
    _assert_409(*start(client, "primary.0102"))
