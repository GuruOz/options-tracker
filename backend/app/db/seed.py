"""Idempotent seeding of the single-row global settings record."""
from __future__ import annotations

from app.analytics.defaults import DEFAULT_SETTINGS
from app.db.base import AsyncSessionLocal
from app.db.models import Setting

# `underlyings` and `alerts` are per-account (see `AccountSetting`); the global
# row only carries what every account shares.
_PER_ACCOUNT_KEYS = ("underlyings", "alerts")


async def seed_settings() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.get(Setting, 1)
        if existing is None:
            session.add(Setting(
                id=1,
                data={
                    k: v for k, v in DEFAULT_SETTINGS.items()
                    if k not in _PER_ACCOUNT_KEYS
                },
            ))
            await session.commit()
