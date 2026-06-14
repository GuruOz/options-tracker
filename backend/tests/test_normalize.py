from datetime import date

from app.clients.ibkr.normalize import (
    normalize_position,
    normalize_summary,
    normalize_trade,
    parse_expiry,
    parse_history,
    parse_option_desc,
    parse_snapshot_row,
    parse_trade_time,
    parse_underlying_quote,
    to_float,
)


def test_to_float_tolerant():
    assert to_float(None) is None
    assert to_float(1.5) == 1.5
    assert to_float("1,234.5") == 1234.5
    assert to_float("C150.20") == 150.20   # leading market-data prefix
    assert to_float("-0.45") == -0.45
    assert to_float("n/a") is None


def test_parse_expiry():
    assert parse_expiry("20240119") == date(2024, 1, 19)
    assert parse_expiry("202401") == date(2024, 1, 1)
    assert parse_expiry("") is None
    assert parse_expiry(None) is None


def test_parse_trade_time_prefers_epoch_ms():
    dt = parse_trade_time({"trade_time_r": 1705591800000, "trade_time": "20240118-153000"})
    assert dt is not None and dt.year == 2024 and dt.tzinfo is not None


def test_parse_trade_time_string_fallback():
    dt = parse_trade_time({"trade_time": "20240118-153000"})
    assert dt is not None and dt.year == 2024 and dt.month == 1 and dt.day == 18


def test_normalize_position_option():
    raw = {
        "conid": 265598, "ticker": "AAPL", "contractDesc": "AAPL 19JAN24 150 P",
        "position": -2, "mktPrice": 1.25, "mktValue": -250, "avgCost": 2.0,
        "unrealizedPnl": 150, "assetClass": "OPT", "strike": "150",
        "putOrCall": "P", "expiry": "20240119",
    }
    n = normalize_position(raw)
    assert n["conid"] == 265598
    assert n["sec_type"] == "OPT"
    assert n["right"] == "P"
    assert n["strike"] == 150.0
    assert n["expiry"] == date(2024, 1, 19)
    assert n["position"] == -2.0
    assert n["mark"] == 1.25


def test_parse_option_desc_from_osi():
    p = parse_option_desc("QQQ    JUL2026 715 P [QQQ   260702P00715000 100]")
    assert p["underlying"] == "QQQ"
    assert p["right"] == "P"
    assert p["strike"] == 715.0
    assert p["expiry"] == date(2026, 7, 2)


def test_normalize_position_option_from_description_only():
    # The real failing payload: putOrCall/strike/expiry empty, data in the desc,
    # and the desc is far longer than the old 32-char column.
    raw = {
        "conid": 885518714,
        "contractDesc": "QQQ    JUL2026 715 P [QQQ   260702P00715000 100]",
        "position": -1.0, "mktPrice": 13.5, "mktValue": -1350.75,
        "avgCost": 1798.81, "unrealizedPnl": 448.06, "assetClass": "OPT",
        "putOrCall": None, "strike": 0.0, "expiry": None,
    }
    n = normalize_position(raw)
    assert n["symbol"] == "QQQ"        # underlying, not the 48-char description
    assert len(n["symbol"]) <= 64
    assert n["right"] == "P"
    assert n["strike"] == 715.0
    assert n["expiry"] == date(2026, 7, 2)
    assert n["position"] == -1.0


def test_normalize_position_stock_ignores_option_fields():
    raw = {
        "conid": 265599, "ticker": "AAPL", "position": 100, "mktPrice": "C150.20",
        "mktValue": 15020, "avgCost": 145, "unrealizedPnl": 520,
        "assetClass": "STK", "strike": "0", "putOrCall": None,
    }
    n = normalize_position(raw)
    assert n["sec_type"] == "STK"
    assert n["right"] is None
    assert n["strike"] is None
    assert n["expiry"] is None
    assert n["mark"] == 150.20


def test_normalize_summary():
    raw = {
        "netliquidation": {"amount": 100000, "currency": "USD"},
        "availablefunds": {"amount": 50000},
        "excessliquidity": {"amount": 60000},
        "fullmaintmarginreq": {"amount": 20000},
        "buyingpower": {"amount": 200000},
        "totalcashvalue": {"amount": 30000},
    }
    n = normalize_summary(raw)
    assert n["net_liquidation"] == 100000.0
    assert n["maintenance_margin"] == 20000.0
    assert n["cash"] == 30000.0
    assert n["leverage"] is None


def test_normalize_trade_commission_and_ids():
    raw = {
        "execution_id": "00abc.1", "symbol": "AAPL", "side": "S", "price": "2.05",
        "size": 2, "conid": 265598, "sec_type": "OPT", "commission": "1.10",
        "account": "U123", "put_or_call": "P", "strike": "150",
        "expiry": "20240119", "trade_time_r": 1705591800000,
    }
    n = normalize_trade(raw, account_id="U123")
    assert n["exec_id"] == "00abc.1"
    assert n["account_id"] == "U123"
    assert n["side"] == "S"
    assert n["qty"] == 2.0
    assert n["price"] == 2.05
    assert n["commission"] == 1.10
    assert n["right"] == "P"
    assert n["strike"] == 150.0


def test_parse_snapshot_row_greeks_and_iv_priority():
    row = {
        "conid": 265598, "31": "1.25", "84": "1.20", "86": "1.30", "7635": "1.25",
        "7308": "-0.35", "7309": "0.02", "7310": "-0.04", "7311": "0.10",
        "7283": "24.5", "7633": "99.9",
    }
    s = parse_snapshot_row(row)
    assert s["delta"] == -0.35
    assert s["iv"] == 24.5          # 7283 preferred over 7633
    assert s["has_greeks"] is True


def test_parse_history_closes():
    raw = {"data": [{"t": 1, "c": 100.0}, {"t": 2, "c": "101.5"}, {"t": 3}]}
    assert parse_history(raw) == [100.0, 101.5]
    assert parse_history({}) == []


def test_parse_underlying_quote():
    q = parse_underlying_quote({"31": "452.30", "7283": "23.5"})
    assert q["price"] == 452.30
    assert q["iv"] == 23.5
    assert parse_underlying_quote({"31": "100"})["iv"] is None


def test_parse_snapshot_row_iv_fallback_and_warmup():
    # No 7283 -> fall back to 7633.
    assert parse_snapshot_row({"conid": 1, "7308": "0.1", "7633": "30"})["iv"] == 30.0
    # Partial warm-up row with only conid -> no greeks yet.
    assert parse_snapshot_row({"conid": 1, "_updated": 123})["has_greeks"] is False
