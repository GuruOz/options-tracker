"""Premium-income analytics.

Aggregates roll-chain P&L into the monthly -> YTD layout the user tracks in their
Excel sheet, overlaid with manual withdrawal / "cashed out" entries. Pure
function over ORM-ish rows so it's unit-testable with plain fixtures.

A chain's `cumulative_credit` is its commission-net realized P&L (dollars). P&L
is attributed to the month the chain was *opened* (matching the Excel tabs).
Closed chains are realized and drive the win rate.

An open chain contributes only what it has *banked* — its credit less the
`open_credit` still riding on the short leg that's open. That leg's premium
isn't income yet: it can only be collected once the option expires worthless or
is bought back, and until then a roll has merely extended the trade. Counting it
would book premium that is still at risk.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence


def _month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def compute_income(
    chains: Sequence,
    adjustments: Sequence,
    *,
    net_liquidation: float | None = None,
) -> dict:
    """Build the income summary.

    chains: rows with .opened_at (datetime|None), .status (str),
        .cumulative_credit and .open_credit.
    adjustments: rows with .month (date), .cashed_out, .withdrawal_amount, .note.
    """
    monthly_pnl: dict[str, float] = defaultdict(float)
    monthly_count: dict[str, int] = defaultdict(int)
    realized = 0.0
    unrealized = 0.0
    closed = 0
    open_ = 0
    wins = 0

    for c in chains:
        credit = float(c.cumulative_credit) if c.cumulative_credit is not None else 0.0
        is_closed = (c.status or "") == "closed"
        if is_closed:
            closed += 1
            realized += credit
            if credit > 0:
                wins += 1
        else:
            # Only the banked part of an open chain counts — the credit locked in
            # its open leg isn't collectable yet.
            credit -= float(getattr(c, "open_credit", 0) or 0)
            open_ += 1
            unrealized += credit

        if c.opened_at is None:
            continue
        mk = _month_key(c.opened_at)
        monthly_pnl[mk] += credit
        monthly_count[mk] += 1

    adj_by_month = {
        _month_key(a.month): a for a in adjustments if a.month is not None
    }

    months = []
    for mk in sorted(set(monthly_pnl) | set(adj_by_month)):
        a = adj_by_month.get(mk)
        withdrawal = (
            float(a.withdrawal_amount)
            if a is not None and a.withdrawal_amount is not None
            else None
        )
        months.append({
            "month": mk,
            "pnl": round(monthly_pnl.get(mk, 0.0), 2),
            "chain_count": monthly_count.get(mk, 0),
            "cashed_out": bool(a.cashed_out) if a is not None else False,
            "withdrawal": withdrawal,
            "note": (a.note if a is not None else None),
        })

    year_pnl: dict[int, float] = defaultdict(float)
    year_withdrawn: dict[int, float] = defaultdict(float)
    for m in months:
        y = int(m["month"][:4])
        year_pnl[y] += m["pnl"]
        if m["withdrawal"]:
            year_withdrawn[y] += m["withdrawal"]

    years = []
    for y in sorted(year_pnl):
        ytd = round(year_pnl[y], 2)
        withdrawn = round(year_withdrawn[y], 2)
        years.append({
            "year": y,
            "ytd": ytd,
            "withdrawn": withdrawn,
            "remaining": round(ytd - withdrawn, 2),
        })

    all_time = round(sum(year_pnl.values()), 2)

    return {
        "months": months,
        "years": years,
        "all_time": all_time,
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "win_rate": (wins / closed) if closed else None,
        "closed_count": closed,
        "open_count": open_,
        "net_liquidation": float(net_liquidation) if net_liquidation else None,
        "yield_pct": (all_time / net_liquidation) if net_liquidation else None,
    }
