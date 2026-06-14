from app.analytics.defaults import DEFAULT_SETTINGS


def test_signal_weights_sum_to_one():
    weights = DEFAULT_SETTINGS["signal"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_thresholds_reproduce_prototype():
    thresholds = DEFAULT_SETTINGS["signal"]["thresholds"]
    assert thresholds["favorable"] == 66
    assert thresholds["selective"] == 45


def test_alert_defaults():
    alerts = DEFAULT_SETTINGS["alerts"]
    assert alerts["take_profit_pct"] == 0.70
    assert alerts["expiry_dte"] == 2
    assert alerts["near_strike_cushion"] == 0.03
