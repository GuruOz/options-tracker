"""Flex Web Service import job — runs independently of auth.

Pulls historical trades from IBKR's Flex Web Service directly (not via CP Gateway).
Each user configures their own token/query (IBKR_USER{n}_FLEX_TOKEN /
IBKR_USER{n}_FLEX_QUERY_ID); a user who hasn't set one up is simply skipped.
"""
from __future__ import annotations

from app.core.gateways import GatewayRuntime, all_runtimes
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db.base import AsyncSessionLocal
from app.db.models import Execution

log = get_logger("poller.flex")


async def import_flex_trades() -> None:
    """Run the Flex import for every user that has one configured."""
    for runtime in all_runtimes():
        try:
            await _import_flex_one(runtime)
        except Exception as exc:
            log.warning("flex_job_failed", gateway=runtime.gateway_id, error=str(exc))


async def _import_flex_one(runtime: GatewayRuntime) -> None:
    """Idempotent — skips existing exec_ids.

    Note the account only has to have been *detected* (not currently logged in):
    `account_id` stays set after logout, so the hourly import keeps backfilling
    history for a user who has since released their session.
    """
    token = runtime.config.flex_token
    query_id = runtime.config.flex_query_id
    if not token or not query_id:
        return

    account_id = runtime.state.account_id
    if not account_id:
        return

    from app.clients.ibkr.flex_web import fetch_flex_trades
    trades = await fetch_flex_trades(token, query_id)
    if not trades:
        return

    for t in trades:
        t["account_id"] = account_id

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Execution)
            .values(trades)
            .on_conflict_do_nothing(index_elements=["exec_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        flex_count = result.rowcount

    log.info(
        "flex_job_import", gateway=runtime.gateway_id,
        parsed=len(trades), inserted=flex_count,
    )
    await broadcast_event("trades", account_id)
