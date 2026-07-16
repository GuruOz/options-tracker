"""Single shared-login authentication: login, logout, me.

`public_router` (login) is mounted unauthenticated; `router` (logout, me) sits
behind `require_auth` like the rest of the API — see app/api/__init__.py.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import (
    hash_token,
    login_tracker,
    new_csrf_token,
    new_session_token,
    verify_password,
)
from app.db import auth_repo
from app.db.base import get_session

log = get_logger("auth")
settings = get_settings()

public_router = APIRouter(tags=["auth"])
router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@public_router.post("/auth/login")
async def login(
    body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> dict:
    ip = _client_ip(request)

    if login_tracker.is_locked(ip):
        raise HTTPException(status_code=429, detail="Too many failed logins. Try again later.")

    if not settings.auth_password_hash:
        raise HTTPException(status_code=503, detail="Login is not configured (AUTH_PASSWORD_HASH is unset).")

    # Always run verify_password, even on a username mismatch, so response
    # timing doesn't leak whether the username was correct.
    password_ok = verify_password(settings.auth_password_hash, body.password)
    username_ok = secrets.compare_digest(body.username, settings.auth_username)

    if not (username_ok and password_ok):
        login_tracker.record_failure(ip)
        log.warning("auth_login_failed", client_ip=ip)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    login_tracker.reset(ip)
    await auth_repo.purge_expired(db)

    token = new_session_token()
    csrf_token = new_csrf_token()
    client = (request.headers.get("user-agent") or "")[:255]
    await auth_repo.create_session(
        db, hash_token(token), csrf_token, settings.auth_session_ttl_hours, client
    )
    log.info("auth_login_success", client_ip=ip)

    max_age = settings.auth_session_ttl_hours * 3600
    response.set_cookie(
        "session", token, httponly=True, secure=settings.auth_cookie_secure,
        samesite="strict", path="/", max_age=max_age,
    )
    response.set_cookie(
        "csrf_token", csrf_token, httponly=False, secure=settings.auth_cookie_secure,
        samesite="strict", path="/", max_age=max_age,
    )
    return {"status": "ok"}


@router.post("/auth/logout")
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> dict:
    token = request.cookies.get("session")
    if token:
        await auth_repo.delete_session(db, hash_token(token))
    response.delete_cookie("session", path="/")
    response.delete_cookie("csrf_token", path="/")
    log.info("auth_logout")
    return {"status": "ok"}


@router.get("/auth/me")
async def me() -> dict:
    return {"authenticated": True, "username": settings.auth_username}
