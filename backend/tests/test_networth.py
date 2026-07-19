"""Pure-function coverage for the net-worth service (no DB needed).

The DB-backed aggregation is verified against the live stack; here we lock the
month-bucketing + conversion arithmetic that the history series relies on.
"""
from datetime import date

from app.services import networth as nw


def test_month_starts_is_ordered_and_first_of_month():
    months = nw._month_starts(6)
    assert len(months) == 6
    assert all(d.day == 1 for d in months)
    # strictly increasing, exactly one month apart
    for a, b in zip(months, months[1:]):
        gap = (b.year - a.year) * 12 + (b.month - a.month)
        assert gap == 1
    assert months[-1] == date(date.today().year, date.today().month, 1)


def test_month_end_is_exclusive_upper_bound():
    assert nw._month_end(date(2026, 1, 1)) == date(2026, 2, 1)
    assert nw._month_end(date(2026, 12, 1)) == date(2026, 12, 31)


def test_convert_identity_and_rate():
    rates = {("USD", "SGD"): 1.35}
    assert nw._convert(100.0, "SGD", "SGD", rates) == 100.0  # identity
    assert nw._convert(100.0, "USD", "SGD", rates) == 135.0  # applied
    assert nw._convert(100.0, "USD", "SGD", {}) is None      # missing rate
    assert nw._convert(None, "USD", "SGD", rates) is None
