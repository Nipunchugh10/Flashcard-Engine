"""Deck API endpoints (JSON)."""
from __future__ import annotations

import gc
import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..flashcard_generator import generate_cards_for_chunks
from ..pdf_processor import extract_pdf
from ..schemas import DeckOut, DeckStats, RenameDeckIn
from ..stats import compute_deck_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decks", tags=["decks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_deck(deck: models.Deck, db: Session) -> DeckOut:
    stats = compute_deck_stats(db, deck.id)
    return DeckOut(
        id=deck.id,
        name=deck.name,
        description=deck.description,
        source_filename=deck.source_filename,
        source_pages=deck.source_pages,
        generation_status=deck.generation_status,
        generation_error=deck.generation_error,
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


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Status polling (used by the frontend during background generation)
# ---------------------------------------------------------------------------

class DeckStatusOut(BaseModel):
    generation_status: str
    generation_error: str | None = None
    stats: DeckStats


@router.get("/{deck_id}/status", response_model=DeckStatusOut)
def deck_status(
    deck_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Lightweight polling endpoint — the frontend calls this every 2s while
    a deck is being processed in the background."""
    deck = _get_user_deck(deck_id, user, db)
    stats = compute_deck_stats(db, deck.id)
    return DeckStatusOut(
        generation_status=deck.generation_status,
        generation_error=deck.generation_error,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Upload + background generation
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=DeckOut, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Upload a PDF, validate it, create a deck in 'processing' state, and
    kick off card generation in a background thread.  Returns immediately
    so the request never times out on Render's free tier."""

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    max_bytes = config.MAX_PDF_SIZE_MB * 1024 * 1024
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF too large (max {config.MAX_PDF_SIZE_MB} MB).",
        )

    # Persist upload to disk with a unique name.
    safe_name = f"{uuid.uuid4().hex}.pdf"
    dest = config.UPLOAD_DIR / safe_name
    dest.write_bytes(content)
    del content  # free upload buffer immediately

    # Create the deck in "processing" state and return instantly.
    deck_name = (name or "").strip() or _derive_deck_name(file.filename)
    deck = models.Deck(
        user_id=user.id,
        name=deck_name[:200],
        description=f"Generated from {file.filename}",
        source_filename=file.filename,
        generation_status="processing",
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)

    # Fire-and-forget background thread.
    thread = threading.Thread(
        target=_process_deck_background,
        args=(deck.id, dest),
        daemon=True,
        name=f"gen-deck-{deck.id}",
    )
    thread.start()

    return _serialize_deck(deck, db)


def _process_deck_background(deck_id: int, pdf_path: Path) -> None:
    """Run PDF extraction + LLM generation in a background thread.

    Uses its own DB session so it's fully independent of the request lifecycle.
    """
    db = SessionLocal()
    try:
        # Give the main request a moment to finish its commit if needed.
        deck = db.get(models.Deck, deck_id)
        if not deck:
            logger.error("Background: deck %d disappeared before processing", deck_id)
            return

        logger.info("Background: starting deck %d (%s)", deck_id, deck.name)

        # --- Step 1: Extract ---
        try:
            extract = extract_pdf(pdf_path)
        except Exception as e:
            logger.exception("Background: PDF extraction failed for deck %d", deck_id)
            deck.generation_status = "failed"
            deck.generation_error = f"Could not read PDF: {e}"
            db.commit()
            return

        if not extract.chunks:
            logger.warning("Background: deck %d has no text chunks", deck_id)
            deck.generation_status = "failed"
            deck.generation_error = (
                "PDF appears empty or contains only images. Try a text-based PDF."
            )
            db.commit()
            return

        deck.source_pages = extract.page_count
        db.commit() # Save page count early

        # --- Step 2: Generate ---
        try:
            generated = generate_cards_for_chunks(extract.chunks)
        except Exception as e:
            logger.exception("Background: Card generation failed for deck %d", deck_id)
            deck.generation_status = "failed"
            deck.generation_error = f"Card generation failed: {e}"
            db.commit()
            return

        if not generated:
            logger.warning("Background: deck %d generated 0 cards", deck_id)
            deck.generation_status = "failed"
            deck.generation_error = "Couldn't generate any cards from this PDF. Try a more text-dense document."
            db.commit()
            return

        # --- Step 3: Persist cards ---
        logger.info("Background: deck %d saving %d cards", deck_id, len(generated))
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

        deck.generation_status = "ready"
        deck.generation_error = None
        db.commit()
        logger.info(
            "Background: deck %d ready — %d cards generated", deck_id, len(generated)
        )

    except Exception:
        logger.exception("Background: unexpected error for deck %d", deck_id)
        try:
            db.rollback()
            deck = db.get(models.Deck, deck_id)
            if deck:
                deck.generation_status = "failed"
                deck.generation_error = "Unexpected server error during generation."
                db.commit()
        except Exception:
            logger.exception("Background: failed to save failure status for deck %d", deck_id)
    finally:
        db.close()
        _safe_unlink(pdf_path)
        gc.collect()


# ---------------------------------------------------------------------------
# Other CRUD
# ---------------------------------------------------------------------------

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
