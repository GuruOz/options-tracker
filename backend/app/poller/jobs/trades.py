"""Poll recent fills and append them to `executions`, deduped by exec id.

IBKR's trades endpoint only returns a ~7-day window; persisting here (idempotent
on exec_id) builds the unbounded history the analytics depend on. Each logged-in
user's gateway reports only that user's fills.
"""
from __future__ import annotations

from app.clients.ibkr import IBKRAuthError, IBKRError
from app.clients.ibkr.normalize import normalize_trade
from app.core.gateways import GatewayRuntime, active_runtimes
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db import repo
from app.db.base import AsyncSessionLocal

log = get_logger("poller.trades")

_COLUMNS = {
    "exec_id", "account_id", "conid", "symbol", "sec_type", "side", "right",
    "strike", "expiry", "qty", "price", "commission", "realized_pnl", "currency",
    "exec_time", "source", "raw",
}


async def poll_trades() -> None:
    for runtime in active_runtimes():
        try:
            await _poll_trades_one(runtime)
        except Exception as exc:
            log.warning("trades_poll_failed", gateway=runtime.gateway_id, error=str(exc))


async def _poll_trades_one(runtime: GatewayRuntime) -> None:
    account_id = runtime.state.account_id

    try:
        raw_trades = await runtime.client.trades()
    except (IBKRAuthError, IBKRError) as exc:
        log.warning("trades_fetch_failed", gateway=runtime.gateway_id, error=str(exc))
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

    async with AsyncSessionLocal() as session:
        inserted = await repo.insert_poll_executions(session, values, account_id)
        await session.commit()
    log.info(
        "trades_polled", gateway=runtime.gateway_id,
        fetched=len(values), inserted=inserted,
    )
    await broadcast_event("trades", account_id)
