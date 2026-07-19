"""Live FX rates for cross-currency aggregation.

The household can hold accounts with different base currencies (e.g. USD and
SGD), and combined views need one display currency. Rates come from IBKR's
gateway when any session is authenticated (market data is identical whoever
asks), falling back to Yahoo Finance's public quote, with an in-process TTL
cache plus a never-expiring last-known copy so a feed outage degrades to a
stale rate (flagged as such) instead of suppressed figures.

In-process cache only — a restart refetches. Rates are spot snapshots; callers
converting historical figures accept that simplification.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.gateways import any_authenticated_client
from app.core.logging import get_logger

log = get_logger("core.fx")

_FX_TTL_SECONDS = 600
# (src, dst) -> (rate, monotonic fetch time). `_last_known` never expires and
# is re-served as source="cache" when both feeds are down.
_cache: dict[tuple[str, str], tuple["FxRate", float]] = {}
_last_known: dict[tuple[str, str], "FxRate"] = {}
# Throttle retries against dead feeds the same way market.py throttles yfinance.
_fetch_attempt: dict[tuple[str, str], float] = {}
_semaphore = asyncio.Semaphore(2)


@dataclass
class FxRate:
    pair: str  # "USD/SGD"
    rate: float  # value of 1 unit of source, in target
    as_of: datetime
    source: str  # "ibkr" | "public" | "cache" | "identity"

    def as_dict(self) -> dict:
        return {
            "pair": self.pair,
            "rate": self.rate,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "source": self.source,
        }


def _valid(rate) -> bool:
    try:
        return rate is not None and float(rate) > 0
    except (TypeError, ValueError):
        return False


async def _fetch_ibkr_rate(src: str, dst: str) -> float | None:
    client = any_authenticated_client()
    if client is None:
        return None
    try:
        payload = await client.exchange_rate(src, dst)
    except Exception as exc:  # gateway down / not authenticated / bad payload
        log.debug("ibkr fx %s/%s failed: %s", src, dst, exc)
        return None
    rate = (payload or {}).get("rate")
    return float(rate) if _valid(rate) else None


def _fetch_yf_rate_sync(src: str, dst: str) -> float | None:
    """Blocking yfinance call — always run via asyncio.to_thread."""
    import yfinance as yf

    hist = yf.Ticker(f"{src}{dst}=X").history(period="1d")
    if hist.empty:
        return None
    rate = float(hist["Close"].iloc[-1])
    return rate if _valid(rate) else None


def _fresh(key: tuple[str, str]) -> FxRate | None:
    hit = _cache.get(key)
    if hit is not None and time.monotonic() - hit[1] < _FX_TTL_SECONDS:
        return hit[0]
    return None


def _store(key: tuple[str, str], rate: float, source: str) -> FxRate:
    fx = FxRate(
        pair=f"{key[0]}/{key[1]}",
        rate=rate,
        as_of=datetime.now(timezone.utc),
        source=source,
    )
    _cache[key] = (fx, time.monotonic())
    _last_known[key] = fx
    return fx


async def get_rate(src: str, dst: str) -> FxRate | None:
    """Resolve one pair: identity, fresh cache, IBKR, Yahoo, inverse, stale."""
    src, dst = src.upper(), dst.upper()
    if src == dst:
        return FxRate(
            pair=f"{src}/{dst}", rate=1.0,
            as_of=datetime.now(timezone.utc), source="identity",
        )
    key = (src, dst)

    fresh = _fresh(key)
    if fresh is not None:
        return fresh

    # Throttle full fetch attempts per pair so dead feeds aren't hammered on
    # every request; within the window we fall through to inverse/stale.
    now = time.monotonic()
    last_attempt = _fetch_attempt.get(key)
    if last_attempt is None or now - last_attempt >= _FX_TTL_SECONDS:
        _fetch_attempt[key] = now
        rate = await _fetch_ibkr_rate(src, dst)
        if rate is not None:
            return _store(key, rate, "ibkr")
        async with _semaphore:
            try:
                rate = await asyncio.to_thread(_fetch_yf_rate_sync, src, dst)
            except Exception as exc:
                log.debug("yahoo fx %s/%s failed: %s", src, dst, exc)
                rate = None
        if rate is not None:
            return _store(key, rate, "public")

    inverse = _fresh((dst, src)) or _last_known.get((dst, src))
    if inverse is not None and inverse.rate:
        return FxRate(
            pair=f"{src}/{dst}", rate=1.0 / inverse.rate,
            as_of=inverse.as_of, source=inverse.source,
        )

    stale = _last_known.get(key)
    if stale is not None:
        return FxRate(pair=stale.pair, rate=stale.rate, as_of=stale.as_of, source="cache")
    return None


async def rate_map(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], FxRate]:
    """Resolve a set of (src, dst) pairs, dropping the unresolvable ones."""
    out: dict[tuple[str, str], FxRate] = {}
    for src, dst in pairs:
        if not src or not dst:
            continue
        fx = await get_rate(src, dst)
        if fx is not None:
            out[(src.upper(), dst.upper())] = fx
    return out
