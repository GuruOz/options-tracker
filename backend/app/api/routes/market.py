import asyncio
import hashlib
import re
import time
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.market_history import build_history_series
from app.api.deps import account_scope
from app.db import repo
from app.db.base import get_session
from app.schemas.responses import (
    MarketHistoryOut,
    MarketHistoryPointOut,
    MarketOut,
    SignalOut,
    SignalPointOut,
)

router = APIRouter(tags=["market"])

_SMA_WINDOW = 50
_SMA_200 = 200

# IBKR/yfinance tickers: letters, digits, and the handful of punctuation marks
# real symbols use (BRK.B, ^VIX, EURUSD=X). Guards both the on-demand yfinance
# fetch and cached-DB reads against being used as an injection vector.
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,12}$")


def validate_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail=f"Invalid symbol '{symbol}'.")
    return symbol


# Throttle on-demand yfinance fetches: skip a re-fetch of the same symbol
# within this window, and cap how many fetches can run concurrently so a burst
# of unique symbols can't stall the event loop or hammer Yahoo's endpoint.
_YF_REFETCH_SECONDS = 600
_yf_last_fetch: dict[str, float] = {}
_yf_semaphore = asyncio.Semaphore(2)


def _synthetic_conid(symbol: str) -> int:
    """Stable negative int for symbols without an IBKR conid (yfinance-only)."""
    digest = int(hashlib.md5(symbol.upper().encode()).hexdigest()[:8], 16)
    return -(digest % (10**9) + 2)  # always negative, never -1 (VIX) or 0


def _fetch_yf_history_sync(symbol: str) -> list[dict]:
    """Blocking yfinance call — always run this via asyncio.to_thread."""
    import pandas as pd
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="2y")
    if hist.empty:
        return []
    conid = _synthetic_conid(symbol)
    rows = []
    for ts, close in zip(hist.index, hist["Close"]):
        if close is None or pd.isna(close):
            continue
        try:
            d = ts.date()
        except Exception:
            continue
        rows.append({
            "conid": conid, "symbol": symbol.upper(), "bar_date": d,
            "close": float(close), "is_vix": False, "source": "public",
        })
    return rows


async def _fetch_yf_bars(symbol: str) -> list[dict]:
    """Fetch 2 years of daily closes from yfinance for an arbitrary symbol.

    Throttled to one fetch per symbol per _YF_REFETCH_SECONDS and at most 2
    concurrent fetches — a burst of distinct on-demand symbols must not stall
    the event loop or hammer Yahoo's endpoint.
    """
    now = time.monotonic()
    last = _yf_last_fetch.get(symbol)
    if last is not None and now - last < _YF_REFETCH_SECONDS:
        return []
    async with _yf_semaphore:
        _yf_last_fetch[symbol] = time.monotonic()
        try:
            return await asyncio.to_thread(_fetch_yf_history_sync, symbol)
        except ImportError:
            return []
        except Exception:
            return []


def _build_points(
    pairs: list[tuple], vix_by_date: dict, window_days: int
) -> list[MarketHistoryPointOut]:
    """Compute SMA50+SMA200 over the full series, slice to the visible window."""
    series = build_history_series(
        pairs, vix_by_date, sma_window=_SMA_WINDOW, sma200_window=_SMA_200
    )
    cutoff = date.today() - timedelta(days=window_days)
    return [
        MarketHistoryPointOut(
            date=p["date"], close=p["close"],
            sma=p["sma"], sma200=p["sma200"], vix=p["vix"],
        )
        for p in series
        if p["date"] >= cutoff
    ]


@router.get("/market", response_model=list[MarketOut])
async def get_market(db: AsyncSession = Depends(get_session)):
    # Latest *priced* row per symbol: a null-price IBKR poll must not blank a spot
    # a good yfinance refresh just wrote (see repo.latest_priced_market).
    return await repo.latest_priced_market(db)


@router.get("/market/history", response_model=MarketHistoryOut)
async def get_market_history(
    conid: int, months: int = 12, db: AsyncSession = Depends(get_session)
):
    """Daily close series for the market-context chart: price + 50-day SMA + 200-day SMA + VIX."""
    months = max(1, min(months, 24))
    window_days = months * 31
    lead_days = _SMA_200 * 2  # enough lead-in for both SMA50 and SMA200
    since = date.today() - timedelta(days=window_days + lead_days)

    bars = await repo.daily_bar_series(db, conid, since)
    pairs = [(b.bar_date, float(b.close)) for b in bars if b.close is not None]
    symbol = next((b.symbol for b in bars if b.symbol), None)

    vix_rows = await repo.vix_series(db, since)
    vix_by_date = {v.bar_date: float(v.close) for v in vix_rows if v.close is not None}

    points = _build_points(pairs, vix_by_date, window_days)
    market_row = await repo.market_snapshot_by_symbol(db, symbol) if symbol else None
    return MarketHistoryOut(
        conid=conid, symbol=symbol, months=months, sma_window=_SMA_WINDOW,
        points=points,
        market=MarketOut.model_validate(market_row) if market_row else None,
    )


@router.get("/market/history/by-symbol", response_model=MarketHistoryOut)
async def get_market_history_by_symbol(
    symbol: str, months: int = 12, db: AsyncSession = Depends(get_session)
):
    """Like /market/history but accepts a symbol string.

    Reads from the daily-bar cache first. If no rows exist for this symbol,
    fetches 2 years of history from yfinance on-demand, stores it, then returns.
    This lets the user chart any ticker, not just tracked underlyings.
    """
    symbol = validate_symbol(symbol)

    months = max(1, min(months, 24))
    window_days = months * 31
    lead_days = _SMA_200 * 2
    since = date.today() - timedelta(days=window_days + lead_days)

    bars = await repo.daily_bar_series_by_symbol(db, symbol, since)

    if not bars:
        yf_rows = await _fetch_yf_bars(symbol)
        if not yf_rows:
            raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")
        await repo.upsert_daily_bars(db, yf_rows)
        bars = await repo.daily_bar_series_by_symbol(db, symbol, since)

    if not bars:
        raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")

    conid = bars[0].conid
    pairs = [(b.bar_date, float(b.close)) for b in bars if b.close is not None]

    vix_rows = await repo.vix_series(db, since)
    vix_by_date = {v.bar_date: float(v.close) for v in vix_rows if v.close is not None}

    points = _build_points(pairs, vix_by_date, window_days)
    market_row = await repo.market_snapshot_by_symbol(db, symbol)
    return MarketHistoryOut(
        conid=conid, symbol=symbol, months=months, sma_window=_SMA_WINDOW,
        points=points,
        market=MarketOut.model_validate(market_row) if market_row else None,
    )


@router.get("/signals", response_model=list[SignalOut])
async def get_signals(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    """Signals for the scoped account's watchlist (the union, for all accounts).

    The signals themselves are market-wide; the watchlist only decides which of
    them this user cares to see.
    """
    scope = set(accounts)
    tracked_conids = set()
    for row in await repo.all_account_settings(db):
        if row.account_id not in scope:
            continue
        for u in (row.data or {}).get("underlyings", []):
            try:
                tracked_conids.add(int(u["conid"]))
            except (KeyError, ValueError, TypeError):
                pass
    rows = await repo.latest_signals(db)
    result = [r for r in rows if r.underlying_conid in tracked_conids]
    market_rows = await repo.latest_market(db)
    market_by_conid = {m.conid: m.source for m in market_rows}
    for r in result:
        r.source = market_by_conid.get(r.underlying_conid)
    return result


@router.get("/signal/history", response_model=list[SignalPointOut])
async def get_signal_history(conid: int, db: AsyncSession = Depends(get_session)):
    return await repo.signal_series(db, conid)
