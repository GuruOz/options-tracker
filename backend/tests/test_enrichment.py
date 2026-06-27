from datetime import date, datetime, timedelta, timezone

from app.analytics.enrichment import enrich_positions
from app.db.models import MarketSnapshot, PositionSnapshot


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
    
    res = enrich_positions([p], [m], {2: "chain-123"})
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
