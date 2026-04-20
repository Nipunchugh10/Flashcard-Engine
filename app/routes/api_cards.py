"""Card CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import CardEditIn, CardOut

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("", response_model=list[CardOut])
def list_cards(
    deck_id: int = Query(...),
    search: str | None = Query(None),
    status_filter: str | None = Query(None, pattern="^(new|learning|review|mastered|all)$"),
    db: Session = Depends(get_db),
):
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
def update_card(card_id: int, payload: CardEditIn, db: Session = Depends(get_db)):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.front = payload.front.strip()
    card.back = payload.back.strip()
    db.commit()
    db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(card_id: int, db: Session = Depends(get_db)):
    card = db.get(models.Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(card)
    db.commit()
    return None
