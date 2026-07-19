from app.analytics.risk import compute_risk
from app.api.routes.risk import _combine
from app.db.models import AccountSnapshot, MarketSnapshot, PositionSnapshot


def _account_result(
    *, base, exposure, net_liq, scenario_pnl, bw_delta, gross_delta,
    obligation, cash, mismatch=False,
):
    """A per-account dict shaped like `_risk_for`'s output, for _combine tests."""
    return {
        "scenario_move": -0.10,
        "index_symbol": "QQQ",
        "net_liquidation": net_liq,
        "beta_weighted_delta_dollars": bw_delta,
        "gross_delta_dollars": gross_delta,
        "scenario_pnl": scenario_pnl,
        "scenario_pnl_pct": None,
        "currency_mismatch": mismatch,
        "exposure_currency": exposure,
        "base_currency": base,
        "assignment": {
            "total_obligation": obligation,
            "cash": cash,
            "coverage_ratio": None,
            "short_put_count": 1,
        },
        "positions": [],
        "equity_curve": [],
    }


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


def test_currency_mismatch_converts_ratios_with_fx_rate():
    # Same SGD-base account with a USD book, but now a live rate is available:
    # the ratios come back, computed in the account's base currency.
    short_put = PositionSnapshot(
        conid=1, symbol="QQQ", sec_type="OPT", right="P",
        strike=400.0, position=-2.0, delta=-0.30, mark=2.0, currency="USD",
    )
    markets = [MarketSnapshot(symbol="QQQ", price=450.0)]
    acct = AccountSnapshot(cash=100_000.0, net_liquidation=250_000.0)

    r = compute_risk(
        [short_put], markets, acct, account_currency="SGD",
        fx_rates={("USD", "SGD"): 1.35},
    )

    assert r["currency_mismatch"] is True  # provenance flag survives
    # 27,000 USD delta -> scenario -2,700 USD -> ×1.35 over 250k SGD.
    assert round(r["scenario_pnl_pct"], 6) == round(-2_700.0 * 1.35 / 250_000.0, 6)
    # 80,000 USD obligation ×1.35 vs 100k SGD cash.
    assert round(r["assignment"]["coverage_ratio"], 6) == round(100_000.0 / (80_000.0 * 1.35), 6)
    # Dollar figures stay in the exposure currency.
    assert r["assignment"]["total_obligation"] == 80_000.0


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


def _usd_sgd_household():
    usd = _account_result(
        base="USD", exposure="USD", net_liq=100_000.0, scenario_pnl=-1_000.0,
        bw_delta=10_000.0, gross_delta=12_000.0, obligation=50_000.0, cash=60_000.0,
    )
    sgd = _account_result(
        base="SGD", exposure="SGD", net_liq=50_000.0, scenario_pnl=-2_000.0,
        bw_delta=20_000.0, gross_delta=24_000.0, obligation=20_000.0, cash=10_000.0,
    )
    return [usd, sgd]


def test_combine_converts_before_summing_when_rates_available():
    combined = _combine(
        _usd_sgd_household(),
        display_currency="USD",
        rates={"USD": 1.0, "SGD": 0.5},
        fx_used=[{"pair": "SGD/USD", "rate": 0.5, "as_of": None, "source": "ibkr"}],
    )

    assert combined["net_liquidation"] == 100_000.0 + 25_000.0
    assert combined["scenario_pnl"] == -1_000.0 + -1_000.0
    assert combined["beta_weighted_delta_dollars"] == 10_000.0 + 10_000.0
    assert combined["assignment"]["cash"] == 60_000.0 + 5_000.0
    assert combined["assignment"]["total_obligation"] == 50_000.0 + 10_000.0
    # Ratios come back because everything shares the display currency now.
    assert round(combined["scenario_pnl_pct"], 6) == round(-2_000.0 / 125_000.0, 6)
    assert round(combined["assignment"]["coverage_ratio"], 6) == round(65_000.0 / 60_000.0, 6)
    assert combined["currency_mismatch"] is True  # provenance flag survives
    assert combined["display_currency"] == "USD"
    assert combined["exposure_currency"] == "USD"
    assert combined["fx_rates"]


def test_combine_degrades_to_raw_sums_without_rates():
    combined = _combine(_usd_sgd_household(), display_currency="USD", rates={"USD": 1.0})

    # Old behavior: raw sums, suppressed ratios, no display currency claimed.
    assert combined["net_liquidation"] == 150_000.0
    assert combined["scenario_pnl_pct"] is None
    assert combined["assignment"]["coverage_ratio"] is None
    assert combined["currency_mismatch"] is True
    assert combined["display_currency"] is None
    assert combined["fx_rates"] == []


def test_combine_ambiguous_book_blocks_conversion():
    # An account whose own book mixes currencies has no single exposure
    # currency, so no one rate can convert its figures.
    household = _usd_sgd_household()
    household[1]["currency_mismatch"] = True
    household[1]["exposure_currency"] = None

    combined = _combine(
        household, display_currency="USD", rates={"USD": 1.0, "SGD": 0.5},
    )
    assert combined["display_currency"] is None
    assert combined["net_liquidation"] == 150_000.0
    assert combined["scenario_pnl_pct"] is None
