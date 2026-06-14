"""The "Is now a good time to sell?" composite signal.

Transparent 0-100 score from four sub-scores, each clamped to 0-100, combined
with configurable weights. Missing sub-scores are dropped and the remaining
weights renormalised. Decision aid only — NOT a recommendation.
"""
from __future__ import annotations

from app.analytics.defaults import DEFAULT_SETTINGS


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def variance_premium_score(
    iv: float | None, rv: float | None, full_spread: float = 0.20
) -> float | None:
    """(IV - RV)/RV mapped so a +`full_spread` (e.g. +20%) richness ≈ 100."""
    if iv is None or not rv:
        return None
    spread = (iv - rv) / rv
    return _clamp(spread / full_spread * 100.0)


def trend_score(price: float | None, sma: float | None, band: float = 0.05) -> float | None:
    """Price vs SMA: at the SMA = 50; `band` above = 100, `band` below = 0."""
    if price is None or not sma:
        return None
    pct = (price - sma) / sma
    return _clamp(50.0 + (pct / band) * 50.0)


def rsi_drawdown_score(
    rsi: float | None, drawdown: float | None = None, dd_cap: float = 0.12
) -> float | None:
    """High in the 40-65 RSI band; low when oversold (<30) or overbought; a
    drawdown beyond `dd_cap` off the period high caps the score."""
    if rsi is None:
        return None
    if 40.0 <= rsi <= 65.0:
        score = 100.0
    elif rsi < 40.0:
        score = _clamp((rsi - 25.0) / 15.0 * 100.0)   # 25->0, 40->100
    else:
        score = _clamp((100.0 - rsi) / 35.0 * 100.0)  # 65->100, 100->0
    if drawdown is not None and drawdown > dd_cap:
        score = min(score, 30.0)
    return score


def compute_signal(inputs: dict, settings: dict | None = None) -> dict:
    """inputs: iv_percentile, iv, realized_vol, price, sma50, rsi, drawdown.

    Returns composite (0-100 or None), verdict, the sub-scores, and the weights
    actually used — everything needed to persist a reproducible signal_history row.
    """
    cfg = (settings or DEFAULT_SETTINGS)["signal"]
    weights = cfg["weights"]
    thresholds = cfg["thresholds"]
    full_spread = cfg.get("variance_premium_full_spread", 0.20)

    ivp = inputs.get("iv_percentile")
    sub_scores = {
        "iv_percentile": _clamp(ivp) if ivp is not None else None,
        "variance_premium": variance_premium_score(
            inputs.get("iv"), inputs.get("realized_vol"), full_spread
        ),
        "trend": trend_score(inputs.get("price"), inputs.get("sma50")),
        "rsi_drawdown": rsi_drawdown_score(inputs.get("rsi"), inputs.get("drawdown")),
    }

    weighted = 0.0
    weight_sum = 0.0
    for key, value in sub_scores.items():
        if value is not None:
            weighted += value * weights[key]
            weight_sum += weights[key]
    composite = weighted / weight_sum if weight_sum > 0 else None

    verdict = None
    if composite is not None:
        if composite >= thresholds["favorable"]:
            verdict = "FAVORABLE"
        elif composite >= thresholds["selective"]:
            verdict = "SELECTIVE"
        else:
            verdict = "WAIT"

    return {
        "composite": composite,
        "verdict": verdict,
        "sub_scores": sub_scores,
        "weights": weights,
    }
