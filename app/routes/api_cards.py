"""Card CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..database import get_db
from ..schemas import CardEditIn, CardOut

router = APIRouter(prefix="/api/cards", tags=["cards"])


def _verify_card_ownership(card: models.Card, user: models.User, db: Session) -> None:
    """Verify that the card's deck belongs to the user."""
    deck = db.get(models.Deck, card.deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("", response_model=list[CardOut])
def list_cards(
    deck_id: int = Query(...),
    search: str | None = Query(None),
    status_filter: str | None = Query(None, pattern="^(new|learning|review|mastered|all)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Verify deck belongs to user
    deck = db.get(models.Deck, deck_id)
    if not deck or deck.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    stmt = select(models.Card).where(models.Card.deck_id == deck_id)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(models.Card.front.ilike(pattern), models.Card.back.ilike(pattern))
        )
    if status_filter and status_filter != "all":
        stmt = stmt.where(models.Card.status == status_filter)
    stmt = stmt.order_by(models.Card.id)
    cards = db.execute(stmt).scalars().all()
    return cards


@router.patch("/{card_id}", response_model=CardOut)
def update_card(
    card_id: int,
    payload: CardEditIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    _verify_card_ownership(card, user, db)
    card.front = payload.front.strip()
    card.back = payload.back.strip()
    db.commit()
    db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    _verify_card_ownership(card, user, db)
    db.delete(card)
    db.commit()
    return None
