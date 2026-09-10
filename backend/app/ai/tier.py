"""app.ai.tier：模型策略解析器（docs/09 R12，标注 R12）。

对每次 AI 调用决策链：基础档(内容/学段) → 升级触发 → 用户覆盖，输出 `fast | think`。

- 基础档：primary/middle/high → fast；college/ai → think；内容标记 `feynman.thinking: true` → think。
- 升级触发（smart 模式开启；light 关闭 a/b，deep 全 think）：
  a. 费曼边缘分（首轮 fast 综合分 ∈ [threshold−0.15, threshold+0.10]）→ 下一轮 think；
     轮次 ≥2 → think。
  b. 答疑 fast 回复 out_of_scope → 同题自动 think 重生成。
- 用户覆盖（最高优先）：model_mode light 关触发但保 college/ai think 底线；deep 全 think；
  单次 payload.think_deep true/false/null 覆盖该次。
- R30 F6（另行一条，不改上面决策链）：完整稿本轮综合分落**复评边缘带**
  （``feynman_recheck_band``，−0.05/+0.08）且本轮非 think → 以 think 复评一次取高分。
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

# R30 F6：费曼完整稿（首讲/终验）**边缘带复评**区间宽度（门槛 ± 常量）。
# 含义：本轮综合分离及格线太近 → 同一篇讲解可能"这次过、下次不过"（阈值抖动，
# R28 F6 实测同一稿 0.863 / 0.73）→ 用 think 档复评一次、取较高分（成本见 R30 §F6.5）。
FEYNMAN_RECHECK_LOW = 0.05
FEYNMAN_RECHECK_HIGH = 0.08


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


def feynman_recheck_band(combined: float, threshold: float) -> bool:
    """R30 F6：本轮综合分是否落在**复评边缘带** ``[threshold−0.05, threshold+0.08]``。

    与 R12 的"下轮升 think"边缘区间（−0.15/+0.10）刻意分开：R12 决定**下一轮**档位，
    本函数决定**本轮已出分**是否需要用 think 档再评一次取高分（防阈值抖动）。
    """
    return threshold - FEYNMAN_RECHECK_LOW <= combined <= threshold + FEYNMAN_RECHECK_HIGH


def feynman_round_should_think(current_round: int) -> bool:
    """费曼轮次 ≥2 → think（触发 a 的一部分，由 resolve extra_think 承载）。"""
    return current_round >= 2


# ---------------------------------------------------------------------------
# R42 C1：**降档必须显性**（architecture 裁决 docs/09 R41 §3-③：逐次记账）
# ---------------------------------------------------------------------------
# "降档"＝**本来该走重推理档（think），实际跑了轻档（fast）**。三种成因：
#   ① 用户单次覆盖 `payload.think_deep=false`（override=false）；
#   ② 用户模型模式 = light（关掉触发，但保住 college/ai 底线——那种**不算**降档）；
#   ③ 命中升级触发的场景（如"轮次≥2 应变 think"）在 smart 下**未**升级。
# 判据（可判定、不猜）：`base == think`（学段/内容要求 think）**且**最终 decision == fast。
# 这是"没按用户以为的档位跑"，属铁则正题；降档是异常路径，量级可控。
def downgrade_of(decision: TierDecision, *, level: str | None = None,
                 content_think: bool | None = None,
                 model_mode: str = "smart", override: bool | None = None) -> dict | None:
    """返回**降档说明**（未降档 → ``None``）：``{base, strategy, reason, reason_zh}``。"""
    base = base_strategy(level=level, content_think=content_think)
    if base != THINK or decision.strategy != FAST:
        return None
    if override is False:
        zh = "本节点按学段/内容本应走**重推理档（think）**，但本次被**单次覆盖**为轻档（think_deep=false）"
    elif model_mode == "light":
        zh = ("本节点按学段/内容本应走**重推理档（think）**，但当前模型模式为「⚡ 快」，"
              "本次降为轻档（fast）")
    else:
        zh = (f"本节点按学段/内容本应走**重推理档（think）**，本次按策略解析降为轻档（fast）"
              f"（解析依据：{decision.reason}）")
    return {"base": base, "strategy": decision.strategy, "reason": decision.reason,
            "reason_zh": zh, "model_mode": model_mode,
            "override": None if override is None else bool(override)}


def note_downgrade(decision: TierDecision, *, subject_id: str = "", unit_id: str = "",
                   call_name: str = "", level: str | None = None,
                   content_think: bool | None = None, model_mode: str = "smart",
                   override: bool | None = None) -> dict | None:
    """**R42 C1**：若本次是降档 → 记一条账本（``CAT_MODEL_CALL``，中文原因）；返回降档说明。"""
    info = downgrade_of(decision, level=level, content_think=content_think,
                        model_mode=model_mode, override=override)
    if info is None:
        return None
    try:
        from ..service import ledger

        ledger.note(
            ledger.CAT_MODEL_CALL, f"模型档位（{call_name or decision.strategy}）",
            info["reason_zh"] + "——如需重推理，可在设置里切到「🧠 深度」或单次勾选深度思考",
            impact=ledger.SCOPE_THIS_RUN, remedy=ledger.REMEDY_YES,
            subject_id=subject_id, unit_id=unit_id,
            detail={"kind": "tier_downgrade", "call_name": call_name, **info},
        )
    except Exception:  # 记账失败不影响调用
        pass
    return info


__all__ = [
    "TierDecision",
    "FAST",
    "THINK",
    "resolve",
    "base_strategy",
    "feynman_edge",
    "feynman_recheck_band",
    "feynman_round_should_think",
    "is_think_level",
    "downgrade_of",
    "note_downgrade",
    "THINK_LEVELS",
]
