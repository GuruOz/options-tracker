"""Poll underlying history + IV, compute indicators and the composite signal.

Tracked underlyings come exclusively from settings.underlyings (user-configured).

Two modes:
  * refresh_public_prices — yfinance fallback, runs WITHOUT IBKR auth
  * poll_market — IBKR-sourced snapshots, requires active user session
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
    if not session_state.user_logged_in:
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
        raw_snap_keys = list(snap[0].keys()) if snap else []
        quote = parse_underlying_quote(snap[0]) if snap else {"price": None, "iv": None}

        price = quote["price"] if quote["price"] is not None else (closes[-1] if closes else None)
        iv = quote["iv"]  # percent (None if IBKR subscription doesn't supply it)
        if iv is None:
            log.warning(
                "iv_missing", symbol=symbol, conid=conid,
                snap_keys=raw_snap_keys,
                snap_values={k: snap[0].get(k) for k in ["7283", "7633", "7607", "7087"] if snap} if snap else {},
                hint="check IBKR market-data subscription or snapshot field codes",
            )
        rv = indicators.realized_vol(closes, window=20)
        rv_pct = rv * 100.0 if rv is not None else None

        iv_hist = await _iv_history(conid)
        log.debug(
            "iv_percentile_inputs", symbol=symbol, conid=conid,
            iv=iv, iv_hist_count=len(iv_hist), min_required=_MIN_IV_HISTORY,
        )
        if iv is not None and len(iv_hist) >= _MIN_IV_HISTORY:
            ivp = indicators.iv_percentile(iv, iv_hist)
            ivr = indicators.iv_rank(iv, iv_hist)
            log.debug("iv_percentile_result", symbol=symbol, ivp=ivp, ivr=ivr)
        else:
            ivp = ivr = None
            log.info(
                "iv_percentile_skipped", symbol=symbol, conid=conid,
                reason="iv_none" if iv is None else "insufficient_history",
                iv=iv, iv_hist_count=len(iv_hist), min_required=_MIN_IV_HISTORY,
            )

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
            is_vix=False, source="ibkr", raw={"closes": len(closes)},
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


async def refresh_public_prices(client: IBKRClient) -> None:
    """Public price refresh via yfinance — runs without IBKR auth.

    Fetches current price and IV for tracked underlyings from yfinance
    and writes to MarketSnapshot with source="public". Falls back to
    latest cached data on failure.
    """
    tracked = await _tracked_underlyings()
    if not tracked:
        return

    symbols = list(tracked.values())
    ts = datetime.now(timezone.utc)
    objs: list = []

    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        log.warning("yfinance_not_installed_public_price_skipped")
        return

    try:
        tickers = yf.Tickers(" ".join(symbols))
        for conid, symbol in tracked.items():
            try:
                t = tickers.tickers.get(symbol)
                if t is None:
                    raise ValueError(f"no ticker data for {symbol}")
                info = t.fast_info if hasattr(t, "fast_info") else t.info
                price = getattr(info, "last_price", None) or getattr(info, "regular_market_previous_close", None) or getattr(info, "previous_close", None)
                if price is None:
                    info2 = t.info or {}
                    price = info2.get("regular_market_previous_close") or info2.get("previous_close")
                price = float(price) if price is not None else None
            except Exception as exc:
                log.warning("yfinance_ticker_failed", symbol=symbol, error=str(exc))
                price = None

            if price is None:
                async with AsyncSessionLocal() as session:
                    row = await session.execute(
                        select(MarketSnapshot)
                        .where(MarketSnapshot.conid == conid)
                        .order_by(desc(MarketSnapshot.snapshot_ts))
                        .limit(1)
                    )
                    last = row.scalar_one_or_none()
                if last and last.price is not None:
                    price = float(last.price)
                    objs.append(MarketSnapshot(
                        conid=conid, symbol=symbol, snapshot_ts=ts,
                        price=price, source="cache",
                        raw={"fallback": "yfinance_unreachable"},
                    ))
                continue

            # yfinance does not expose a single implied-vol index, so on the
            # public fallback IV (and therefore the IV-percentile and variance-
            # premium sub-scores) is intentionally absent. The composite signal
            # is computed from the remaining sub-scores (trend + RSI/drawdown)
            # with the weights renormalised. IBKR polls fill IV when logged in.
            iv = None
            ivp = ivr = None

            closes: list[float] = []
            try:
                hist = t.history(period="1y")
                if not hist.empty:
                    closes = [float(c) for c in hist["Close"].tolist() if c is not None and not pd.isna(c)]
            except Exception:
                pass

            rv = indicators.realized_vol(closes, window=20) if len(closes) >= 20 else None
            rv_pct = rv * 100.0 if rv is not None else None

            inputs = {
                "iv_percentile": ivp,
                "iv": iv,
                "realized_vol": rv_pct,
                "price": price,
                "sma50": indicators.sma(closes, 50) if closes else None,
                "rsi": indicators.rsi(closes, 14) if len(closes) >= 14 else None,
                "drawdown": indicators.drawdown_from_high(closes, lookback=126) if closes else None,
            }

            async with AsyncSessionLocal() as session:
                settings_row = await session.get(Setting, 1)
            settings_data = settings_row.data if settings_row else None
            sig = compute_signal(inputs, settings_data)

            objs.append(MarketSnapshot(
                conid=conid, symbol=symbol, snapshot_ts=ts,
                price=price, iv=iv, realized_vol=rv_pct,
                iv_percentile=ivp, iv_rank=ivr,
                rsi14=inputs["rsi"], sma50=inputs["sma50"],
                sma200=indicators.sma(closes, 200) if closes else None,
                is_vix=False, source="public",
                raw={"closes": len(closes)},
            ))
            objs.append(SignalHistory(
                underlying_conid=conid, symbol=symbol, ts=ts,
                composite_score=sig["composite"], verdict=sig["verdict"],
                sub_scores=sig["sub_scores"], inputs=inputs, weights=sig["weights"],
            ))
    except Exception as exc:
        log.warning("yfinance_batch_failed", error=str(exc))

        for conid, symbol in tracked.items():
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.conid == conid)
                    .order_by(desc(MarketSnapshot.snapshot_ts))
                    .limit(1)
                )
                last = row.scalar_one_or_none()
            if last:
                objs.append(MarketSnapshot(
                    conid=conid, symbol=symbol, snapshot_ts=ts,
                    price=float(last.price) if last.price is not None else None,
                    iv=float(last.iv) if last.iv is not None else None,
                    realized_vol=float(last.realized_vol) if last.realized_vol is not None else None,
                    iv_percentile=float(last.iv_percentile) if last.iv_percentile is not None else None,
                    iv_rank=float(last.iv_rank) if last.iv_rank is not None else None,
                    rsi14=float(last.rsi14) if last.rsi14 is not None else None,
                    sma50=float(last.sma50) if last.sma50 is not None else None,
                    sma200=float(last.sma200) if last.sma200 is not None else None,
                    is_vix=False, source="cache",
                    raw={"fallback": "yfinance_batch_failed"},
                ))

    if objs:
        async with AsyncSessionLocal() as session:
            session.add_all(objs)
            await session.commit()
        log.info("public_price_refresh", underlyings=len(tracked), cached=sum(1 for o in objs if isinstance(o, MarketSnapshot) and o.source == "cache"))
        await broadcast_event("market")
        await broadcast_event("signals")
