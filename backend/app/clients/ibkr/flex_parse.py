"""Parse IBKR Flex Query Activity Statement XML into normalized trade dicts.

The flex query returns XML with <Trade> elements under <FlexStatement>/<Trades>.
Each trade is idempotently upserted into `executions` by exec_id.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from typing import Any


def _text(elem: ET.Element | None, key: str) -> str | None:
    """Get attribute value from an XML element."""
    if elem is None:
        return None
    return elem.get(key) or None


def _float_val(elem: ET.Element | None, key: str) -> float | None:
    v = _text(elem, key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int_val(elem: ET.Element | None, key: str) -> int | None:
    v = _text(elem, key)
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _parse_flex_time(value: str | None) -> datetime | None:
    """Parse IBKR flex query timestamps: '2026-06-20T14:30:00.000-05:00' or '20260620;143000'."""
    if not value:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y%m%d;%H%M%S",
        "%Y%m%d",
    ):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _parse_expiry_date(value: str | None) -> date | None:
    """Parse expiry '20260717' -> date(2026, 7, 17).

    Returns a `datetime.date` (not a string) because the executions.expiry
    column is a SQL DATE — asyncpg rejects str values for DATE bindings.
    Also accepts already-hyphenated '2026-07-17'. Unparseable input -> None.
    """
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _side_from_buy_sell(buy_sell: str | None) -> str | None:
    if buy_sell is None:
        return None
    v = buy_sell.upper().strip()
    if v == "BUY":
        return "B"
    if v == "SELL":
        return "S"
    return v


def _right_from_put_call(put_call: str | None) -> str | None:
    if put_call is None:
        return None
    v = put_call.upper().strip()
    if v == "P":
        return "P"
    if v == "C":
        return "C"
    return v


def parse_flex_xml(xml_text: str, account_id: str) -> list[dict[str, Any]]:
    """Parse an IBKR Flex Query Activity Statement XML into trade dicts.

    Returns a list of dicts suitable for upsert into the `executions` table.
    """
    root = ET.fromstring(xml_text)
    trades: list[dict[str, Any]] = []

    ns = ""
    if "}" in (root.tag or ""):
        ns = root.tag.split("}")[0] + "}"

    for stmt in root.iter(f"{ns}FlexStatement"):
        trades_elem = stmt.find(f"{ns}Trades")
        if trades_elem is None:
            continue
        for trade in trades_elem.findall(f"{ns}Trade"):
            exec_id = _text(trade, "execId") or _text(trade, "tradeID")
            if not exec_id:
                continue

            asset = (_text(trade, "assetCategory") or "").upper()
            if asset not in ("OPT", "FOP", "FUT", "STK", "CASH"):
                continue

            symbol = _text(trade, "symbol")
            side = _side_from_buy_sell(_text(trade, "buySell"))
            put_call = _right_from_put_call(_text(trade, "putCall"))
            sec_type = asset

            trades.append({
                "exec_id": exec_id,
                "account_id": account_id,
                "conid": _int_val(trade, "conid"),
                "symbol": symbol[:64] if symbol else None,
                "sec_type": sec_type,
                "side": side,
                "right": put_call if sec_type in ("OPT", "FOP", "FUT") else None,
                "strike": _float_val(trade, "strike"),
                "expiry": _parse_expiry_date(_text(trade, "expiry")),
                "qty": _float_val(trade, "quantity"),
                "price": _float_val(trade, "tradePrice"),
                "commission": _float_val(trade, "ibCommission"),
                "realized_pnl": _float_val(trade, "fifoPnlRealized"),
                "exec_time": _parse_flex_time(
                    _text(trade, "tradeDate") or _text(trade, "dateTime")
                ),
                "source": "flex",
                "raw": {
                    k: v for k, v in trade.attrib.items()
                    if v is not None
                },
            })

        # Also parse OptionEAE for expirations
        for eae in stmt.iter(f"{ns}OptionEAE"):
            ttype = _text(eae, "transactionType")
            if not ttype or ttype.upper() != "EXPIRATION":
                continue

            symbol = _text(eae, "symbol")
            qty = _float_val(eae, "quantity")
            if not qty:
                continue

            exec_id = _text(eae, "transactionID")
            if not exec_id:
                date_val = _text(eae, "date") or ""
                conid_val = _text(eae, "conid") or ""
                exec_id = f"eae_exp_{conid_val}_{date_val}"

            # If qty < 0 (short), we Buy to close. If qty > 0 (long), we Sell to close.
            side = "B" if qty < 0 else "S"

            trades.append({
                "exec_id": exec_id,
                "account_id": account_id,
                "conid": _int_val(eae, "conid"),
                "symbol": symbol[:64] if symbol else None,
                "sec_type": "OPT",
                "side": side,
                "right": _right_from_put_call(_text(eae, "putCall")),
                "strike": _float_val(eae, "strike"),
                "expiry": _parse_expiry_date(_text(eae, "expiry") or _text(eae, "date")),
                "qty": abs(qty),
                "price": 0.0,
                "commission": 0.0,
                "realized_pnl": 0.0,
                "exec_time": _parse_flex_time(_text(eae, "date")),
                "source": "flex_eae",
                "raw": {k: v for k, v in eae.attrib.items() if v is not None},
            })

    return trades
