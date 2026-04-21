"""Authentication helpers: password hashing, session cookies, FastAPI deps."""
from __future__ import annotations

from typing import Optional

import bcrypt
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import config, models
from .database import get_db

_signer = URLSafeTimedSerializer(config.SECRET_KEY)


# ---------------------------------------------------------------------------
#  Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
#  Session cookie helpers
# ---------------------------------------------------------------------------

def create_session_token(user_id: int) -> str:
    return _signer.dumps({"uid": user_id})


def decode_session_token(token: str) -> Optional[int]:
    try:
        data = _signer.loads(token, max_age=config.SESSION_MAX_AGE)
        return data.get("uid")
    except (BadSignature, Exception):
        return None


def set_session_cookie(response: RedirectResponse, user_id: int) -> RedirectResponse:
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=create_session_token(user_id),
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


def clear_session_cookie(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(key=config.SESSION_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
#  FastAPI dependencies
# ---------------------------------------------------------------------------

def _get_user_from_request(request: Request, db: Session) -> Optional[models.User]:
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = decode_session_token(token)
    if not user_id:
        return None
    return db.get(models.User, user_id)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Dependency: returns the logged-in user or redirects to /login."""
    user = _get_user_from_request(request, db)
    if not user:
        raise _login_redirect()
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    """Dependency: returns the logged-in user or None (no redirect)."""
    return _get_user_from_request(request, db)


def _login_redirect():
    from fastapi import HTTPException
    # For API routes we raise 401; for page routes the router will catch this.
    raise HTTPException(status_code=401, detail="Not authenticated")
