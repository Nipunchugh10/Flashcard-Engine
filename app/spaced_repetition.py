"""
SM-2 spaced repetition.

We expose a 4-button rating system that's more intuitive than raw 0-5:
    Again  -> quality 0   (complete blackout / wrong)
    Hard   -> quality 3   (recalled with serious effort)
    Good   -> quality 4   (recalled correctly with some effort)
    Easy   -> quality 5   (perfect response)

Algorithm (classic SM-2 with small, pragmatic tweaks):
    - EF starts at 2.5, bounded below by 1.3.
    - On quality < 3 (Again): repetitions -> 0, interval -> ~10 min (0.007 days),
      lapses += 1. This re-enters the learning queue without punishing EF too hard.
    - On quality >= 3:
        * if repetitions == 0: interval = 1 day
        * if repetitions == 1: interval = 6 days
        * else: interval = round(interval * EF)
        * repetitions += 1
    - EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
      Clamped to >= 1.3.

Status derivation:
    new       -> never reviewed
    learning  -> reviewed, interval_days < 1 (still inside a day)
    review    -> scheduled in days but not yet stable
    mastered  -> interval_days >= 21 and repetitions >= 4
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Literal

Rating = Literal["again", "hard", "good", "easy"]

RATING_TO_QUALITY: dict[str, int] = {
    "again": 0,
    "hard": 3,
    "good": 4,
    "easy": 5,
}


@dataclass
class SRSState:
    ease_factor: float
    interval_days: float
    repetitions: int
    lapses: int
    next_review: datetime
    status: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _derive_status(repetitions: int, interval_days: float, reviews_count: int) -> str:
    if reviews_count == 0:
        return "new"
    if interval_days < 1:
        return "learning"
    if interval_days >= 21 and repetitions >= 4:
        return "mastered"
    return "review"


def apply_rating(
    *,
    rating: Rating,
    ease_factor: float,
    interval_days: float,
    repetitions: int,
    lapses: int,
    reviews_count: int,
) -> SRSState:
    """Return the updated SRS state after applying a single review."""
    if rating not in RATING_TO_QUALITY:
        raise ValueError(f"Invalid rating: {rating!r}")

    q = RATING_TO_QUALITY[rating]
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, new_ef)

    if q < 3:
        # Lapse: show again in ~10 minutes; reset repetition counter.
        new_interval = 10 / (60 * 24)  # 10 minutes expressed in days
        new_reps = 0
        new_lapses = lapses + 1
    else:
        if repetitions == 0:
            new_interval = 1.0
        elif repetitions == 1:
            new_interval = 6.0
        else:
            base_interval = max(interval_days, 1.0)
            new_interval = round(base_interval * new_ef)

        # "Hard" should schedule sooner than "Good"; "Easy" later.
        if rating == "hard":
            new_interval = max(1.0, new_interval * 0.8)
        elif rating == "easy":
            new_interval = new_interval * 1.3

        new_reps = repetitions + 1
        new_lapses = lapses

    next_review = _now() + timedelta(days=new_interval)
    status = _derive_status(new_reps, new_interval, reviews_count + 1)

    return SRSState(
        ease_factor=round(new_ef, 4),
        interval_days=round(new_interval, 4),
        repetitions=new_reps,
        lapses=new_lapses,
        next_review=next_review,
        status=status,
    )


def minutes_until(dt: datetime) -> int:
    """Positive minutes until dt (0 if in the past)."""
    delta = dt - _now()
    return max(0, int(delta.total_seconds() // 60))
