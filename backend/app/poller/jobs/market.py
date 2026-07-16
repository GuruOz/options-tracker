"""Poll underlying history + IV, compute indicators and the composite signal.

Tracked underlyings are the UNION of every account's watchlist: market data is
conid-keyed and shared, so one fetch serves whoever is watching that symbol.

Two modes:
  * refresh_public_prices — yfinance fallback, runs WITHOUT IBKR auth
  * poll_market — IBKR-sourced snapshots, requires any active user session
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select

from app.analytics import indicators
from app.analytics.signal import compute_signal
from app.clients.ibkr import IBKRAuthError, IBKRError
from app.clients.ibkr.fields import UNDERLYING_FIELD_CODES
from app.clients.ibkr.normalize import (
    parse_history,
    parse_history_bars,
    parse_underlying_quote,
)
from app.core.gateways import any_authenticated_client
from app.core.logging import get_logger
from app.core.state import broadcast_event
from app.db import repo
from app.db.base import AsyncSessionLocal
from app.db.models import AccountSetting, MarketSnapshot, PositionSnapshot, Setting, SignalHistory


log = get_logger("poller.market")

_MIN_IV_HISTORY = 5  # observations before IV rank/percentile is meaningful

# VIX is market-wide, not tied to a tracked underlying, so it is cached under a
# synthetic conid with is_vix=True and queried by that flag.
VIX_CONID = -1
VIX_SYMBOL = "^VIX"


async def _tracked_underlyings() -> dict[int, str]:
    """`{conid: symbol}` — the union of every account's watchlist.

    Each user curates their own list, but the resulting market data is
    conid-keyed and shared, so the poller fetches every symbol anyone tracks.
    """
    async with AsyncSessionLocal() as session:
        rows = await session.execute(select(AccountSetting.data))

    tracked: dict[int, str] = {}
    for (data,) in rows.all():
        for u in (data or {}).get("underlyings", []):
            try:
                tracked[int(u["conid"])] = u.get("symbol") or str(u["conid"])
            except (KeyError, ValueError, TypeError):
                continue
    return tracked


async def _position_underlyings() -> dict[int, str]:
    """``{underlying_conid: symbol}`` for the underlyings of currently-held options.

    Option position rows carry their underlying in ``raw`` (``undConid``/``undSym``),
    so we can fetch a spot for every underlier we actually hold options on — not
    just the user-configured watchlists. Without this, an option on a symbol the
    user never added to the tracked list never gets an underlying spot and
    silently drops out of the decay / P&L panels.

    The latest batch is resolved PER ACCOUNT: a single global max(snapshot_ts)
    belongs to whichever account polled most recently, which would silently drop
    every other user's option underlyings.
    """
    async with AsyncSessionLocal() as session:
        account_ids = await repo.all_account_ids(session)

        positions: list[PositionSnapshot] = []
        for account_id in account_ids:
            max_ts = (
                select(PositionSnapshot.snapshot_ts)
                .where(PositionSnapshot.account_id == account_id)
                .order_by(desc(PositionSnapshot.snapshot_ts))
                .limit(1)
                .scalar_subquery()
            )
            rows = await session.execute(
                select(PositionSnapshot).where(
                    PositionSnapshot.account_id == account_id,
                    PositionSnapshot.snapshot_ts == max_ts,
                    PositionSnapshot.sec_type.in_(("OPT", "FOP", "WAR")),
                )
            )
            positions.extend(rows.scalars().all())

    out: dict[int, str] = {}
    for p in positions:
        raw = p.raw or {}
        try:
            conid = int(raw.get("undConid"))
        except (TypeError, ValueError):
            continue
        symbol = raw.get("undSym") or p.symbol
        if conid and symbol:
            out[conid] = symbol
    return out


async def _iv_history(conid: int, limit: int = 252) -> list[float]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(MarketSnapshot.iv)
            .where(MarketSnapshot.conid == conid, MarketSnapshot.iv.is_not(None))
            .order_by(desc(MarketSnapshot.snapshot_ts))
            .limit(limit)
        )
        return [float(v) for (v,) in rows.all() if v is not None]


async def poll_market() -> None:
    # Market data is account-agnostic (conid-keyed), so any authenticated
    # session can fetch it on everyone's behalf.
    client = any_authenticated_client()
    if client is None:
        return

    async with AsyncSessionLocal() as session:
        settings_row = await session.get(Setting, 1)
    settings = settings_row.data if settings_row else None

    tracked = await _tracked_underlyings()
    tracked.update(await _position_underlyings())  # cover underlyings we hold options on
    if not tracked:
        return

    ts = datetime.now(timezone.utc)
    objs: list = []
    daily_rows: list[dict] = []
    for conid, symbol in tracked.items():
        try:
            hist = await client.market_history(conid, period="1y", bar="1d")
        except (IBKRError, IBKRAuthError) as exc:
            log.warning("history_failed", symbol=symbol, error=str(exc))
            hist = {}
        closes = parse_history(hist)
        for d, c in parse_history_bars(hist):
            daily_rows.append({
                "conid": conid, "symbol": symbol, "bar_date": d,
                "close": c, "is_vix": False, "source": "ibkr",
            })

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

    if daily_rows:
        async with AsyncSessionLocal() as session:
            await repo.upsert_daily_bars(session, daily_rows)

    if objs:
        async with AsyncSessionLocal() as session:
            session.add_all(objs)
            await session.commit()
        log.info("market_snapshot", underlyings=len(tracked), daily_bars=len(daily_rows))
        await broadcast_event("market")
        await broadcast_event("signals")


def _yf_daily_pairs(hist) -> list[tuple]:
    """``(date, close)`` pairs from a yfinance history DataFrame (NaN-safe)."""
    import pandas as pd

    pairs: list[tuple] = []
    try:
        for ts, close in zip(hist.index, hist["Close"]):
            if close is None or pd.isna(close):
                continue
            try:
                d = ts.date()
            except Exception:
                continue
            pairs.append((d, float(close)))
    except Exception:
        return []
    return pairs


async def _vix_daily_rows() -> list[dict]:
    """Fetch the VIX 1y daily series from yfinance for the market-context chart."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        hist = yf.Ticker(VIX_SYMBOL).history(period="1y")
    except Exception as exc:
        log.warning("vix_fetch_failed", error=str(exc))
        return []
    return [
        {"conid": VIX_CONID, "symbol": VIX_SYMBOL, "bar_date": d,
         "close": c, "is_vix": True, "source": "public"}
        for d, c in _yf_daily_pairs(hist)
    ]


async def refresh_public_prices() -> None:
    """Public price refresh via yfinance — runs without IBKR auth.

    Fetches current price and IV for tracked underlyings from yfinance
    and writes to MarketSnapshot with source="public". Falls back to
    latest cached data on failure.
    """
    tracked = await _tracked_underlyings()
    tracked.update(await _position_underlyings())  # cover underlyings we hold options on
    if not tracked:
        return

    symbols = list(tracked.values())
    ts = datetime.now(timezone.utc)
    objs: list = []
    daily_rows: list[dict] = []

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
                    for d, c in _yf_daily_pairs(hist):
                        daily_rows.append({
                            "conid": conid, "symbol": symbol, "bar_date": d,
                            "close": c, "is_vix": False, "source": "public",
                        })
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

    daily_rows.extend(await _vix_daily_rows())
    if daily_rows:
        async with AsyncSessionLocal() as session:
            await repo.upsert_daily_bars(session, daily_rows)

    if objs:
        async with AsyncSessionLocal() as session:
            session.add_all(objs)
            await session.commit()
        log.info("public_price_refresh", underlyings=len(tracked), cached=sum(1 for o in objs if isinstance(o, MarketSnapshot) and o.source == "cache"), daily_bars=len(daily_rows))
        await broadcast_event("market")
        await broadcast_event("signals")
