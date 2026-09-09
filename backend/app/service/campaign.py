"""service.campaign：关卡化快照（docs/10 §2.1、docs/11 阶段 2）。

- 关卡分组 = (level, topic)；组内节点 + 可选 boss（kind=boss，综合+费曼综述）。
- 解锁/通关复用现有掌握度/前置（user_nodes + 图谱 prereq），不建第二套引擎：
  组完成 = 组内全部节点 mastered（reviewing 视同 mastered）；关卡入口解锁沿用图谱 available。
- 学段解锁：上一学段所有已定义关卡组完成（或上一学段无内容）→ 下一学段入口开放（表现层）。
- 自续提示：当前已学尽且下一关尚无内容 → next_generating（"下一关生成中…"，阶段 3 接 roadmap）。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..content.schemas import NodeDoc
from ..domain.graph import LEVELS
from . import progress as progress_svc
from . import review as review_svc
from .library import get_library

MASTERED_OR_REVIEWING = {"mastered", "reviewing"}


@dataclass
class Group:
    level: str
    topic: str
    nodes: list[NodeDoc] = field(default_factory=list)

    @property
    def normal_nodes(self) -> list[NodeDoc]:
        return [n for n in self.nodes if n.kind != "boss"]

    @property
    def boss(self) -> NodeDoc | None:
        bosses = [n for n in self.nodes if n.kind == "boss"]
        return bosses[0] if bosses else None


def _groups_by_level() -> dict[str, list[Group]]:
    lib = get_library()
    grouped: dict[str, dict[str, Group]] = {}
    for loaded in lib.nodes:
        doc = loaded.doc
        grouped.setdefault(doc.level, {}).setdefault(doc.topic, Group(level=doc.level, topic=doc.topic)).nodes.append(doc)
    out: dict[str, list[Group]] = {}
    for level, topics in grouped.items():
        groups = list(topics.values())
        # 组间稳定顺序：组内最小节点 id（反映编辑/课程序列）
        groups.sort(key=lambda g: min((n.id for n in g.nodes), default=""))
        out[level] = groups
    return out


def _completed(group: Group, states: dict[str, str]) -> bool:
    return all(states.get(n.id, "locked") in MASTERED_OR_REVIEWING for n in group.nodes)


def _stage_defined(level: str) -> bool:
    return bool(_groups_by_level().get(level))


def snapshot(db: Session, user_id: str = "local", *, now: dt.datetime | None = None) -> dict[str, Any]:
    from . import outline_gate as og

    graph = get_library().graph
    states = progress_svc.state_map(db, user_id, graph, now=now)
    by_level = _groups_by_level()

    # C3（docs/14 §9/R23 B4#2）：关卡地图按 subject.enabled 过滤——停用学科（含 math）
    # 的内容节点整体从地图隐藏（引擎 409 之外的视觉层；与图谱/仪表盘口径一致）。
    visible = set(og.visible_node_ids(db, graph.node_ids))
    for level in [lv for lv, groups in by_level.items() if groups]:
        kept: list[Group] = []
        for g in by_level[level]:
            g.nodes = [n for n in g.nodes if n.id in visible]
            if g.nodes:
                kept.append(g)
        by_level[level] = kept
    for lv in [lv for lv, groups in by_level.items() if not groups]:
        by_level.pop(lv, None)

    # 学段解锁：本学段所有已定义组完成（或本学段无内容组）
    stage_unlocked: dict[str, bool] = {}
    for level in LEVELS:
        groups = by_level.get(level, [])
        stage_unlocked[level] = (not groups) or all(_completed(g, states) for g in groups)

    level_views = []
    next_group_ref: dict | None = None
    next_generating = False
    all_defined_completed = True
    any_defined = False
    for level in LEVELS:
        groups = by_level.get(level, [])
        if groups:
            any_defined = True
        for g in groups:
            for n in g.nodes:
                if states.get(n.id, "locked") not in MASTERED_OR_REVIEWING:
                    all_defined_completed = False
        view_groups = []
        for g in groups:
            boss = g.boss
            completed = _completed(g, states)
            mastered_n = sum(1 for n in g.nodes if states.get(n.id, "locked") in MASTERED_OR_REVIEWING)
            view_groups.append(
                {
                    "topic": g.topic,
                    "completed": completed,
                    "progress": {"mastered": mastered_n, "total": len(g.nodes)},
                    "nodes": [
                        {
                            "id": n.id,
                            "title": n.title,
                            "kind": n.kind,
                            "state": states.get(n.id, "locked"),
                        }
                        for n in sorted(g.nodes, key=lambda x: x.id)
                    ],
                    "boss": (
                        {
                            "id": boss.id,
                            "title": boss.title,
                            "state": states.get(boss.id, "locked"),
                        }
                        if boss
                        else None
                    ),
                }
            )
            # 找"下一关"：第一个未完成组（本学段解锁时）
            if next_group_ref is None and not completed and stage_unlocked.get(level, False):
                next_group_ref = {"level": level, "topic": g.topic, "key": f"{level}:{g.topic}"}
        level_views.append({"level": level, "unlocked": stage_unlocked[level], "groups": view_groups})

    # 全部已定义组完成 & 后续无内容 → 自续提示（无任何可见内容时不算"全部通关"）
    if any_defined and all_defined_completed:
        next_generating = True
    return {
        "levels": level_views,
        "next": next_group_ref,
        "next_generating": next_generating,
        "boss_trigger": None,  # 由 boss 通过事件动态填充（见 service/session）
    }


def boss_recap(db: Session, user_id: str, group: Group) -> dict[str, Any]:
    """boss 通过后的学段小结/复习整合提示（docs/10 §2.1）。"""
    due = review_svc.due_queue(db, user_id)
    profile = None
    try:
        from .library import ensure_user
        from ..domain.profile import Profile

        user = ensure_user(db, user_id)
        profile = Profile.from_dict(user.profile_json or {})
    except Exception:
        pass
    top_errors = []
    if profile:
        top_errors = [et for et, _ in sorted(profile.error_profile.items(), key=lambda kv: -kv[1])[:3]]
    return {
        "topic": group.topic,
        "due_reviews": len(due),
        "top_error_types": top_errors,
        "suggestion": "主题首领已掌握：建议顺手完成到期复习，并针对高频错误做一次口述复盘。",
    }


__all__ = ["snapshot", "boss_recap", "Group", "_groups_by_level"]
