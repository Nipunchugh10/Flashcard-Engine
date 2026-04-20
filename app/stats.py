"""Small helper functions used across routes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .schemas import DeckStats


def compute_deck_stats(db: Session, deck_id: int) -> DeckStats:
    now = datetime.now(timezone.utc)

    rows = db.execute(
        select(models.Card.status, func.count(models.Card.id)).where(
            models.Card.deck_id == deck_id
        ).group_by(models.Card.status)
    ).all()

    counts = {status: count for status, count in rows}
    total = sum(counts.values())

    due_now = db.execute(
        select(func.count(models.Card.id)).where(
            models.Card.deck_id == deck_id,
            models.Card.next_review <= now,
        )
    ).scalar_one()

    return DeckStats(
        total=total,
        new=counts.get("new", 0),
        learning=counts.get("learning", 0),
        review=counts.get("review", 0),
        mastered=counts.get("mastered", 0),
        due_now=int(due_now or 0),
    )
