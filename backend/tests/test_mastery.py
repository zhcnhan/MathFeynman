"""domain.mastery 单测（docs/03 §2 达标规则）。"""
from __future__ import annotations

import pytest

from app.domain.mastery import (
    MISS_REASON_FEYNMAN,
    MISS_REASON_PRACTICE,
    MasteryStats,
    evaluate_pass,
)


def pass_stats(**kw) -> MasteryStats:
    base = dict(
        consecutive_correct=3,
        min_difficulty_among_streak=1.0,
        feynman_score=0.8,
        feynman_threshold=0.7,
    )
    base.update(kw)
    return MasteryStats(**base)


def test_pass_all_conditions():
    v = evaluate_pass(pass_stats())
    assert v.passed is True and v.missing == []


def test_fail_when_only_two_correct():
    v = evaluate_pass(pass_stats(consecutive_correct=2))
    assert not v.passed and v.missing == [MISS_REASON_PRACTICE]


def test_fail_when_streak_is_easy_only():
    # 三连简单题（难度 <1）不算达标（docs/03 §2：难度不低于基础档）
    v = evaluate_pass(pass_stats(min_difficulty_among_streak=0.5))
    assert not v.passed and v.missing == [MISS_REASON_PRACTICE]


def test_fail_when_feynman_missing():
    v = evaluate_pass(pass_stats(feynman_score=None))
    assert not v.passed and v.missing == [MISS_REASON_FEYNMAN]


def test_fail_when_feynman_below_threshold():
    v = evaluate_pass(pass_stats(feynman_score=0.69))
    assert not v.passed and v.missing == [MISS_REASON_FEYNMAN]


def test_fail_both_reasons():
    v = evaluate_pass(pass_stats(consecutive_correct=0, feynman_score=None))
    assert not v.passed
    assert MISS_REASON_PRACTICE in v.missing and MISS_REASON_FEYNMAN in v.missing


def test_threshold_exact_boundary():
    v = evaluate_pass(pass_stats(feynman_score=0.7))
    assert v.passed is True  # ≥ 及格线


def test_threshold_custom_from_content():
    v = evaluate_pass(pass_stats(feynman_score=0.75, feynman_threshold=0.8))
    assert not v.passed
    v2 = evaluate_pass(pass_stats(feynman_score=0.8, feynman_threshold=0.8))
    assert v2.passed is True
