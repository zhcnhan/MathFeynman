"""domain.graph：知识图谱（docs/03 §1）。纯 Python，零 LLM/UI/DB 依赖。

- 图 = 节点 + 依赖边，必须为 DAG（构造时拒绝环/重名/悬空 prereq）。
- 节点状态机：locked → available → learning → mastered（reviewing 属复习侧，见 fsrs）。
- 推荐顺序：available 中按拓扑层序取最浅者。

用户进度以集合形式注入（mastered/learning），由 service 层从 user_nodes 表读取；
本模块不碰数据库，保持可单测。
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

# 学段（docs/03 §1）
LEVELS = ("primary", "middle", "high", "college", "ai")

# 节点状态
LOCKED = "locked"
AVAILABLE = "available"
LEARNING = "learning"
MASTERED = "mastered"
REVIEWING = "reviewing"

NODE_STATES = (LOCKED, AVAILABLE, LEARNING, MASTERED, REVIEWING)


class GraphError(ValueError):
    """图谱结构非法（重名/悬空依赖/成环）。"""


@dataclass(frozen=True)
class NodeDef:
    """一个知识点节点（最小粒度 = 可独立学习、可独立判定）。"""

    id: str
    title: str = ""
    level: str = ""
    topic: str = ""
    prereqs: tuple[str, ...] = ()


@dataclass
class KnowledgeGraph:
    """只读 DAG：构造时全量校验。"""

    nodes: list[NodeDef] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 重名
        ids = [n.id for n in self.nodes]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise GraphError(f"重复节点 id: {sorted(dup)}")
        self._by_id: dict[str, NodeDef] = {n.id: n for n in self.nodes}
        # 悬空 prereq + level 命名空间约束（docs/14 Phase A A4 语义）
        # level：math 学段 ∈ LEVELS；通用学科内容节点的 level = 其大纲关卡组标识（任意非空串）。
        # 约束：以学段名开头的节点（数学内容命名空间 primary.xxx 等）必须使用合法学段 level，
        # 防数学内容 typo 静默旁路（学习顺序权威仍在 service/path roadmap 门禁）；其余命名空间放开。
        for n in self.nodes:
            head = n.id.partition(".")[0] if "." in n.id else ""
            if head in LEVELS and n.level not in LEVELS:
                raise GraphError(f"节点 {n.id} 学段非法: {n.level!r}（{head} 命名空间须用合法学段）")
            for p in n.prereqs:
                if p not in self._by_id:
                    raise GraphError(f"节点 {n.id} 的 prereq {p!r} 不存在")
        # 环检测（DFS 三色）
        self._detect_cycle()
        self._children: dict[str, list[str]] = defaultdict(list)
        for n in self.nodes:
            for p in n.prereqs:
                self._children[p].append(n.id)
        self._topo_layers = self._layers()

    # ---------- 结构 ----------
    def _detect_cycle(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n.id: WHITE for n in self.nodes}
        stack: list[str] = []
        cycle: list[str] = []

        def dfs(node_id: str) -> bool:
            color[node_id] = GRAY
            stack.append(node_id)
            for p in self._by_id[node_id].prereqs:
                if color[p] == GRAY:
                    # 找到环：取栈内 p..node_id 段
                    idx = stack.index(p)
                    cycle.extend(stack[idx:])
                    return True
                if color[p] == WHITE and dfs(p):
                    return True
            stack.pop()
            color[node_id] = BLACK
            return False

        for n in self.nodes:
            if color[n.id] == WHITE and dfs(n.id):
                raise GraphError(f"检测到依赖环: {' -> '.join(cycle + [cycle[0]])}")

    def _layers(self) -> list[list[str]]:
        """按依赖做拓扑分层（层 0 = 无 prereq 的最浅层）。"""
        indeg = {n.id: len(n.prereqs) for n in self.nodes}
        children = defaultdict(list)
        for n in self.nodes:
            for p in n.prereqs:
                children[p].append(n.id)
        queue = deque(sorted(i for i, d in indeg.items() if d == 0))
        layers: list[list[str]] = []
        while queue:
            level_ids = sorted(queue)
            layers.append(level_ids)
            for _ in range(len(queue)):
                cur = queue.popleft()
                for ch in sorted(children[cur]):
                    indeg[ch] -= 1
                    if indeg[ch] == 0:
                        queue.append(ch)
        if any(d > 0 for d in indeg.values()):  # 不应发生（构造已查环），防御
            raise GraphError("拓扑分层失败：仍存在未解除依赖")
        return layers

    # ---------- 查询 ----------
    def get(self, node_id: str) -> NodeDef:
        return self._by_id[node_id]

    def has(self, node_id: str) -> bool:
        return node_id in self._by_id

    @property
    def node_ids(self) -> list[str]:
        return [n.id for n in self.nodes]

    def prereqs_of(self, node_id: str) -> list[str]:
        return list(self._by_id[node_id].prereqs)

    def children_of(self, node_id: str) -> list[str]:
        return list(self._children.get(node_id, []))

    def topological_order(self) -> list[str]:
        return [i for layer in self._topo_layers for i in layer]

    def depth_of(self, node_id: str) -> int:
        """节点所在拓扑层（推荐时"最浅优先"用）。"""
        for depth, layer in enumerate(self._topo_layers):
            if node_id in layer:
                return depth
        raise KeyError(node_id)

    def ancestors(self, node_id: str) -> list[str]:
        """全部祖先（含间接），按由近及远。"""
        seen: list[str] = []
        stack = list(self._by_id[node_id].prereqs)
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.append(cur)
                stack.extend(self._by_id[cur].prereqs)
        return seen

    # ---------- 用户侧状态机（docs/03 §1） ----------
    def state_of(
        self,
        node_id: str,
        *,
        mastered: set[str],
        learning: set[str] | None = None,
    ) -> str:
        """节点状态：mastered > learning > available > locked。

        reviewing 态由复习调度在 mastered 上叠加（docs/03 §3：mastered──FSRS到期──▶reviewing），
        本函数返回 mastered；上层读 reviews.due_at 展示 reviewing。
        """
        learning = learning or set()
        if node_id in mastered:
            return MASTERED
        if node_id in learning:
            return LEARNING
        node = self._by_id[node_id]
        if all(p in mastered for p in node.prereqs):
            return AVAILABLE
        return LOCKED

    def available(self, *, mastered: set[str], learning: set[str] | None = None) -> list[str]:
        """available 节点集（按拓扑层序，层内按 id）。"""
        learning = learning or set()
        out: list[str] = []
        for layer in self._topo_layers:
            for nid in layer:
                if self.state_of(nid, mastered=mastered, learning=learning) == AVAILABLE:
                    out.append(nid)
        return out

    def recommend(self, *, mastered: set[str], learning: set[str] | None = None) -> str | None:
        """推荐下一个可学节点（docs/03 §1 + USER_FEEDBACK 起点学段修复）。

        排序键：学段(primary→middle→high→college→ai) → 图谱层序(最浅优先)
        → 节点编号；取首个。保证基础捡拾用户优先被推荐最低学段内容。
        """
        avail = self.available(mastered=mastered, learning=learning)
        if not avail:
            return None
        level_index = {level: i for i, level in enumerate(LEVELS)}

        def sort_key(node_id: str):
            node = self._by_id[node_id]
            return (level_index.get(node.level, len(LEVELS)), self.depth_of(node_id), node_id)

        return min(avail, key=sort_key)

    def path_to(self, node_id: str) -> list[str]:
        """到 node_id 的学习路径（最浅层 → 目标），供"前置链"展示。"""
        if node_id not in self._by_id:
            raise KeyError(node_id)
        chain: list[str] = []
        for layer in self._topo_layers:
            for nid in layer:
                if nid == node_id:
                    chain.append(nid)
                    return chain
                if nid in self.ancestors(node_id):
                    chain.append(nid)
        return chain  # pragma: no cover - 不可达
