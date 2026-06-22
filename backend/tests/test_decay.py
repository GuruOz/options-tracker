import math
from decimal import Decimal

from app.analytics.decay import bs_price, theta_decay_curve


def test_bs_atm_call_put_parity():
    # Put-call parity: C - P == S - K*e^{-rT}
    S, K, t, sig, r = 100.0, 100.0, 0.5, 0.25, 0.04
    c = bs_price(True, S, K, t, sig, r)
    p = bs_price(False, S, K, t, sig, r)
    assert round(c - p, 6) == round(S - K * math.exp(-r * t), 6)


def test_bs_at_expiry_is_intrinsic():
    assert bs_price(True, 110.0, 100.0, 0.0, 0.25) == 10.0  # ITM call
    assert bs_price(False, 110.0, 100.0, 0.0, 0.25) == 0.0  # OTM put


def test_curve_decays_to_zero_and_is_ordered():
    curve = theta_decay_curve("P", 400.0, 450.0, 25.0, 30)
    assert curve is not None
    # Newest-expiry first (current DTE), 0 last.
    assert curve[0]["dte"] == 30
    assert curve[-1]["dte"] == 0
    assert curve[-1]["extrinsic"] == 0.0
    # Extrinsic is monotonically non-increasing as DTE shrinks.
    vals = [pt["extrinsic"] for pt in curve]
    assert all(a >= b - 1e-9 for a, b in zip(vals, vals[1:]))


def test_curve_anchors_to_real_extrinsic():
    # The point at the current DTE should equal the supplied anchor.
    curve = theta_decay_curve("P", 400.0, 450.0, 25.0, 20, anchor_extrinsic=3.5)
    assert curve is not None
    assert curve[0]["extrinsic"] == 3.5


def test_zero_anchor_falls_back_to_model_curve():
    # A clamped extrinsic of 0 (mark <= intrinsic on a stale ITM quote) must NOT
    # zero out the whole curve — that produced a misleading flat $0 chart for ITM
    # puts. With a non-positive anchor we fall back to the unscaled model estimate.
    # NVDA 215P with spot 205.42 is ITM, so the model still shows real time value.
    anchored0 = theta_decay_curve("P", 215.0, 205.42, 34.5, 10, anchor_extrinsic=0.0)
    model = theta_decay_curve("P", 215.0, 205.42, 34.5, 10)
    assert anchored0 is not None and model is not None
    assert anchored0 == model  # 0 anchor ignored -> identical to the unanchored curve
    assert anchored0[0]["extrinsic"] > 0  # and it is NOT flattened to zero


def test_iv_percent_and_decimal_scales_agree():
    # 25.0 (percent) and 0.25 (decimal) describe the same vol.
    pct = theta_decay_curve("C", 100.0, 95.0, 25.0, 30)
    dec = theta_decay_curve("C", 100.0, 95.0, 0.25, 30)
    assert pct == dec


def test_curve_none_when_inputs_missing_or_expired():
    assert theta_decay_curve(None, 400.0, 450.0, 25.0, 30) is None
    assert theta_decay_curve("P", None, 450.0, 25.0, 30) is None
    assert theta_decay_curve("P", 400.0, None, 25.0, 30) is None
    assert theta_decay_curve("P", 400.0, 450.0, None, 30) is None
    assert theta_decay_curve("P", 400.0, 450.0, 25.0, 0) is None  # expired
    assert theta_decay_curve("P", 400.0, 450.0, 0.0, 30) is None  # zero vol


def test_curve_accepts_decimal_inputs():
    # The DB hands these in as Decimal; the curve must not choke on Decimal/float ops.
    curve = theta_decay_curve(
        "P",
        Decimal("400"),
        Decimal("450.5"),
        Decimal("22.0"),
        Decimal("30"),
        anchor_extrinsic=Decimal("2.5"),
    )
    assert curve is not None
    assert curve[0]["extrinsic"] == 2.5
    assert curve[-1]["dte"] == 0


def test_curve_point_count_capped():
    curve = theta_decay_curve("P", 400.0, 450.0, 25.0, 365, max_points=24)
    assert curve is not None
    assert len(curve) <= 26  # max_points samples + a forced 0 endpoint
