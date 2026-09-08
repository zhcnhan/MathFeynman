"""service.guardrails：内容质量护栏（docs/12 P4 配套 · 北极星"运行期无人审"的兜底）。

高+ 学段默认自动入库后，以**机械护栏 + 纠错召回熔断**替代强制人审：
1. 自动校验（pipeline.validate_candidate）：结构 / prereq 白名单（仅库内+本批前置链）/ 每题 8-seed
   sympy 验算 broken=0 —— 全部通过才入库（既有权责，本模块不重复）。
2. 白名单：蓝图条目 id 与其 prereq 链即为生成白名单（generate_sequence 注入 known_ids），
   概念白名单在 ai/prompts ContextBlock（docs/05）。
3. **纠错召回熔断（本模块）**：用户纠错反馈（feedback 表 status=pending）命中某蓝图主题的
   "已入库 auto 节点"达到问题率阈值 → 该主题后续生成转 _drafts 待检（selfextend 接线 force_drafts）；
   pending 清零（复核 reviewed / 自动重生成替换）→ 自动恢复入库。
   - 分母 = 该主题已入库 **auto** 节点数（锚点覆盖的人工节点不算：人工质量本就有人把关）。
   - 分子 = 其中被"未处置(pending)反馈"命中的去重节点数。
   - 阈值与最小样本见常量；样本过小不触发（防单点误伤）。

计数与恢复均可由 DB 推导（无状态、无持久化标志），服务重启不丢失。
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..content.loader import load_library
from ..content.roadmap import load_roadmap

# 问题率阈值：pending 反馈节点 / 已入库 auto 节点 > TRIP_RATIO 即熔断
TRIP_RATIO = 0.3
# 最小触发样本：至少 2 个不同问题节点、且分母 ≥ 3（防少量样本误伤）
MIN_PROBLEM_NODES = 2
MIN_DENOM = 3

KINDS = ("lecture", "exercise", "content")


def _landed_auto_ids(level: str, topic: str) -> set[str]:
    """该主题已入库的 auto 内容节点 id（蓝图条目自身 id；锚点覆盖的人工节点不计入分母）。"""
    roadmap = load_roadmap(level)
    lib = load_library().by_id
    landed: set[str] = set()
    for e in roadmap.entries:
        if e.topic != topic or e.anchors:
            continue
        if e.id in lib:
            landed.add(e.id)
    return landed


def topic_problem_stats(db: Session, level: str, topic: str) -> dict:
    """主题问题率统计：{landed, problems, ratio, tripped}。"""
    landed = _landed_auto_ids(level, topic)
    if not landed:
        return {"landed": 0, "problems": 0, "ratio": 0.0, "tripped": False}
    rows = (
        db.query(models.Feedback.node_id)
        .filter(
            models.Feedback.status == "pending",
            models.Feedback.node_id.in_(landed),
            models.Feedback.kind.in_(KINDS),
        )
        .distinct()
        .all()
    )
    problems = len(rows)
    ratio = problems / len(landed)
    tripped = (
        ratio > TRIP_RATIO
        and problems >= MIN_PROBLEM_NODES
        and len(landed) >= MIN_DENOM
    )
    return {"landed": len(landed), "problems": problems, "ratio": round(ratio, 4), "tripped": tripped}


def should_force_draft(db: Session, level: str, topic: str) -> bool:
    """熔断判定：该主题转 _drafts 待检。"""
    return topic_problem_stats(db, level, topic)["tripped"]


__all__ = [
    "TRIP_RATIO",
    "MIN_PROBLEM_NODES",
    "MIN_DENOM",
    "topic_problem_stats",
    "should_force_draft",
]
