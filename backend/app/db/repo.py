"""Read helpers for the API. Latest-batch queries over the snapshot tables."""
from __future__ import annotations

from datetime import date

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.dedup import (
    AUTHORITATIVE_SOURCES,
    is_superseded_poll_row,
    option_content_key,
    superseded_poll_exec_ids,
)
from app.analytics.rolls import _credit
from app.core.occ import parse_occ_symbol
from app.db.models import (
    Account,
    AccountSetting,
    AccountSnapshot,
    DailyBar,
    Execution,
    MarketSnapshot,
    PositionSnapshot,
    RollChainLeg,
    SignalHistory,
)


def _f(v) -> float | None:
    """Money columns read back as Decimal; the API speaks float."""
    return float(v) if v is not None else None


async def all_accounts(db: AsyncSession) -> list[Account]:
    """Every known account, oldest first — the switcher's source of truth."""
    rows = await db.execute(select(Account).order_by(Account.first_seen, Account.id))
    return list(rows.scalars().all())


async def all_account_ids(db: AsyncSession) -> list[str]:
    rows = await db.execute(
        select(Account.account_id).order_by(Account.first_seen, Account.id)
    )
    return [r for (r,) in rows.all()]


async def account_by_id(db: AsyncSession, account_id: str) -> Account | None:
    rows = await db.execute(select(Account).where(Account.account_id == account_id))
    return rows.scalar_one_or_none()


async def account_labels(db: AsyncSession) -> dict[str, str]:
    """`{account_id: label}`, falling back to the id when a label is unset."""
    rows = await db.execute(select(Account.account_id, Account.label))
    return {aid: (label or aid) for aid, label in rows.all()}


async def account_settings(db: AsyncSession, account_id: str) -> AccountSetting | None:
    return await db.get(AccountSetting, account_id)


async def chain_exists(db: AsyncSession, chain_id: str) -> bool:
    from app.db.models import RollChain
    rows = await db.execute(
        select(RollChain.chain_id).where(RollChain.chain_id == chain_id).limit(1)
    )
    return rows.scalar_one_or_none() is not None


async def all_account_settings(db: AsyncSession) -> list[AccountSetting]:
    rows = await db.execute(select(AccountSetting))
    return list(rows.scalars().all())


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


async def _authoritative_option_keys(db: AsyncSession, account_id: str) -> set[tuple]:
    """Content keys of stored authoritative (Flex/CSV) option fills for an account.

    Used to drop poll-fed option rows the authoritative feed already covers — see
    `app.analytics.dedup`.
    """
    rows = await db.execute(
        select(Execution.conid, Execution.side, Execution.qty, Execution.price, Execution.sec_type)
        .where(
            Execution.account_id == account_id,
            Execution.source.in_(tuple(AUTHORITATIVE_SOURCES)),
            Execution.sec_type.in_(("OPT", "FOP", "WAR")),
        )
    )
    keys: set[tuple] = set()
    for conid, side, qty, price, sec_type in rows.all():
        key = option_content_key(
            {"conid": conid, "side": side, "qty": qty, "price": price, "sec_type": sec_type}
        )
        if key is not None:
            keys.add(key)
    return keys


async def insert_poll_executions(
    db: AsyncSession, values: list[dict], account_id: str
) -> int:
    """Insert live-poll execution rows, skipping option fills an authoritative
    feed already recorded (same contract/side/qty/price under a different
    exec_id). Idempotent on exec_id like the other feeds. Caller commits.

    Returns the number of rows actually inserted.
    """
    if not values:
        return 0

    auth_keys = await _authoritative_option_keys(db, account_id)
    kept = [v for v in values if not is_superseded_poll_row(v, auth_keys)]
    if not kept:
        return 0

    stmt = (
        pg_insert(Execution)
        .values(kept)
        .on_conflict_do_nothing(index_elements=["exec_id"])
    )
    result = await db.execute(stmt)
    return result.rowcount or 0


async def dedupe_executions(db: AsyncSession, account_id: str) -> int:
    """Delete poll-fed option rows that have an authoritative (Flex/CSV) twin.

    Collapses the same fill reported by two feeds down to the authoritative copy,
    which carries the OCC symbol + strike. Caller commits. Returns rows deleted.
    """
    rows = await db.execute(
        select(Execution).where(
            Execution.account_id == account_id,
            Execution.sec_type.in_(("OPT", "FOP", "WAR")),
        )
    )
    dupe_ids = superseded_poll_exec_ids(list(rows.scalars().all()))
    if dupe_ids:
        # Drop any roll-chain legs pointing at the soon-to-be-deleted poll rows
        # first: a prior build_rolls pass may have linked a poll fill into a chain
        # before its authoritative Flex/CSV twin arrived, and the FK
        # (roll_chain_legs.exec_id -> executions.exec_id) blocks the delete
        # otherwise. Auto-generated legs are rebuilt from the authoritative twin in
        # the same build_rolls pass, so removing them here changes nothing downstream.
        await db.execute(delete(RollChainLeg).where(RollChainLeg.exec_id.in_(dupe_ids)))
        await db.execute(delete(Execution).where(Execution.exec_id.in_(dupe_ids)))
    return len(dupe_ids)


async def latest_market(db: AsyncSession) -> list[MarketSnapshot]:
    """Most recent market snapshot per underlying (Postgres DISTINCT ON)."""
    rows = await db.execute(
        select(MarketSnapshot)
        .distinct(MarketSnapshot.conid)
        .order_by(MarketSnapshot.conid, desc(MarketSnapshot.snapshot_ts))
    )
    return list(rows.scalars().all())


async def latest_priced_market(db: AsyncSession) -> list[MarketSnapshot]:
    """Most recent snapshot *with a non-null price* per underlying symbol.

    Position enrichment keys the underlying spot by symbol and only needs the
    price. Plain ``latest_market`` returns the newest row per conid even when its
    price is null: an IBKR market poll with no data subscription writes
    ``price=None``, shadowing a good yfinance price written moments earlier, and
    the position then loses its spot and silently drops out of the decay / P&L
    panels. Taking the latest *priced* row per symbol keeps a transient empty poll
    from blanking the spot.
    """
    rows = await db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.price.is_not(None), MarketSnapshot.symbol.is_not(None))
        .distinct(MarketSnapshot.symbol)
        .order_by(MarketSnapshot.symbol, desc(MarketSnapshot.snapshot_ts))
    )
    return list(rows.scalars().all())


async def upsert_daily_bars(db: AsyncSession, rows: list[dict]) -> int:
    """Idempotent insert of daily bars, keyed by ``(conid, bar_date)``.

    Each poll re-upserts the same trailing-year window: today's bar is updated in
    place and older bars are stable, so the chart cache self-heals without
    duplicating rows. Returns the number of rows sent.
    """
    if not rows:
        return 0
    # Last-wins dedup by the conflict target: Postgres' ON CONFLICT DO UPDATE
    # errors if the same (conid, bar_date) appears twice in one statement.
    deduped = {(r["conid"], r["bar_date"]): r for r in rows}
    rows = list(deduped.values())
    stmt = pg_insert(DailyBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["conid", "bar_date"],
        set_={
            "close": stmt.excluded.close,
            "symbol": stmt.excluded.symbol,
            "source": stmt.excluded.source,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def daily_bar_series(
    db: AsyncSession, conid: int, since: date
) -> list[DailyBar]:
    """Underlying daily closes on/after ``since`` (oldest->newest)."""
    rows = await db.execute(
        select(DailyBar)
        .where(
            DailyBar.conid == conid,
            DailyBar.is_vix.is_(False),
            DailyBar.bar_date >= since,
        )
        .order_by(DailyBar.bar_date)
    )
    return list(rows.scalars().all())


async def daily_bar_series_by_symbol(
    db: AsyncSession, symbol: str, since: date
) -> list[DailyBar]:
    """Daily closes for a symbol looked up case-insensitively (oldest->newest)."""
    rows = await db.execute(
        select(DailyBar)
        .where(
            func.lower(DailyBar.symbol) == symbol.lower(),
            DailyBar.is_vix.is_(False),
            DailyBar.bar_date >= since,
        )
        .order_by(DailyBar.bar_date)
    )
    return list(rows.scalars().all())


async def market_snapshot_by_symbol(
    db: AsyncSession, symbol: str
) -> MarketSnapshot | None:
    """Latest market snapshot for a symbol (case-insensitive)."""
    rows = await db.execute(
        select(MarketSnapshot)
        .where(func.lower(MarketSnapshot.symbol) == symbol.lower())
        .order_by(desc(MarketSnapshot.snapshot_ts))
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def vix_series(db: AsyncSession, since: date) -> list[DailyBar]:
    """VIX daily closes on/after ``since`` (oldest->newest)."""
    rows = await db.execute(
        select(DailyBar)
        .where(DailyBar.is_vix.is_(True), DailyBar.bar_date >= since)
        .order_by(DailyBar.bar_date)
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


async def open_roll_chains(db: AsyncSession, account_id: str) -> dict[int, dict]:
    """conid -> its open chain's identity and cycle economics.

    Carries the credit figures (not just the id) because a rolled position's
    headline numbers are properties of the whole chain, not of the leg that
    happens to be open — see `analytics/enrichment.py`.
    """
    from app.db.models import RollChain, RollChainLeg
    rows = await db.execute(
        select(
            RollChainLeg.conid,
            RollChain.chain_id,
            RollChain.cumulative_credit,
            RollChain.initial_credit,
            RollChain.cycle_base_credit,
        )
        .join(RollChain, RollChain.chain_id == RollChainLeg.chain_id)
        .where(
            RollChain.account_id == account_id,
            RollChain.status == "open",
            RollChainLeg.conid.is_not(None)
        )
    )
    return {
        row.conid: {
            "chain_id": row.chain_id,
            "cumulative_credit": _f(row.cumulative_credit),
            "initial_credit": _f(row.initial_credit),
            "cycle_base_credit": _f(row.cycle_base_credit) or 0.0,
        }
        for row in rows
    }


def _underlying_ticker(symbol: str | None) -> str | None:
    """Strip an option/OCC symbol down to its underlying ticker.

    'NVDA 260618P00216000' -> 'NVDA'; 'NVDA' -> 'NVDA'.
    """
    if not symbol:
        return None
    return symbol.strip().split()[0] or None


def _exec_strike(exec_obj) -> float | None:
    """Strike of an execution, recovered from the OSI symbol when the explicit
    column is null/zero (feeds often omit it, which otherwise degrades the chain
    label to e.g. "NVDA P")."""
    if exec_obj is None:
        return None
    if exec_obj.strike is not None and float(exec_obj.strike) != 0.0:
        return float(exec_obj.strike)
    return parse_occ_symbol(exec_obj.symbol)["strike"]


def _exec_expiry(exec_obj) -> str | None:
    """ISO expiry of an execution, recovered from the OSI symbol when the
    explicit column is null (feeds often omit it)."""
    if exec_obj is None:
        return None
    if exec_obj.expiry is not None:
        return exec_obj.expiry.isoformat()
    d = parse_occ_symbol(exec_obj.symbol)["expiry"]
    return d.isoformat() if d else None


def _exec_right(exec_obj) -> str | None:
    """Right (P/C) of an execution, recovered from the OSI symbol when null."""
    if exec_obj is None:
        return None
    return exec_obj.right or parse_occ_symbol(exec_obj.symbol)["right"]


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
        right = _exec_right(opening) or chain.right
        strike = _exec_strike(opening)

        # The poll-only assignment delivers shares with no stock execution, so
        # its synthetic `assignment_stock` leg has no economics to join. Derive
        # them for display from the chain strike and the assigned contract count
        # (carried by the preceding `assignment` leg's option execution), so the
        # timeline shows "100 shares @ $216" and the running total ties out.
        contracts = 1.0
        leg_dicts = []
        for leg, e in leg_rows:
            if leg.role == "assignment" and e is not None and e.qty:
                contracts = abs(float(e.qty))
            if leg.role == "assignment_stock" and e is None:
                shares = contracts * 100.0
                buy = (right or "").upper() == "P"
                value = shares * float(strike or 0.0)
                leg_dicts.append({
                    "leg_id": str(leg.id),
                    "exec_id": None,
                    "role": leg.role,
                    "date": leg.created_at.isoformat() if leg.created_at else None,
                    "action": "B" if buy else "S",
                    "strike": strike,
                    "expiry": None,
                    "price": float(strike or 0.0),
                    "credit": -value if buy else value,
                    "qty": shares,
                })
                continue
            leg_dicts.append({
                "leg_id": str(leg.id),
                "exec_id": leg.exec_id,
                "role": leg.role,
                "date": (
                    e.exec_time.isoformat() if e and e.exec_time
                    else (leg.created_at.isoformat() if leg.created_at else None)
                ),
                "action": (e.side if e else None),
                "strike": _exec_strike(e),
                "expiry": _exec_expiry(e),
                "price": (float(e.price) if e and e.price is not None else 0.0),
                "credit": (_credit(e) if e else 0.0),
                "qty": (float(e.qty) if e and e.qty is not None else None),
            })

        # What's actually banked so far: a roll only realizes the decay on the leg
        # it replaced, so the credit riding on the leg that's still open isn't
        # money in hand until it expires worthless or gets bought back.
        cumulative = _f(chain.cumulative_credit)
        open_credit = _f(chain.open_credit) or 0.0
        banked = None if cumulative is None else cumulative - open_credit

        result.append({
            "chain_id": chain.chain_id,
            "underlying_symbol": underlying,
            "right": right,
            "strike": strike,
            "status": chain.status,
            "close_reason": chain.close_reason,
            "opened_at": chain.opened_at.isoformat() if chain.opened_at else None,
            "closed_at": chain.closed_at.isoformat() if chain.closed_at else None,
            "cumulative_credit": cumulative,
            "open_credit": open_credit,
            "initial_credit": _f(chain.initial_credit),
            "banked_credit": banked,
            "leg_count": len(leg_rows),
            "conids": [leg.conid for leg, _ in leg_rows if leg.conid is not None],
            "legs": leg_dicts,
        })
    return result
