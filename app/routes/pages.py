"""HTML page routes (server-rendered with Jinja2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..stats import compute_deck_stats

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    decks = db.execute(
        select(models.Deck).order_by(models.Deck.updated_at.desc())
    ).scalars().all()
    deck_views = []
    for d in decks:
        deck_views.append({
            "deck": d,
            "stats": compute_deck_stats(db, d.id),
        })
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": config.APP_NAME,
            "app_tagline": config.APP_TAGLINE,
            "decks": deck_views,
            "has_llm": config.has_llm(),
            "provider": config.active_provider(),
        },
    )


@router.get("/decks/{deck_id}", response_class=HTMLResponse)
def deck_page(deck_id: int, request: Request, db: Session = Depends(get_db)):
    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    stats = compute_deck_stats(db, deck.id)
    return templates.TemplateResponse(
        request,
        "deck.html",
        {
            "app_name": config.APP_NAME,
            "deck": deck,
            "stats": stats,
        },
    )


@router.get("/decks/{deck_id}/study", response_class=HTMLResponse)
def study_page(deck_id: int, request: Request, db: Session = Depends(get_db)):
    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    stats = compute_deck_stats(db, deck.id)
    return templates.TemplateResponse(
        request,
        "study.html",
        {
            "app_name": config.APP_NAME,
            "deck": deck,
            "stats": stats,
        },
    )
