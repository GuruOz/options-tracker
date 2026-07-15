"""Business logic to enrich raw PositionSnapshot rows with derived cockpit metrics."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.analytics.decay import theta_decay_curve
from app.db.models import PositionSnapshot, MarketSnapshot
from app.schemas.responses import PositionOut


def get_intrinsic_value(right: str | None, strike: float | None, underlying_price: float | None) -> float:
    if not right or strike is None or underlying_price is None:
        return 0.0
    r = right.upper()
    s = float(strike)
    u = float(underlying_price)
    if r == "P":
        return max(0.0, s - u)
    elif r == "C":
        return max(0.0, u - s)
    return 0.0


def enrich_positions(
    positions: list[PositionSnapshot],
    markets: list[MarketSnapshot],
    roll_chains: dict[int, dict],
) -> list[PositionOut]:
    """`roll_chains`: conid -> its open chain's id and cycle economics
    (see `repo.open_roll_chains`). Positions outside a chain get leg-level
    metrics only."""
    market_by_symbol = {m.symbol: m for m in markets if m.symbol}
    today = datetime.now(timezone.utc).date()

    # What it would cost to buy back every open short in a chain. Summed per
    # chain so that if one chain holds more than one short leg, each row nets
    # against all of them rather than claiming the chain's whole credit against
    # its own leg.
    chain_buyback: dict[str, float] = {}
    for p in positions:
        info = roll_chains.get(p.conid)
        if (
            info is not None
            and p.mark is not None
            and p.position is not None
            and float(p.position) < 0
        ):
            cost = float(p.mark) * 100.0 * abs(float(p.position))
            chain_buyback[info["chain_id"]] = chain_buyback.get(info["chain_id"], 0.0) + cost

    out = []

    for p in positions:
        # Convert to dictionary (similar to what Pydantic from_attributes does) to use as base
        data: dict[str, Any] = {
            "conid": p.conid,
            "symbol": p.symbol,
            "sec_type": p.sec_type,
            "right": p.right,
            "strike": p.strike,
            "expiry": p.expiry,
            "position": p.position,
            "avg_cost": p.avg_cost,
            "mark": p.mark,
            "market_value": p.market_value,
            "unrealized_pnl": p.unrealized_pnl,
            "delta": p.delta,
            "gamma": p.gamma,
            "theta": p.theta,
            "vega": p.vega,
            "iv": p.iv,
            "greeks_source": p.greeks_source,
            "snapshot_ts": p.snapshot_ts,
        }

        # Roll chain
        chain = roll_chains.get(p.conid)
        data["chain_id"] = chain["chain_id"] if chain else None

        # DTE
        if p.expiry:
            dte = (p.expiry - today).days
            data["dte"] = max(0, dte)
        else:
            data["dte"] = None

        # Underlying spot price (only if we track this underlier).
        underlying_price = None
        if p.symbol and p.symbol in market_by_symbol:
            underlying_price = market_by_symbol[p.symbol].price
        data["underlying_price"] = (
            float(underlying_price) if underlying_price is not None else None
        )

        # Intrinsic / extrinsic split (per share). We need the underlying spot to
        # split the mark; without it, report None rather than fabricating a 0
        # intrinsic — that would mislabel a deep-ITM option as "all extrinsic".
        if (
            p.sec_type in ("OPT", "FOP", "WAR")
            and p.mark is not None
            and underlying_price is not None
        ):
            intrinsic = get_intrinsic_value(p.right, p.strike, underlying_price)
            data["intrinsic_value"] = intrinsic
            data["extrinsic_value"] = max(0.0, float(p.mark) - intrinsic)
        else:
            data["intrinsic_value"] = None
            data["extrinsic_value"] = None

        # Theta-decay curve: modeled extrinsic value from today's DTE down to expiry,
        # anchored to the real extrinsic above so it lines up with the table.
        data["decay_curve"] = theta_decay_curve(
            p.right,
            p.strike,
            underlying_price,
            p.iv,
            data["dte"],
            anchor_extrinsic=data["extrinsic_value"],
        )

        # Premium Captured
        # avg_cost for a short position (credit) is positive.
        # It's usually the total cash amount per contract.
        # mark is the per-share price. We normalize mark to match avg_cost magnitude (assumes 100 multiplier).
        if p.position is not None and float(p.position) < 0 and p.avg_cost is not None and float(p.avg_cost) > 0 and p.mark is not None:
            current_cost_per_contract = float(p.mark) * 100.0
            data["premium_captured_pct"] = (float(p.avg_cost) - current_cost_per_contract) / float(p.avg_cost)
        else:
            data["premium_captured_pct"] = None

        # Cushion %
        if p.position is not None and float(p.position) < 0 and p.strike is not None and underlying_price is not None and float(underlying_price) > 0:
            u = float(underlying_price)
            s = float(p.strike)
            if p.right == "P" or p.right == "PUT":
                data["cushion_pct"] = (u - s) / u
            elif p.right == "C" or p.right == "CALL":
                data["cushion_pct"] = (s - u) / u
            else:
                data["cushion_pct"] = None
        else:
            data["cushion_pct"] = None

        # Break-even cushion: a short option's break-even is strike ∓ the premium
        # you collected (put: strike − premium; call: strike + premium), so the
        # *real* buffer before the trade turns into a loss is wider than the raw
        # strike cushion. Reported alongside cushion_pct, not instead of it.
        data["breakeven"] = None
        data["breakeven_cushion_pct"] = None
        if (
            p.position is not None and float(p.position) < 0
            and p.strike is not None and p.avg_cost is not None and float(p.avg_cost) > 0
            and underlying_price is not None and float(underlying_price) > 0
        ):
            u = float(underlying_price)
            s = float(p.strike)
            prem = float(p.avg_cost) / 100.0  # premium collected, per share
            if p.right in ("P", "PUT"):
                be = s - prem
                data["breakeven"] = be
                data["breakeven_cushion_pct"] = (u - be) / u
            elif p.right in ("C", "CALL"):
                be = s + prem
                data["breakeven"] = be
                data["breakeven_cushion_pct"] = (be - u) / u

        # Chain-level capture. For a rolled short, the leg-level number above is
        # misleading: a roll re-sells a fresh, fatter premium, so the new leg can
        # read "76% captured" while the trade as a whole is nowhere near done.
        # What you'd actually pocket by unwinding today is the chain's credit
        # since this cycle began, less the cost to buy the short back — measured
        # against `initial_credit`, the sale the cycle is working toward.
        data["chain_captured_pct"] = None
        data["chain_profit_if_closed"] = None
        data["chain_initial_credit"] = None
        if chain is not None:
            initial = chain.get("initial_credit")
            cumulative = chain.get("cumulative_credit")
            buyback = chain_buyback.get(chain["chain_id"])
            if initial and initial > 0 and cumulative is not None and buyback is not None:
                profit = cumulative - chain.get("cycle_base_credit", 0.0) - buyback
                data["chain_initial_credit"] = initial
                data["chain_profit_if_closed"] = profit
                data["chain_captured_pct"] = profit / initial

        # Status rules. The first three are critical (TAKE PROFIT / AT RISK /
        # EXPIRING). WATCH is a softer tier for a position sitting *near* a
        # threshold — so one hovering on the line (e.g. cushion ~3% as the live
        # price ticks) stays visible instead of flickering in and out of alerts.
        # Capture is judged on the chain when the position belongs to one, so a
        # rolled trade isn't called done on the strength of its newest leg alone.
        cap = data["chain_captured_pct"]
        if cap is None:
            cap = data["premium_captured_pct"]
        cush = data["cushion_pct"]
        dte = data["dte"]
        status = "OPEN"
        if cap is not None and cap >= 0.7:
            status = "TAKE PROFIT"
        elif cush is not None and cush < 0.03:
            status = "AT RISK"
        elif dte is not None and dte <= 2:
            status = "EXPIRING"
        elif (cap is not None and cap >= 0.65) or (cush is not None and cush < 0.05):
            status = "WATCH"

        data["status"] = status

        out.append(PositionOut.model_validate(data))

    return out
