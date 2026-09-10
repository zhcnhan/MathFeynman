"""app.content.pipeline：内容自续流水线核心（docs/04 §6、docs/10 §2.3、docs/11 子步 7）。

职责：按蓝图主题组批量"出稿 → 自动校验 → 入库策略"：
1. 出稿：AI（provider.chat_json CALL_DRAFT_CONTENT）或**离线确定性 Stub**（无 key 的机制验证/测试用）。
2. 自动校验（逐条，入库前）：front-matter 结构合法 / prereq 存在且无环 / 每题模板多 seed 渲染
   + sympy 自检（broken=0）。（prereq 白名单：只能引用"已在库节点或本批前置链"——见 validate_candidate。）
3. 入库策略（docs/10 §3 + docs/12 P4 升级）：**全学段默认自动入库**（content/stages/<level>/，
   front-matter 标注 `source: auto`）；质量护栏替代强制人审 = 自动校验 + 服务层**内容问题率熔断**
   （主题问题率 > 阈值 → 该主题转 _drafts 待检，见 service/guardrails.py；selfextend 接线时传
   force_drafts=True）。CLI `--to-drafts` / 显式 force_drafts 仍可强制草稿。

- 幂等：目标 id 已存在（stages 或 _drafts）→ 跳过并报 exists。
- 本模块不 import 任何 LLM 依赖路径以外的组件：AI 出稿经注入的 provider（schema 化调用点 draft_content）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import content_root, stages_dir
from .loader import load_library, parse_node_text
from .roadmap import (
    Roadmap,
    RoadmapEntry,
    all_entries,
    landed_id_for,
    load_roadmap,
)
from .schemas import (
    CheckDoc,
    ExerciseDoc,
    FeynmanDoc,
    NodeDoc,
    RubricDoc,
    RubricDimension,
    TemplateDoc,
)
from .templates import render_exercise

# 默认自检 seed 数（docs/04 §4 重取样上限语义：全失败 → broken）
SELFCHECK_SEEDS = 8

# R13/A2：出稿校验失败自动修复重试（携带校验错误要求模型修正；stub 忽略 errors）
DRAFT_RETRY_MAX = 2

# drafter(entry, errors=None) -> .md 全文；errors 非空=上轮校验错误反馈
Drafter = Callable[..., str]


class PipelineError(ValueError):
    pass


@dataclass
class ItemResult:
    entry_id: str
    status: str  # ok | exists | failed
    path: str | None = None
    errors: list = field(default_factory=list)


def topic_dir_name(topic: str) -> str:
    clean = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "general"
    return f"topic_{clean}"


# --------------------------------------------------------------------------
# 出稿：离线确定性 Stub（结构合法、模板可自检；供无 key 的机制测试/演示）
# --------------------------------------------------------------------------
def stub_drafter(entry: RoadmapEntry, errors: list[str] | None = None) -> str:
    """按蓝图条目生成最小但完全合法的节点（模板数值题 + 标准费曼四维 rubric）。

    说明：真实 AI 出稿在配置 LLM_API_KEY 时使用（pipeline 入口选择 drafter）；
    stub 保证流水线机制（校验/入库/自续）可离线端到端验证。errors 参数供协议兼容（忽略）。
    """
    del errors
    node_id = entry.id
    title = entry.title
    topic = entry.topic
    prereqs = list(entry.prereqs) or []
    objectives = entry.objectives or ["理解并掌握本知识点"]
    concept = re.sub(r"[（(].*?[)）]", "", title).split("·")[0][:8] or "核心概念"
    body_lines = [f"# {title}", ""]
    body_lines.append("## 讲解")
    body_lines.append("本节目标：" + "；".join(objectives[:3]) + "。")
    body_lines.append("（本文档由内容自续流水线生成，`source: auto`；请在使用中反馈纠错。）")
    body_md = "\n".join(body_lines)

    ex = ExerciseDoc(
        id="e1",
        kind="template",
        difficulty=entry.difficulty,
        template=TemplateDoc(
            prompt="基础练习：计算 {a} + {b} = ？（输入结果数字）",
            params={
                "a": {"range": [1, 20], "exclude": []},
                "b": {"range": [1, 20], "exclude": []},
            },
            constraint=None,
            answer_expr="a + b",
        ),
        check=CheckDoc(mode="numeric_value", tolerance=None),
        interactive=["workbench"],
    )
    feynman = FeynmanDoc(
        task_prompt=f"用你自己的话讲清楚：{title}。要求：(1) 说明它解决什么问题；(2) 举一个例子；(3) 指出最容易错的地方。",
        rubric=RubricDoc(
            dimensions=[
                RubricDimension(key="correctness", weight=0.4, description="概念与结论是否正确"),
                RubricDimension(key="own_words", weight=0.2, description="是否用自己的话而非背诵"),
                RubricDimension(key="example_and_edge", weight=0.2, description="是否给出例子/反例"),
                RubricDimension(key="self_correction", weight=0.2, description="被追问后能否自纠"),
            ],
            pass_threshold=0.7,
        ),
        socratic_followups=[
            f"如果题目换个说法，{concept}还成立吗？举一个反例。",
            "这一步能省略吗？为什么？",
        ],
        thinking=entry.requires_thinking,
    )
    doc = NodeDoc(
        id=node_id,
        title=title,
        level=entry.level,
        topic=topic,
        prereqs=prereqs,
        objectives=objectives,
        core_concepts=[concept],
        explanation={"role": "AI 讲解稿（auto）", "body": "\n".join(body_lines[1:])},
        exercises=[ex],
        feynman=feynman,
        body_md=body_md,
    )
    meta = doc.model_dump(exclude={"body_md"})
    meta["source"] = "auto"  # 入库标注（loader 校验忽略未知键，原始文件保留）
    meta["requires_thinking"] = entry.requires_thinking
    header = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{header}---\n\n{body_md}\n"


# --------------------------------------------------------------------------
# 自动校验（入库前，不落盘）
# --------------------------------------------------------------------------
def validate_candidate(raw_md: str, known_ids: set[str]) -> list[str]:
    """结构/渲染/sympy 自检；prereq 指向已知节点（含本批前序）。返回错误列表。"""
    errors: list[str] = []
    try:
        meta, body = parse_node_text(raw_md)
        doc = NodeDoc(**meta)
    except Exception as e:
        return [f"front-matter 结构非法: {e}"]
    # prereq 存在 + 自指
    if doc.id in doc.prereqs:
        errors.append("prereq 不能包含自身")
    for p in doc.prereqs:
        if p not in known_ids:
            errors.append(f"prereq {p!r} 不存在或未在本批前置生成")
    # 模板渲染 + sympy 自检（每题 8 seed；任一 broken → 报错）
    for ex in doc.exercises:
        for seed in range(SELFCHECK_SEEDS):
            r = render_exercise(doc.id, ex, seed)
            if r.broken:
                errors.append(f"练习 {ex.id} seed={seed} broken: {r.detail}")
                break
    return errors


def validate_semantics(raw_md: str) -> list[str]:
    """R35 §12 **语义自检闸门**（与结构校验**分开的独立函数**，各自调用）：
    模板题的答案必须与题面语义自洽——通用层（声明的领域谓词）+ L1 验算插件（math=sympy 独立验算）。
    返回错误清单（空 = 过闸门；**不一致 → 拒绝入库**）。
    """
    from .verify import gate_errors

    try:
        meta, _ = parse_node_text(raw_md)
        doc = NodeDoc(**meta)
    except Exception as e:
        return [f"语义闸门无法解析内容: {e}"]
    return gate_errors(doc)


def semantic_findings(raw_md: str) -> list[str]:
    """体检用：闸门的"无法验证"提示（缺声明/无验算器）——不阻断入库，但要求内容显式声明。"""
    from .verify import check_node

    try:
        meta, _ = parse_node_text(raw_md)
        doc = NodeDoc(**meta)
    except Exception as e:
        return [f"语义体检无法解析内容: {e}"]
    out: list[str] = []
    for v in check_node(doc, seeds=4):
        out.extend(f"{v.ex_id}: {f}" for f in v.findings)
    return out


# --------------------------------------------------------------------------
# 入库策略（docs/12 P4：全学段默认自动入库；_drafts 仅由显式 force_drafts / 服务层熔断驱动）
# --------------------------------------------------------------------------
def _dest_dir(level: str, topic: str, *, force_drafts: bool | None = None) -> tuple[Path, bool]:
    """返回 (目标目录, is_draft)。默认自动入库（stages）；force_drafts=True → _drafts（CLI/熔断）。"""
    to_draft = bool(force_drafts)
    if to_draft:
        d = content_root() / "_drafts"
        d.mkdir(parents=True, exist_ok=True)
        return d, True
    d = stages_dir() / level / topic_dir_name(topic)
    d.mkdir(parents=True, exist_ok=True)
    return d, False


def _filename(node_id: str) -> str:
    safe = node_id.replace(".", "_")
    return f"node_{safe}_auto.md"


def _content_file_exists(entry: RoadmapEntry) -> bool:
    """该蓝图条目的内容是否已落盘（stages 同 id 或 _drafts）。"""
    fn = _filename(entry.id)
    if (content_root() / "_drafts" / fn).exists():
        return True
    level_dir = stages_dir() / entry.level
    if level_dir.exists():
        for p in level_dir.rglob(fn):
            return True
    return False


def generate_entry(
    entry: RoadmapEntry,
    *,
    drafter: Drafter = stub_drafter,
    known_ids: set[str],
    force_drafts: bool | None = None,
) -> ItemResult:
    """生成单个条目：校验通过 → 按策略落盘；已存在 → exists。"""
    # 幂等：目标 id 已在库（真实节点/本批先产）或文件已落盘 → exists
    if entry.id in known_ids or _content_file_exists(entry):
        return ItemResult(entry_id=entry.id, status="exists")

    # anchors：已有真实人工节点覆盖本蓝图条目的学习目标 → 不再生成重复内容
    if any(a in known_ids for a in entry.anchors):
        return ItemResult(entry_id=entry.id, status="covered", path=None)

    # R13/A2：出稿 → 自动校验；失败自动带错误重试一次（≤DRAFT_RETRY_MAX 次），
    # 重试仍失败 → failed（每轮错误均带 attempt 前缀透传，供 UI/自续统计）
    attempts_errors: list[str] = []
    raw_md: str | None = None
    for attempt in range(1, DRAFT_RETRY_MAX + 1):
        try:
            raw_md = drafter(entry, attempts_errors or None)
        except Exception as e:  # 出稿器自身异常（DraftingError 等）
            attempts_errors.append(f"[attempt {attempt}] 出稿器异常: {e}")
            continue
        errs = validate_candidate(raw_md, known_ids)
        if not errs:
            errs = validate_semantics(raw_md)   # R35 §12：语义闸门（独立函数、独立调用）
        if not errs:
            break
        attempts_errors.extend(f"[attempt {attempt}] {e}" for e in errs)
        raw_md = None
    if raw_md is None:
        failed_errors = attempts_errors or ["出稿/校验失败"]
        return ItemResult(entry_id=entry.id, status="failed", errors=failed_errors)

    dest, is_draft = _dest_dir(entry.level, entry.topic, force_drafts=force_drafts)
    path = dest / _filename(entry.id)
    path.write_text(_with_source_marker(raw_md), encoding="utf-8")
    return ItemResult(entry_id=entry.id, status="ok", path=str(path))


def _with_source_marker(raw_md: str) -> str:
    """入库文件必须带 `source: auto` 标记（纠错/护栏/审计按文件 front-matter 判断来源）。

    历史 bug：管线曾在内存 meta 标 auto 但写盘保留 AI 原文 → 文件无标记 → node_source()
    默认 'human'，auto 节点纠错被当人工、护栏分母失效（2026-09-08 实测发现，已修）。
    """
    if "\nsource:" in raw_md or raw_md.startswith("source:"):
        return raw_md
    lines = raw_md.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("id:"):
            lines.insert(i + 1, "source: auto")
            return "\n".join(lines)
    return "source: auto\n" + raw_md


def _anchor_map(roadmap: Roadmap) -> dict[str, str]:
    """蓝图条目 → 已入库锚点节点 id（anchors[0]），供前置翻译。"""
    return {e.id: e.anchors[0] for e in roadmap.entries if e.anchors}


def _needed_ids(roadmap: Roadmap, target_topics: set[str]) -> list[str]:
    """含传递前置的所需条目 id（按蓝图顺序，保证先决先生成）。"""
    index = {e.id: i for i, e in enumerate(roadmap.entries)}
    wanted = {e.id for e in roadmap.entries if e.topic in target_topics}
    # 传递收集前置（蓝图条目 id 域内）
    stack = list(wanted)
    need: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in need:
            continue
        need.add(cur)
        by_id = roadmap.by_id()
        for p in by_id[cur].prereqs:
            if p in index:
                stack.append(p)
    return [e.id for e in roadmap.entries if e.id in need]


def _resolve_prereqs(
    entry: RoadmapEntry,
    *,
    amap: dict[str, str],
    registry: dict[str, tuple[str, RoadmapEntry]],
    known: set[str],
    level: str,
) -> list[str]:
    """把蓝图条目 prereq 翻译为"内容节点可落地的 prereq 列表"（R14 后续 #1 跨学段语义）：

    - 同文件条目被锚点覆盖 → 指真实锚点节点（原 amap 行为）；
    - 跨学段引用（registry 其它学段条目）：目标条目已落地（锚点节点或已生成 auto 节点在库）
      → 用其落地 id 建内容边；**未落地 → 剔除**（该依赖由学段顺序推进兜底，见 selfextend 缺口提示；
      内容文件不得声明指向不存在节点的 prereq——loader/图谱校验不允许）。
    - 其余（同文件条目 / 真实节点引用）原样保留。
    """
    out: list[str] = []
    for x in entry.prereqs:
        if x in amap:
            out.append(amap[x])
            continue
        ref = registry.get(x)
        if ref is not None and ref[0] != level:
            landed = landed_id_for(ref[1], known)
            if landed in known:
                out.append(landed)
            # else：未落地 → 剔除（缺口由 cross_level_gaps/selfextend 提示）
            continue
        out.append(x)
    return out


def cross_level_gaps(level: str, lib_ids: set[str] | None = None) -> list[str]:
    """该学段条目中"跨学段前置条目未落地"清单（提示用，不阻塞；学段顺序推进兜底）。"""
    roadmap = load_roadmap(level)
    lib = lib_ids if lib_ids is not None else set(load_library().by_id)
    registry = all_entries()
    gaps: list[str] = []
    for e in roadmap.entries:
        for x in e.prereqs:
            ref = registry.get(x)
            if ref is not None and ref[0] != level and landed_id_for(ref[1], lib) not in lib:
                gaps.append(f"{e.id}->{x}({ref[0]} 条目未落地)")
    return gaps


def generate_sequence(
    roadmap: Roadmap,
    entry_ids: list[str],
    *,
    drafter: Drafter = stub_drafter,
    force_drafts: bool | None = None,
) -> list[ItemResult]:
    """按蓝图顺序生成给定条目（含 anchor 覆盖/前置翻译；ancestor 自动补齐不在此处）。"""
    lib = load_library()
    known: set[str] = set(lib.by_id)
    amap = _anchor_map(roadmap)
    registry = all_entries()  # 跨学段蓝图条目注册表（跨文件引用解析）
    results: list[ItemResult] = []
    for eid in entry_ids:
        entry = roadmap.by_id()[eid]
        # 前置翻译：同文件锚点覆盖 → 真实节点；跨学段引用 → 落地 id（未落地剔除）
        translated = _resolve_prereqs(entry, amap=amap, registry=registry, known=known, level=roadmap.level)
        eff = entry
        if translated != list(entry.prereqs):
            eff = entry.model_copy(update={"prereqs": translated})
        # 被覆盖的锚点视为已知（其前置通过）
        for a in eff.anchors:
            if a not in known:
                known.add(a)
        known.add(eid)  # 占位：允许本批后继条目前置引用
        res = generate_entry(eff, drafter=drafter, known_ids=known - {eid}, force_drafts=force_drafts)
        results.append(res)
        if res.status == "failed":
            known.discard(eid)
        elif res.status == "covered":
            # 该条被锚点覆盖 → 锚点 id 视为其内容落地
            if eff.anchors:
                known.add(eff.anchors[0])
    return results


def generate_topic(
    level: str,
    topic: str,
    *,
    drafter: Drafter = stub_drafter,
    limit: int | None = None,
    force_drafts: bool | None = None,
) -> list[ItemResult]:
    """按蓝图生成某学段某主题所需条目（传递前置自动补齐，顺序保证先决先生成）。"""
    roadmap = load_roadmap(level)
    needed = _needed_ids(roadmap, {topic})
    if limit:
        needed = needed[:limit]
    if not needed:
        raise PipelineError(f"蓝图 {level} 中无主题 {topic!r} 的条目")
    return generate_sequence(roadmap, needed, drafter=drafter, force_drafts=force_drafts)


__all__ = [
    "Drafter",
    "ItemResult",
    "PipelineError",
    "stub_drafter",
    "generate_topic",
    "generate_sequence",
    "generate_entry",
    "validate_candidate",
    "validate_semantics",
    "semantic_findings",
    "cross_level_gaps",
    "SELFCHECK_SEEDS",
]
