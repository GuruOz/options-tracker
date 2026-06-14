import math
from datetime import date

from app.analytics.greeks import bs_greeks, year_fraction


def test_year_fraction():
    assert year_fraction(date(2026, 1, 1), date(2026, 1, 1)) == 0.0
    assert math.isclose(year_fraction(date(2027, 1, 1), date(2026, 1, 1)), 365 / 365)
    assert year_fraction(date(2025, 1, 1), date(2026, 1, 1)) == 0.0  # past -> clamped


def test_put_greeks_signs():
    g = bs_greeks(spot=100, strike=100, t=0.5, sigma=0.25, right="P")
    assert g is not None
    assert -1.0 < g["delta"] < 0.0      # short-able put has negative delta
    assert g["gamma"] > 0
    assert g["vega"] > 0
    assert g["theta"] < 0               # long option loses time value


def test_call_put_delta_parity():
    call = bs_greeks(100, 100, 0.5, 0.25, "C")
    put = bs_greeks(100, 100, 0.5, 0.25, "P")
    assert math.isclose(call["delta"] - put["delta"], 1.0, abs_tol=1e-9)


def test_invalid_inputs_return_none():
    assert bs_greeks(100, 100, 0.5, 0.0, "C") is None     # zero vol
    assert bs_greeks(100, 100, 0.0, 0.25, "C") is None     # expired
    assert bs_greeks(None, 100, 0.5, 0.25, "C") is None    # missing spot
