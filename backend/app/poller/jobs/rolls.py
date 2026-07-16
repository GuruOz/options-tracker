"""Roll-chain builder job.

Rebuilds roll_chains + roll_chain_legs from scratch using the deterministic
strike-scoped algorithm, preserving manual edits.
Runs periodically to catch new trades as they arrive.
"""
from __future__ import annotations

from sqlalchemy import delete, select

from app.analytics.rolls import build_roll_chains
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db import repo
from app.db.base import AsyncSessionLocal
from app.db.models import ChainAdjustment, Execution, RollChain, RollChainLeg

log = get_logger("poller.rolls")


async def build_rolls() -> None:
    """Rebuild every known account's chains from its executions.

    Deliberately keyed off the `accounts` table rather than the logged-in
    sessions: chains are built from stored executions, so a CSV upload or Flex
    import for a user who is currently logged out must still rebuild.
    """
    async with AsyncSessionLocal() as session:
        account_ids = await repo.all_account_ids(session)

    for account_id in account_ids:
        try:
            await _build_rolls_one(account_id)
        except Exception as exc:
            log.warning("roll_build_failed", account=account_id, error=str(exc))


async def _build_rolls_one(account_id: str) -> None:
    # Collapse cross-source duplicate fills (live poll vs Flex/CSV) before
    # building, so a fill reported by both feeds isn't double-counted and
    # doesn't spawn a phantom strike-0 chain. The poll feed won't re-add these
    # on its next run (it skips fills an authoritative feed already covers).
    async with AsyncSessionLocal() as session:
        removed = await repo.dedupe_executions(session, account_id)
        if removed:
            await session.commit()
            log.info("poll_duplicates_superseded", account=account_id, count=removed)

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

        rebuilt_ids = {c["chain_id"] for c in chains_data}

        # Clear legs for all auto-generated chains; they're re-inserted below.
        # Legs have no inbound FK, so this is always safe.
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

        # IMPORTANT: upsert the rebuilt chains BEFORE deleting any chain row.
        # A chain still referenced by a chain_adjustment (e.g. a manual link)
        # cannot be deleted — the adjustments FK blocks it and rolls back the
        # whole rebuild, freezing the pipeline indefinitely. Since a chain's id
        # is deterministic, every chain an adjustment targets is re-produced and
        # simply updated in place here, never momentarily removed.
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
                        "open_credit": c["open_credit"],
                        "initial_credit": c["initial_credit"],
                        "cycle_base_credit": c["cycle_base_credit"],
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

        # Drop only the stale auto chains this rebuild no longer produces (e.g. a
        # phantom strike-0 chain whose lossy poll rows were since deduped away).
        # First clear any adjustments that pointed at them — a dead manual edit
        # whose target chain is gone — so the chain delete isn't FK-blocked.
        stale_chains = select(RollChain.chain_id).where(
            RollChain.account_id == account_id,
            RollChain.is_manual.is_(False),
            RollChain.chain_id.notin_(rebuilt_ids),
        )
        await session.execute(
            delete(ChainAdjustment).where(ChainAdjustment.chain_id.in_(stale_chains))
        )
        await session.execute(
            delete(RollChain).where(
                RollChain.account_id == account_id,
                RollChain.is_manual.is_(False),
                RollChain.chain_id.notin_(rebuilt_ids),
            )
        )

        await session.commit()

    log.info(
        "roll_chains_rebuilt", account=account_id,
        chains=len(chains_data), legs=len(legs_data),
    )
    await broadcast_event("positions", account_id)
