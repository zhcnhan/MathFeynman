"""R18 测试支撑：按蓝图总序在 hermetic 内容副本中"生成缺失 auto 内容 + 直插链达成"，
把环境解锁到目标节点可学（模拟真实懒生成的既定结果；不污染真实仓库，副本隔离）。

用法（测试模块）：
    from order_support import unlock_until
    # 模块 fixture 中（client DB 就绪后）：
    with SessionLocal() as db:
        unlock_until(db, "middle.0102")   # 链上 auto 生成 + 前置达成（不含目标自身，目标留给测试真学）
        db.commit()
    # boss：unlock_until(db, "middle.0199") → 归属主题组全部达成，boss 可开。
"""
from __future__ import annotations

LVLS = ("primary", "middle", "high", "college", "ai")


def _roadmaps() -> dict:
    from app.content.roadmap import load_roadmap

    out = {}
    for lv in LVLS:
        try:
            out[lv] = load_roadmap(lv)
        except Exception:
            pass
    return out


def _registry() -> dict:
    from app.content.roadmap import all_entries

    return all_entries()


def _landed(e, lib_ids: set) -> str | None:
    if e.anchors and e.anchors[0] in lib_ids:
        return e.anchors[0]
    if e.id in lib_ids:
        return e.id
    return None


def _owner_of(node_id: str, roadmaps: dict):
    for _lv, rd in roadmaps.items():
        if node_id in rd.by_id():
            return rd.by_id()[node_id]
    for _lv, rd in roadmaps.items():
        for e in rd.entries:
            if node_id in e.anchors:
                return e
    return None


def _boss_group_entries(node_id: str, level: str, topic: str, roadmaps: dict) -> list:
    from app.service.path import boss_group_topic

    rd = roadmaps.get(level)
    if rd is None:
        return []
    group = boss_group_topic(level, topic, rd)
    if group is None:
        return []
    return [e for e in rd.entries if e.topic == group]


def closure_entries(node_id: str, *, include_self: bool = False) -> list:
    """目标可学所需"达成闭包"：目标所属条目 + 全部蓝图前置条目（递归；跨学段仅收已落地者）。"""
    from app.content.loader import load_library

    lib = load_library()
    lib_ids = set(lib.by_id)
    doc = lib.by_id[node_id].doc
    level, kind, topic = doc.level, doc.kind or "", doc.topic or ""
    roadmaps = _roadmaps()
    reg = _registry()
    roots = []
    if kind == "boss":
        roots = _boss_group_entries(node_id, level, topic, roadmaps)
    else:
        own = _owner_of(node_id, roadmaps)
        if own is None:
            return []  # 孤儿：无需达成（学段解锁由调用方另行处理）
        roots = [own]

    seen: dict[str, object] = {}

    def add(e) -> None:
        if e.id in seen:
            return
        seen[e.id] = e
        for p in e.prereqs:
            ref = reg.get(p)
            if ref is not None and ref[0] != e.level:
                ref_entry = ref[1]
                if _landed(ref_entry, lib_ids) is None:
                    continue  # 跨学段目标未落地 → 不阻塞
                add(ref_entry)
                continue
            for _lv2, rd2 in roadmaps.items():
                by2 = rd2.by_id()
                if p in by2:
                    add(by2[p])
                    break

    for e in roots:
        add(e)
    if not include_self and kind != "boss" and roots:
        seen.pop(roots[0].id, None)
    # 稳定排序：学段顺序 → 蓝图列表顺序（生成/达成按此执行）
    order_index = {lv: i for i, lv in enumerate(LVLS)}
    ordered = sorted(seen.values(), key=lambda e: (order_index.get(e.level, 99), _list_index(e)))
    return ordered


def _list_index(e) -> int:
    from app.content.roadmap import load_roadmap

    try:
        rd = load_roadmap(e.level)
    except Exception:
        return 0
    return list(rd.by_id()).index(e.id)


def unlock_until(db, node_id: str, *, include_self: bool = False) -> None:
    """生成链上缺失 auto 内容 → 刷新库 → DB 同步 → 把闭包（不含目标自身）达成（UserNode mastered）。"""
    from app.content import pipeline as pl
    from app.content.loader import load_library
    from app.service.library import refresh_library, sync_content

    closure = closure_entries(node_id, include_self=include_self)

    closure = closure_entries(node_id, include_self=include_self)
    if not closure:
        # 孤儿目标：无条目闭包 → 至少需要前序学段通关；由下方前序达成逻辑兜底
        pass
    # 1) 生成缺失内容（蓝图列表序，先决先生成；幂等：已落地条目 exists/covered 自动跳过）
    for lv in LVLS:
        missing = [e for e in closure if e.level == lv and _landed(e, set(load_library().by_id)) is None]
        if not missing:
            continue
        from app.content.roadmap import load_roadmap

        rd = load_roadmap(lv)
        ordered_ids = [e.id for e in missing]
        # 先确保同文件前置也入本批（防列表序在子集内靠后）
        res = pl.generate_sequence(rd, ordered_ids)
        refresh_library()
        bad = [r for r in res if r.status == "failed"]
        if bad:
            raise RuntimeError(f"unlock_until 生成失败: {bad[0].entry_id} {bad[0].errors[:2]}")
    refresh_library()
    # 2) DB 同步（Node/Edge 行，UserNode FK 依赖）——先 flush 本会话 pending，防重复 add 冲突
    db.flush()
    sync_content(db)
    db.flush()
    # 3) 达成：闭包全部落地条目 + 目标学段之前的"前序学段已落地条目"全部 mastered
    #    （R18 level_unlocked：前序学段通关才能进目标学段）
    lib_ids = set(load_library().by_id)
    from app.content.loader import load_library as _ll

    doc = _ll().by_id[node_id].doc
    to_master: list[str] = []
    for e in closure:
        landed = _landed(e, lib_ids)
        if landed:
            to_master.append(landed)
    prior_ok = False
    if doc.level in LVLS:
        idx = LVLS.index(doc.level)
        roadmaps = _roadmaps()
        for prior in LVLS[:idx]:
            rd = roadmaps.get(prior)
            if rd is None or not rd.entries:
                continue
            for e in rd.entries:
                landed = _landed(e, lib_ids)
                if landed:
                    to_master.append(landed)
        prior_ok = True
    if not prior_ok and not to_master and closure:
        pass
    from app import models as m

    for nid in to_master:
        row = db.get(m.UserNode, ("local", nid))
        if row is None:
            row = m.UserNode(user_id="local", node_id=nid)
            db.add(row)
        row.state = "mastered"
        row.consecutive_correct = 3
    db.flush()


def master(db, ids: list[str]) -> None:
    from app import models as m

    for nid in ids:
        row = db.get(m.UserNode, ("local", nid))
        if row is None:
            row = m.UserNode(user_id="local", node_id=nid)
            db.add(row)
        row.state = "mastered"
        row.consecutive_correct = 3
    db.flush()


__all__ = ["unlock_until", "master", "closure_entries", "LVLS"]
