"""Parse OCC/OSI option symbols into their components.

IBKR stores an option's identity in an OSI-style symbol —
``<root> <yymmdd><C|P><strike×1000>``, e.g. ``NVDA 260618P00216000`` is an NVDA
put expiring 2026-06-18 at strike 216.0. The trade/execution feeds sometimes
leave the explicit strike/right/expiry fields empty while always carrying this
symbol, so it's the reliable fallback for recovering those values.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# yymmdd + C/P + strike×1000 (8 digits). Used with .search() so it also finds the
# OSI embedded in a longer contract description like
# 'QQQ JUL2026 715 P [QQQ 260702P00715000 100]'.
_OSI_RE = re.compile(r"(\d{6})([CP])(\d{8})")


def parse_occ_symbol(symbol: str | None) -> dict:
    """Pull underlying/right/strike/expiry out of an OSI option symbol.

    Returns a dict with keys ``underlying``, ``right``, ``strike``, ``expiry``.
    A missing or non-option symbol yields all-None components, except that the
    leading token is still returned as ``underlying`` (so a bare ``'NVDA'`` stock
    symbol gives underlying='NVDA' with right/strike/expiry=None).
    """
    out: dict = {"underlying": None, "right": None, "strike": None, "expiry": None}
    if not symbol:
        return out
    text = str(symbol).strip()
    tokens = text.split()
    if tokens:
        out["underlying"] = tokens[0]
    m = _OSI_RE.search(text)
    if m:
        yymmdd, right, strike = m.groups()
        try:
            out["expiry"] = datetime.strptime(yymmdd, "%y%m%d").date()
        except ValueError:
            pass
        out["right"] = right
        out["strike"] = int(strike) / 1000.0
    return out
