"""app.content.roadmap：课程蓝图（docs/10 §2.2）。

蓝图 = 机器可读的全课程规划，独立于内容文件：条目极轻
（id 草案 / 标题 / 学段 / 主题 / 目标 1–3 句 / 前置猜测 / 难度 / 是否需要思考模型）。
蓝图条目 ≠ 内容文件：内容按需从蓝图条目由流水线生成（docs/10 §2.3）。

- 文件：content/roadmap/<level>.yaml，列表为学习序列（顺序即关卡建议顺序）。
- 校验：id 唯一、prereq 指向文件内条目（或锚点真实节点 id）、学段合法。
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from ..config import REPO_ROOT
from . import content_root

LEVELS = ("primary", "middle", "high", "college", "ai")


class RoadmapEntry(BaseModel):
    id: str
    title: str
    level: str = "primary"
    topic: str = ""
    objectives: list[str] = Field(default_factory=list)
    prereqs: list[str] = Field(default_factory=list)  # 蓝图内条目 id 或真实锚点节点 id
    difficulty: int = Field(default=2, ge=1, le=3)
    requires_thinking: bool = False  # R12：生成讲解/题目的默认模型档（true→think）
    anchors: list[str] = Field(default_factory=list)  # 已有人工节点（满足本条目，生成时跳过）

    @field_validator("level")
    @classmethod
    def _level_ok(cls, v: str) -> str:
        if v not in LEVELS:
            raise ValueError(f"非法学段 {v!r}")
        return v


class Roadmap(BaseModel):
    """单学段蓝图：顺序即建议学习序列。"""

    level: str = "primary"
    entries: list[RoadmapEntry] = Field(default_factory=list)

    def by_id(self) -> dict[str, RoadmapEntry]:
        return {e.id: e for e in self.entries}


class RoadmapError(ValueError):
    """蓝图结构错误。"""


def roadmap_path(level: str) -> Path:
    return content_root() / "roadmap" / f"{level}.yaml"


def load_roadmap(level: str, *, path: Path | None = None) -> Roadmap:
    """载入并校验某学段蓝图；结构问题抛 RoadmapError（含具体条目）。"""
    p = path or roadmap_path(level)
    if not p.exists():
        raise RoadmapError(f"蓝图文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RoadmapError(f"{p.name} YAML 解析失败: {e}") from e
    if not isinstance(raw, dict):
        raise RoadmapError(f"{p.name}: 顶层应为映射（level/entries）")
    level_ok = raw.get("level", level) in LEVELS
    if not level_ok:
        raise RoadmapError(f"{p.name}: level 非法")
    try:
        roadmap = Roadmap(**raw)
    except Exception as e:
        raise RoadmapError(f"{p.name} 结构校验失败: {e}") from e
    # 文件级 level 归一：条目未显式声明时继承文件学段（默认字段 primary → 实际文件学段）
    if roadmap.level != "primary":
        for e in roadmap.entries:
            if e.level == "primary":
                e.level = roadmap.level

    ids = set(roadmap.by_id())
    if len(ids) != len(roadmap.entries):
        raise RoadmapError(f"{p.name}: 条目 id 重复")
    # prereq 指向：蓝图内条目 id（推荐）或锚点真实节点 id（允许，按格式含 '.' 两级）
    known = ids
    for e in roadmap.entries:
        for pr in e.prereqs:
            if pr not in known and "." not in pr:
                raise RoadmapError(f"{p.name}/{e.id}: prereq {pr!r} 未指向文件内条目或锚点节点")
    return roadmap


def all_levels_exist() -> list[str]:
    """已存在蓝图的学段列表。"""
    rd = content_root() / "roadmap"
    return sorted(p.stem for p in rd.glob("*.yaml")) if rd.exists() else []


def audit(
    level: str,
    *,
    known_node_ids: set[str] | None = None,
    roadmap: Roadmap | None = None,
) -> dict:
    """蓝图自动自查（供人工精核参考；REVIEW-blueprint C 增强）。

    检查项：
    - 前置引用：指向文件内条目 / 真实节点（含 '.'，提供 known_node_ids 时校验存在性）；
    - **锚点存在性（C）**：条目 anchors 引用的节点 id 必须存在于当前内容库（known_node_ids），
      缺失即报错（防"文件名与 front-matter id 不同名"类回归）；
    - 环检测：文件内前置边构成的有向图；
    - 顺序：指向"更后条目"的正向引用告警（需批量生成先补齐，见 pipeline 展开）；
    - 主题连续性：相同主题是否连续成组（孤立单条 → 提示）；
    - **covered 明细（C）**：列出 锚点已覆盖 / 待生成 条目（与 pipeline 判定一致口径）。
    """
    roadmap = roadmap or load_roadmap(level)
    index = {e.id: i for i, e in enumerate(roadmap.entries)}
    missing: list[str] = []
    self_refs: list[str] = []
    forward: list[str] = []
    anchors_missing: list[str] = []
    for e in roadmap.entries:
        for p in e.prereqs:
            if p == e.id:
                self_refs.append(f"{e.id}->{p}")
            elif p in index:
                if index[p] > index[e.id]:
                    forward.append(f"{e.id}->{p}")
            elif "." in p:
                if known_node_ids is not None and p not in known_node_ids:
                    missing.append(f"{e.id}->{p}(锚点节点不在内容库)")
            else:
                missing.append(f"{e.id}->{p}(蓝图内条目不存在)")
        # C：anchors 必须指向当前内容库真实节点
        if e.anchors and known_node_ids is not None:
            for a in e.anchors:
                if a not in known_node_ids:
                    anchors_missing.append(f"{e.id} 锚点 {a} 不在内容库")
    # 环（DFS）
    cycles: list[str] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {e.id: WHITE for e in roadmap.entries}
    stack: list[str] = []

    def dfs(nid: str) -> bool:
        color[nid] = GRAY
        stack.append(nid)
        byid = roadmap.by_id()
        for p in byid[nid].prereqs:
            if p not in index:
                continue
            if color[p] == GRAY:
                i = stack.index(p)
                cycles.append("->".join(stack[i:] + [p]))
                return True
            if color[p] == WHITE and dfs(p):
                return True
        stack.pop()
        color[nid] = BLACK
        return False

    for e in roadmap.entries:
        if color[e.id] == WHITE:
            dfs(e.id)
    # 主题连续性（相邻 run）
    runs: list[dict] = []
    for e in roadmap.entries:
        if runs and runs[-1]["topic"] == e.topic:
            runs[-1]["count"] += 1
            runs[-1]["ids"].append(e.id)
        else:
            runs.append({"topic": e.topic, "count": 1, "ids": [e.id]})
    isolated = [r["topic"] for r in runs if r["count"] == 1]
    # C：covered / 待生成 明细（锚点全部在库=covered；否则视为待生成内容）
    covered_entries = [
        {"id": e.id, "title": e.title, "anchors": list(e.anchors)}
        for e in roadmap.entries
        if e.anchors and known_node_ids is not None and all(a in known_node_ids for a in e.anchors)
    ]
    pending_entries = [
        {"id": e.id, "title": e.title, "has_anchor": bool(e.anchors)}
        for e in roadmap.entries
        if not (e.anchors and known_node_ids is not None and all(a in known_node_ids for a in e.anchors))
    ]
    # 注：anchors 指向条目 id 若在库，则 covered；preq 里引用了 covered 条目也视为已有内容（不重复判）
    return {
        "level": level,
        "entries": len(roadmap.entries),
        "prereq_missing": missing,
        "self_refs": self_refs,
        "anchors_missing": anchors_missing,
        "cycles": cycles,
        "forward_refs": forward,
        "topic_runs": runs,
        "isolated_topics": isolated,
        "covered_entries": covered_entries,
        "pending_entries": pending_entries,
        "ok": not (missing or self_refs or cycles or anchors_missing),
    }


__all__ = [
    "Roadmap",
    "RoadmapEntry",
    "RoadmapError",
    "load_roadmap",
    "roadmap_path",
    "all_levels_exist",
    "audit",
]
