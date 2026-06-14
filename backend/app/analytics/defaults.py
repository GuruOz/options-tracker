"""Default user-configurable settings, seeded into the `settings` table.

These reproduce the prototype's reference numbers (see README appendix) and are
fully editable at runtime via the settings API.
"""
from __future__ import annotations

DEFAULT_SETTINGS: dict = {
    "signal": {
        "weights": {
            "iv_percentile": 0.34,
            "variance_premium": 0.20,
            "trend": 0.26,
            "rsi_drawdown": 0.20,
        },
        "thresholds": {"favorable": 66, "selective": 45},
        # A +20% (IV - RV)/RV spread maps to ~100 on the variance sub-score.
        "variance_premium_full_spread": 0.20,
    },
    "alerts": {
        "take_profit_pct": 0.70,   # ~70% of premium captured
        "expiry_dte": 2,           # expiry imminent at <= 2 DTE
        "near_strike_cushion": 0.03,  # < 3% cushion to strike
    },
    "bs": {
        # Black-Scholes fallback is used ONLY when a live IBKR Greek is missing.
        "risk_free_rate": 0.045,
    },
    "risk": {
        "scenario_move": -0.10,    # the -10% stress move
        "index_symbol": "QQQ",     # beta-weighting reference index
        # Rough Nasdaq-equivalent betas; prefer live beta-weighted delta where possible.
        "beta_map": {
            "TQQQ": 3.0, "QLD": 2.0, "SSO": 1.7,
            "QQQ": 1.0, "QQQM": 1.0,
            "SPY": 0.85, "SPYM": 0.85, "VOO": 0.85,
        },
    },
    # User-chosen underlyings to track, e.g. [{"symbol": "QQQ", "conid": 320227571}].
    "underlyings": [],
}
