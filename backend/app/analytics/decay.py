"""Theta-decay curve for a single option: modeled extrinsic value vs. time to expiry.

Pure functions — given an option's strike/right/spot/IV and current DTE, produce a
Black-Scholes extrinsic-value curve from today down to expiry. The curve holds spot
and IV constant and only walks time forward, so it isolates time decay (theta) the
way the cockpit wants to show it: "how the remaining time value bleeds out if the
underlying just sits here."

The shape is anchored to the position's real extrinsic value at the current DTE when
that is available, so the curve passes through the number shown in the table rather
than a pure model estimate that may disagree on magnitude.
"""
from __future__ import annotations

import math

# Flat risk-free rate. The decay *shape* is essentially insensitive to r for the
# short tenors we deal with; a constant keeps the curve deterministic and testable.
_RISK_FREE = 0.04
_MAX_POINTS = 24


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _intrinsic(is_call: bool, S: float, K: float) -> float:
    return max(0.0, (S - K) if is_call else (K - S))


def bs_price(is_call: bool, S: float, K: float, t_years: float, sigma: float, r: float = _RISK_FREE) -> float:
    """Black-Scholes price per share. Falls back to intrinsic at/after expiry."""
    if t_years <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return _intrinsic(is_call, S, K)
    vol_t = sigma * math.sqrt(t_years)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * t_years) / vol_t
    d2 = d1 - vol_t
    disc = math.exp(-r * t_years)
    if is_call:
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _extrinsic(is_call: bool, S: float, K: float, t_years: float, sigma: float, r: float = _RISK_FREE) -> float:
    return max(0.0, bs_price(is_call, S, K, t_years, sigma, r) - _intrinsic(is_call, S, K))


def _normalize_iv(iv: float) -> float:
    """IBKR's IV field is a percent (e.g. 23.0 == 23%); convert to a decimal vol.

    Guard both scales: a value > 3 can only be a percentage (300%+ vol is absurd),
    while <= 3 is already a fraction.
    """
    return iv / 100.0 if iv > 3.0 else iv


def theta_decay_curve(
    right: str | None,
    strike: float | None,
    underlying_price: float | None,
    iv: float | None,
    dte: int | None,
    *,
    anchor_extrinsic: float | None = None,
    max_points: int = _MAX_POINTS,
) -> list[dict] | None:
    """Modeled extrinsic value per share at each step from `dte` down to 0.

    Returns ``[{"dte": int, "extrinsic": float}, ...]`` newest-expiry-first (current
    DTE first, 0 last), or ``None`` when the inputs can't support a model (missing
    spot/IV/strike, expired, or non-positive vol). When ``anchor_extrinsic`` is a
    *positive* value and the model is positive at the current DTE, the whole curve is
    scaled to pass through that real value. A non-positive (or missing) anchor is
    ignored — see the anchoring block for why.
    """
    if right is None or strike is None or underlying_price is None or iv is None or dte is None:
        return None
    # Inputs may arrive as Decimal from the DB; coerce to float so the BS math
    # (which mixes in float literals) doesn't blow up on Decimal/float operations.
    dte = int(dte)
    strike = float(strike)
    underlying_price = float(underlying_price)
    if dte <= 0 or underlying_price <= 0 or strike <= 0:
        return None
    sigma = _normalize_iv(float(iv))
    if sigma <= 0:
        return None

    is_call = right.upper().startswith("C")

    # Sample integer DTE days, always including the current DTE and 0.
    step = max(1, math.ceil(dte / max_points))
    days = list(range(dte, -1, -step))
    if days[-1] != 0:
        days.append(0)

    curve = [
        {"dte": d, "extrinsic": _extrinsic(is_call, underlying_price, strike, d / 365.0, sigma)}
        for d in days
    ]

    # Anchor the curve to the position's real extrinsic at the current DTE so it lines
    # up with the cockpit's Extrinsic ($) column instead of drifting on model error.
    #
    # Only anchor to a *positive* extrinsic. A non-positive anchor means the live mark
    # is at or below intrinsic (a stale or crossed quote on a deep-ITM option, where
    # the table clamps extrinsic to 0). Scaling by 0 would flatten every point to zero
    # and produce a misleading $0 chart even though the option clearly still has time
    # value (theta != 0). In that case we leave the unscaled Black-Scholes curve as a
    # best-effort *modeled* estimate; the frontend labels it as such.
    if anchor_extrinsic is not None and float(anchor_extrinsic) > 1e-9:
        modeled_now = curve[0]["extrinsic"]
        if modeled_now > 1e-9:
            scale = float(anchor_extrinsic) / modeled_now
            for pt in curve:
                pt["extrinsic"] *= scale

    return [{"dte": pt["dte"], "extrinsic": round(pt["extrinsic"], 4)} for pt in curve]
