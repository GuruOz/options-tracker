"""Pure market-indicator math (no numpy dependency).

All functions take plain lists of closes (oldest -> newest) and return None when
there isn't enough data, so callers can render "n/a" rather than guess.
"""
from __future__ import annotations

import math
from statistics import fmean, pstdev


def sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return fmean(values[-window:])


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gains = sum(c for c in changes if c > 0)
    losses = -sum(c for c in changes if c < 0)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def log_returns(closes: list[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def realized_vol(
    closes: list[float],
    window: int = 20,
    annualize: bool = True,
    periods_per_year: int = 252,
) -> float | None:
    series = closes[-(window + 1):] if len(closes) > window else closes
    rets = log_returns(series)
    if len(rets) < 2:
        return None
    vol = pstdev(rets)
    return vol * math.sqrt(periods_per_year) if annualize else vol


def drawdown_from_high(closes: list[float], lookback: int | None = None) -> float | None:
    """Fractional drawdown of the latest close from the period high (0..1)."""
    series = closes[-lookback:] if lookback else closes
    if not series:
        return None
    high = max(series)
    if high <= 0:
        return None
    return (high - series[-1]) / high


def iv_rank(current_iv: float | None, iv_series: list[float]) -> float | None:
    """Where current IV sits between the min and max of the series, 0..100."""
    s = [x for x in iv_series if x is not None]
    if current_iv is None or len(s) < 2:
        return None
    lo, hi = min(s), max(s)
    if hi == lo:
        return None
    return max(0.0, min(1.0, (current_iv - lo) / (hi - lo))) * 100.0


def iv_percentile(current_iv: float | None, iv_series: list[float]) -> float | None:
    """Percent of observations strictly below current IV, 0..100."""
    s = [x for x in iv_series if x is not None]
    if current_iv is None or not s:
        return None
    below = sum(1 for x in s if x < current_iv)
    return below / len(s) * 100.0
