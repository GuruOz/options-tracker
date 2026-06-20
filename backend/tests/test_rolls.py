"""Unit tests for roll-chain detection (`analytics/rolls.py`).

Focus on the cases the look-ahead roll detection has to get right: fresh opens,
plain closes, and — critically — rolls (buy-to-close immediately followed by a
sell-to-open), both within a single batch and continuing a chain seeded from a
prior run.
"""
from datetime import datetime, timedelta, timezone

from app.analytics.rolls import build_roll_chains
from app.db.models import Execution

_T0 = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
_ACCT = "U123"


def _ex(exec_id, side, conid, *, symbol="QQQ", right="P",
        t=_T0, qty=1.0, price=1.0, comm=1.0, sec_type="OPT"):
    return Execution(
        exec_id=exec_id, account_id=_ACCT, conid=conid, symbol=symbol,
        sec_type=sec_type, side=side, right=right, qty=qty, price=price,
        commission=comm, exec_time=t,
    )


def _legs_for(legs, exec_id):
    return [l for l in legs if l["exec_id"] == exec_id]


def test_fresh_open():
    chains, legs = build_roll_chains([_ex("e1", "S", 100, price=2.0)], _ACCT)
    assert len(chains) == 1
    assert chains[0]["status"] == "open"
    # 1 contract * 2.00 * 100 - 1.00 comm = 199.0
    assert chains[0]["cumulative_credit"] == 199.0
    assert len(legs) == 1 and legs[0]["role"] == "open"


def test_open_then_close_beyond_window_closes_chain():
    exs = [
        _ex("e1", "S", 100, price=2.0, t=_T0),
        _ex("e2", "B", 100, price=0.5, t=_T0 + timedelta(minutes=10)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)
    assert len(chains) == 1
    c = chains[0]
    assert c["status"] == "closed"
    assert c["closed_at"] == _T0 + timedelta(minutes=10)
    # 199.0 (sell) + -(50 + 1) (buy) = 148.0
    assert c["cumulative_credit"] == 148.0
    roles = sorted(l["role"] for l in legs)
    assert roles == ["close", "open"]


def test_roll_in_single_batch_keeps_one_open_chain():
    """SELL(X) → BUY(X) → SELL(Y) within the window is ONE chain, still open,
    and the buy-to-close is counted exactly once."""
    exs = [
        _ex("open1", "S", 100, price=2.0, t=_T0),
        _ex("close1", "B", 100, price=0.5, t=_T0 + timedelta(minutes=1)),
        _ex("open2", "S", 200, price=2.5, t=_T0 + timedelta(minutes=2)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT)

    assert len(chains) == 1, "a roll must not fragment into multiple chains"
    c = chains[0]
    assert c["status"] == "open"
    assert c["closed_at"] is None
    # 199.0 - 51.0 + 249.0 = 397.0  (buy counted ONCE)
    assert c["cumulative_credit"] == 397.0

    # Exactly three legs, all on the same chain; the buy appears once.
    assert len(legs) == 3
    assert {l["chain_id"] for l in legs} == {c["chain_id"]}
    assert len(_legs_for(legs, "close1")) == 1
    # The new conid is the one tracked as open.
    open_legs = [l for l in legs if l["role"] == "open"]
    assert {l["conid"] for l in open_legs} == {100, 200}


def test_cross_batch_roll_continues_seeded_chain():
    """A roll whose original open lives in a prior run must continue that exact
    chain (same chain_id), stay open, and not double-count the buy."""
    existing = {
        100: {
            "chain_id": "rc_existing",
            "account_id": _ACCT,
            "underlying_symbol": "QQQ",
            "underlying_conid": None,
            "right": "P",
            "status": "open",
            "opened_at": _T0 - timedelta(days=20),
            "closed_at": None,
            "cumulative_credit": 199.0,  # credit from the original open
            "meta": None,
        }
    }
    exs = [
        _ex("close1", "B", 100, price=0.5, t=_T0),
        _ex("open2", "S", 200, price=2.5, t=_T0 + timedelta(minutes=1)),
    ]
    chains, legs = build_roll_chains(exs, _ACCT, existing_open_chains=existing)

    assert len(chains) == 1
    c = chains[0]
    assert c["chain_id"] == "rc_existing", "must continue the seeded chain"
    assert c["status"] == "open"
    assert c["closed_at"] is None
    # 199.0 (seeded) - 51.0 (buy) + 249.0 (new sell) = 397.0
    assert c["cumulative_credit"] == 397.0
    assert len(_legs_for(legs, "close1")) == 1


def test_cross_batch_plain_close_closes_seeded_chain():
    existing = {
        100: {
            "chain_id": "rc_existing",
            "account_id": _ACCT,
            "underlying_symbol": "QQQ",
            "underlying_conid": None,
            "right": "P",
            "status": "open",
            "opened_at": _T0 - timedelta(days=20),
            "closed_at": None,
            "cumulative_credit": 199.0,
            "meta": None,
        }
    }
    exs = [_ex("close1", "B", 100, price=0.5, t=_T0)]
    chains, legs = build_roll_chains(exs, _ACCT, existing_open_chains=existing)

    assert len(chains) == 1
    c = chains[0]
    assert c["chain_id"] == "rc_existing"
    assert c["status"] == "closed"
    assert c["cumulative_credit"] == 148.0  # 199 - 51


def test_buy_then_sell_different_right_is_not_a_roll():
    """Closing a put and opening a call within the window is NOT a same-right
    roll — the put chain closes and the call opens a fresh chain."""
    exs = [
        _ex("openP", "S", 100, right="P", t=_T0),
        _ex("closeP", "B", 100, right="P", t=_T0 + timedelta(minutes=1)),
        _ex("openC", "S", 300, right="C", t=_T0 + timedelta(minutes=2)),
    ]
    chains, _ = build_roll_chains(exs, _ACCT)
    assert len(chains) == 2
    by_status = sorted(c["status"] for c in chains)
    assert by_status == ["closed", "open"]


def test_orphan_buy_creates_closed_chain():
    chains, legs = build_roll_chains([_ex("b1", "B", 100, price=0.5)], _ACCT)
    assert len(chains) == 1
    assert chains[0]["status"] == "closed"
    assert legs[0]["role"] == "close"
