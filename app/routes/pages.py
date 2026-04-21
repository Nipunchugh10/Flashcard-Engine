"""HTML page routes (server-rendered with Jinja2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..auth import _get_user_from_request
from ..database import get_db
from ..stats import compute_deck_stats

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = _get_user_from_request(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    decks = db.execute(
        select(models.Deck)
        .where(models.Deck.user_id == user.id)
        .order_by(models.Deck.updated_at.desc())
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
            "user": user,
        },
    )


@router.get("/decks/{deck_id}", response_class=HTMLResponse)
def deck_page(deck_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_user_from_request(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    if deck.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    stats = compute_deck_stats(db, deck.id)
    return templates.TemplateResponse(
        request,
        "deck.html",
        {
            "app_name": config.APP_NAME,
            "deck": deck,
            "stats": stats,
            "user": user,
        },
    )


@router.get("/decks/{deck_id}/study", response_class=HTMLResponse)
def study_page(deck_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_user_from_request(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    deck = db.get(models.Deck, deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    if deck.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    stats = compute_deck_stats(db, deck.id)
    return templates.TemplateResponse(
        request,
        "study.html",
        {
            "app_name": config.APP_NAME,
            "deck": deck,
            "stats": stats,
            "user": user,
        },
    )
