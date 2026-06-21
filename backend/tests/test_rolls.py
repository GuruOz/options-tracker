"""Unit tests for roll-chain detection (`analytics/rolls.py`).

Focus on strike-scoped grouping, 60-day continuation, synthetic expirations, and assignment tracking.
"""
from datetime import datetime, timedelta, timezone, date

from app.analytics.rolls import _chain_id, build_roll_chains
from app.db.models import ChainAdjustment, Execution

_T0 = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
_ACCT = "U123"

def _ex(exec_id, side, conid, *, symbol="QQQ", right="P", strike=100.0,
        t=_T0, qty=1.0, price=1.0, comm=1.0, sec_type="OPT", expiry=None,
        notes=None, source=None):
    return Execution(
        exec_id=exec_id, account_id=_ACCT, conid=conid, symbol=symbol,
        sec_type=sec_type, side=side, right=right, strike=strike, qty=qty, price=price,
        commission=comm, exec_time=t, expiry=expiry, source=source,
        raw={"notes": notes} if notes else None
    )

def _legs_for(legs, exec_id):
    return [l for l in legs if l["exec_id"] == exec_id]

def test_fresh_open():
    chains, legs = build_roll_chains([_ex("e1", "S", 100, price=2.0)], _ACCT)
    assert len(chains) == 1
    assert chains[0]["status"] == "open"
    assert chains[0]["cumulative_credit"] == 199.0
    assert len(legs) == 1 and legs[0]["role"] == "open"

def test_open_then_close_stays_closed_if_no_roll():
    exs = [
        _ex("e1", "S", 100, price=2.0, t=_T0),
        _ex("e2", "B", 100, price=0.5, t=_T0 + timedelta(days=1)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "closed"
    assert c["close_reason"] == "bought_back"
    assert c["cumulative_credit"] == 148.0

def test_roll_within_window_continues_chain():
    exs = [
        _ex("open1", "S", 100, price=2.0, t=_T0),
        _ex("close1", "B", 100, price=0.5, t=_T0 + timedelta(days=10)),
        _ex("open2", "S", 200, price=2.5, t=_T0 + timedelta(days=30)), # Within 60 days
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "open"
    assert c["cumulative_credit"] == 397.0 # 199 - 51 + 249
    assert len(legs) == 3

def test_roll_beyond_window_starts_new_chain():
    exs = [
        _ex("open1", "S", 100, price=2.0, t=_T0),
        _ex("close1", "B", 100, price=0.5, t=_T0 + timedelta(days=10)),
        _ex("open2", "S", 200, price=2.5, t=_T0 + timedelta(days=80)), # Beyond 60 days
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 2
    by_status = sorted(c["status"] for c in chains)
    assert by_status == ["closed", "open"]

def test_cross_strike_creates_separate_chains():
    exs = [
        _ex("open1", "S", 100, strike=100.0, price=2.0, t=_T0),
        _ex("close1", "B", 100, strike=100.0, price=0.5, t=_T0 + timedelta(days=10)),
        _ex("open2", "S", 200, strike=90.0, price=2.5, t=_T0 + timedelta(days=12)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 2
    c1 = next(c for c in chains if c["strike"] == 100.0)
    c2 = next(c for c in chains if c["strike"] == 90.0)
    assert c1["status"] == "closed"
    assert c2["status"] == "open"

def test_synthetic_expiry():
    # Option expires on Jan 10
    expiry_date = date(2026, 1, 10)
    exs = [
        _ex("open1", "S", 100, t=_T0, expiry=expiry_date), # Jan 5
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    # the test runs 'now', which is in June 2026, so it should be expired
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "closed"
    assert c["close_reason"] == "expired"
    assert c["closed_at"].date() == expiry_date
    expired_legs = [l for l in legs if l["role"] == "expired"]
    assert len(expired_legs) == 1

def test_assignment_and_stock_close():
    exs = [
        # Short put
        _ex("open1", "S", 100, strike=150.0, right="P", price=2.0, t=_T0),
        # Assignment (Buy stock)
        _ex("stk1", "B", 999, strike=None, right=None, price=150.0, qty=100, sec_type="STK", t=_T0 + timedelta(days=5), notes="A"),
        # Sell stock
        _ex("stk2", "S", 999, strike=None, right=None, price=160.0, qty=100, sec_type="STK", t=_T0 + timedelta(days=10)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "closed"
    assert c["close_reason"] == "assigned_closed"
    # Option premium: 199.0
    # Stock buy (assigned): -150 * 100 - 1 = -15001.0
    # Stock sell: 160 * 100 - 1 = +15999.0
    # Net: 199 - 15001 + 15999 = 1197.0
    assert c["cumulative_credit"] == 1197.0

    roles = [l["role"] for l in legs]
    # Expect: open, assignment (synthetic close), assignment_stock, stock_close
    assert roles == ["open", "assignment", "assignment_stock", "stock_close"]


# --- Regression tests for the real-data symbol bug -------------------------
# Executions carry the full OCC symbol (expiry-encoded). Chains must key on the
# underlying ticker so rolling the same strike to a new expiry stays one chain.

def test_roll_to_new_expiry_same_strike_is_one_chain():
    exs = [
        _ex("e1", "S", 101, symbol="NVDA 260618P00216000", strike=216.0,
            price=2.0, t=_T0, expiry=date(2026, 6, 18)),
        _ex("e2", "B", 101, symbol="NVDA 260618P00216000", strike=216.0,
            price=0.5, t=_T0 + timedelta(days=20), expiry=date(2026, 6, 18)),
        _ex("e3", "S", 102, symbol="NVDA 260718P00216000", strike=216.0,
            price=2.0, t=_T0 + timedelta(days=20), expiry=date(2026, 7, 18)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 1, "same strike rolled to a new expiry must be one chain"
    c = chains[0]
    assert c["status"] == "open"
    assert c["underlying_symbol"] == "NVDA"  # stored as the ticker, not the OCC


def test_assignment_matches_occ_option_symbol():
    """Assignment stock (ticker symbol) must attach to the option chain even
    though the option's symbol is the full OCC string."""
    exs = [
        _ex("o1", "S", 101, symbol="NVDA 260618P00216000", strike=216.0,
            right="P", price=2.0, t=_T0),
        _ex("a1", "B", 999, symbol="NVDA", strike=None, right=None,
            price=216.0, qty=100, sec_type="STK",
            t=_T0 + timedelta(days=5), notes="A"),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    roles = [l["role"] for l in legs]
    assert roles == ["open", "assignment", "assignment_stock"]


def test_eae_expiry_is_labeled_expired_not_bought_back():
    exs = [
        _ex("o1", "S", 101, symbol="NVDA 260618P00216000", strike=216.0,
            price=2.0, t=_T0, expiry=date(2026, 6, 18)),
        # OptionEAE worthless expiry -> synthetic price-0 buy with source flex_eae
        _ex("x1", "B", 101, symbol="NVDA 260618P00216000", strike=216.0,
            price=0.0, comm=0.0, t=_T0 + timedelta(days=20),
            expiry=date(2026, 6, 18), source="flex_eae"),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    c = chains[0]
    assert c["status"] == "closed"
    assert c["close_reason"] == "expired"
    assert c["cumulative_credit"] == 199.0  # full premium kept
    assert any(l["role"] == "expired" for l in legs)


def test_manual_close_adjustment_forces_closed():
    exs = [_ex("open1", "S", 100, price=2.0, t=_T0)]
    close_dt = _T0 + timedelta(days=3)
    adj = ChainAdjustment(
        chain_id=_chain_id("open1"),
        adjustment_type="manual_close",
        close_date=close_dt,
        close_reason="manual_close",
    )
    chains, _ = build_roll_chains(exs, _ACCT, adjustments=[adj])
    c = chains[0]
    assert c["status"] == "closed"
    assert c["close_reason"] == "manual_close"
    assert c["closed_at"] == close_dt


def test_manual_link_merges_cross_strike_chains():
    exs = [
        _ex("e1", "S", 101, strike=216.0, price=2.0, t=_T0),
        _ex("e2", "B", 101, strike=216.0, price=0.5, t=_T0 + timedelta(days=5)),
        # Cross-strike roll to 210 -> auto-builds a separate chain
        _ex("e3", "S", 102, strike=210.0, price=2.5, t=_T0 + timedelta(days=5)),
    ]
    # Without the adjustment: two separate chains.
    chains, _ = build_roll_chains(exs, _ACCT)
    assert len(chains) == 2

    # Link the 210 open into the 216 chain.
    adj = ChainAdjustment(
        chain_id=_chain_id("e1"),
        adjustment_type="manual_link",
        exec_id="e3",
    )
    chains, legs = build_roll_chains(exs, _ACCT, adjustments=[adj])
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "open"            # adopts the open 210 leg
    assert c["cumulative_credit"] == 397.0  # 199 - 51 + 249
    assert all(l["chain_id"] == c["chain_id"] for l in legs)
