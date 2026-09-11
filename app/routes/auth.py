"""Authentication routes: login, signup, logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, models
from ..auth import (
    clear_session_cookie,
    get_optional_user,
    hash_password,
    invalidate_sessions,
    set_session_cookie,
    verify_password,
    verify_password_dummy,
)
from ..database import get_db
from ..security import auth_limiter, client_key

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")

# Deliberately identical for "no such account" and "wrong password", so the
# response body cannot be used to discover which emails are registered.
_BAD_CREDENTIALS = "Invalid email or password."
_TOO_MANY = "Too many attempts. Please wait a few minutes and try again."


def _render(request: Request, template: str, error: str | None, status: int = 400, **extra):
    return templates.TemplateResponse(
        request, template,
        {"app_name": config.APP_NAME, "error": error, **extra},
        status_code=status,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: models.User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=302)
    return _render(request, "login.html", None, status=200)


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    key = client_key(request, "login")
    if auth_limiter.is_limited(key):
        return _render(request, "login.html", _TOO_MANY, status=429)

    email = email.strip().lower()
    user = db.execute(
        select(models.User).where(models.User.email == email)
    ).scalar_one_or_none()

    if user is None:
        # Spend the same time a real bcrypt comparison costs, otherwise the
        # response time reveals whether the account exists.
        verify_password_dummy()
        auth_limiter.record_failure(key)
        return _render(request, "login.html", _BAD_CREDENTIALS)

    if not verify_password(password, user.password_hash):
        auth_limiter.record_failure(key)
        return _render(request, "login.html", _BAD_CREDENTIALS)

    auth_limiter.reset(key)
    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user, request)


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, user: models.User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=302)
    return _render(request, "signup.html", None, status=200)


@router.post("/signup", response_class=HTMLResponse)
def signup_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    key = client_key(request, "signup")
    if auth_limiter.is_limited(key):
        return _render(request, "signup.html", _TOO_MANY, status=429)

    username = username.strip()
    email = email.strip().lower()

    errors = []
    if len(username) < 2:
        errors.append("Username must be at least 2 characters.")
    if len(username) > 100:
        errors.append("Username must be 100 characters or fewer.")
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 255:
        errors.append("Please enter a valid email address.")
    if len(password) < config.MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > 72:
        errors.append("Password must be 72 bytes or fewer.")
    if password != confirm_password:
        errors.append("Passwords do not match.")

    if not errors:
        existing = db.execute(
            select(models.User).where(models.User.email == email)
        ).scalar_one_or_none()
        if existing:
            errors.append("An account with this email already exists.")

    if errors:
        auth_limiter.record_failure(key)
        return _render(
            request, "signup.html", " ".join(errors),
            form_username=username, form_email=email,
        )

    user = models.User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    auth_limiter.reset(key)
    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user, request)


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_optional_user),
):
    # Bump the session epoch so the token just discarded -- and any copy of it
    # taken from a shared machine or a proxy log -- stops validating.
    if user is not None:
        invalidate_sessions(user, db)
    response = RedirectResponse("/login", status_code=302)
    return clear_session_cookie(response, request)
