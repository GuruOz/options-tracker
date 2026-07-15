from datetime import date, datetime, timedelta, timezone

from app.analytics.enrichment import enrich_positions
from app.db.models import MarketSnapshot, PositionSnapshot


def _chain(chain_id, *, cumulative, initial, cycle_base=0.0):
    """One entry of the conid -> open-chain map (see repo.open_roll_chains)."""
    return {
        "chain_id": chain_id,
        "cumulative_credit": cumulative,
        "initial_credit": initial,
        "cycle_base_credit": cycle_base,
    }


def test_enrich_short_put():
    today = datetime.now(timezone.utc).date()
    p = PositionSnapshot(
        conid=1,
        symbol="QQQ",
        sec_type="OPT",
        right="P",
        strike=400.0,
        expiry=today + timedelta(days=10),
        position=-2.0,
        avg_cost=500.0,  # Credit received (per contract, so if avg_cost is 5.00 * 100)
        mark=2.0,
    )
    m = MarketSnapshot(symbol="QQQ", price=450.0)
    
    res = enrich_positions([p], [m], {})
    assert len(res) == 1
    out = res[0]
    
    assert out.dte == 10
    # intrinsic = max(0, 400 - 450) = 0
    # extrinsic = 2.0 - 0 = 2.0
    assert out.extrinsic_value == 2.0
    # cushion = (450 - 400) / 450 = 50 / 450 = 0.111...
    assert round(out.cushion_pct, 4) == 0.1111
    # captured: avg_cost is 500 (total cash), mark is 2.0 (per share).
    # current_cost = 2.0 * 100 = 200. (500 - 200) / 500 = 300 / 500 = 0.6
    assert out.premium_captured_pct == 0.6
    assert out.status == "OPEN"
    # break-even = strike - premium/share = 400 - 5.00 = 395
    assert out.breakeven == 395.0
    # BE cushion = (450 - 395) / 450 = 55 / 450 = 0.1222...; wider than the
    # raw strike cushion (0.1111) because the collected premium extends the buffer.
    assert round(out.breakeven_cushion_pct, 4) == 0.1222
    assert out.breakeven_cushion_pct > out.cushion_pct


def test_enrich_breakeven_cushion_short_call():
    today = datetime.now(timezone.utc).date()
    p = PositionSnapshot(
        conid=9, symbol="QQQ", sec_type="OPT", right="C", strike=500.0,
        expiry=today + timedelta(days=10), position=-1.0,
        avg_cost=300.0,  # $3.00/share premium collected
        mark=1.0,
    )
    m = MarketSnapshot(symbol="QQQ", price=490.0)
    out = enrich_positions([p], [m], {})[0]
    # call break-even = strike + premium/share = 500 + 3 = 503
    assert out.breakeven == 503.0
    # BE cushion = (503 - 490) / 490 = 13 / 490 = 0.0265
    assert round(out.breakeven_cushion_pct, 4) == 0.0265


def test_enrich_short_call_itm():
    today = datetime.now(timezone.utc).date()
    p = PositionSnapshot(
        conid=2,
        symbol="SPY",
        sec_type="OPT",
        right="C",
        strike=500.0,
        expiry=today + timedelta(days=1),
        position=-1.0,
        avg_cost=1000.0,
        mark=15.0,
    )
    m = MarketSnapshot(symbol="SPY", price=510.0)
    
    res = enrich_positions([p], [m], {2: _chain("chain-123", cumulative=1000.0, initial=1000.0)})
    out = res[0]

    assert out.chain_id == "chain-123"
    assert out.dte == 1
    # intrinsic = max(0, 510 - 500) = 10.0
    # extrinsic = 15.0 - 10.0 = 5.0
    assert out.extrinsic_value == 5.0
    # cushion = (500 - 510) / 510 < 0, AT RISK
    assert out.cushion_pct < 0
    assert out.status == "AT RISK" # cushion takes precedence if < 0.03


def test_enrich_watch_thin_cushion():
    today = datetime.now(timezone.utc).date()
    p = PositionSnapshot(
        conid=4,
        symbol="QQQ",
        sec_type="OPT",
        right="P",
        strike=100.0,
        expiry=today + timedelta(days=10),
        position=-1.0,
        avg_cost=100.0,
        mark=0.5,  # 50% captured — below the 65% watch band, so cushion drives it
    )
    m = MarketSnapshot(symbol="QQQ", price=104.0)  # cushion = 4 / 104 = 3.85%

    out = enrich_positions([p], [m], {})[0]
    # Cushion 3.85% clears AT RISK (< 3%) but is inside the WATCH band (< 5%).
    assert round(out.cushion_pct, 4) == 0.0385
    assert out.status == "WATCH"


def test_enrich_take_profit():
    p = PositionSnapshot(
        conid=3,
        symbol="AAPL",
        sec_type="OPT",
        right="P",
        strike=150.0,
        position=-1.0,
        avg_cost=400.0,
        mark=1.0, # 75% captured, current cost = 1.0 * 100 = 100
    )
    m = MarketSnapshot(symbol="AAPL", price=170.0)

    res = enrich_positions([p], [m], {})
    out = res[0]

    assert out.premium_captured_pct == 0.75
    assert out.status == "TAKE PROFIT"


# --- Capture is judged on the chain, not the newest leg ---------------------
# Rolling re-sells a fresh, fatter premium, so the open leg can read "76%
# captured" while the trade is only part-way to the premium it's working toward.
# These pin the real NVDA case: 216P sold @6.95, rolled out to a 215P now
# carrying $2,126 of credit and marked at $5.10.


def test_chain_capture_overrides_optimistic_leg_capture():
    p = PositionSnapshot(
        conid=7, symbol="NVDA", sec_type="OPT", right="P", strike=215.0,
        expiry=datetime.now(timezone.utc).date() + timedelta(days=36),
        position=-1.0,
        avg_cost=2126.0,  # the current leg's credit
        mark=5.10,        # 76% of *this leg* captured
    )
    m = MarketSnapshot(symbol="NVDA", price=232.0)
    chains = {7: _chain("rc_nvda", cumulative=791.0, initial=695.0)}

    out = enrich_positions([p], [m], chains)[0]

    assert round(out.premium_captured_pct, 2) == 0.76  # the leg looks done…
    # …but unwinding the chain only nets 791 - 510 = 281 of the 695 it's after.
    assert round(out.chain_profit_if_closed, 2) == 281.0
    assert out.chain_initial_credit == 695.0
    assert round(out.chain_captured_pct, 4) == 0.4043
    assert out.status == "OPEN"  # NOT "TAKE PROFIT"


def test_chain_capture_fires_take_profit_when_chain_is_really_done():
    p = PositionSnapshot(
        conid=8, symbol="NVDA", sec_type="OPT", right="P", strike=215.0,
        expiry=datetime.now(timezone.utc).date() + timedelta(days=36),
        position=-1.0, avg_cost=2126.0,
        mark=0.60,  # buying the short back costs 60
    )
    m = MarketSnapshot(symbol="NVDA", price=260.0)
    # Closing now nets 791 - 60 = 731 against the 695 target -> over 100%.
    out = enrich_positions([p], [m], {8: _chain("rc_nvda", cumulative=791.0, initial=695.0)})[0]

    assert out.chain_captured_pct > 0.7
    assert out.status == "TAKE PROFIT"


def test_chain_capture_measures_from_cycle_base():
    # A chain that already banked 500 on an earlier cycle then sold a new put for
    # 300: only the new cycle counts, so closing at a 90 mark is (800-500-90)/300.
    p = PositionSnapshot(
        conid=10, symbol="QQQ", sec_type="OPT", right="P", strike=400.0,
        expiry=datetime.now(timezone.utc).date() + timedelta(days=20),
        position=-1.0, avg_cost=300.0, mark=0.90,
    )
    m = MarketSnapshot(symbol="QQQ", price=450.0)
    chains = {10: _chain("rc_q", cumulative=800.0, initial=300.0, cycle_base=500.0)}

    out = enrich_positions([p], [m], chains)[0]
    assert out.chain_profit_if_closed == 210.0
    assert round(out.chain_captured_pct, 4) == 0.70


def test_chain_capture_nets_every_open_leg_in_the_chain():
    # Two shorts in one chain: each row must net against both buybacks, not just
    # its own, or each would claim the chain's whole credit.
    exp = datetime.now(timezone.utc).date() + timedelta(days=20)
    a = PositionSnapshot(conid=11, symbol="QQQ", sec_type="OPT", right="P", strike=400.0,
                         expiry=exp, position=-1.0, avg_cost=300.0, mark=1.0)
    b = PositionSnapshot(conid=12, symbol="QQQ", sec_type="OPT", right="P", strike=390.0,
                         expiry=exp, position=-1.0, avg_cost=300.0, mark=2.0)
    m = MarketSnapshot(symbol="QQQ", price=450.0)
    info = _chain("rc_two", cumulative=900.0, initial=600.0)
    out = enrich_positions([a, b], [m], {11: info, 12: info})

    # Both legs cost 100 + 200 = 300 to buy back -> 900 - 300 = 600 of the 600 target.
    for o in out:
        assert o.chain_profit_if_closed == 600.0
        assert o.chain_captured_pct == 1.0


def test_position_without_chain_keeps_leg_capture_only():
    p = PositionSnapshot(
        conid=13, symbol="AAPL", sec_type="OPT", right="P", strike=150.0,
        position=-1.0, avg_cost=400.0, mark=1.0,
    )
    m = MarketSnapshot(symbol="AAPL", price=170.0)
    out = enrich_positions([p], [m], {})[0]

    assert out.chain_captured_pct is None
    assert out.chain_profit_if_closed is None
    assert out.premium_captured_pct == 0.75
    assert out.status == "TAKE PROFIT"  # still judged on the leg
