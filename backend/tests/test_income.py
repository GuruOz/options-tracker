"""Unit tests for premium-income aggregation (`analytics/income.py`)."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.analytics.income import compute_income
from app.api.routes.income import _combine


def _chain(opened, status, credit, open_credit=0.0):
    return SimpleNamespace(
        opened_at=datetime(opened[0], opened[1], opened[2], tzinfo=timezone.utc),
        status=status,
        cumulative_credit=credit,
        open_credit=open_credit,
    )


def _adj(year, month, *, cashed_out=False, withdrawal=None, note=None):
    return SimpleNamespace(
        month=date(year, month, 1),
        cashed_out=cashed_out,
        withdrawal_amount=withdrawal,
        note=note,
    )


def test_empty():
    out = compute_income([], [])
    assert out["all_time"] == 0
    assert out["months"] == []
    assert out["years"] == []
    assert out["win_rate"] is None


def test_monthly_and_yearly_rollup_by_open_month():
    chains = [
        _chain((2025, 7, 7), "closed", 515.0),
        _chain((2025, 8, 6), "closed", 1267.0),
        _chain((2026, 1, 14), "closed", 950.0),
        # opened Jan, still open -> counts in Jan unrealized
        _chain((2026, 1, 20), "open", 232.0),
    ]
    out = compute_income(chains, [])
    by_month = {m["month"]: m for m in out["months"]}
    assert by_month["2025-07"]["pnl"] == 515.0
    assert by_month["2026-01"]["pnl"] == 1182.0  # 950 + 232 same month
    assert by_month["2026-01"]["chain_count"] == 2

    by_year = {y["year"]: y for y in out["years"]}
    assert by_year[2025]["ytd"] == 1782.0
    assert by_year[2026]["ytd"] == 1182.0
    assert out["all_time"] == 2964.0
    assert out["realized"] == 2732.0
    assert out["unrealized"] == 232.0


def test_win_rate_counts_closed_only():
    chains = [
        _chain((2026, 1, 1), "closed", 100.0),   # win
        _chain((2026, 1, 2), "closed", -50.0),   # loss
        _chain((2026, 1, 3), "closed", 200.0),   # win
        _chain((2026, 1, 4), "open", 10.0),      # ignored for win rate
    ]
    out = compute_income(chains, [])
    assert out["closed_count"] == 3
    assert out["open_count"] == 1
    assert out["win_rate"] == 2 / 3


def test_withdrawals_and_remaining():
    chains = [_chain((2026, 1, 1), "closed", 1000.0)]
    adj = [
        _adj(2026, 1, cashed_out=True),
        _adj(2026, 4, withdrawal=235.0, note="paid rent"),
    ]
    out = compute_income(chains, adj)
    by_month = {m["month"]: m for m in out["months"]}
    assert by_month["2026-01"]["cashed_out"] is True
    assert by_month["2026-04"]["withdrawal"] == 235.0
    assert by_month["2026-04"]["note"] == "paid rent"

    year = next(y for y in out["years"] if y["year"] == 2026)
    assert year["ytd"] == 1000.0
    assert year["withdrawn"] == 235.0
    assert year["remaining"] == 765.0


def test_open_chain_counts_only_what_it_banked():
    # The open leg was sold for 865 and the chain has 927 of credit, but only the
    # 62 of roll decay is collectable — the 865 rides until it expires or is
    # bought back, so income must not book it.
    chains = [_chain((2026, 3, 2), "open", 927.0, open_credit=865.0)]
    out = compute_income(chains, [])

    assert out["unrealized"] == 62.0
    assert out["all_time"] == 62.0
    by_month = {m["month"]: m for m in out["months"]}
    assert by_month["2026-03"]["pnl"] == 62.0


def test_closed_chain_books_its_full_credit():
    # Once the chain is closed nothing is locked, so the whole credit counts.
    chains = [_chain((2026, 3, 2), "closed", 927.0, open_credit=0.0)]
    out = compute_income(chains, [])
    assert out["realized"] == 927.0
    assert out["unrealized"] == 0.0


def test_yield_uses_net_liquidation():
    chains = [_chain((2026, 1, 1), "closed", 1000.0)]
    out = compute_income(chains, [], net_liquidation=50000.0)
    assert out["yield_pct"] == 0.02
    assert compute_income(chains, [])["yield_pct"] is None


def test_currency_mismatch_suppresses_yield_not_pnl():
    # A SGD-base account whose premium is actually USD (US-listed options):
    # the P&L totals stay valid dollar figures, but dividing by SGD
    # net_liquidation would silently mix currencies.
    chains = [_chain((2026, 1, 1), "closed", 1000.0)]
    out = compute_income(
        chains, [], net_liquidation=50000.0, currency_mismatch=True
    )
    assert out["currency_mismatch"] is True
    assert out["yield_pct"] is None
    assert out["all_time"] == 1000.0
    assert out["realized"] == 1000.0


def test_currency_mismatch_with_fx_rate_computes_yield():
    # Same mismatched account, but a live USD->SGD rate lets the yield through.
    chains = [_chain((2026, 1, 1), "closed", 1000.0)]
    out = compute_income(
        chains, [], net_liquidation=50000.0, currency_mismatch=True, fx_rate=1.35,
    )
    assert out["currency_mismatch"] is True
    assert out["yield_pct"] == 1000.0 * 1.35 / 50000.0


def _summary(
    *, base, premium, all_time, net_liq, month_pnl, withdrawn=0.0,
    mismatch=False, ambiguous=False,
):
    """A per-account dict shaped like `_income_for`'s output, for _combine tests."""
    return {
        "months": [
            {"month": "2026-01", "pnl": month_pnl, "chain_count": 1,
             "cashed_out": False, "withdrawal": None, "note": None},
        ],
        "years": [
            {"year": 2026, "ytd": month_pnl, "withdrawn": withdrawn,
             "remaining": month_pnl - withdrawn},
        ],
        "all_time": all_time,
        "realized": all_time,
        "unrealized": 0.0,
        "win_rate": 1.0,
        "closed_count": 1,
        "open_count": 0,
        "net_liquidation": net_liq,
        "yield_pct": None,
        "currency_mismatch": mismatch,
        "base_currency": base,
        "premium_currency": premium,
        "premium_ambiguous": ambiguous,
        "fx_rates": [],
    }


def test_combine_flags_cross_account_currency_mix_without_rates():
    # Regression: two internally-consistent accounts with different base
    # currencies used to slip past the guard and produce a mixed-unit yield.
    per_account = [
        _summary(base="USD", premium="USD", all_time=1000.0, net_liq=50_000.0, month_pnl=1000.0),
        _summary(base="SGD", premium="SGD", all_time=500.0, net_liq=25_000.0, month_pnl=500.0),
    ]
    out = _combine(per_account)
    assert out["currency_mismatch"] is True
    assert out["yield_pct"] is None
    assert out["display_currency"] is None


def test_combine_converts_before_summing_when_rates_available():
    per_account = [
        _summary(base="USD", premium="USD", all_time=1000.0, net_liq=50_000.0,
                 month_pnl=1000.0),
        _summary(base="SGD", premium="SGD", all_time=500.0, net_liq=25_000.0,
                 month_pnl=500.0, withdrawn=100.0),
    ]
    out = _combine(
        per_account,
        display_currency="USD",
        rates={"USD": 1.0, "SGD": 0.5},
        fx_used=[{"pair": "SGD/USD", "rate": 0.5, "as_of": None, "source": "ibkr"}],
    )
    assert out["all_time"] == 1000.0 + 250.0
    assert out["net_liquidation"] == 50_000.0 + 12_500.0
    assert out["yield_pct"] == 1250.0 / 62_500.0
    by_month = {m["month"]: m for m in out["months"]}
    assert by_month["2026-01"]["pnl"] == 1250.0
    year = next(y for y in out["years"] if y["year"] == 2026)
    assert year["withdrawn"] == 50.0  # withdrawals convert at the base rate
    assert out["display_currency"] == "USD"
    assert out["currency_mismatch"] is True  # provenance flag survives
    assert out["fx_rates"]


def test_combine_ambiguous_premium_blocks_conversion():
    per_account = [
        _summary(base="USD", premium="USD", all_time=1000.0, net_liq=50_000.0, month_pnl=1000.0),
        _summary(base="SGD", premium=None, all_time=500.0, net_liq=25_000.0,
                 month_pnl=500.0, mismatch=True, ambiguous=True),
    ]
    out = _combine(per_account, display_currency="USD", rates={"USD": 1.0, "SGD": 0.5})
    assert out["display_currency"] is None
    assert out["yield_pct"] is None
    assert out["all_time"] == 1500.0  # raw sum, old behavior
