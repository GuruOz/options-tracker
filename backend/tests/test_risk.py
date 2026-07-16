from app.analytics.risk import compute_risk
from app.db.models import AccountSnapshot, MarketSnapshot, PositionSnapshot


def test_beta_weighted_scenario_and_assignment():
    # Short 2 QQQ 400 puts (per-share delta -0.30) + long 100 shares of TQQQ.
    short_put = PositionSnapshot(
        conid=1, symbol="QQQ", sec_type="OPT", right="P",
        strike=400.0, position=-2.0, delta=-0.30, mark=2.0,
    )
    stock = PositionSnapshot(
        conid=2, symbol="TQQQ", sec_type="STK", position=100.0, mark=70.0,
    )
    markets = [
        MarketSnapshot(symbol="QQQ", price=450.0),
        MarketSnapshot(symbol="TQQQ", price=70.0),
    ]
    acct = AccountSnapshot(cash=100_000.0, net_liquidation=250_000.0)

    r = compute_risk([short_put, stock], markets, acct)

    # QQQ: share delta = -0.30 * -2 * 100 = +60 -> $delta 60*450 = 27,000 (beta 1)
    # TQQQ: share delta = 1 * 100 * 1 = 100 -> $delta 100*70 = 7,000, beta 3 -> 21,000
    assert round(r["beta_weighted_delta_dollars"], 2) == 48_000.0
    assert round(r["scenario_pnl"], 2) == -4_800.0  # -10% move
    assert round(r["scenario_pnl_pct"], 6) == round(-4_800.0 / 250_000.0, 6)

    # Assignment: one short put, 400 * 100 * 2 = 80,000; coverage 100k / 80k = 1.25
    assert r["assignment"]["short_put_count"] == 1
    assert round(r["assignment"]["total_obligation"], 2) == 80_000.0
    assert round(r["assignment"]["coverage_ratio"], 4) == 1.25

    # Largest contributor sorts first.
    assert r["positions"][0]["symbol"] == "QQQ"


def test_skips_delta_without_price_but_still_counts_assignment():
    # No market snapshot for AAPL: excluded from delta, still an assignment obligation.
    short_put = PositionSnapshot(
        conid=3, symbol="AAPL", sec_type="OPT", right="P",
        strike=150.0, position=-1.0, delta=-0.25, mark=1.0,
    )
    r = compute_risk([short_put], [], None)

    assert r["beta_weighted_delta_dollars"] == 0.0
    assert r["assignment"]["total_obligation"] == 15_000.0
    assert r["assignment"]["coverage_ratio"] is None  # no account/cash
    assert r["scenario_pnl_pct"] is None


def test_currency_mismatch_suppresses_ratios_not_dollar_figures():
    # A SGD-base account (cash/net_liq) holding a USD-listed short put: the
    # obligation/scenario P&L stay valid dollar figures, but dividing them by
    # SGD cash/net_liq would silently mix currencies.
    short_put = PositionSnapshot(
        conid=1, symbol="QQQ", sec_type="OPT", right="P",
        strike=400.0, position=-2.0, delta=-0.30, mark=2.0, currency="USD",
    )
    markets = [MarketSnapshot(symbol="QQQ", price=450.0)]
    acct = AccountSnapshot(cash=100_000.0, net_liquidation=250_000.0)

    r = compute_risk([short_put], markets, acct, account_currency="SGD")

    assert r["currency_mismatch"] is True
    assert r["exposure_currency"] == "USD"
    assert r["scenario_pnl_pct"] is None
    assert r["assignment"]["coverage_ratio"] is None
    # The dollar figures themselves are untouched - just not divisible by SGD.
    assert r["assignment"]["total_obligation"] == 80_000.0
    assert r["scenario_pnl"] != 0.0


def test_unknown_currency_does_not_trigger_mismatch():
    # No currency recorded on the position (older row / feed gap) - unknown
    # isn't evidence of a mismatch, so behavior matches pre-currency-tracking.
    short_put = PositionSnapshot(
        conid=1, symbol="QQQ", sec_type="OPT", right="P",
        strike=400.0, position=-2.0, delta=-0.30, mark=2.0,
    )
    markets = [MarketSnapshot(symbol="QQQ", price=450.0)]
    acct = AccountSnapshot(cash=100_000.0, net_liquidation=250_000.0)

    r = compute_risk([short_put], markets, acct, account_currency="SGD")

    assert r["currency_mismatch"] is False
    assert r["scenario_pnl_pct"] is not None
    assert r["assignment"]["coverage_ratio"] is not None
