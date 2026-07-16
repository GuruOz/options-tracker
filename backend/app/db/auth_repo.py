"""Read/write helpers for auth_sessions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession


async def create_session(
    db: AsyncSession, token_hash: str, csrf_token: str, ttl_hours: int, client: str | None
) -> AuthSession:
    row = AuthSession(
        token_hash=token_hash,
        csrf_token=csrf_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        client=client,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_session_by_hash(db: AsyncSession, token_hash: str) -> AuthSession | None:
    rows = await db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash))
    return rows.scalar_one_or_none()


async def delete_session(db: AsyncSession, token_hash: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
    await db.commit()


async def purge_expired(db: AsyncSession) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.expires_at < datetime.now(timezone.utc)))
    await db.commit()
