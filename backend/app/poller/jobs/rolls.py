"""Roll-chain builder job.

Scans unlinked executions and builds roll_chains + roll_chain_legs rows.
Runs periodically to catch new trades as they arrive.
"""
from __future__ import annotations

from sqlalchemy import select, outerjoin

from app.analytics.rolls import build_roll_chains
from app.clients.ibkr import IBKRClient
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import Execution, RollChain, RollChainLeg

log = get_logger("poller.rolls")


async def _unlinked_executions(account_id: str) -> list[Execution]:
    """Executions not yet linked to any roll_chain_leg."""
    async with AsyncSessionLocal() as session:
        subq = select(RollChainLeg.exec_id).where(
            RollChainLeg.exec_id.is_not(None)
        ).subquery()
        rows = await session.execute(
            select(Execution)
            .where(
                Execution.account_id == account_id,
                Execution.exec_id.not_in(select(subq.c.exec_id)),
            )
            .order_by(Execution.exec_time)
        )
        return list(rows.scalars().all())


async def _existing_open_chains(account_id: str) -> dict[int, dict]:
    """Load currently-open chains from the DB, keyed by conid.

    Queries roll_chain_legs (role='open') joined with roll_chains (status='open')
    so each open position's conid maps to its chain.
    """
    from sqlalchemy import and_
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(RollChain, RollChainLeg.conid)
            .join(RollChainLeg, RollChainLeg.chain_id == RollChain.chain_id)
            .where(
                and_(
                    RollChain.account_id == account_id,
                    RollChain.status == "open",
                    RollChainLeg.role == "open",
                    RollChainLeg.conid.is_not(None),
                )
            )
        )
        results = rows.all()
    return {
        row.conid: {
            "chain_id": row.RollChain.chain_id,
            "account_id": row.RollChain.account_id,
            "underlying_symbol": row.RollChain.underlying_symbol,
            "underlying_conid": row.RollChain.underlying_conid,
            "right": row.RollChain.right,
            "status": row.RollChain.status,
            "opened_at": row.RollChain.opened_at,
            "closed_at": row.RollChain.closed_at,
            "cumulative_credit": float(row.RollChain.cumulative_credit) if row.RollChain.cumulative_credit is not None else 0.0,
            "meta": row.RollChain.meta,
        }
        for row in results
    }


async def build_rolls(client: IBKRClient) -> None:  # noqa: ARG001 — client kept for scheduler interface
    """Find new roll chains and persist them."""
    if not session_state.account_id:
        return
    account_id = session_state.account_id

    unlinked = await _unlinked_executions(account_id)
    if not unlinked:
        return

    existing = await _existing_open_chains(account_id)
    chains_data, legs_data = build_roll_chains(
        unlinked, account_id, existing_open_chains=existing,
    )
    if not chains_data:
        return

    async with AsyncSessionLocal() as session:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        for c in chains_data:
            stmt = (
                pg_insert(RollChain)
                .values(**c)
                .on_conflict_do_update(
                    index_elements=["chain_id"],
                    set_={
                        "status": c["status"],
                        "closed_at": c["closed_at"],
                        "cumulative_credit": c["cumulative_credit"],
                    },
                )
            )
            await session.execute(stmt)

        if legs_data:
            stmt = (
                pg_insert(RollChainLeg)
                .values(legs_data)
                .on_conflict_do_nothing(
                    constraint="uq_chain_exec"
                )
            )
            await session.execute(stmt)

        await session.commit()

    created = len(chains_data)
    leg_count = len(legs_data)
    if created or leg_count:
        log.info("roll_chains_built", chains=created, legs=leg_count)
        await broadcast_event("positions")
