"""Poll open positions, enrich option legs with live Greeks, and snapshot them.

Each run appends a fresh batch sharing one `snapshot_ts`, so the latest batch is
the current portfolio and the history is preserved for roll-chain reconstruction.
Each logged-in user's gateway is polled independently.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.clients.ibkr import IBKRAuthError, IBKRError
from app.clients.ibkr.normalize import normalize_position, parse_snapshot_row
from app.core.gateways import GatewayRuntime, active_runtimes
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db.base import AsyncSessionLocal
from app.db.models import PositionSnapshot

log = get_logger("poller.positions")


async def poll_positions() -> None:
    for runtime in active_runtimes():
        try:
            await _poll_positions_one(runtime)
        except Exception as exc:
            log.warning(
                "positions_poll_failed", gateway=runtime.gateway_id, error=str(exc)
            )


async def _poll_positions_one(runtime: GatewayRuntime) -> None:
    client = runtime.client
    account_id = runtime.state.account_id

    try:
        raw_positions = await client.all_positions(account_id)
    except (IBKRAuthError, IBKRError) as exc:
        log.warning("positions_fetch_failed", gateway=runtime.gateway_id, error=str(exc))
        return

    normalized = [normalize_position(p) for p in raw_positions]

    # Enrich option legs with live Greeks via a warmed-up snapshot.
    option_conids = [
        n["conid"]
        for n in normalized
        if n["conid"] and (n["sec_type"] or "").upper() in ("OPT", "FOP", "WAR")
    ]
    greeks: dict[int, dict] = {}
    if option_conids:
        try:
            rows = await client.snapshot_with_warmup(option_conids)
            for row in rows:
                conid = row.get("conid")
                if conid is not None:
                    greeks[int(conid)] = parse_snapshot_row(row)
        except (IBKRAuthError, IBKRError) as exc:
            log.warning("greeks_fetch_failed", gateway=runtime.gateway_id, error=str(exc))

    ts = datetime.now(timezone.utc)
    objs: list[PositionSnapshot] = []
    for n in normalized:
        if n["conid"] is None:
            continue
        g = greeks.get(n["conid"])
        snap = PositionSnapshot(
            account_id=account_id,
            snapshot_ts=ts,
            conid=n["conid"],
            sec_type=n["sec_type"],
            symbol=n["symbol"],
            right=n["right"],
            strike=n["strike"],
            expiry=n["expiry"],
            position=n["position"],
            avg_cost=n["avg_cost"],
            mark=n["mark"],
            market_value=n["market_value"],
            unrealized_pnl=n["unrealized_pnl"],
            raw=n["raw"],
        )
        if g and g["has_greeks"]:
            snap.delta = g["delta"]
            snap.gamma = g["gamma"]
            snap.theta = g["theta"]
            snap.vega = g["vega"]
            snap.iv = g["iv"]
            snap.greeks_source = "ibkr"
            if g["mark"] is not None:
                snap.mark = g["mark"]
        objs.append(snap)

    if not objs:
        return
    async with AsyncSessionLocal() as session:
        session.add_all(objs)
        await session.commit()
    log.info(
        "positions_snapshot", gateway=runtime.gateway_id,
        count=len(objs), options=len(option_conids),
    )
    await broadcast_event("positions", account_id)
