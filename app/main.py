"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .database import init_db
from .routes import api_cards, api_decks, api_study, auth, pages
from .security import SecurityHeadersMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    log = logging.getLogger(__name__)
    if config.SECRET_KEY_WARNING:
        log.critical(
            "=" * 72 + "\n"
            "  INSECURE CONFIGURATION: %s.\n"
            "  A random key has been generated for this process instead, so\n"
            "  session cookies CANNOT be forged -- but every user will be\n"
            "  logged out whenever the app restarts.\n"
            "  Fix it by setting a strong SECRET_KEY, for example:\n"
            "      python3 -c 'import secrets; print(secrets.token_urlsafe(48))'\n"
            + "=" * 72,
            config.SECRET_KEY_WARNING,
        )
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


# Security headers on every response (CSP, nosniff, frame-ancestors, HSTS).
app.add_middleware(SecurityHeadersMiddleware)

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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Browsers request /favicon.ico directly, without reading the HTML."""
    return FileResponse("static/favicon.ico", media_type="image/x-icon")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
