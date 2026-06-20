"""Flex Web Service import job — runs independently of auth.

Pulls historical trades from IBKR's Flex Web Service directly (not via CP Gateway).
Requires IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env.
"""
from __future__ import annotations

from app.clients.ibkr import IBKRClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import Execution

log = get_logger("poller.flex")
_settings = get_settings()


async def import_flex_trades(client: IBKRClient) -> None:  # noqa: ARG001
    """Run Flex Web Service import. Idempotent — skips existing exec_ids."""
    token = _settings.ibkr_flex_token
    query_id = _settings.ibkr_flex_query_id
    if not token or not query_id:
        return

    if not session_state.account_id:
        return

    try:
        from app.clients.ibkr.flex_web import fetch_flex_trades
        trades = await fetch_flex_trades(token, query_id)
        if not trades:
            return

        account_id = session_state.account_id
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

        log.info("flex_job_import", parsed=len(trades), inserted=flex_count)
        await broadcast_event("trades")
    except Exception as exc:
        log.warning("flex_job_failed", error=str(exc))
