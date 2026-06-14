"""Read helpers for the API. Latest-batch queries over the snapshot tables."""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AccountSnapshot,
    Execution,
    MarketSnapshot,
    PositionSnapshot,
    SignalHistory,
)


async def latest_positions(db: AsyncSession, account_id: str) -> list[PositionSnapshot]:
    """Rows from the most recent positions batch with a non-zero position."""
    max_ts = (
        select(PositionSnapshot.snapshot_ts)
        .where(PositionSnapshot.account_id == account_id)
        .order_by(desc(PositionSnapshot.snapshot_ts))
        .limit(1)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(PositionSnapshot)
        .where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.snapshot_ts == max_ts,
            PositionSnapshot.position != 0,
        )
        .order_by(PositionSnapshot.symbol)
    )
    return list(rows.scalars().all())


async def latest_account(db: AsyncSession, account_id: str) -> AccountSnapshot | None:
    rows = await db.execute(
        select(AccountSnapshot)
        .where(AccountSnapshot.account_id == account_id)
        .order_by(desc(AccountSnapshot.snapshot_ts))
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def recent_trades(
    db: AsyncSession, account_id: str, limit: int = 100
) -> list[Execution]:
    rows = await db.execute(
        select(Execution)
        .where(Execution.account_id == account_id)
        .order_by(desc(Execution.exec_time))
        .limit(limit)
    )
    return list(rows.scalars().all())


async def latest_market(db: AsyncSession) -> list[MarketSnapshot]:
    """Most recent market snapshot per underlying (Postgres DISTINCT ON)."""
    rows = await db.execute(
        select(MarketSnapshot)
        .distinct(MarketSnapshot.conid)
        .order_by(MarketSnapshot.conid, desc(MarketSnapshot.snapshot_ts))
    )
    return list(rows.scalars().all())


async def latest_signals(db: AsyncSession) -> list[SignalHistory]:
    rows = await db.execute(
        select(SignalHistory)
        .distinct(SignalHistory.underlying_conid)
        .order_by(SignalHistory.underlying_conid, desc(SignalHistory.ts))
    )
    return list(rows.scalars().all())


async def signal_series(
    db: AsyncSession, conid: int, limit: int = 500
) -> list[SignalHistory]:
    rows = await db.execute(
        select(SignalHistory)
        .where(SignalHistory.underlying_conid == conid)
        .order_by(desc(SignalHistory.ts))
        .limit(limit)
    )
    out = list(rows.scalars().all())
    out.reverse()
    return out
