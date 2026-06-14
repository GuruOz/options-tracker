"""Idempotent seeding of the single-row settings record."""
from __future__ import annotations

from app.analytics.defaults import DEFAULT_SETTINGS
from app.db.base import AsyncSessionLocal
from app.db.models import Setting


async def seed_settings() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.get(Setting, 1)
        if existing is None:
            session.add(Setting(id=1, data=DEFAULT_SETTINGS))
            await session.commit()
