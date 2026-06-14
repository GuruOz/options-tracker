import math

from app.analytics.signal import (
    compute_signal,
    rsi_drawdown_score,
    trend_score,
    variance_premium_score,
)


def test_variance_premium_score():
    assert math.isclose(variance_premium_score(0.22, 0.20, 0.20), 50.0)
    assert variance_premium_score(0.30, 0.20, 0.20) == 100.0  # clamped
    assert variance_premium_score(0.20, None) is None


def test_trend_score():
    assert trend_score(105, 100, 0.05) == 100.0
    assert trend_score(100, 100) == 50.0
    assert trend_score(95, 100, 0.05) == 0.0


def test_rsi_drawdown_score_band_and_cap():
    assert rsi_drawdown_score(50) == 100.0
    assert rsi_drawdown_score(20) == 0.0
    assert math.isclose(rsi_drawdown_score(70), (100 - 70) / 35 * 100)
    assert rsi_drawdown_score(50, drawdown=0.15) == 30.0  # drawdown caps it


def test_compute_signal_favorable():
    result = compute_signal(
        {
            "iv_percentile": 80, "iv": 0.25, "realized_vol": 0.20,
            "price": 105, "sma50": 100, "rsi": 50, "drawdown": 0.0,
        }
    )
    assert result["verdict"] == "FAVORABLE"
    assert math.isclose(result["composite"], 93.2, abs_tol=0.5)


def test_compute_signal_renormalises_missing_subscores():
    # Only trend + rsi available; weights renormalise over those two.
    result = compute_signal({"price": 105, "sma50": 100, "rsi": 50})
    assert result["sub_scores"]["iv_percentile"] is None
    assert result["composite"] == 100.0  # both present sub-scores are 100
    assert result["verdict"] == "FAVORABLE"


def test_compute_signal_all_missing():
    result = compute_signal({})
    assert result["composite"] is None
    assert result["verdict"] is None
