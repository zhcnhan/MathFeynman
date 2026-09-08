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
# 学段学习顺序（北极星：小学→初中→高中→大学→AI）。跨学段 prereq 只能引用"本学段或前序学段"条目。
LEVEL_ORDER = {lv: i for i, lv in enumerate(LEVELS)}


def _split_entry_ref(ref: str) -> tuple[str, str] | None:
    """把 `level.local` 引用拆成 (level, local)；非两级格式返回 None。"""
    if "." not in ref:
        return None
    level, _, local = ref.partition(".")
    if level not in LEVELS or not local:
        return None
    return level, local


def all_entries() -> dict[str, tuple[str, "RoadmapEntry"]]:
    """跨学段蓝图条目注册表：{entry_id: (level, entry)}（读取所有已存在 level.yaml）。

    供 audit / pipeline 判定 prereq 是否指向其它学段的蓝图条目（非内容节点）。
    蓝图条目 id 全局唯一（学段前缀 + 本地号），重复 id 在注册表构建时以先读到的文件为准
    （当前各学段无重复；如未来出现重复属蓝图错误，应在精核批处理）。
    """
    registry: dict[str, tuple[str, RoadmapEntry]] = {}
    for lv in LEVELS:
        p = roadmap_path(lv)
        if not p.exists():
            continue
        try:
            rd = load_roadmap(lv, path=p)
        except RoadmapError:
            continue  # 单文件损坏不应拖垮全局注册（audit 会针对该 level 报错）
        for e in rd.entries:
            registry.setdefault(e.id, (lv, e))
    return registry


def landed_id_for(entry: "RoadmapEntry", known_node_ids: set[str] | None = None) -> str:
    """蓝图条目的"内容落地 id"：有锚点（且锚点在内容库）→ anchors[0]；否则条目自身 id（生成后即入库 id）。"""
    if entry.anchors and (known_node_ids is None or entry.anchors[0] in known_node_ids):
        return entry.anchors[0]
    return entry.id


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
    # prereq 指向：蓝图内条目 id（推荐）、其它学段蓝图条目 id（`level.local` 跨文件引用）、
    # 或真实锚点节点 id（`level.local`，含 '.'）。格式层：含 '.' 者必须是合法学段前缀 + 非空本地号；
    # 语义层（存在性/方向/环）由 audit 校验。
    known = ids
    for e in roadmap.entries:
        for pr in e.prereqs:
            if pr in known:
                continue
            if "." in pr:
                if _split_entry_ref(pr) is None:
                    raise RoadmapError(
                        f"{p.name}/{e.id}: prereq {pr!r} 格式非法——跨文件/节点引用须为 "
                        f"`<学段>.<本地号>`（学段 ∈ {LEVELS}）"
                    )
                continue  # 合法格式：跨文件蓝图条目或真实节点，语义交给 audit
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
    registry: dict[str, tuple[str, "RoadmapEntry"]] | None = None,
) -> dict:
    """蓝图自动自查（供人工精核参考；REVIEW-blueprint C 增强 + R14 后续跨学段增强）。

    检查项：
    - 前置引用：指向文件内条目 / 其它学段蓝图条目（跨文件，`level.local`）/ 真实锚点节点；
    - **锚点存在性（C）**：条目 anchors 引用的节点 id 必须存在于当前内容库（known_node_ids），
      缺失即报错（防"文件名与 front-matter id 不同名"类回归）；
    - **跨学段引用（R14 后续 #1）**：prereq 引用其它 level.yaml 条目必须指向"前序学段"条目
      （方向按 LEVELS 学习顺序）；反向引用（引用后序学段）报错；缺失条目报错；
      合法但目标学段条目**未落地**到内容库 → 记 cross_gaps 提示（不阻塞 ok——学段顺序推进兜底，
      生成器/自续可据此提示缺口）；
    - 环检测：文件内前置边构成的有向图（跨学段方向单向（前序学段），方向规则下跨文件不可能成环）；
    - 顺序：同文件内指向"更后条目"的正向引用告警（需批量生成先补齐，见 pipeline 展开）；
    - 主题连续性：相同主题是否连续成组（孤立单条 → 提示）；
    - **covered 明细（C）**：列出 锚点已覆盖 / 待生成 条目（与 pipeline 判定一致口径）。

    registry 可注入（测试用）；缺省读全部已存在 level.yaml（见 all_entries）。
    """
    roadmap = roadmap or load_roadmap(level)
    registry = registry if registry is not None else all_entries()
    index = {e.id: i for i, e in enumerate(roadmap.entries)}
    missing: list[str] = []
    self_refs: list[str] = []
    forward: list[str] = []
    anchors_missing: list[str] = []
    cross_refs: list[str] = []
    cross_reverse: list[str] = []
    cross_gaps: list[str] = []
    for e in roadmap.entries:
        for p in e.prereqs:
            if p == e.id:
                self_refs.append(f"{e.id}->{p}")
                continue
            if p in index:  # 同文件条目：只许向前引用
                if index[p] > index[e.id]:
                    forward.append(f"{e.id}->{p}")
                continue
            ref = registry.get(p)
            if ref is not None and ref[0] != level:  # 其它学段的蓝图条目（跨文件引用）
                ref_level = ref[0]
                if LEVEL_ORDER[ref_level] > LEVEL_ORDER[level]:
                    cross_reverse.append(
                        f"{e.id}->{p}(反向引用：{ref_level} 是 {level} 的后序学段)"
                    )
                    continue
                cross_refs.append(f"{e.id}->{p}")
                # 落地提示：目标条目对应内容是否已入库（锚点覆盖 or auto 节点已生成）
                if known_node_ids is not None:
                    landed = landed_id_for(ref[1], known_node_ids)
                    if landed not in known_node_ids:
                        cross_gaps.append(f"{e.id}->{p}({ref_level} 条目未落地，学段顺序兜底)")
                continue
            if "." in p:  # 真实节点引用（或未注册的 '.', 引用）
                if known_node_ids is not None and p not in known_node_ids:
                    missing.append(f"{e.id}->{p}(锚点节点不在内容库)")
                continue
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
        "cross_refs": cross_refs,          # 合法跨学段引用（前序学段）
        "cross_reverse": cross_reverse,    # 非法：引用后序学段（进 ok 判定）
        "cross_gaps": cross_gaps,          # 合法但目标学段条目未落地（提示，不进 ok 判定）
        "cycles": cycles,
        "forward_refs": forward,
        "topic_runs": runs,
        "isolated_topics": isolated,
        "covered_entries": covered_entries,
        "pending_entries": pending_entries,
        "ok": not (missing or self_refs or cycles or anchors_missing or cross_reverse),
    }


__all__ = [
    "Roadmap",
    "RoadmapEntry",
    "RoadmapError",
    "load_roadmap",
    "roadmap_path",
    "all_levels_exist",
    "all_entries",
    "landed_id_for",
    "_split_entry_ref",
    "audit",
]
