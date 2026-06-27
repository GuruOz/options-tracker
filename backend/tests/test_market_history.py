from datetime import date

from app.analytics.market_history import build_history_series, rolling_sma


def test_rolling_sma_none_until_window_then_trailing_mean():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert rolling_sma(closes, 3) == [None, None, 2.0, 3.0, 4.0]


def test_rolling_sma_window_larger_than_series_is_all_none():
    assert rolling_sma([1.0, 2.0], 5) == [None, None]


def test_build_series_sorts_and_filters_null_closes():
    bars = [
        (date(2026, 1, 3), 12.0),
        (date(2026, 1, 1), 10.0),
        (date(2026, 1, 2), None),  # dropped — no close
    ]
    series = build_history_series(bars, sma_window=2, sma200_window=3)
    assert [p["date"] for p in series] == [date(2026, 1, 1), date(2026, 1, 3)]
    assert [p["close"] for p in series] == [10.0, 12.0]
    assert series[0]["sma"] is None       # only one prior point
    assert series[1]["sma"] == 11.0       # mean(10, 12)
    assert series[0]["sma200"] is None    # need 3 for sma200_window=3
    assert series[1]["sma200"] is None    # still only 2 points


def test_build_series_joins_vix_by_exact_date():
    bars = [(date(2026, 1, 1), 10.0), (date(2026, 1, 2), 11.0)]
    vix = {date(2026, 1, 2): 18.5}
    series = build_history_series(bars, vix, sma_window=1)
    assert series[0]["vix"] is None       # no VIX for this date
    assert series[1]["vix"] == 18.5


def test_build_series_windows_to_last_n_but_sma_uses_full_history():
    # SMA(window=3) computed over all 5 days, then sliced to the last 2 — so the
    # visible head still carries an overlay rather than starting blank.
    bars = [(date(2026, 1, d), float(d)) for d in range(1, 6)]
    series = build_history_series(bars, sma_window=3, window_days=2)
    assert [p["date"] for p in series] == [date(2026, 1, 4), date(2026, 1, 5)]
    assert series[0]["sma"] == 3.0        # mean(2, 3, 4)
    assert series[1]["sma"] == 4.0        # mean(3, 4, 5)


def test_build_series_empty_input():
    assert build_history_series([]) == []
