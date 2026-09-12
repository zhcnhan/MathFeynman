"""app.content.roadmap：课程蓝图（docs/10 §2.2）。

蓝图 = 机器可读的全课程规划，独立于内容文件：条目极轻
（id 草案 / 标题 / 学段 / 主题 / 目标 1–3 句 / 前置猜测 / 难度 / 是否需要思考模型）。
蓝图条目 ≠ 内容文件：内容按需从蓝图条目由流水线生成（docs/10 §2.3）。

- 文件：content/roadmap/<level>.yaml，列表为学习序列（顺序即关卡建议顺序）。
- 校验：id 唯一、prereq 指向文件内条目（或锚点真实节点 id）、学段合法。
"""
from __future__ import annotations

import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from ..config import REPO_ROOT
from . import content_root

LEVELS = ("primary", "middle", "high", "college", "ai")
# 学段学习顺序（北极星：小学→初中→高中→大学→AI）。跨学段 prereq 只能引用"本学段或前序学段"条目。
LEVEL_ORDER = {lv: i for i, lv in enumerate(LEVELS)}


# ---------------------------------------------------------------------------
# R63 任务 ②：蓝图文件的**进程内缓存**（按文件指纹失效）
# ---------------------------------------------------------------------------
# 口径**照抄** `service/outline_gate.py::_cached_outline`（仓库已有的成熟做法，不发明新机制）：
#   指纹 = 文件 (mtime_ns, size)；文件被原子替换 / 内容变化 ⇒ 指纹变化 ⇒ 自动重读。
# 为什么不用 `@lru_cache`：那会让"文件改了读不到新的"和"测试之间互相污染"同时发生；
# 指纹方案两者都不沾（文件一变就是新的；测试换目录/换文件自然换指纹）。
# `all_entries()` 的指纹是**五个学段文件拼起来**的（含"文件不存在"记 "-"），
# 所以新增 / 删除 content/roadmap/*.yaml 也会让缓存失效（不需要单独枚举目录）。
_roadmap_lock = threading.Lock()
_roadmap_cache: dict[str, tuple[str, "Roadmap"]] = {}
_entries_cache: tuple[str, dict[str, tuple[str, "RoadmapEntry"]]] | None = None


def _file_fingerprint(p: Path) -> str:
    """文件的 (mtime_ns, size) 指纹；读不到（不存在/无权限）= 空串。"""
    try:
        st = p.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return ""


def clear_roadmap_cache() -> None:
    """清空蓝图进程缓存（**指纹已能自动失效**，这里是显式入口：测试/外部文件变更后用）。

    形状与 `service/outline_gate.clear_outline_cache` 一致。
    """
    global _entries_cache
    with _roadmap_lock:
        _roadmap_cache.clear()
        _entries_cache = None



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

    **R63 任务 ②**：进程内缓存（指纹 = 五个学段文件的 mtime_ns+size 拼接，含"缺失"标记）；
    返回**浅拷贝**字典，调用方改它不会污染缓存。
    """
    global _entries_cache
    fp = "|".join(f"{lv}={_file_fingerprint(roadmap_path(lv))}" for lv in LEVELS)
    with _roadmap_lock:
        if _entries_cache is not None and _entries_cache[0] == fp:
            return dict(_entries_cache[1])
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
    with _roadmap_lock:
        _entries_cache = (fp, registry)
    return dict(registry)


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
    """载入并校验某学段蓝图；结构问题抛 RoadmapError（含具体条目）。

    **R63 任务 ②**：命中进程内缓存（键 = 解析后的文件路径，指纹 = mtime_ns+size）时直接返回，
    不重复读盘/不重复解析；文件一变（原子替换、编辑、删除后重建）指纹就变 ⇒ 立刻读到新的。
    返回的是**同一个 Roadmap 对象**（只读语义：`audit` / `PathEngine` / 生成管线都只读它，
    唯一会改它的地方是本函数内部那次 `e.level` 归一——发生在入缓存之前）。
    """
    p = path or roadmap_path(level)
    if not p.exists():
        raise RoadmapError(f"蓝图文件不存在: {p}")
    key = str(p)
    fp = _file_fingerprint(p)
    with _roadmap_lock:
        cached = _roadmap_cache.get(key)
        if cached is not None and cached[0] == fp:
            return cached[1]
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
    with _roadmap_lock:
        _roadmap_cache[key] = (fp, roadmap)
    return roadmap


def all_levels_exist() -> list[str]:
    """已存在蓝图的学段列表。"""
    rd = content_root() / "roadmap"
    return sorted(p.stem for p in rd.glob("*.yaml")) if rd.exists() else []


def boss_group_topic(level: str, content_topic: str, roadmap: "Roadmap") -> str | None:
    """首领节点归属主题组：内容 topic 精确匹配蓝图 topic；否则唯一"前缀"匹配（蓝图 topic 以内容 topic 开头）。

    R18：boss 门禁 = 归属主题组全部条目达成；无匹配/多匹配 = 无主/错主（audit 报错）。
    """
    topics: list[str] = []
    for e in roadmap.entries:
        if e.topic not in topics:
            topics.append(e.topic)
    if content_topic in topics:
        return content_topic
    cands = [t for t in topics if t.startswith(content_topic)]
    return cands[0] if len(cands) == 1 else None


def _content_closure_landed(
    owner: "RoadmapEntry",
    registry: dict[str, tuple[str, "RoadmapEntry"]],
    known_node_ids: set[str] | None,
) -> set[str]:
    """owner 条目的蓝图前置闭包（同文件 + 跨学段已落地部分）对应内容落地 id 集（含 owner 自身）。

    R18 audit 不变式：内容节点手写 prereq ⊆ 该闭包（跨学段未落地 → 不参与；反向引用不扩以防环）。
    """
    seen: set[str] = set()
    stack = [owner]
    landed: set[str] = set()
    while stack:
        e = stack.pop()
        if e.id in seen:
            continue
        seen.add(e.id)
        ld = landed_id_for(e, known_node_ids)
        if ld:
            landed.add(ld)
        for p in e.prereqs:
            ref = registry.get(p)
            if ref is None:
                continue
            ref_level, ref_entry = ref[0], ref[1]
            if LEVEL_ORDER.get(ref_level, 99) > LEVEL_ORDER.get(e.level, 99):
                continue  # 反向引用（audit 已另报）
            if ref_level != e.level and landed_id_for(ref_entry, known_node_ids) is None:
                continue  # 跨学段目标未落地 → 不阻塞
            stack.append(ref_entry)
    return landed


def audit(
    level: str,
    *,
    known_node_ids: set[str] | None = None,
    roadmap: Roadmap | None = None,
    registry: dict[str, tuple[str, "RoadmapEntry"]] | None = None,
    content_edges: dict[str, list[str]] | None = None,
    content_meta: dict[str, dict] | None = None,
) -> dict:
    """蓝图自动自查（供人工精核参考；REVIEW-blueprint C + R14 跨学段 + R18 总序不变式增强）。

    检查项：
    - 前置引用：指向文件内条目 / 其它学段蓝图条目（跨文件）/ 真实锚点节点；
    - **锚点存在性（C）**：anchors 必须指向内容库真实节点；
    - **跨学段引用（R14 #1）**：只许指向前序学段条目；缺失/反向报错；未落地 → cross_gaps 提示；
    - 环检测：文件内前置边（跨学段方向单向不可能成环）；正向引用告警；主题连续；covered 明细；
    - **R18 内容不变式**（传 content_edges/content_meta 时启用）：
      ① 普通内容节点手写 prereq ⊆ 其所属蓝图条目前置闭包的落地 id 集（防"内容手写边引蓝图序更后项"回归）；
      ② boss 节点归属蓝图主题组（内容 topic 精确/唯一前缀匹配）；无主/错主 → 报错；手写 prereq
        ⊆ 归属组落地集（缺组内落地 → 记差异说明，门禁以引擎组达成判定为准）；
      ③ 孤儿（无所属条目）节点：内容 prereq 不受蓝图闭包约束（学段预修），仅记录差异说明。

    registry/content 数据可注入（测试用）；缺省读全部已存在 level.yaml 与当前内容库。
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
    # ---- R18 内容不变式（提供 content_edges/content_meta 时启用）----
    content_violations: list[str] = []
    boss_unmatched: list[str] = []
    content_diff_notes: list[str] = []
    if content_edges is not None:
        # owner 反查（含跨学段 anchors 引用）
        owner_of: dict[str, "RoadmapEntry"] = {}
        for _rid, (_rlv, re_) in registry.items():
            if re_.id in content_edges and re_.id not in owner_of:
                owner_of[re_.id] = re_
            for a in re_.anchors:
                if a in content_edges and a not in owner_of:
                    owner_of[a] = re_
        for node_id, preqs in content_edges.items():
            meta = (content_meta or {}).get(node_id, {}) or {}
            kind = meta.get("kind") or ""
            content_topic = meta.get("topic") or ""
            if kind == "boss":
                group = boss_group_topic(level, content_topic, roadmap)
                if group is None:
                    boss_unmatched.append(f"{node_id} 首领主题 {content_topic!r} 无匹配蓝图主题组")
                    continue
                group_landed = {landed_id_for(e, known_node_ids) for e in roadmap.entries if e.topic == group}
                group_landed.discard(None)
                for p in preqs:
                    if p not in group_landed:
                        content_violations.append(f"{node_id}->{p}(boss 手写前置不在归属组落地集)")
                gap_ids = sorted(n for n in group_landed if n not in set(preqs))
                if gap_ids:
                    content_diff_notes.append(
                        f"{node_id} 组内已落地节点未在其手写 prereq 中: {'、'.join(gap_ids[:8])}（门禁=引擎组达成，手写仅展示）"
                    )
                continue
            owner = owner_of.get(node_id)
            if owner is None:
                content_diff_notes.append(f"{node_id}(无所属蓝图条目=孤儿，内容 prereq 仅受学段/内容边约束)")
                continue
            closure = _content_closure_landed(owner, registry, known_node_ids)
            for p in preqs:
                if p not in closure:
                    content_violations.append(
                        f"{node_id}->{p}(内容手写 prereq 超出所属蓝图条目 {owner.id} 的前置闭包)"
                    )
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
        "content_prereq_violations": content_violations,  # R18：内容手写边越界（进 ok 判定）
        "boss_unmatched": boss_unmatched,                  # R18：首领无主/错主（进 ok 判定）
        "content_diff_notes": content_diff_notes,          # R18：总序 vs 内容手写边差异说明（提示）
        "cycles": cycles,
        "forward_refs": forward,
        "topic_runs": runs,
        "isolated_topics": isolated,
        "covered_entries": covered_entries,
        "pending_entries": pending_entries,
        "ok": not (
            missing
            or self_refs
            or cycles
            or anchors_missing
            or cross_reverse
            or content_violations
            or boss_unmatched
        ),
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
    "boss_group_topic",
    "_content_closure_landed",
    "_split_entry_ref",
    "clear_roadmap_cache",
    "audit",
]
