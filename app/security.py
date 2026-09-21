"""Abuse limiting and hardened response headers."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from . import config


# ---------------------------------------------------------------------------
#  Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Fixed-memory sliding-window limiter.

    Deliberately in-process: this app runs as a single uvicorn worker, and an
    in-memory counter needs no extra infrastructure. It therefore resets on
    restart and does not coordinate across replicas -- if this is ever scaled
    out, move the counter to Redis or the database.
    """

    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._hits[key]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return len(self._prune(key, now)) >= self.attempts

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)
            # Stop unbounded growth from a spray of distinct keys.
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v][:5_000]:
                    del self._hits[stale]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        """Forget every recorded attempt (used by the security tests)."""
        with self._lock:
            self._hits.clear()

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            if not bucket:
                return 0
            return max(1, int(self.window - (now - bucket[0])))


auth_limiter = RateLimiter(
    attempts=config.AUTH_RATE_LIMIT_ATTEMPTS,
    window_seconds=config.AUTH_RATE_LIMIT_WINDOW,
)

# Upload is the one endpoint where a single authenticated request causes PDF
# parsing, several LLM calls and billable token spend.
upload_limiter = RateLimiter(
    attempts=config.UPLOAD_RATE_LIMIT,
    window_seconds=config.UPLOAD_RATE_WINDOW,
)


def client_ip(request: Request) -> str:
    """Best-available client address, resistant to header spoofing.

    X-Forwarded-For is appended to by each proxy, so it reads
    ``<client>, <proxy1>, <proxy2>``. Everything left of the last
    TRUSTED_PROXY_HOPS entries is attacker-controlled: a caller can simply send
    their own X-Forwarded-For and it lands at the front. Taking the left-most
    entry therefore let anyone defeat rate limiting by rotating the header, so
    we count in from the RIGHT instead, and ignore the header entirely when no
    proxy is configured.
    """
    peer = request.client.host if request.client else "unknown"
    hops = config.TRUSTED_PROXY_HOPS
    if hops <= 0:
        return peer

    raw = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return peer
    # parts[-hops] is the address the nearest trusted proxy observed.
    idx = len(parts) - hops
    return parts[idx] if 0 <= idx < len(parts) else peer


def client_key(request: Request, suffix: str = "") -> str:
    """Rate-limit key for the caller's network origin."""
    ip = client_ip(request)
    return f"{ip}:{suffix}" if suffix else ip


def account_key(identifier: str, suffix: str = "") -> str:
    """Rate-limit key for a targeted account.

    IP-based limits alone do not stop a distributed or proxy-rotated attack on
    one account, so failed logins are counted per-email as well.
    """
    return f"account:{identifier.strip().lower()}:{suffix}"


# ---------------------------------------------------------------------------
#  Response headers
# ---------------------------------------------------------------------------

# The app loads Tailwind and Alpine from CDNs and configures Tailwind from an
# inline <script>, and Alpine compiles its expressions with new Function().
# That forces 'unsafe-inline' and 'unsafe-eval' on script-src, so this CSP is
# not an XSS backstop. What it does buy is real: script and style sources are
# pinned to an allowlist, the page cannot be framed, forms cannot post
# off-site, and plugins/objects are blocked outright.
CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'self' https://huggingface.co https://*.huggingface.co https://*.hf.space",
    "form-action 'self'",
    "img-src 'self' data:",
    "font-src 'self' https://fonts.gstatic.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
    "connect-src 'self'",
])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        # X-Frame-Options is omitted in favor of CSP frame-ancestors, which allows
        # embedding within Hugging Face Spaces (https://huggingface.co) while blocking all others.
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        # Anything rendered for a signed-in user is per-user data. Without this
        # a shared proxy or the browser back-button cache can serve one user's
        # decks to the next person on the machine.
        if request.cookies.get(config.SESSION_COOKIE_NAME):
            headers.setdefault("Cache-Control", "no-store, private")

        if _https(request):
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _https(request: Request) -> bool:
    setting = config.ENABLE_HSTS
    if setting in {"0", "false", "no", "off"}:
        return False
    if setting in {"1", "true", "yes", "on"}:
        return True
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (forwarded or request.url.scheme) == "https"
