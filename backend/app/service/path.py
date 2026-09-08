"""service.path：蓝图总序门禁（docs/09 R18 —— roadmap-authoritative progression）。

背景：R18 裁决——"能否学"此前由内容文件手写 prereq 决定，与权威课程序（roadmap）脱节
（分数先于口诀、boss 门禁含分数、乘法口诀前置被生成期剔除等）。本模块让学习进度由
**蓝图总序权威驱动**：

- 条目达成（entry achieved）= 覆盖节点 mastered；覆盖节点 = anchors[0]（人工锚点在库）
  或条目自身 id 落地的 auto 节点；未落地条目不可学、不可达成（懒生成后自然可达成）。
- 条目开放（entry open）= 全部蓝图前置已达成（同文件条目；跨学段 preref 目标已落地 → 需其
  达成，未落地 → 不阻塞，学段顺序兜底）且自身未达成。
- 内容节点可学（node allowed）：mastered/learning/reviewing 照旧不锁；
  普通节点 = 所属条目 open（所属：节点 id=条目 auto id 或条目 anchors 含该节点）；
  首领（boss）= 归属主题组（内容 topic ↔ 蓝图 topic：精确或唯一前缀）全部条目达成；
  孤儿人工节点（无所属条目，如 high.0201 学段预修）= 学段已解锁且内容 prereq（若有）全达成；
  学段解锁：primary 恒开；其余需前序（有蓝图内容的）学段全部已落地条目达成。

内容手写 prereq 不再单独决定可学性（roadmap.audit 另有不变式禁止其引用蓝图序后项）。

**纯计算模块**：不 import db/service/progress/library（防环）；调用方传入内容库 by_id 元信息。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

from ..domain.graph import LEVELS


def _roadmaps() -> dict[str, Any]:
    from ..content.roadmap import load_roadmap

    out: dict[str, Any] = {}
    for lv in LEVELS:
        try:
            out[lv] = load_roadmap(lv)
        except Exception:
            pass  # 蓝图缺失学段跳过
    return out


def _registry() -> dict[str, tuple[str, Any]]:
    from ..content.roadmap import all_entries

    return all_entries()


@functools.lru_cache(maxsize=8)
def _cached_maps() -> tuple[dict[str, Any], dict[str, tuple[str, Any]]]:
    """蓝图注册表/roadmaps 缓存：会话内蓝图文件不变；R18 门禁每次状态重算复用，避免重复 IO。"""
    return _roadmaps(), _registry()


def boss_group_topic(level: str, content_topic: str, roadmap) -> str | None:
    """首领节点归属主题组：精确匹配蓝图 topic；否则唯一"前缀"匹配（蓝图 topic 以内容 topic 开头）。"""
    topics: list[str] = []
    for e in roadmap.entries:
        if e.topic not in topics:
            topics.append(e.topic)
    if content_topic in topics:
        return content_topic
    cands = [t for t in topics if t.startswith(content_topic)]
    return cands[0] if len(cands) == 1 else None


@dataclass
class PathEngine:
    """给定用户 mastered 集的一次性总序求值器（状态变化后重建）。"""

    mastered: set[str]
    lib_ids: set[str]
    roadmaps: dict[str, Any]
    registry: dict[str, tuple[str, Any]]
    # node_id -> RoadmapEntry（auto 条目自身 id 或 anchors 反向命中）
    owner: dict[str, Any]

    def __post_init__(self) -> None:
        for _lv, rd in self.roadmaps.items():
            for e in rd.entries:
                landed = self._landed(e)
                if landed is not None and landed in self.lib_ids:
                    self.owner.setdefault(landed, e)
            for a in e.anchors:
                if a in self.lib_ids:
                    self.owner.setdefault(a, e)

    def _landed(self, e) -> str | None:
        """条目落地节点 id：anchors[0] 在库 → 它；否则自身 id 在库 → 它；都无 → None。"""
        if e.anchors and e.anchors[0] in self.lib_ids:
            return e.anchors[0]
        if e.id in self.lib_ids:
            return e.id
        return None

    def entry_achieved(self, e) -> bool:
        landed = self._landed(e)
        return bool(landed and landed in self.mastered)

    def _peer_entry(self, p: str):
        """在全部学段蓝图里找引用目标条目。"""
        for _lv, rd in self.roadmaps.items():
            byid = rd.by_id()
            if p in byid:
                return byid[p]
        return None

    def prereq_ok(self, e) -> bool:
        """蓝图前置全达成（同文件条目 achieved；跨学段：目标落地→achieved，未落地→跳过）。"""
        level = e.level
        for p in e.prereqs:
            ref = self.registry.get(p)
            if ref is not None and ref[0] != level:
                ref_entry = ref[1]
                if self._landed(ref_entry) is None:  # 目标未落地 → 不阻塞（学段顺序兜底）
                    continue
                if not self.entry_achieved(ref_entry):
                    return False
                continue
            peer = self._peer_entry(p)
            if peer is None:
                continue  # 非蓝图条目引用（不应出现；audit 已查）→ 防御放行
            if not self.entry_achieved(peer):
                return False
        return True

    def entry_open(self, e) -> bool:
        if self.entry_achieved(e):
            return False
        return self.prereq_ok(e)

    def level_unlocked(self, level: str) -> bool:
        if level not in LEVELS:
            return True
        for prior in LEVELS[: LEVELS.index(level)]:
            rd = self.roadmaps.get(prior)
            if rd is None or not rd.entries:
                continue  # 前序学段无蓝图 → 不阻塞
            if not self.level_done(prior):
                return False
        return True

    def level_done(self, level: str) -> bool:
        """学段通关：该学段已落地条目全部达成。"""
        rd = self.roadmaps.get(level)
        if rd is None or not rd.entries:
            return True
        return all(self.entry_achieved(e) for e in rd.entries if self._landed(e) is not None)

    def node_allowed(
        self,
        node_id: str,
        *,
        kind: str = "",
        level: str = "",
        topic: str = "",
        prereqs=(),
    ) -> tuple[bool, list[str]]:
        """(是否允许进入学习, 未满足前置说明)。

        调用方需先排除 learning（学习中）；mastered/复习/重学放行——总序只防"越级先学新内容"，
        已达成节点重学（巩固/复习入口）不越级，允许。
        """
        if node_id in self.mastered:  # 已达成 → 重学/复习放行
            return True, []
        own = self.owner.get(node_id)
        if own is not None:
            e = own
            if not self.level_unlocked(e.level):
                return False, [f"需先完成前序学段（{e.level} 尚未解锁）"]
            if not self.prereq_ok(e):
                return False, [f"请先完成：{'、'.join(self._pending_titles(e) or ['前置条目'])}"]
            return True, []
        if kind == "boss":
            return self._boss_allowed(level, topic)
        # 孤儿（无所属条目的人工预修节点）→ 学段解锁 + 内容 prereq 兜底
        if not self.level_unlocked(level):
            return False, [f"需先完成前序学段（{level} 尚未解锁）"]
        for p in prereqs:
            if p not in self.mastered:
                return False, [f"内容前置未达成：{p}"]
        return True, []

    def _boss_allowed(self, level: str, topic: str) -> tuple[bool, list[str]]:
        rd = self.roadmaps.get(level)
        if rd is None:
            return False, ["该学段无蓝图"]
        group = boss_group_topic(level, topic, rd)
        if group is None:
            return False, [f"首领主题无匹配蓝图主题组（内容 topic={topic!r}）"]
        if not self.level_unlocked(level):
            return False, [f"需先完成前序学段（{level} 尚未解锁）"]
        pending = [e.title for e in rd.entries if e.topic == group and not self.entry_achieved(e)]
        if pending:
            return False, [f"首领战需本组全部条目达成，尚缺：{'、'.join(pending[:5])}"]
        return True, []

    def _pending_titles(self, e) -> list[str]:
        out: list[str] = []
        for p in e.prereqs:
            ref = self.registry.get(p)
            if ref is not None and ref[0] != e.level:
                ref_entry = ref[1]
                if self._landed(ref_entry) is None:
                    continue
                if not self.entry_achieved(ref_entry):
                    out.append(ref_entry.title)
                continue
            peer = self._peer_entry(p)
            if peer is not None and not self.entry_achieved(peer):
                out.append(peer.title)
        return out

    def allowed_node_ids(self, node_infos: dict[str, dict]) -> list[str]:
        """总序允许集（普通节点可学 + 首领开 + 孤儿开）。node_infos: id -> {kind,level,topic,prereqs}。

        不含 mastered（由调用方排除）。
        """
        out = []
        for nid, meta in node_infos.items():
            ok, _ = self.node_allowed(nid, **meta)
            if ok:
                out.append(nid)
        return out


def make_engine(mastered: set[str]) -> PathEngine:
    """从当前内容库 + 蓝图构建总序求值器（mastered = 用户已掌握节点 id 集）。"""
    from ..content.loader import load_library

    lib = load_library()
    roadmaps, registry = _cached_maps()
    return PathEngine(
        mastered=set(mastered),
        lib_ids=set(lib.by_id),
        roadmaps=roadmaps,
        registry=registry,
        owner={},
    )


__all__ = ["PathEngine", "make_engine", "boss_group_topic"]
