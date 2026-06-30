"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .database import init_db
from .routes import api_cards, api_decks, api_study, auth, pages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    provider = config.active_provider()
    model_label = {
        "gemini": config.GEMINI_MODEL,
        "anthropic": config.ANTHROPIC_MODEL,
        "heuristic": "regex fallback",
    }.get(provider, "unknown")
    logging.getLogger(__name__).info(
        "Startup complete. Provider=%s, model=%s",
        provider,
        model_label,
    )
    yield
    # --- shutdown (nothing to tear down) ---


app = FastAPI(
    title=config.APP_NAME,
    description="Turn any PDF into a practice-ready flashcard deck with spaced repetition.",
    version="1.0.0",
    lifespan=lifespan,
)


# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# HTML pages
app.include_router(pages.router)

# Auth (login, signup, logout)
app.include_router(auth.router)

# JSON APIs
app.include_router(api_decks.router)
app.include_router(api_cards.router)
app.include_router(api_study.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
