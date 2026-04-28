"""Application configuration loaded from environment."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'flashcards.db'}")
# Render (and some other hosts) provide a postgres:// URL, but SQLAlchemy 2.x
# dropped support for the "postgres" dialect alias — only "postgresql" works.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# --- LLM providers ---------------------------------------------------------
# We support three providers. The first one with a key set wins.
# Order: explicit LLM_PROVIDER env var > Groq > Gemini > Anthropic > heuristic.

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")

# Optional override. Values: groq | gemini | anthropic | heuristic
LLM_PROVIDER_OVERRIDE = os.getenv("LLM_PROVIDER", "").strip().lower() or None


def active_provider() -> str:
    """Return which provider the app should use right now."""
    if LLM_PROVIDER_OVERRIDE:
        return LLM_PROVIDER_OVERRIDE
    if GROQ_API_KEY:
        return "groq"
    if GEMINI_API_KEY:
        return "gemini"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return "heuristic"


def has_llm() -> bool:
    """Whether we have credentials to call any LLM provider."""
    return active_provider() != "heuristic"


# --- Generation tuning -----------------------------------------------------
MAX_CARDS_PER_CHUNK = int(os.getenv("MAX_CARDS_PER_CHUNK", "8"))
CHUNK_TARGET_CHARS = int(os.getenv("CHUNK_TARGET_CHARS", "3000"))
MAX_TOTAL_CARDS = int(os.getenv("MAX_TOTAL_CARDS", "40"))

# --- PDF limits (keep within Render free-tier resources) --------------------
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "50"))
MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", "10"))

# --- Auth -----------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")
SESSION_COOKIE_NAME = "recall_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# --- App ------------------------------------------------------------------
APP_NAME = "Recall"
APP_TAGLINE = "Turn any PDF into a practice-ready deck"
