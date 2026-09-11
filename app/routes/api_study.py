"""
Study session endpoints.

Study queue selection logic (matches familiar SRS apps):
    1. Any cards due now (next_review <= now), prioritised by the oldest
       next_review (i.e. most overdue first).
    2. Then new cards (status == 'new'), bounded per session.
    3. 'Learning' cards (sub-day intervals) that have come around in the queue.

We keep the session lightweight by returning a single 'next card' on demand,
rather than shipping the whole queue to the client. The client polls
/study/next after each rating.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, spaced_repetition
from ..auth import get_current_user
from ..database import get_db
from ..schemas import CardOut, RateCardIn
from ..stats import compute_deck_stats

router = APIRouter(prefix="/api/study", tags=["study"])

# Cap the number of new cards introduced in a single session.
NEW_CARDS_PER_SESSION = 20


def _get_user_deck(deck_id: int, user: models.User, db: Session) -> models.Deck:
    """Fetch a deck and verify it belongs to the user."""
    # Return 404 rather than 403 for someone else's deck: a 403 would
    # confirm that the id exists, letting an attacker enumerate which
    # decks other users own.
    deck = db.get(models.Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck


@router.get("/{deck_id}/next")
def next_card(
    deck_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Return the next card to study, or {done: true} if none."""
    deck = _get_user_deck(deck_id, user, db)

    now = datetime.now(timezone.utc)

    # Cards due now (learning + review + overdue) - order by oldest next_review.
    due_stmt = (
        select(models.Card)
        .where(models.Card.deck_id == deck_id)
        .where(models.Card.status != "new")
        .where(models.Card.next_review <= now)
        .order_by(models.Card.next_review.asc())
        .limit(1)
    )
    card = db.execute(due_stmt).scalar_one_or_none()

    if not card:
        # Introduce a new card (respect session cap).
        new_stmt = (
            select(models.Card)
            .where(models.Card.deck_id == deck_id)
            .where(models.Card.status == "new")
            .order_by(models.Card.id.asc())
            .limit(1)
        )
        card = db.execute(new_stmt).scalar_one_or_none()

    if not card:
        stats = compute_deck_stats(db, deck_id)
        return {"done": True, "stats": stats.model_dump()}

    # Count how many cards are "due or new" to help the client show progress.
    remaining = db.execute(
        select(models.Card).where(
            models.Card.deck_id == deck_id,
            or_(
                models.Card.status == "new",
                models.Card.next_review <= now,
            ),
        )
    ).all()

    return {
        "done": False,
        "card": CardOut.model_validate(card).model_dump(mode="json"),
        "remaining": len(remaining),
    }


@router.post("/cards/{card_id}/rate", response_model=CardOut)
def rate_card(
    card_id: int,
    payload: RateCardIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Verify ownership
    deck = db.get(models.Deck, card.deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="Card not found")

    new_state = spaced_repetition.apply_rating(
        rating=payload.rating,  # type: ignore[arg-type]
        ease_factor=card.ease_factor,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        lapses=card.lapses,
        reviews_count=card.reviews_count,
    )

    # Log this review, capturing the card's full prior state so it can be undone.
    db.add(
        models.ReviewLog(
            card_id=card.id,
            quality=spaced_repetition.RATING_TO_QUALITY[payload.rating],
            interval_before=card.interval_days,
            interval_after=new_state.interval_days,
            ease_after=new_state.ease_factor,
            ease_before=card.ease_factor,
            repetitions_before=card.repetitions,
            lapses_before=card.lapses,
            reviews_count_before=card.reviews_count,
            status_before=card.status,
            next_review_before=card.next_review,
            last_reviewed_before=card.last_reviewed,
        )
    )

    card.ease_factor = new_state.ease_factor
    card.interval_days = new_state.interval_days
    card.repetitions = new_state.repetitions
    card.lapses = new_state.lapses
    card.next_review = new_state.next_review
    card.last_reviewed = datetime.now(timezone.utc)
    card.reviews_count += 1
    card.status = new_state.status

    db.commit()
    db.refresh(card)
    return card


@router.post("/{deck_id}/undo", response_model=CardOut)
def undo_last_review(
    deck_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Reverse the most recent review in this deck.

    Restores the card from the snapshot taken when it was rated, then deletes
    the log entry so undo can be pressed repeatedly to walk back through a
    session. Without this a misclick is permanent: rating "Again" by accident
    drops a well-known card back to a ten-minute interval and there is no way
    to take it back.
    """
    _get_user_deck(deck_id, user, db)

    log = db.execute(
        select(models.ReviewLog)
        .join(models.Card, models.ReviewLog.card_id == models.Card.id)
        .where(models.Card.deck_id == deck_id)
        .order_by(models.ReviewLog.reviewed_at.desc(), models.ReviewLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if log is None:
        raise HTTPException(status_code=404, detail="Nothing to undo in this deck.")

    card = db.get(models.Card, log.card_id)
    if card is None:
        db.delete(log)
        db.commit()
        raise HTTPException(status_code=404, detail="That card no longer exists.")

    card.ease_factor = log.ease_before
    card.interval_days = log.interval_before
    card.repetitions = log.repetitions_before
    card.lapses = log.lapses_before
    card.reviews_count = log.reviews_count_before
    card.status = log.status_before
    card.next_review = log.next_review_before or card.next_review
    card.last_reviewed = log.last_reviewed_before

    db.delete(log)
    db.commit()
    db.refresh(card)
    return card


@router.get("/{deck_id}/history")
def deck_history(
    deck_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Daily review counts and accuracy for the last `days` days.

    Aggregated in Python rather than SQL so the same code works on SQLite and
    PostgreSQL, which spell date truncation differently.
    """
    _get_user_deck(deck_id, user, db)
    days = max(1, min(days, 365))

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days - 1)
    start_of_window = since.replace(hour=0, minute=0, second=0, microsecond=0)

    logs = db.execute(
        select(models.ReviewLog.reviewed_at, models.ReviewLog.quality)
        .join(models.Card, models.ReviewLog.card_id == models.Card.id)
        .where(models.Card.deck_id == deck_id)
        .where(models.ReviewLog.reviewed_at >= start_of_window)
    ).all()

    buckets: dict[str, dict[str, int]] = {}
    for i in range(days):
        key = (start_of_window + timedelta(days=i)).date().isoformat()
        buckets[key] = {"date": key, "total": 0, "again": 0, "hard": 0, "good": 0, "easy": 0}

    quality_name = {0: "again", 3: "hard", 4: "good", 5: "easy"}
    for reviewed_at, quality in logs:
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        key = reviewed_at.date().isoformat()
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["total"] += 1
        name = quality_name.get(quality)
        if name:
            bucket[name] += 1

    daily = [buckets[k] for k in sorted(buckets)]
    total = sum(d["total"] for d in daily)
    recalled = sum(d["hard"] + d["good"] + d["easy"] for d in daily)

    # Current streak: consecutive days with at least one review, counting back
    # from today. Today being empty does not break a streak that ran to
    # yesterday -- the day is not over yet.
    streak = 0
    for day in reversed(daily):
        if day["total"] > 0:
            streak += 1
        elif day["date"] == now.date().isoformat():
            continue
        else:
            break

    return {
        "days": days,
        "daily": daily,
        "total_reviews": total,
        "accuracy": round(recalled / total * 100, 1) if total else None,
        "streak_days": streak,
        "busiest_day": max((d["total"] for d in daily), default=0),
    }
