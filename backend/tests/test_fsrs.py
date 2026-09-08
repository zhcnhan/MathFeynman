"""domain.fsrs 单测（docs/03 §3）：排程增长、rating 语义、降级计数、序列化。"""
from __future__ import annotations

import datetime as dt

import pytest

from app.domain.fsrs import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    FsrsScheduler,
    ReviewState,
    should_relearn,
)

T0 = dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
DAY = dt.timedelta(days=1)


def days_between(a: dt.datetime, b: dt.datetime) -> float:
    return (b - a).total_seconds() / 86400.0


@pytest.fixture()
def sched() -> FsrsScheduler:
    return FsrsScheduler()


def test_first_schedule_good_about_two_days(sched):
    rs = sched.schedule("n1", RATING_GOOD, now=T0)
    assert rs.due_at is not None
    d = days_between(T0, rs.due_at)
    assert 1.0 <= d <= 4.0
    assert rs.state == "review"


def test_first_schedule_rating_order(sched):
    due = {}
    for r in (RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY):
        rs = sched.schedule("n", r, now=T0)
        due[r] = days_between(T0, rs.due_at)
    # again < hard < good < easy（docs/03 §3 rating 语义）
    assert due[RATING_AGAIN] <= due[RATING_HARD] <= due[RATING_GOOD] < due[RATING_EASY]


def test_good_review_interval_grows(sched):
    first = sched.schedule("n", RATING_GOOD, now=T0)
    later = T0 + dt.timedelta(days=max(1, int(days_between(T0, first.due_at))))
    second = sched.schedule("n", RATING_GOOD, current=first, now=later)
    assert second.stability > first.stability
    assert days_between(later, second.due_at) > days_between(T0, first.due_at)


def test_lapse_counts_again_and_hard(sched):
    rs = sched.schedule("n", RATING_AGAIN, now=T0)
    assert rs.lapse_count == 1
    rs = sched.schedule("n", RATING_HARD, current=rs, now=T0 + DAY)
    assert rs.lapse_count == 2
    rs = sched.schedule("n", RATING_GOOD, current=rs, now=T0 + 2 * DAY)
    assert rs.lapse_count == 2  # good 不增
    assert should_relearn(rs.lapse_count) is True


def test_relearn_rule_boundary(sched):
    rs = sched.schedule("n", RATING_AGAIN, now=T0)
    assert should_relearn(rs.lapse_count) is False  # 1 次不降级
    assert should_relearn(2) is True  # docs/03 §3：累计 2 次降级回炉
    assert should_relearn(3) is True


def test_is_due(sched):
    rs = sched.schedule("n", RATING_GOOD, now=T0)
    assert sched.is_due(rs, now=T0) is False
    assert sched.is_due(rs, now=rs.due_at + dt.timedelta(seconds=1)) is True


def test_interval_days_never_negative(sched):
    rs = sched.schedule("n", RATING_GOOD, now=T0)
    assert sched.interval_days(rs) >= 0.0


def test_invalid_rating(sched):
    with pytest.raises(ValueError):
        sched.schedule("n", 9, now=T0)
    with pytest.raises(ValueError):
        sched.schedule("n", 0, now=T0)


def test_serialization_roundtrip(sched):
    rs = sched.schedule("n", RATING_EASY, now=T0)
    rs2 = ReviewState.from_dict(rs.to_dict())
    assert rs2.node_id == rs.node_id
    assert rs2.due_at == rs.due_at
    assert abs(rs2.stability - rs.stability) < 1e-9
    assert rs2.lapse_count == rs.lapse_count and rs2.reps == rs.reps
    # 序列化后继续排程不报错
    sched.schedule("n", RATING_GOOD, current=rs2, now=rs2.due_at)


def test_multi_node_independent(sched):
    a = sched.schedule("a", RATING_GOOD, now=T0)
    b = sched.schedule("b", RATING_AGAIN, now=T0)
    assert a.node_id == "a" and b.node_id == "b"
    assert b.due_at < a.due_at
