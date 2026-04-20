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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, spaced_repetition
from ..database import get_db
from ..schemas import CardOut, RateCardIn
from ..stats import compute_deck_stats

router = APIRouter(prefix="/api/study", tags=["study"])

# Cap the number of new cards introduced in a single session.
NEW_CARDS_PER_SESSION = 20


@router.get("/{deck_id}/next")
def next_card(deck_id: int, db: Session = Depends(get_db)):
    """Return the next card to study, or {done: true} if none."""
    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")

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
def rate_card(card_id: int, payload: RateCardIn, db: Session = Depends(get_db)):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    new_state = spaced_repetition.apply_rating(
        rating=payload.rating,  # type: ignore[arg-type]
        ease_factor=card.ease_factor,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        lapses=card.lapses,
        reviews_count=card.reviews_count,
    )

    # Log this review.
    db.add(
        models.ReviewLog(
            card_id=card.id,
            quality=spaced_repetition.RATING_TO_QUALITY[payload.rating],
            interval_before=card.interval_days,
            interval_after=new_state.interval_days,
            ease_after=new_state.ease_factor,
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
