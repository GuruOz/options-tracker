"""Black-Scholes fallback Greeks — used ONLY when IBKR doesn't supply a live one.

Conventions: theta is per calendar day, vega is per 1 vol-point (1%). sigma is a
decimal (0.25 = 25%). Results are labelled greeks_source='bs_est' by callers.
"""
from __future__ import annotations

import math
from datetime import date

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def year_fraction(expiry: date, today: date) -> float:
    """Calendar days to expiry as a fraction of a 365-day year (>= 0)."""
    return max((expiry - today).days, 0) / 365.0


def bs_greeks(
    spot: float | None,
    strike: float | None,
    t: float | None,
    sigma: float | None,
    right: str | None,
    r: float = 0.045,
) -> dict | None:
    """Return {price, delta, gamma, theta, vega} or None if inputs are invalid."""
    if None in (spot, strike, t, sigma):
        return None
    if spot <= 0 or strike <= 0 or t <= 0 or sigma <= 0:
        return None

    is_put = (right or "C").upper().startswith("P")
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf = _norm_pdf(d1)
    discount = math.exp(-r * t)

    if is_put:
        price = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_annual = (
            -(spot * pdf * sigma) / (2.0 * sqrt_t)
            + r * strike * discount * _norm_cdf(-d2)
        )
    else:
        price = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_annual = (
            -(spot * pdf * sigma) / (2.0 * sqrt_t)
            - r * strike * discount * _norm_cdf(d2)
        )

    gamma = pdf / (spot * sigma * sqrt_t)
    vega = spot * pdf * sqrt_t
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta_annual / 365.0,  # per calendar day
        "vega": vega / 100.0,           # per 1 vol-point
    }
