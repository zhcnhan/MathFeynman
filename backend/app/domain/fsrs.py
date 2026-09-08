"""domain.fsrs：复习调度封装（docs/03 §3）。

- 算法：FSRS 算法族。Python 侧经封装使用开源 `fsrs` pip 包（open-spaced-repetition
  实现，FSRS-4.5 默认权重），**封装接口以便日后替换**（ADR A8/风险对策）。
  配置上关闭分钟级 learning/relearning steps：复习项 = 节点，达标即进入按天间隔的
  review 排程（mastered ──FSRS 到期──▶ reviewing）。
- rating 对齐 1–4：again(1) / hard(2) / good(3) / easy(4)。
- 行为规则（docs/03 §3）：
  * 复习 rating 为 again/hard 累计 2 次 → 节点从 mastered 降级 learning（回炉）。
    （计数由 service 维护于 reviews.lapse_count；本模块提供判定助手。）
- 本模块不碰 DB：状态以 ReviewState（可序列化）进出。
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

from fsrs import Card, Rating as _FsrsRating, Scheduler

RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4
RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}
RATING_VALUES = {v: k for k, v in RATING_NAMES.items()}

# 复习降级阈值（docs/03 §3：again/hard 累计 2 次）
RELEARN_LAPSE_LIMIT = 2

# 复现固定 now（测试友好）；None = 真实当前时间
_EPOCH = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)


@dataclass
class ReviewState:
    """单个复习项（= 节点）的 FSRS 状态，可序列化为 dict 存 reviews.state_json。"""

    node_id: str = ""
    due_at: _dt.datetime | None = None
    stability: float = 0.0
    difficulty: float = 0.0
    reps: int = 0
    lapse_count: int = 0
    last_rating: int | None = None
    last_review_at: _dt.datetime | None = None
    state: str = "new"  # new/learning/review/relearn（fsrs 语义投影）
    scheduled_days: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("due_at", "last_review_at"):
            v = d[k]
            d[k] = v.isoformat() if v else None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewState":
        d = dict(data)
        for k in ("due_at", "last_review_at"):
            v = d.get(k)
            d[k] = _dt.datetime.fromisoformat(v) if v else None
        return cls(**d)


def _fsrs_state_name(state: int) -> str:
    return {0: "new", 1: "learning", 2: "review", 3: "relearn"}.get(int(state), "new")


class FsrsScheduler:
    """薄封装：pip fsrs 负责区间计算；本类负责状态转换与持久化形态。"""

    def __init__(self) -> None:
        self._scheduler = Scheduler()
        # 复习项 = 节点：达标后即按天排程，不经分钟级 steps
        self._scheduler.learning_steps = []
        self._scheduler.relearning_steps = []

    # ---- 内部转换 ----
    _STATE_TO_FSRS = {"new": 1, "learning": 1, "review": 2, "relearn": 3}

    def _to_fsrs_card(self, rs: ReviewState | None) -> Card:
        """ReviewState → pip fsrs Card（其 Card 仅存 7 字段：card_id/state/step/
        stability/difficulty/due/last_review）。"""
        if rs is None:
            return Card()
        if rs.state == "new" and rs.due_at is None:
            return Card()
        return Card.from_dict(
            {
                "card_id": int(rs.extra.get("card_id", 0)),
                "state": self._STATE_TO_FSRS.get(rs.state, 2),
                "step": None,
                "stability": rs.stability if rs.stability else None,
                "difficulty": rs.difficulty if rs.difficulty else None,
                "due": rs.due_at.isoformat() if rs.due_at else None,
                "last_review": rs.last_review_at.isoformat() if rs.last_review_at else None,
            }
        )

    def schedule(
        self,
        node_id: str,
        rating: int,
        current: ReviewState | None = None,
        *,
        now: _dt.datetime | None = None,
    ) -> ReviewState:
        """rating(1-4) → 下一个 ReviewState。首次排程传 current=None。"""
        if rating not in RATING_NAMES:
            raise ValueError(f"rating 必须在 1..4，得到 {rating!r}")
        now = now or _dt.datetime.now(_dt.timezone.utc)
        card = self._to_fsrs_card(current)
        new_card, _log = self._scheduler.review_card(card, _FsrsRating(rating), now)

        lapse_count = (current.lapse_count if current else 0) + (1 if rating in (RATING_AGAIN, RATING_HARD) else 0)
        reps = (current.reps if current else 0) + 1
        extra = dict(current.extra if current else {})
        extra["card_id"] = int(getattr(new_card, "card_id", 0))
        return ReviewState(
            node_id=node_id,
            due_at=getattr(new_card, "due", None) or None,
            stability=float(new_card.stability or 0.0),
            difficulty=float(new_card.difficulty or 0.0),
            reps=reps,
            lapse_count=lapse_count,
            last_rating=rating,
            last_review_at=now,
            state=_fsrs_state_name(int(new_card.state)),
            scheduled_days=0.0,  # 由 due_at - now 计算，见 interval_days
            extra=extra,
        )

    def is_due(self, rs: ReviewState, *, now: _dt.datetime | None = None) -> bool:
        now = now or _dt.datetime.now(_dt.timezone.utc)
        return rs.due_at is not None and rs.due_at <= now

    def interval_days(self, rs: ReviewState) -> float:
        """距下次到期天数（UI：每个节点距下次复习的天数）。"""
        if rs.due_at is None:
            return 0.0
        delta = rs.due_at - _dt.datetime.now(_dt.timezone.utc)
        return max(0.0, delta.total_seconds() / 86400.0)


def should_relearn(lapse_count: int) -> bool:
    """再次/hard 累计 ≥2 次 → mastered 降级 learning（docs/03 §3）。"""
    return lapse_count >= RELEARN_LAPSE_LIMIT


__all__ = [
    "ReviewState",
    "FsrsScheduler",
    "should_relearn",
    "RATING_AGAIN",
    "RATING_HARD",
    "RATING_GOOD",
    "RATING_EASY",
    "RATING_NAMES",
    "RELEARN_LAPSE_LIMIT",
]
