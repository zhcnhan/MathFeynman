"""app.ai.tier：模型策略解析器（docs/09 R12，标注 R12）。

对每次 AI 调用决策链：基础档(内容/学段) → 升级触发 → 用户覆盖，输出 `fast | think`。

- 基础档：primary/middle/high → fast；college/ai → think；内容标记 `feynman.thinking: true` → think。
- 升级触发（smart 模式开启；light 关闭 a/b，deep 全 think）：
  a. 费曼边缘分（首轮 fast 综合分 ∈ [threshold−0.15, threshold+0.10]）→ 下一轮 think；
     轮次 ≥2 → think。
  b. 答疑 fast 回复 out_of_scope → 同题自动 think 重生成。
- 用户覆盖（最高优先）：model_mode light 关触发但保 college/ai think 底线；deep 全 think；
  单次 payload.think_deep true/false/null 覆盖该次。
"""
from __future__ import annotations

from dataclasses import dataclass

FAST = "fast"
THINK = "think"

BASE_FAST_LEVELS = {"primary", "middle", "high"}
BASE_THINK_LEVELS = {"college", "ai"}
THINK_LEVELS = BASE_THINK_LEVELS

# 费曼边缘区间宽度（docs/09 R12 a）
FEYNMAN_EDGE_LOW = 0.15
FEYNMAN_EDGE_HIGH = 0.10


@dataclass(frozen=True)
class TierDecision:
    strategy: str  # fast | think
    reason: str


def is_think_level(level: str | None) -> bool:
    return (level or "") in THINK_LEVELS


def base_strategy(level: str | None = None, content_think: bool | None = None) -> str:
    """基础档：学段 + 内容覆盖（feynman.thinking 置 think 优先于学段判断）。"""
    if content_think:
        return THINK
    return THINK if is_think_level(level) else FAST


def _is_edge(combined: float, threshold: float) -> bool:
    return threshold - FEYNMAN_EDGE_LOW <= combined <= threshold + FEYNMAN_EDGE_HIGH


def resolve(
    *,
    level: str | None = None,
    content_think: bool | None = None,
    model_mode: str = "smart",
    override: bool | None = None,   # 单次 payload.think_deep
    extra_think: bool = False,      # 命中升级触发（边缘/轮次≥2/超纲等），smart 才生效
) -> TierDecision:
    """主解析：base → (smart 触发) → 用户覆盖。"""
    base = base_strategy(level=level, content_think=content_think)

    if override is True:
        return TierDecision(THINK, "override=true")
    if override is False:
        return TierDecision(FAST, "override=false")

    if model_mode == "deep":
        return TierDecision(THINK, "model_mode=deep")
    if model_mode == "light":
        # 关触发但保底线（college/ai/content_think 基础仍 think）
        return TierDecision(base, f"model_mode=light/base={base}")
    # smart
    if base == THINK:
        return TierDecision(THINK, f"base={base}")
    if extra_think:
        return TierDecision(THINK, "trigger")
    return TierDecision(FAST, "base=fast")


def feynman_edge(combined: float, threshold: float) -> bool:
    return _is_edge(combined, threshold)


def feynman_round_should_think(current_round: int) -> bool:
    """费曼轮次 ≥2 → think（触发 a 的一部分，由 resolve extra_think 承载）。"""
    return current_round >= 2


__all__ = [
    "TierDecision",
    "FAST",
    "THINK",
    "resolve",
    "base_strategy",
    "feynman_edge",
    "feynman_round_should_think",
    "is_think_level",
    "THINK_LEVELS",
]
