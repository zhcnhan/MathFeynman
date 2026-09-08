"""R12 模型策略解析器单测：学段基础档 × 触发 × 用户覆盖 矩阵（docs/09 R12）。"""
from __future__ import annotations

import pytest

from app.ai.tier import (
    FAST,
    THINK,
    base_strategy,
    feynman_edge,
    feynman_round_should_think,
    resolve,
)


def test_base_strategy_by_stage():
    assert base_strategy("primary") == FAST
    assert base_strategy("middle") == FAST
    assert base_strategy("high") == FAST
    assert base_strategy("college") == THINK
    assert base_strategy("ai") == THINK
    assert base_strategy(None) == FAST


def test_content_think_overrides_stage():
    # primary + feynman.thinking:true → think（内容覆盖学段默认 fast）
    assert base_strategy("primary", content_think=True) == THINK
    assert base_strategy("college", content_think=False) == THINK  # 学段底线仍在


def test_smart_base_and_trigger():
    # smart：middle 基础 fast；命中触发(extra_think) → think
    assert resolve(level="middle", model_mode="smart").strategy == FAST
    assert resolve(level="middle", model_mode="smart", extra_think=True).strategy == THINK
    assert resolve(level="college", model_mode="smart").strategy == THINK


def test_light_disables_triggers_keeps_college():
    # light：触发关闭（middle+edge 仍 fast）；college/ai 底线仍 think
    assert resolve(level="middle", model_mode="light", extra_think=True).strategy == FAST
    assert resolve(level="college", model_mode="light", extra_think=True).strategy == THINK
    assert resolve(level="middle", model_mode="light").strategy == FAST


def test_deep_all_think():
    assert resolve(level="middle", model_mode="deep").strategy == THINK
    assert resolve(level="primary", model_mode="deep").strategy == THINK
    assert resolve(level=None, model_mode="deep").strategy == THINK


def test_override_wins_everything():
    assert resolve(level="middle", model_mode="light", override=True).strategy == THINK
    assert resolve(level="college", model_mode="deep", override=False).strategy == FAST
    assert resolve(level="college", model_mode="deep", override=True).strategy == THINK
    assert resolve(level="middle", model_mode="smart", override=True, extra_think=True).strategy == THINK


def test_reason_present():
    d = resolve(level="college", model_mode="smart")
    assert d.strategy == THINK and d.reason


def test_feynman_edge_interval():
    threshold = 0.7
    assert feynman_edge(0.6, threshold) is True    # [0.55, 0.80] 内
    assert feynman_edge(0.78, threshold) is True
    assert feynman_edge(0.9, threshold) is False   # 高分通过侧之外
    assert feynman_edge(0.3, threshold) is False   # 明显不过


def test_feynman_round_rule():
    assert feynman_round_should_think(1) is False  # 首轮
    assert feynman_round_should_think(2) is True   # ≥2 轮 → think
    assert feynman_round_should_think(3) is True
