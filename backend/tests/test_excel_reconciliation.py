"""Reconcile the roll-chain builder against the user's Excel tracker.

`docs/Sample Options tracker - Guru.xlsx` is the authoritative record of the
trades. Each monthly tab is a set of roll chains; the chain's "Total P/L" is the
signed sum of the per-share premium *points* (sells +, buys −) plus the stock
legs of any assignment, with **no commissions** and an implicit **1 contract**.

The webapp keeps P&L in **dollars, net of commissions** (the more accurate
figure). With commissions = 0 — which is what the sheet assumes — the webapp's
`cumulative_credit` must therefore equal the Excel points × 100 exactly. These
fixtures encode the chains transcribed from the sheet and assert that identity,
so the chain math stays pinned to the source of truth. (On live data the only
expected delta from the sheet is the commissions, which the sheet omits.)

Transcribed tabs: "Aug 2025" (expiry + roll + assignment/wheel) and "Feb 2026"
(four assignment→resell cycles). Hand-verified month totals: Aug 12.67, Feb
31.53 — matching the "Total P&L" summary tab.
"""
from datetime import datetime, timezone

import pytest

from app.analytics.rolls import build_roll_chains
from app.db.models import Execution

_ACCT = "U-EXCEL"


def _opt(t, side, price, *, ticker, strike, right="P", expiry=None, source=None):
    """An option execution. `qty` unsigned, `comm` 0 (Excel omits commissions)."""
    return Execution(
        exec_id=f"{ticker}-{t.isoformat()}-{side}-{price}",
        account_id=_ACCT, conid=None, symbol=ticker, sec_type="OPT",
        side=side, right=right, strike=strike, qty=1.0, price=abs(price),
        commission=0.0, exec_time=t, expiry=expiry, source=source, raw=None,
    )


def _stk(t, side, price, *, ticker, assigned=False):
    """A 100-share stock leg (assignment buy, or selling the assigned shares)."""
    return Execution(
        exec_id=f"{ticker}-{t.isoformat()}-STK-{side}-{price}",
        account_id=_ACCT, conid=None, symbol=ticker, sec_type="STK",
        side=side, right=None, strike=None, qty=100.0, price=price,
        commission=0.0, exec_time=t, expiry=None, source=None,
        raw={"notes": "A"} if assigned else None,
    )


def _dt(y, m, d, hh=9, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _credit_by_underlying(chains):
    out: dict[str, float] = {}
    for c in chains:
        out[c["underlying_symbol"]] = out.get(c["underlying_symbol"], 0.0) + c["cumulative_credit"]
    return out


# --- Aug 2025 tab ----------------------------------------------------------
# QQQM: sell-to-open 235P @3.5, expires worthless          -> +3.50
# QQQ : roll + early assignment (wheel) on the 577P         -> +9.17
# Month total 12.67 (= summary tab).

def test_aug_2025_reconciles():
    exs = [
        # QQQM chain — sold, expired worthless (modeled as a price-0 flex EAE buy)
        _opt(_dt(2025, 8, 6), "S", 3.5, ticker="QQQM", strike=235.0, expiry=_dt(2025, 8, 15).date()),
        _opt(_dt(2025, 8, 15), "B", 0.0, ticker="QQQM", strike=235.0,
             expiry=_dt(2025, 8, 15).date(), source="flex_eae"),

        # QQQ 577P chain
        _opt(_dt(2025, 8, 16), "S", 4.2, ticker="QQQ", strike=577.0, expiry=_dt(2025, 8, 22).date()),
        _opt(_dt(2025, 8, 21, 9, 0), "B", 12.81, ticker="QQQ", strike=577.0),         # buy to roll
        _opt(_dt(2025, 8, 21, 9, 1), "S", 14.13, ticker="QQQ", strike=577.0, expiry=_dt(2025, 8, 28).date()),
        _stk(_dt(2025, 8, 29, 9, 0), "B", 577.0, ticker="QQQ", assigned=True),         # assigned -> buy shares
        _stk(_dt(2025, 8, 29, 9, 1), "S", 571.0, ticker="QQQ"),                        # sell assigned shares
        _opt(_dt(2025, 8, 29, 9, 2), "S", 8.1, ticker="QQQ", strike=577.0, expiry=_dt(2025, 9, 5).date()),
        _opt(_dt(2025, 9, 4, 9, 0), "B", 8.2, ticker="QQQ", strike=577.0),
        _opt(_dt(2025, 9, 4, 9, 1), "S", 10.0, ticker="QQQ", strike=577.0, expiry=_dt(2025, 9, 12).date()),
        _opt(_dt(2025, 9, 12, 9, 0), "B", 0.25, ticker="QQQ", strike=577.0),
    ]
    chains, _ = build_roll_chains(exs, _ACCT)
    by_u = _credit_by_underlying(chains)

    assert by_u["QQQM"] == pytest.approx(3.5 * 100, abs=0.01)
    assert by_u["QQQ"] == pytest.approx(9.17 * 100, abs=0.01)
    assert sum(by_u.values()) == pytest.approx(12.67 * 100, abs=0.01)


# --- Feb 2026 tab ----------------------------------------------------------
# QQQ 610P: three rolls, then four assignment->resell cycles, final buy-to-close.
# Month total 31.53 (= summary tab).

def test_feb_2026_reconciles():
    T = "QQQ"
    K = 610.0
    exs = [
        _opt(_dt(2026, 2, 4), "S", 11.0, ticker=T, strike=K, expiry=_dt(2026, 2, 20).date()),
        _opt(_dt(2026, 2, 20, 9, 0), "B", 4.81, ticker=T, strike=K),
        _opt(_dt(2026, 2, 20, 9, 1), "S", 9.86, ticker=T, strike=K, expiry=_dt(2026, 2, 27).date()),
        _opt(_dt(2026, 2, 27, 9, 0), "B", 4.35, ticker=T, strike=K),
        _opt(_dt(2026, 2, 27, 9, 1), "S", 9.15, ticker=T, strike=K, expiry=_dt(2026, 3, 6).date()),
        _opt(_dt(2026, 3, 6, 9, 0), "B", 6.66, ticker=T, strike=K),
        _opt(_dt(2026, 3, 6, 9, 1), "S", 11.76, ticker=T, strike=K, expiry=_dt(2026, 3, 13).date()),
        # cycle 1
        _stk(_dt(2026, 3, 13, 9, 0), "B", K, ticker=T, assigned=True),
        _stk(_dt(2026, 3, 13, 9, 1), "S", 597.76, ticker=T),
        _opt(_dt(2026, 3, 13, 9, 2), "S", 15.45, ticker=T, strike=K, expiry=_dt(2026, 3, 20).date()),
        # cycle 2
        _stk(_dt(2026, 3, 20, 9, 0), "B", K, ticker=T, assigned=True),
        _stk(_dt(2026, 3, 20, 9, 1), "S", 587.85, ticker=T),
        _opt(_dt(2026, 3, 20, 9, 2), "S", 23.35, ticker=T, strike=K, expiry=_dt(2026, 3, 27).date()),
        # cycle 3
        _stk(_dt(2026, 3, 25, 9, 0), "B", K, ticker=T, assigned=True),
        _stk(_dt(2026, 3, 25, 9, 1), "S", 588.92, ticker=T),
        _opt(_dt(2026, 3, 25, 9, 2), "S", 21.7, ticker=T, strike=K, expiry=_dt(2026, 4, 2).date()),
        # cycle 4
        _stk(_dt(2026, 3, 27, 9, 0), "B", K, ticker=T, assigned=True),
        _stk(_dt(2026, 3, 28, 9, 0), "S", 567.04, ticker=T),
        _opt(_dt(2026, 3, 28, 9, 1), "S", 45.91, ticker=T, strike=K, expiry=_dt(2026, 5, 15).date()),
        # final close
        _opt(_dt(2026, 4, 24, 9, 0), "B", 2.4, ticker=T, strike=K),
    ]
    chains, _ = build_roll_chains(exs, _ACCT)
    total = sum(c["cumulative_credit"] for c in chains)
    assert total == pytest.approx(31.53 * 100, abs=0.01)
