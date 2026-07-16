"""Pure functions mapping raw IBKR CP Web API JSON into DB-ready dicts.

No IBKR client or DB imports here — just data in, normalized dicts out — so this
module is exhaustively unit-testable with recorded payload fixtures.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from app.clients.ibkr.fields import (
    FIELD_ASK,
    FIELD_BID,
    FIELD_DELTA,
    FIELD_GAMMA,
    FIELD_LAST,
    FIELD_MARK,
    FIELD_THETA,
    FIELD_VEGA,
    GREEK_PRESENCE_FIELDS,
    IV_FIELD_CANDIDATES,
)
from app.core.occ import parse_occ_symbol

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_float(value) -> float | None:
    """Tolerant numeric parse: handles None, numbers, '1,234.5', 'C150.20', '23%'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUM_RE.search(str(value).replace(",", ""))
    return float(match.group()) if match else None


def to_int(value) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None


def parse_expiry(value) -> date | None:
    """Parse IBKR expiry strings: '20240119' (YYYYMMDD) or '202401' (YYYYMM)."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y%m%d", "%Y%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_option_desc(desc: str | None) -> dict:
    """Pull underlying/right/strike/expiry out of an IBKR option contractDesc.

    Positions rows leave putOrCall/strike/expiry empty for options; the data
    lives in the description, e.g. 'QQQ JUL2026 715 P [QQQ 260702P00715000 100]'.
    The bracketed OSI symbol (yymmdd + C/P + strike*1000) is the reliable source.
    """
    return parse_occ_symbol(desc)


def parse_trade_time(raw: dict) -> datetime | None:
    """Prefer epoch-ms `trade_time_r`; fall back to 'YYYYMMDD-HHMMSS'."""
    epoch_ms = raw.get("trade_time_r")
    if epoch_ms is not None:
        try:
            return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            pass
    s = raw.get("trade_time")
    if s:
        try:
            return datetime.strptime(str(s), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _is_option(asset_class: str | None) -> bool:
    return (asset_class or "").upper() in ("OPT", "FOP", "WAR")


def normalize_position(raw: dict) -> dict:
    """Map a /portfolio/{acct}/positions row to PositionSnapshot columns."""
    asset_class = raw.get("assetClass") or raw.get("secType")
    is_opt = _is_option(asset_class)
    desc = raw.get("contractDesc")

    if is_opt:
        parsed = parse_option_desc(desc)
        underlying = parsed["underlying"] or raw.get("ticker")
        right = parsed["right"] or (raw.get("putOrCall") or None)
        strike = parsed["strike"]
        if strike is None:
            s = to_float(raw.get("strike"))
            strike = s if s else None  # positions often report strike 0 for opts
        expiry = parsed["expiry"] or parse_expiry(raw.get("expiry"))
    else:
        underlying = raw.get("ticker") or desc
        right = strike = expiry = None

    symbol = (underlying or desc or "")[:64] or None
    return {
        "conid": to_int(raw.get("conid")),
        "symbol": symbol,
        "sec_type": asset_class,
        "right": right,
        "strike": strike,
        "expiry": expiry,
        "position": to_float(raw.get("position")),
        "avg_cost": to_float(raw.get("avgCost")),
        "mark": to_float(raw.get("mktPrice")),
        "market_value": to_float(raw.get("mktValue")),
        "unrealized_pnl": to_float(raw.get("unrealizedPnl")),
        # The contract's own trading currency - not the account's base
        # currency. IBKR reports this separately and never converts it.
        "currency": raw.get("currency") or None,
        "raw": raw,
    }


_SUMMARY_KEYS = {
    "net_liquidation": ("netliquidation",),
    "available_funds": ("availablefunds",),
    "excess_liquidity": ("excessliquidity",),
    "maintenance_margin": ("fullmaintmarginreq", "maintmarginreq"),
    "buying_power": ("buyingpower",),
    "cash": ("totalcashvalue", "totalcashbalance"),
    "leverage": ("leverage",),
}


def normalize_summary(raw: dict) -> dict:
    """Map /portfolio/{acct}/summary (keyed metrics with .amount) to columns."""
    def amount(*keys) -> float | None:
        for k in keys:
            cell = raw.get(k)
            if isinstance(cell, dict) and cell.get("amount") is not None:
                return to_float(cell["amount"])
            if cell is not None and not isinstance(cell, dict):
                return to_float(cell)
        return None

    def currency(*keys) -> str | None:
        for k in keys:
            cell = raw.get(k)
            if isinstance(cell, dict) and cell.get("currency"):
                return cell["currency"]
        return None

    result = {field: amount(*keys) for field, keys in _SUMMARY_KEYS.items()}
    # The account's base currency - IBKR converts every summary total (net
    # liq, buying power, ...) into this currency, unlike individual
    # position/trade prices which stay in the contract's own currency.
    result["base_currency"] = currency("netliquidation", "totalcashvalue", "availablefunds")
    return result


def normalize_trade(raw: dict, account_id: str | None = None) -> dict:
    """Map a /iserver/account/trades row to Execution columns."""
    asset_class = raw.get("sec_type") or raw.get("secType")
    is_opt = _is_option(asset_class)
    qty_raw = to_float(raw.get("size"))
    symbol = ((raw.get("symbol") or raw.get("contract_description_1") or "")[:64]) or None

    # The trades feed often omits strike/right/expiry for options; recover them
    # from the OSI symbol so chains key + label correctly (e.g. "NVDA 216P").
    right = strike = expiry = None
    if is_opt:
        right = raw.get("put_or_call") or None
        strike = to_float(raw.get("strike")) or None  # feed reports 0 for opts
        expiry = parse_expiry(raw.get("expiry"))
        if right is None or strike is None or expiry is None:
            occ = parse_occ_symbol(symbol)
            right = right or occ["right"]
            strike = strike if strike is not None else occ["strike"]
            expiry = expiry or occ["expiry"]

    return {
        "exec_id": raw.get("execution_id") or raw.get("exec_id"),
        "account_id": account_id or raw.get("account") or raw.get("acctId"),
        "conid": to_int(raw.get("conid")),
        "symbol": symbol,
        "sec_type": asset_class,
        "side": raw.get("side"),
        "right": right,
        "strike": strike,
        "expiry": expiry,
        "qty": abs(qty_raw) if qty_raw is not None else None,
        "price": to_float(raw.get("price")),
        "commission": to_float(raw.get("commission")),
        "realized_pnl": to_float(raw.get("realized_pnl")),
        "currency": raw.get("currency") or None,
        "exec_time": parse_trade_time(raw),
        "source": "poll",
        "raw": raw,
    }


def snapshot_has_greeks(row: dict) -> bool:
    """True if a snapshot row carries at least one Greek (i.e. it has warmed up)."""
    return any(code in row for code in GREEK_PRESENCE_FIELDS)


def parse_history(raw: dict) -> list[float]:
    """Extract the close series from /iserver/marketdata/history (oldest->newest)."""
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        return []
    closes = [to_float(bar.get("c")) for bar in data if isinstance(bar, dict)]
    return [c for c in closes if c is not None]


def parse_history_bars(raw: dict) -> list[tuple[date, float]]:
    """Extract ``(date, close)`` pairs from /iserver/marketdata/history.

    History bars carry an epoch-ms timestamp ``t`` and close ``c`` (oldest->newest).
    Rows missing either, or with an unparseable timestamp, are skipped. Used to
    persist the daily series that backs the market-context chart.
    """
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        return []
    out: list[tuple[date, float]] = []
    for bar in data:
        if not isinstance(bar, dict):
            continue
        close = to_float(bar.get("c"))
        t = bar.get("t")
        if close is None or t is None:
            continue
        try:
            d = datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc).date()
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        out.append((d, close))
    return out


def parse_underlying_quote(row: dict) -> dict:
    """Pull last price and an implied-vol index (percent) from a snapshot row."""
    iv = None
    for code in IV_FIELD_CANDIDATES:
        if code in row:
            iv = to_float(row[code])
            if iv is not None:
                break
    return {"price": to_float(row.get(FIELD_LAST)), "iv": iv}


def parse_snapshot_row(row: dict) -> dict:
    """Extract marks + Greeks from a /marketdata/snapshot row."""
    iv = None
    for code in IV_FIELD_CANDIDATES:
        if code in row:
            iv = to_float(row[code])
            if iv is not None:
                break
    return {
        "last": to_float(row.get(FIELD_LAST)),
        "bid": to_float(row.get(FIELD_BID)),
        "ask": to_float(row.get(FIELD_ASK)),
        "mark": to_float(row.get(FIELD_MARK)),
        "delta": to_float(row.get(FIELD_DELTA)),
        "gamma": to_float(row.get(FIELD_GAMMA)),
        "theta": to_float(row.get(FIELD_THETA)),
        "vega": to_float(row.get(FIELD_VEGA)),
        "iv": iv,
        "has_greeks": snapshot_has_greeks(row),
    }
