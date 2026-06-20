"""Portfolio-level risk math.

Three first-order, **LINEAR** estimates for the risk panel:
  * beta-weighted dollar delta (all exposure expressed in index terms),
  * a stress P&L for a configurable index move (default −10%),
  * cash-secured-put assignment coverage (cash vs. total put obligation).

Pure functions over ORM rows so they're unit-testable with plain fixtures.
"""
from __future__ import annotations

from app.analytics.defaults import DEFAULT_SETTINGS
from app.db.models import AccountSnapshot, MarketSnapshot, PositionSnapshot


def _multiplier(sec_type: str | None) -> float:
    """Options trade in lots of 100; shares are 1:1."""
    return 1.0 if (sec_type or "").upper() == "STK" else 100.0


def _position_delta(p: PositionSnapshot) -> float | None:
    """Per-share delta. Stock is delta 1; options use the IBKR Greek (None if absent)."""
    if (p.sec_type or "").upper() == "STK":
        return 1.0
    return float(p.delta) if p.delta is not None else None


def compute_risk(
    positions: list[PositionSnapshot],
    markets: list[MarketSnapshot],
    account: AccountSnapshot | None,
    settings: dict | None = None,
) -> dict:
    cfg = (settings or DEFAULT_SETTINGS).get("risk") or DEFAULT_SETTINGS["risk"]
    scenario_move = float(cfg.get("scenario_move", -0.10))
    index_symbol = cfg.get("index_symbol", "QQQ")
    beta_map = {str(k).upper(): float(v) for k, v in (cfg.get("beta_map") or {}).items()}

    price_by_symbol = {
        m.symbol: float(m.price)
        for m in markets
        if m.symbol and m.price is not None
    }

    beta_weighted = 0.0
    gross = 0.0
    contributions: list[dict] = []

    for p in positions:
        if not p.symbol or p.position in (None, 0):
            continue
        delta = _position_delta(p)
        if delta is None:
            continue
        # Underlying spot: a tracked market snapshot, else (for a stock) its own mark.
        spot = price_by_symbol.get(p.symbol)
        if spot is None and (p.sec_type or "").upper() == "STK":
            spot = float(p.mark) if p.mark is not None else None
        if spot is None:
            continue  # can't value the exposure without a price

        share_delta = delta * float(p.position) * _multiplier(p.sec_type)
        dollar_delta = share_delta * spot
        beta = beta_map.get(p.symbol.upper(), 1.0)
        bw = dollar_delta * beta

        beta_weighted += bw
        gross += dollar_delta
        contributions.append(
            {
                "symbol": p.symbol,
                "sec_type": p.sec_type,
                "right": p.right,
                "strike": float(p.strike) if p.strike is not None else None,
                "beta": beta,
                "delta_dollars": dollar_delta,
                "beta_weighted_delta_dollars": bw,
                "scenario_pnl": bw * scenario_move,
            }
        )

    scenario_pnl = beta_weighted * scenario_move

    # Cash-secured-put assignment coverage: total cash needed if every short put
    # were assigned (strike × 100 × contracts), vs. cash on hand.
    total_obligation = 0.0
    short_puts = 0
    for p in positions:
        right = (p.right or "").upper()
        if (
            p.position is not None
            and float(p.position) < 0
            and right in ("P", "PUT")
            and p.strike is not None
        ):
            total_obligation += float(p.strike) * 100.0 * abs(float(p.position))
            short_puts += 1

    cash = float(account.cash) if account and account.cash is not None else None
    net_liq = (
        float(account.net_liquidation)
        if account and account.net_liquidation is not None
        else None
    )
    coverage_ratio = (
        cash / total_obligation if cash is not None and total_obligation > 0 else None
    )

    contributions.sort(key=lambda c: abs(c["scenario_pnl"]), reverse=True)

    return {
        "scenario_move": scenario_move,
        "index_symbol": index_symbol,
        "net_liquidation": net_liq,
        "beta_weighted_delta_dollars": beta_weighted,
        "gross_delta_dollars": gross,
        "scenario_pnl": scenario_pnl,
        "scenario_pnl_pct": (scenario_pnl / net_liq) if net_liq else None,
        "assignment": {
            "total_obligation": total_obligation,
            "cash": cash,
            "coverage_ratio": coverage_ratio,
            "short_put_count": short_puts,
        },
        "positions": contributions,
    }
