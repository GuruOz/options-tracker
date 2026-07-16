"""Shared route dependencies — chiefly, which account(s) a request is about.

Every account-scoped endpoint takes `?account_id=`: a specific IBKR account id,
or the literal `all` for the combined household view. The frontend always sends
it explicitly; the omitted case is a convenience fallback for a bare curl.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import auth_repo, repo
from app.db.base import get_session
from app.core.security import hash_token

ALL = "all"

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


async def require_auth(request: Request, db: AsyncSession = Depends(get_session)) -> None:
    """Session-cookie auth + CSRF check for mutating requests.

    Applied to every /api route except /api/health and /api/auth/login — see
    the public_router/api_router split in app/api/__init__.py.
    """
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    row = await auth_repo.get_session_by_hash(db, hash_token(token))
    if row is None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired.")
    if request.method in _MUTATING:
        header = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(header, row.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")
    request.state.auth_session = row


async def account_scope(
    account_id: str | None = Query(
        None, description="An IBKR account id, or 'all' for the combined view."
    ),
    db: AsyncSession = Depends(get_session),
) -> list[str]:
    """Resolve `?account_id=` to the list of accounts a request covers.

    An unknown id resolves to an empty list rather than a 404: the account may
    simply not have logged in yet, and every consumer already renders "no data"
    for an empty scope.
    """
    if account_id == ALL:
        return await repo.all_account_ids(db)
    if account_id:
        return [account_id]
    return await repo.all_account_ids(db)


async def single_account(
    account_id: str | None = Query(
        None, description="An IBKR account id. 'all' is not valid here."
    ),
    db: AsyncSession = Depends(get_session),
) -> str:
    """Resolve `?account_id=` for endpoints that must write to exactly one account.

    A write can't be aimed at the combined view — there is no household account
    to save an income adjustment or a watchlist entry against.
    """
    if account_id == ALL:
        raise HTTPException(
            status_code=400,
            detail="Pick a specific account — 'all' is a read-only combined view.",
        )
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required.")
    if await repo.account_by_id(db, account_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown account '{account_id}'.")
    return account_id
