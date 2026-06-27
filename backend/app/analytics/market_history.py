"""Pure helpers for the market-context chart series.

Joins a daily close series with a rolling SMA overlay and the VIX series,
windowed to the most recent N points. No DB or network here, so it is fully
unit-testable with plain lists.
"""
from __future__ import annotations

from datetime import date

from app.analytics.indicators import sma


def rolling_sma(closes: list[float], window: int) -> list[float | None]:
    """Trailing simple moving average at each index (None until `window` points)."""
    out: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sma(closes[: i + 1], window))
    return out


def build_history_series(
    bars: list[tuple[date, float]],
    vix_by_date: dict[date, float] | None = None,
    *,
    sma_window: int = 50,
    sma200_window: int = 200,
    window_days: int | None = None,
) -> list[dict]:
    """Build ``[{date, close, sma, sma200, vix}]`` from ``(date, close)`` bars.

    Both SMAs are computed over the *full* series first (so the windowed head still
    carries an overlay), then the result is sliced to the last ``window_days``
    points. ``vix_by_date`` is joined by exact date; missing days yield ``None``.
    """
    clean = sorted(((d, c) for d, c in bars if c is not None), key=lambda b: b[0])
    closes = [c for _, c in clean]
    smas = rolling_sma(closes, sma_window)
    smas200 = rolling_sma(closes, sma200_window)
    vix_by_date = vix_by_date or {}

    points = [
        {
            "date": d,
            "close": c,
            "sma": smas[i],
            "sma200": smas200[i],
            "vix": vix_by_date.get(d),
        }
        for i, (d, c) in enumerate(clean)
    ]
    if window_days is not None and 0 <= window_days < len(points):
        points = points[-window_days:]
    return points
