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
    set_session_cookie,
    verify_password,
)
from ..database import get_db

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    user: models.User | None = Depends(get_optional_user),
):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": config.APP_NAME, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.execute(
        select(models.User).where(models.User.email == email)
    ).scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"app_name": config.APP_NAME, "error": "Invalid email or password."},
            status_code=400,
        )

    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user.id)


@router.get("/signup", response_class=HTMLResponse)
def signup_page(
    request: Request,
    user: models.User | None = Depends(get_optional_user),
):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"app_name": config.APP_NAME, "error": None},
    )


@router.post("/signup", response_class=HTMLResponse)
def signup_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()
    email = email.strip().lower()

    # Validation
    errors = []
    if len(username) < 2:
        errors.append("Username must be at least 2 characters.")
    if "@" not in email or "." not in email:
        errors.append("Please enter a valid email address.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if password != confirm_password:
        errors.append("Passwords do not match.")

    # Check existing email
    if not errors:
        existing = db.execute(
            select(models.User).where(models.User.email == email)
        ).scalar_one_or_none()
        if existing:
            errors.append("An account with this email already exists.")

    if errors:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {
                "app_name": config.APP_NAME,
                "error": " ".join(errors),
                "form_username": username,
                "form_email": email,
            },
            status_code=400,
        )

    user = models.User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/", status_code=302)
    return set_session_cookie(response, user.id)


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    return clear_session_cookie(response)
