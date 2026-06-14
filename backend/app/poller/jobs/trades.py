"""Poll recent fills and append them to `executions`, deduped by exec id.

IBKR's trades endpoint only returns a ~7-day window; persisting here (idempotent
on exec_id) builds the unbounded history the analytics depend on.
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError
from app.clients.ibkr.normalize import normalize_trade
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import Execution

log = get_logger("poller.trades")

_COLUMNS = {
    "exec_id", "account_id", "conid", "symbol", "sec_type", "side", "right",
    "strike", "expiry", "qty", "price", "commission", "realized_pnl",
    "exec_time", "source", "raw",
}


async def poll_trades(client: IBKRClient) -> None:
    if not (session_state.authenticated and session_state.account_id):
        return
    account_id = session_state.account_id

    try:
        raw_trades = await client.trades()
    except (IBKRAuthError, IBKRError) as exc:
        log.warning("trades_fetch_failed", error=str(exc))
        return
    if not isinstance(raw_trades, list) or not raw_trades:
        return

    values = []
    for t in raw_trades:
        n = normalize_trade(t, account_id=account_id)
        if not n["exec_id"]:
            continue
        values.append({k: v for k, v in n.items() if k in _COLUMNS})
    if not values:
        return

    stmt = (
        pg_insert(Execution)
        .values(values)
        .on_conflict_do_nothing(index_elements=["exec_id"])
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        await session.commit()
    log.info("trades_polled", fetched=len(values), inserted=result.rowcount)
    await broadcast_event("trades")
