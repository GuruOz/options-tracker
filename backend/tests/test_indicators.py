import math

from app.analytics.indicators import (
    drawdown_from_high,
    iv_percentile,
    iv_rank,
    realized_vol,
    rsi,
    sma,
)


def test_sma():
    assert sma([1, 2, 3, 4, 5], 3) == 4.0
    assert sma([1, 2], 3) is None


def test_rsi_extremes():
    rising = list(range(1, 20))
    falling = list(range(20, 1, -1))
    assert rsi(rising, 14) == 100.0
    assert rsi(falling, 14) == 0.0
    assert rsi([1, 2, 3], 14) is None


def test_realized_vol_positive_and_zero():
    assert realized_vol([100, 100, 100, 100], window=3) == 0.0
    v = realized_vol([100, 102, 99, 101, 103, 98], window=5)
    assert v is not None and v > 0


def test_drawdown_from_high():
    assert drawdown_from_high([10, 12, 9]) == (12 - 9) / 12
    assert drawdown_from_high([]) is None


def test_iv_rank_and_percentile():
    series = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert math.isclose(iv_rank(0.3, series), 50.0)
    assert math.isclose(iv_percentile(0.3, series), 40.0)
    assert iv_rank(0.3, [0.2]) is None        # too few points
    assert iv_rank(0.3, [0.2, 0.2]) is None   # flat series
