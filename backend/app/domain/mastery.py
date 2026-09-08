"""domain.mastery：掌握度模型（docs/03 §2）。

MVP 采用 Mastery Learning 规则（确定、可解释）：
一次"达标判定"需同时满足
  1) 本节点连续答对 ≥ 3 道练习（难度不低于基础档）；
  2) 本节点费曼评估通过（Rubric 综合分 ≥ 及格线）。

未达标原因分类记录到画像由 service 层负责（error_profile）。
本模块纯规则：输入统计 → 输出达标判定 + 未达原因。升级路径（BKT）接口预留：
get(node_id) 抽象由 service 在 P2 引入，不在此实现。
"""
from __future__ import annotations

from dataclasses import dataclass

# 达标规则常量（docs/03 §2）
MIN_CONSECUTIVE_CORRECT = 3
MIN_DIFFICULTY = 1  # 难度不低于基础档(1)

MISS_REASON_PRACTICE = "practice_not_enough"   # 连续答对不足 3
MISS_REASON_FEYNMAN = "feynman_not_passed"     # 费曼未通过
MISS_REASON_NONE = None


@dataclass(frozen=True)
class MasteryStats:
    """达标判定所需统计（由 service 从会话/user_nodes 汇总注入）。"""

    consecutive_correct: int = 0
    # 最近 MIN_CONSECUTIVE_CORRECT 道答对题的最低难度（防"三连简单题"过关）
    min_difficulty_among_streak: float = 0.0
    feynman_score: float | None = None   # Rubric 加权综合分 0..1；未评过为 None
    feynman_threshold: float = 0.7       # 每节点 rubric.pass_threshold（docs/04 §2）


@dataclass(frozen=True)
class MasteryVerdict:
    passed: bool
    missing: list[str]  # 未达原因（passed=True 时为空）


def evaluate_pass(stats: MasteryStats) -> MasteryVerdict:
    """达标判定：练习 3 连对（难度≥1） 且 费曼通过。"""
    missing: list[str] = []
    if stats.consecutive_correct < MIN_CONSECUTIVE_CORRECT:
        missing.append(MISS_REASON_PRACTICE)
    elif stats.min_difficulty_among_streak < MIN_DIFFICULTY:
        missing.append(MISS_REASON_PRACTICE)  # 三连简单题不算数
    if stats.feynman_score is None:
        missing.append(MISS_REASON_FEYNMAN)
    elif stats.feynman_score < stats.feynman_threshold:
        missing.append(MISS_REASON_FEYNMAN)
    return MasteryVerdict(passed=not missing, missing=missing)


__all__ = [
    "MasteryStats",
    "MasteryVerdict",
    "evaluate_pass",
    "MIN_CONSECUTIVE_CORRECT",
    "MIN_DIFFICULTY",
    "MISS_REASON_PRACTICE",
    "MISS_REASON_FEYNMAN",
]
