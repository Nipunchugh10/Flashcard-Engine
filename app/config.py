"""Application configuration loaded from environment."""
from __future__ import annotations

import os
import secrets
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
# We support two providers. The first one with a key set wins.
# Order: explicit LLM_PROVIDER env var > Gemini > Anthropic > heuristic.

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")

# Optional override. Values: gemini | anthropic | heuristic
LLM_PROVIDER_OVERRIDE = os.getenv("LLM_PROVIDER", "").strip().lower() or None


def active_provider() -> str:
    """Return which provider the app should use right now."""
    if LLM_PROVIDER_OVERRIDE:
        return LLM_PROVIDER_OVERRIDE
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
MAX_TOTAL_CARDS = int(os.getenv("MAX_TOTAL_CARDS", "70"))

# --- PDF limits (keep within Render free-tier resources) --------------------
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "100"))
MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", "10"))

# --- Auth -----------------------------------------------------------------
# The session cookie is a signed token, so anyone who knows SECRET_KEY can mint
# a valid session for ANY user id -- full account takeover without a password.
# Placeholder and short keys are therefore refused outright: we fall back to a
# random key so a misconfigured deploy is never trivially forgeable. The cost is
# that sessions do not survive a restart until a real key is configured, which
# SECRET_KEY_WARNING reports loudly at startup.
_PLACEHOLDER_SECRETS = {
    "",
    "dev-secret-change-me-in-production",
    "change-me-to-something-random",
    "recall-flashcard-engine-secret-key-2026",
    "secret",
    "secretkey",
    "changeme",
    "please-change-me",
    "your-secret-key-here",
}

MIN_SECRET_KEY_LENGTH = 32


def _resolve_secret_key() -> tuple[str, str | None]:
    """Return (key, warning). Never returns a guessable key."""
    raw = os.getenv("SECRET_KEY", "").strip()
    if not raw:
        return secrets.token_urlsafe(48), "SECRET_KEY is not set"
    if raw.lower() in _PLACEHOLDER_SECRETS:
        return secrets.token_urlsafe(48), "SECRET_KEY is a known placeholder value"
    if len(raw) < MIN_SECRET_KEY_LENGTH:
        return (
            secrets.token_urlsafe(48),
            f"SECRET_KEY is only {len(raw)} characters "
            f"(minimum {MIN_SECRET_KEY_LENGTH})",
        )
    return raw, None


SECRET_KEY, SECRET_KEY_WARNING = _resolve_secret_key()

SESSION_COOKIE_NAME = "recall_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# Send the session cookie only over HTTPS. "auto" decides per request from the
# request scheme, so local http://localhost development still works while a
# real deployment behind TLS gets a Secure cookie.
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "auto").strip().lower()

# --- Abuse limits ----------------------------------------------------------
# Failed login/signup attempts allowed per client within the window.
AUTH_RATE_LIMIT_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_ATTEMPTS", "10"))
AUTH_RATE_LIMIT_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_WINDOW", "300"))  # seconds

# Minimum password length accepted at signup.
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "8"))

# How many reverse proxies sit in front of this app. X-Forwarded-For is a
# client-supplied header that each proxy APPENDS to, so only the last N entries
# are trustworthy -- the left-most value is whatever the caller typed. Rate
# limiting keyed on the left-most entry is bypassed by rotating the header.
# 1 = one trusted proxy (Hugging Face, Render). 0 = no proxy, use the peer
# address and ignore X-Forwarded-For entirely.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))

# Outbound LLM call limits, so a slow or hung provider cannot pin worker threads.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))

# Uploads allowed per client per window. PDF parsing plus LLM calls is the most
# expensive thing an authenticated user can trigger, and it costs real money.
UPLOAD_RATE_LIMIT = int(os.getenv("UPLOAD_RATE_LIMIT", "10"))
UPLOAD_RATE_WINDOW = int(os.getenv("UPLOAD_RATE_WINDOW", "3600"))

# Emit HSTS. Only enable when the site is genuinely HTTPS-only.
ENABLE_HSTS = os.getenv("ENABLE_HSTS", "auto").strip().lower()

# --- App ------------------------------------------------------------------
APP_NAME = "Recall"
APP_TAGLINE = "Turn any PDF into a practice-ready deck"
