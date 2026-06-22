"""Read helpers for the API. Latest-batch queries over the snapshot tables."""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rolls import _credit
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


async def all_executions(
    db: AsyncSession, account_id: str
) -> list[Execution]:
    """Every execution (all sec-types incl. STK), chronologically.

    Used by the diagnostics dump — assignments arrive as STK fills, so the
    options-only view can't reconcile a wheel against the Excel tracker.
    """
    rows = await db.execute(
        select(Execution)
        .where(Execution.account_id == account_id)
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


async def all_roll_chains(db: AsyncSession, account_id: str) -> list:
    """Every roll chain for an account (for income aggregation)."""
    from app.db.models import RollChain
    rows = await db.execute(
        select(RollChain).where(RollChain.account_id == account_id)
    )
    return list(rows.scalars().all())


async def income_adjustments(db: AsyncSession, account_id: str) -> list:
    """The per-month manual income overlay rows for an account."""
    from app.db.models import IncomeAdjustment
    rows = await db.execute(
        select(IncomeAdjustment)
        .where(IncomeAdjustment.account_id == account_id)
        .order_by(IncomeAdjustment.month)
    )
    return list(rows.scalars().all())


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


def _underlying_ticker(symbol: str | None) -> str | None:
    """Strip an option/OCC symbol down to its underlying ticker.

    'NVDA 260618P00216000' -> 'NVDA'; 'NVDA' -> 'NVDA'.
    """
    if not symbol:
        return None
    return symbol.strip().split()[0] or None


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
        # Pull each leg with its execution so we can derive a clean ticker +
        # strike for display ("NVDA 216P") rather than the raw OCC symbol.
        legs = await db.execute(
            select(RollChainLeg, Execution)
            .join(Execution, Execution.exec_id == RollChainLeg.exec_id, isouter=True)
            .where(RollChainLeg.chain_id == chain.chain_id)
            .order_by(RollChainLeg.created_at)
        )
        leg_rows = list(legs.all())

        # Identify the trade by its opening leg: that's the strike/right the
        # user sold and (typically) rolled at.
        opening = next(
            (e for leg, e in leg_rows if e is not None and (leg.role == "open")),
            None,
        )
        if opening is None:
            opening = next((e for _, e in leg_rows if e is not None), None)

        underlying = _underlying_ticker(
            (opening.symbol if opening else None) or chain.underlying_symbol
        )
        right = (opening.right if opening else None) or chain.right
        strike = float(opening.strike) if opening and opening.strike is not None else None

        result.append({
            "chain_id": chain.chain_id,
            "underlying_symbol": underlying,
            "right": right,
            "strike": strike,
            "status": chain.status,
            "close_reason": chain.close_reason,
            "opened_at": chain.opened_at.isoformat() if chain.opened_at else None,
            "closed_at": chain.closed_at.isoformat() if chain.closed_at else None,
            "cumulative_credit": float(chain.cumulative_credit) if chain.cumulative_credit is not None else None,
            "leg_count": len(leg_rows),
            "conids": [leg.conid for leg, _ in leg_rows if leg.conid is not None],
            "legs": [
                {
                    "leg_id": str(leg.id),
                    "exec_id": leg.exec_id,
                    "role": leg.role,
                    "date": (
                        e.exec_time.isoformat() if e and e.exec_time
                        else (leg.created_at.isoformat() if leg.created_at else None)
                    ),
                    "action": (e.side if e else None),
                    "strike": (float(e.strike) if e and e.strike is not None else None),
                    "price": (float(e.price) if e and e.price is not None else 0.0),
                    "credit": (_credit(e) if e else 0.0),
                }
                for leg, e in leg_rows
            ],
        })
    return result
