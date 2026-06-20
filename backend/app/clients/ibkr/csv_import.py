"""Parse IBKR Activity Statement CSV exports into normalized trade dicts.

Handles the CSV format exported from IBKR Client Portal:
  Reports -> Activity -> Custom Date Range -> Download (CSV)
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any


_SIDE_MAP: dict[str, str] = {"b": "B", "s": "S", "buy": "B", "sell": "S"}


def _parse_exec_time(value: str | None) -> datetime | None:
    """Parse IBKR datetime formats like '2026-06-20, 14:30:00' or '20260620;143000'."""
    if not value:
        return None
    v = value.strip()
    for fmt in (
        "%Y-%m-%d, %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d;%H%M%S",
        "%Y%m%d",
    ):
        try:
            dt = datetime.strptime(v, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _parse_expiry(value: str | None) -> date | None:
    """'20260717' -> date(2026, 7, 17). Returns a date (not str) for the DATE column."""
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _exec_id(row: dict[str, str], idx: int) -> str:
    """Build a deterministic exec_id from row data."""
    date = (row.get("Date/Time") or "").replace(",", "").replace(" ", "").replace(":", "").replace("-", "").replace(";", "")
    sym = (row.get("Symbol") or "X")[:8]
    side = (row.get("Code") or "")[:1]
    return f"csv_{date}_{sym}_{side}_{idx}"


def _parse_option_symbol(symbol: str | None) -> dict:
    """Parse IBKR option description into underlying, strike, right, expiry."""
    result: dict = {"underlying": None, "strike": None, "right": None, "expiry": None}
    if not symbol:
        return result
    parts = symbol.strip().split()
    if not parts:
        return result
    result["underlying"] = parts[0]
    for p in parts[1:]:
        if p.upper() in ("P", "C"):
            result["right"] = p[:1].upper()
        try:
            result["strike"] = float(p)
        except ValueError:
            pass
        try:
            result["expiry"] = datetime.strptime(p.upper(), "%d%b%y").date()
        except ValueError:
            pass
    return result


def parse_ibkr_csv(content: bytes | str, account_id: str) -> list[dict[str, Any]]:
    """Parse IBKR Activity Statement CSV and return trade dicts for upsert."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(content))
    trades: list[dict[str, Any]] = []

    for idx, row in enumerate(reader):
        category = (row.get("Asset Category") or "").upper().strip()
        symbol_raw = (row.get("Symbol") or "").strip()
        date_raw = row.get("Date/Time", "").strip()

        if category not in ("OPT", "FOP", "STK", "FUT"):
            continue
        if not symbol_raw or not date_raw:
            continue

        # Signed quantity: IBKR reports negative for sells, positive for buys.
        qty_signed = None
        if row.get("Quantity"):
            try:
                qty_signed = float(str(row["Quantity"]).replace(",", ""))
            except ValueError:
                qty_signed = None

        # Side: prefer an explicit Buy/Sell column, then the sign of Quantity.
        # IBKR's "Code" column holds trade codes (O/C/A/Ex/...), NOT buy/sell,
        # so it must not be used to determine direction.
        buysell = (row.get("Buy/Sell") or "").strip().lower()
        if buysell in _SIDE_MAP:
            side = _SIDE_MAP[buysell]
        elif qty_signed is not None:
            side = "S" if qty_signed < 0 else "B"
        else:
            side = None

        opt_info = _parse_option_symbol(symbol_raw)

        trades.append({
            "exec_id": _exec_id(row, idx),
            "account_id": account_id,
            "conid": None,
            "symbol": symbol_raw[:64],
            "sec_type": category,
            "side": side,
            "right": opt_info["right"],
            "strike": opt_info["strike"],
            "expiry": opt_info["expiry"],
            # Store the unsigned magnitude (consistent with the poll path); the
            # `side` column carries direction.
            "qty": abs(qty_signed) if qty_signed is not None else None,
            "price": (
                float(row["T. Price"]) if row.get("T. Price")
                else float(row["Trade Price"]) if row.get("Trade Price")
                else None
            ),
            "commission": float(row["Comm/Fee"]) if row.get("Comm/Fee") else None,
            "realized_pnl": float(row["Realized P/L"]) if row.get("Realized P/L") else None,
            "exec_time": _parse_exec_time(date_raw),
            "source": "flex_import",
            "raw": {k: v for k, v in row.items() if v},
        })

    return trades
