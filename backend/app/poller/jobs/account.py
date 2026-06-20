"""Poll the account summary (net liq, margin, funds) into account_snapshots."""
from __future__ import annotations

from datetime import datetime, timezone

from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError
from app.clients.ibkr.normalize import normalize_summary
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import AccountSnapshot

log = get_logger("poller.account")


async def poll_account(client: IBKRClient) -> None:
    if not (session_state.user_logged_in and session_state.account_id):
        return
    account_id = session_state.account_id

    try:
        raw = await client.portfolio_summary(account_id)
    except (IBKRAuthError, IBKRError) as exc:
        log.warning("account_fetch_failed", error=str(exc))
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
    log.info("account_snapshot", net_liq=n["net_liquidation"])
    await broadcast_event("account")
