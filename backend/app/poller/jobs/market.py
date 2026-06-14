"""Poll underlying history + IV, compute indicators and the composite signal.

Tracked underlyings come exclusively from settings.underlyings (user-configured).
Trend/RSI work immediately from price history; IV-percentile/rank sub-scores
stay "n/a" until enough IV observations accumulate (≥20).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select

from app.analytics import indicators
from app.analytics.signal import compute_signal
from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError
from app.clients.ibkr.fields import UNDERLYING_FIELD_CODES
from app.clients.ibkr.normalize import parse_history, parse_underlying_quote
from app.core.logging import get_logger
from app.core.state import broadcast_event, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import MarketSnapshot, Setting, SignalHistory


log = get_logger("poller.market")

_MIN_IV_HISTORY = 5  # observations before IV rank/percentile is meaningful


async def _tracked_underlyings() -> dict[int, str]:
    """Return {conid: symbol} from settings.underlyings only."""
    async with AsyncSessionLocal() as session:
        settings_row = await session.get(Setting, 1)
    tracked: dict[int, str] = {}
    for u in (settings_row.data if settings_row else {}).get("underlyings", []):
        try:
            tracked[int(u["conid"])] = u.get("symbol") or str(u["conid"])
        except (KeyError, ValueError, TypeError):
            continue
    return tracked


async def _iv_history(conid: int, limit: int = 252) -> list[float]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(MarketSnapshot.iv)
            .where(MarketSnapshot.conid == conid, MarketSnapshot.iv.is_not(None))
            .order_by(desc(MarketSnapshot.snapshot_ts))
            .limit(limit)
        )
        return [float(v) for (v,) in rows.all() if v is not None]


async def poll_market(client: IBKRClient) -> None:
    if not session_state.authenticated:
        return

    async with AsyncSessionLocal() as session:
        settings_row = await session.get(Setting, 1)
    settings = settings_row.data if settings_row else None

    tracked = await _tracked_underlyings()
    if not tracked:
        return

    ts = datetime.now(timezone.utc)
    objs: list = []
    for conid, symbol in tracked.items():
        try:
            hist = await client.market_history(conid, period="1y", bar="1d")
        except (IBKRError, IBKRAuthError) as exc:
            log.warning("history_failed", symbol=symbol, error=str(exc))
            hist = {}
        closes = parse_history(hist)

        try:
            snap = await client.market_snapshot([conid], UNDERLYING_FIELD_CODES)
        except (IBKRError, IBKRAuthError):
            snap = []
        quote = parse_underlying_quote(snap[0]) if snap else {"price": None, "iv": None}

        price = quote["price"] if quote["price"] is not None else (closes[-1] if closes else None)
        iv = quote["iv"]  # percent (None if IBKR subscription doesn't supply it)
        if iv is None:
            log.warning("iv_missing", symbol=symbol, conid=conid,
                        hint="check IBKR market-data subscription or snapshot field codes")
        rv = indicators.realized_vol(closes, window=20)
        rv_pct = rv * 100.0 if rv is not None else None

        iv_hist = await _iv_history(conid)
        if iv is not None and len(iv_hist) >= _MIN_IV_HISTORY:
            ivp = indicators.iv_percentile(iv, iv_hist)
            ivr = indicators.iv_rank(iv, iv_hist)
        else:
            ivp = ivr = None

        inputs = {
            "iv_percentile": ivp,
            "iv": iv,
            "realized_vol": rv_pct,
            "price": price,
            "sma50": indicators.sma(closes, 50),
            "rsi": indicators.rsi(closes, 14),
            "drawdown": indicators.drawdown_from_high(closes, lookback=126),
        }
        sig = compute_signal(inputs, settings)

        objs.append(MarketSnapshot(
            conid=conid, symbol=symbol, snapshot_ts=ts, price=price, iv=iv,
            realized_vol=rv_pct, iv_percentile=ivp, iv_rank=ivr,
            rsi14=inputs["rsi"], sma50=inputs["sma50"], sma200=indicators.sma(closes, 200),
            is_vix=False, raw={"closes": len(closes)},
        ))
        objs.append(SignalHistory(
            underlying_conid=conid, symbol=symbol, ts=ts,
            composite_score=sig["composite"], verdict=sig["verdict"],
            sub_scores=sig["sub_scores"], inputs=inputs, weights=sig["weights"],
        ))

    if objs:
        async with AsyncSessionLocal() as session:
            session.add_all(objs)
            await session.commit()
        log.info("market_snapshot", underlyings=len(tracked))
        await broadcast_event("market")
        await broadcast_event("signals")
