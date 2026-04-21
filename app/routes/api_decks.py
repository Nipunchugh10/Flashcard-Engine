"""Deck API endpoints (JSON)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..auth import get_current_user
from ..database import get_db
from ..flashcard_generator import generate_cards_for_chunks
from ..pdf_processor import extract_pdf
from ..schemas import DeckOut, DeckStats, RenameDeckIn
from ..stats import compute_deck_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decks", tags=["decks"])


def _serialize_deck(deck: models.Deck, db: Session) -> DeckOut:
    stats = compute_deck_stats(db, deck.id)
    return DeckOut(
        id=deck.id,
        name=deck.name,
        description=deck.description,
        source_filename=deck.source_filename,
        source_pages=deck.source_pages,
        created_at=deck.created_at,
        updated_at=deck.updated_at,
        stats=stats,
    )


def _get_user_deck(deck_id: int, user: models.User, db: Session) -> models.Deck:
    """Fetch a deck and verify it belongs to the user."""
    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    if deck.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return deck


@router.get("", response_model=list[DeckOut])
def list_decks(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    decks = db.execute(
        select(models.Deck)
        .where(models.Deck.user_id == user.id)
        .order_by(models.Deck.updated_at.desc())
    ).scalars().all()
    return [_serialize_deck(d, db) for d in decks]


@router.get("/{deck_id}", response_model=DeckOut)
def get_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    deck = _get_user_deck(deck_id, user, db)
    return _serialize_deck(deck, db)


@router.post("/upload", response_model=DeckOut, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Upload a PDF, extract it, generate cards, and create a deck."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Persist upload to disk with a unique name (avoid collisions / path tricks).
    safe_name = f"{uuid.uuid4().hex}.pdf"
    dest = config.UPLOAD_DIR / safe_name
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > 25 * 1024 * 1024:  # 25 MB
        raise HTTPException(status_code=413, detail="PDF too large (max 25 MB).")

    dest.write_bytes(content)

    # Extract + chunk
    try:
        extract = extract_pdf(dest)
    except Exception as e:
        logger.exception("PDF extraction failed")
        _safe_unlink(dest)
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    if not extract.chunks:
        _safe_unlink(dest)
        raise HTTPException(
            status_code=400,
            detail="PDF appears empty or contains only images. Try a text-based PDF.",
        )

    # Generate cards
    try:
        generated = generate_cards_for_chunks(extract.chunks)
    except Exception as e:
        logger.exception("Card generation failed")
        _safe_unlink(dest)
        raise HTTPException(status_code=500, detail=f"Card generation failed: {e}")

    if not generated:
        _safe_unlink(dest)
        raise HTTPException(
            status_code=500,
            detail="Couldn't generate any cards from this PDF.",
        )

    # Create deck + cards in DB
    deck_name = (name or "").strip() or _derive_deck_name(file.filename)
    deck = models.Deck(
        user_id=user.id,
        name=deck_name[:200],
        description=f"Generated from {file.filename}",
        source_filename=file.filename,
        source_pages=extract.page_count,
    )
    db.add(deck)
    db.flush()

    for g in generated:
        db.add(
            models.Card(
                deck_id=deck.id,
                front=g.front,
                back=g.back,
                card_type=g.card_type,
                source_excerpt=g.source_excerpt,
                tags=",".join(g.tags) if g.tags else None,
            )
        )

    db.commit()
    db.refresh(deck)
    return _serialize_deck(deck, db)


@router.patch("/{deck_id}", response_model=DeckOut)
def rename_deck(
    deck_id: int,
    payload: RenameDeckIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    deck = _get_user_deck(deck_id, user, db)
    deck.name = payload.name.strip()
    if payload.description is not None:
        deck.description = payload.description
    db.commit()
    db.refresh(deck)
    return _serialize_deck(deck, db)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    deck = _get_user_deck(deck_id, user, db)
    db.delete(deck)
    db.commit()
    return None


def _derive_deck_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Untitled Deck"


def _safe_unlink(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass
