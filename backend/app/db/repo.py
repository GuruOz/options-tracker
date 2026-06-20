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


async def account_series(
    db: AsyncSession, account_id: str, limit: int = 365
) -> list[dict]:
    """Net-liquidation equity curve (oldest -> newest) for the risk panel.

    Returns up to `limit` of the most recent account *snapshots* (one per poll,
    not per day), reversed to chronological order for the sparkline.
    """
    rows = await db.execute(
        select(AccountSnapshot.snapshot_ts, AccountSnapshot.net_liquidation)
        .where(AccountSnapshot.account_id == account_id)
        .order_by(desc(AccountSnapshot.snapshot_ts))
        .limit(limit)
    )
    out = [{"ts": ts, "net_liquidation": nl} for ts, nl in rows.all()]
    out.reverse()
    return out


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


async def all_option_trades(
    db: AsyncSession, account_id: str
) -> list[Execution]:
    """Every option execution, chronologically (oldest first)."""
    rows = await db.execute(
        select(Execution)
        .where(
            Execution.account_id == account_id,
            Execution.sec_type.in_(["OPT", "FOP", "WAR"]),
        )
        .order_by(Execution.exec_time)
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


async def open_roll_chains(db: AsyncSession, account_id: str) -> dict[int, str]:
    """Returns a dict mapping conid -> chain_id for all open roll chains."""
    from app.db.models import RollChain, RollChainLeg
    rows = await db.execute(
        select(RollChainLeg.conid, RollChain.chain_id)
        .join(RollChain, RollChain.chain_id == RollChainLeg.chain_id)
        .where(
            RollChain.account_id == account_id,
            RollChain.status == "open",
            RollChainLeg.conid.is_not(None)
        )
    )
    return {row.conid: row.chain_id for row in rows}


async def roll_chain_summaries(
    db: AsyncSession, account_id: str, *, status: str = "open"
) -> list[dict]:
    """Return chain summaries with cumulative credit.

    status: "open" (default), "closed", or "all".
    """
    from app.db.models import RollChain, RollChainLeg

    stmt = select(RollChain).where(
        RollChain.account_id == account_id,
    )
    if status == "open":
        stmt = stmt.where(RollChain.status == "open")
    elif status == "closed":
        stmt = stmt.where(RollChain.status == "closed")
    stmt = stmt.order_by(RollChain.opened_at.desc())

    rows = await db.execute(stmt)
    chains = list(rows.scalars().all())

    result = []
    for chain in chains:
        legs = await db.execute(
            select(RollChainLeg)
            .where(RollChainLeg.chain_id == chain.chain_id)
            .order_by(RollChainLeg.created_at)
        )
        leg_list = list(legs.scalars().all())
        result.append({
            "chain_id": chain.chain_id,
            "underlying_symbol": chain.underlying_symbol,
            "right": chain.right,
            "status": chain.status,
            "opened_at": chain.opened_at.isoformat() if chain.opened_at else None,
            "closed_at": chain.closed_at.isoformat() if chain.closed_at else None,
            "cumulative_credit": float(chain.cumulative_credit) if chain.cumulative_credit is not None else None,
            "leg_count": len(leg_list),
            "conids": [l.conid for l in leg_list if l.conid is not None],
        })
    return result
