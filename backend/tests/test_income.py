"""Unit tests for premium-income aggregation (`analytics/income.py`)."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.analytics.income import compute_income


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
