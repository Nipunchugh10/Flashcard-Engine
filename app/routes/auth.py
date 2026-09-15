"""Authentication routes: login, signup, logout."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from ..security import account_key, auth_limiter, client_ip, client_key

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")

# Deliberately identical for "no such account" and "wrong password", so the
# response body cannot be used to discover which emails are registered.
_BAD_CREDENTIALS = "Invalid email or password."
_TOO_MANY = "Too many attempts. Please wait a few minutes and try again."


def _render(request: Request, template: str, error: str | None, status: int = 400, **extra):
    return templates.TemplateResponse(
        request, template,
        {
            "app_name": config.APP_NAME,
            "error": error,
            # Drive the form's client-side hints from the same constant the
            # server validates against, so they cannot drift apart.
            "min_password_length": config.MIN_PASSWORD_LENGTH,
            **extra,
        },
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
    email = email.strip().lower()
    ip_key = client_key(request, "login")
    # Limit per source address AND per targeted account: an attacker behind
    # many addresses would otherwise get unlimited attempts against one user.
    acct_key = account_key(email, "login")

    if auth_limiter.is_limited(ip_key) or auth_limiter.is_limited(acct_key):
        log.warning("auth.login.throttled ip=%s email=%s", client_ip(request), email)
        return _render(request, "login.html", _TOO_MANY, status=429)

    user = db.execute(
        select(models.User).where(models.User.email == email)
    ).scalar_one_or_none()

    def _fail() -> None:
        auth_limiter.record_failure(ip_key)
        auth_limiter.record_failure(acct_key)
        log.warning("auth.login.failed ip=%s email=%s", client_ip(request), email)

    if user is None:
        # Spend the same time a real bcrypt comparison costs, otherwise the
        # response time reveals whether the account exists.
        verify_password_dummy()
        _fail()
        return _render(request, "login.html", _BAD_CREDENTIALS)

    if not verify_password(password, user.password_hash):
        _fail()
        return _render(request, "login.html", _BAD_CREDENTIALS)

    auth_limiter.reset(ip_key)
    auth_limiter.reset(acct_key)
    log.info("auth.login.ok ip=%s user_id=%s", client_ip(request), user.id)
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
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous signups for the same address both pass the check
        # above; the unique index stops the duplicate, but the raised error
        # would otherwise surface as a 500. Show the normal message instead.
        db.rollback()
        auth_limiter.record_failure(key)
        log.warning("auth.signup.duplicate_race email=%s", email)
        return _render(
            request, "signup.html", "An account with this email already exists.",
            form_username=username, form_email=email,
        )
    db.refresh(user)

    auth_limiter.reset(key)
    log.info("auth.signup.ok ip=%s user_id=%s", client_ip(request), user.id)
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
        log.info("auth.logout ip=%s user_id=%s", client_ip(request), user.id)
    response = RedirectResponse("/login", status_code=302)
    return clear_session_cookie(response, request)
