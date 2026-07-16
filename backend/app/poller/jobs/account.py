"""Poll the account summary (net liq, margin, funds) into account_snapshots.

One snapshot per logged-in user per run — each account keeps its own series.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.clients.ibkr import IBKRAuthError, IBKRError
from app.clients.ibkr.normalize import normalize_summary
from app.core.gateways import GatewayRuntime, active_runtimes
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db.base import AsyncSessionLocal
from app.db.models import AccountSnapshot

log = get_logger("poller.account")


async def poll_account() -> None:
    for runtime in active_runtimes():
        try:
            await _poll_account_one(runtime)
        except Exception as exc:
            log.warning(
                "account_poll_failed", gateway=runtime.gateway_id, error=str(exc)
            )


async def _poll_account_one(runtime: GatewayRuntime) -> None:
    account_id = runtime.state.account_id

    try:
        raw = await runtime.client.portfolio_summary(account_id)
    except (IBKRAuthError, IBKRError) as exc:
        log.warning("account_fetch_failed", gateway=runtime.gateway_id, error=str(exc))
        return
    if not isinstance(raw, dict):
        return

    n = normalize_summary(raw)
    snap = AccountSnapshot(
        account_id=account_id,
        snapshot_ts=datetime.now(timezone.utc),
        net_liquidation=n["net_liquidation"],
        available_funds=n["available_funds"],
        excess_liquidity=n["excess_liquidity"],
        maintenance_margin=n["maintenance_margin"],
        buying_power=n["buying_power"],
        leverage=n["leverage"],
        cash=n["cash"],
        raw=raw,
    )
    async with AsyncSessionLocal() as session:
        session.add(snap)
        await session.commit()
    log.info(
        "account_snapshot", gateway=runtime.gateway_id,
        net_liq=n["net_liquidation"],
    )
    await broadcast_event("account", account_id)
