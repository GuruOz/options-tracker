"""Roll-chain builder job.

Rebuilds roll_chains + roll_chain_legs from scratch using the deterministic
strike-scoped algorithm, preserving manual edits.
Runs periodically to catch new trades as they arrive.
"""
from __future__ import annotations

from sqlalchemy import delete, select

from app.analytics.rolls import build_roll_chains
from app.clients.ibkr import IBKRClient
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import ChainAdjustment, Execution, RollChain, RollChainLeg

log = get_logger("poller.rolls")


async def build_rolls(client: IBKRClient) -> None:  # noqa: ARG001 — client kept for scheduler interface
    """Rebuild all chains from executions."""
    if not session_state.account_id:
        return
    account_id = session_state.account_id

    async with AsyncSessionLocal() as session:
        # Load all executions
        exs = await session.execute(
            select(Execution)
            .where(Execution.account_id == account_id)
            .order_by(Execution.exec_time)
        )
        executions = list(exs.scalars().all())
        if not executions:
            return

        # Load adjustments
        adj = await session.execute(
            select(ChainAdjustment)
            .join(RollChain, RollChain.chain_id == ChainAdjustment.chain_id)
            .where(RollChain.account_id == account_id)
        )
        adjustments = list(adj.scalars().all())

        # Build chains deterministically
        chains_data, legs_data = build_roll_chains(
            executions, account_id, adjustments=adjustments
        )
        if not chains_data:
            return

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Wipe auto-generated chains and their legs
        await session.execute(
            delete(RollChainLeg)
            .where(
                RollChainLeg.chain_id.in_(
                    select(RollChain.chain_id).where(
                        RollChain.account_id == account_id,
                        RollChain.is_manual.is_(False)
                    )
                )
            )
        )
        await session.execute(
            delete(RollChain)
            .where(RollChain.account_id == account_id, RollChain.is_manual.is_(False))
        )

        # Upsert chains
        for c in chains_data:
            stmt = (
                pg_insert(RollChain)
                .values(**c)
                .on_conflict_do_update(
                    index_elements=["chain_id"],
                    set_={
                        "status": c["status"],
                        "closed_at": c["closed_at"],
                        "close_reason": c["close_reason"],
                        "cumulative_credit": c["cumulative_credit"],
                    },
                )
            )
            await session.execute(stmt)

        # Insert legs
        if legs_data:
            # Remove any None values from legs_data dicts where the DB schema doesn't want explicit None if default applies?
            # Actually, insert accepts None if nullable.
            for i in range(0, len(legs_data), 1000):
                chunk = legs_data[i:i + 1000]
                stmt = (
                    pg_insert(RollChainLeg)
                    .values(chunk)
                    .on_conflict_do_nothing(constraint="uq_chain_exec")
                )
                await session.execute(stmt)

        await session.commit()

    log.info("roll_chains_rebuilt", chains=len(chains_data), legs=len(legs_data))
    await broadcast_event("positions")
