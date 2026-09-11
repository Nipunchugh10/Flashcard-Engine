"""Authentication helpers: password hashing, session cookies, FastAPI deps."""
from __future__ import annotations

from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import config, models
from .database import get_db

_signer = URLSafeTimedSerializer(config.SECRET_KEY)

# A real bcrypt hash of a throwaway password. When a login names an account
# that does not exist we verify against this instead of returning early, so a
# failed login costs the same time either way and cannot be used to discover
# which email addresses are registered.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalisation-placeholder", bcrypt.gensalt())


# ---------------------------------------------------------------------------
#  Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    # bcrypt silently truncates at 72 bytes; reject rather than accept a
    # password whose tail is ignored.
    return bcrypt.hashpw(_encode_password(plain), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode_password(plain), hashed.encode())
    except ValueError:
        return False


def _encode_password(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("password exceeds bcrypt's 72-byte limit")
    return encoded


def verify_password_dummy() -> None:
    """Burn the same time a real bcrypt check would, for unknown accounts."""
    bcrypt.checkpw(b"timing-equalisation-placeholder", _DUMMY_HASH)


# ---------------------------------------------------------------------------
#  Session cookie helpers
# ---------------------------------------------------------------------------

def create_session_token(user: models.User) -> str:
    """Bind the token to the user's current session epoch so logout can void it."""
    return _signer.dumps({"uid": user.id, "ep": user.session_epoch})


def decode_session_token(token: str) -> Optional[tuple[int, int]]:
    """Return (user_id, epoch) for a valid token, else None."""
    try:
        data = _signer.loads(token, max_age=config.SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    uid, epoch = data.get("uid"), data.get("ep")
    if not isinstance(uid, int) or not isinstance(epoch, int):
        return None
    return uid, epoch


def _use_secure_cookie(request: Request) -> bool:
    setting = config.SESSION_COOKIE_SECURE
    if setting in {"1", "true", "yes", "on"}:
        return True
    if setting in {"0", "false", "no", "off"}:
        return False
    # "auto": mirror the scheme the request arrived on. Behind a proxy that
    # terminates TLS (Hugging Face, Render), honour the forwarded scheme.
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (forwarded or request.url.scheme) == "https"


def set_session_cookie(response: Response, user: models.User, request: Request) -> Response:
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=create_session_token(user),
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_use_secure_cookie(request),
        path="/",
    )
    return response


def clear_session_cookie(response: Response, request: Request) -> Response:
    response.delete_cookie(
        key=config.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_use_secure_cookie(request),
    )
    return response


def invalidate_sessions(user: models.User, db: Session) -> None:
    """Void every token already issued to this user."""
    user.session_epoch = (user.session_epoch or 0) + 1
    db.commit()


# ---------------------------------------------------------------------------
#  FastAPI dependencies
# ---------------------------------------------------------------------------

def _get_user_from_request(request: Request, db: Session) -> Optional[models.User]:
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        return None
    decoded = decode_session_token(token)
    if decoded is None:
        return None
    user_id, epoch = decoded
    user = db.get(models.User, user_id)
    if user is None:
        return None
    # Reject tokens issued before the user's most recent logout.
    if (user.session_epoch or 0) != epoch:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Dependency: the logged-in user, or 401."""
    user = _get_user_from_request(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    """Dependency: the logged-in user, or None (no error)."""
    return _get_user_from_request(request, db)
