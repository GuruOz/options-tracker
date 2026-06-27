"""Cross-source execution de-duplication.

The live CP-API poll and the Flex import (and CSV upload) both record the *same*
fills, but under different exec_ids — and the poll reports an option as just its
root symbol (``NVDA``) with no strike. De-duping on exec_id alone therefore lets
the same fill land twice: it double-counts roll P&L and spawns a phantom
strike-0 chain ("NVDA P").

A fill has a feed-independent identity: the *contract* (``conid`` pins the
underlying, right, strike and expiry), the side, the quantity and the price.
That identity is the same whatever feed reported it, so we keep one row per fill
and let the authoritative (Flex/CSV) copy win over the lossy poll copy.

This is scoped to options: for an option, ``conid`` uniquely pins strike+expiry,
so two fills sharing (conid, side, qty, price) are the same execution. Stock
fills aren't cross-matched here (a bare underlying ``conid`` doesn't pin a unique
trade), so assignment rows are left untouched.

Pure functions only — no DB/session imports — so the matching rules are unit
testable. Inputs may be dicts or ORM objects (see ``_get``).
"""
from __future__ import annotations

# Feeds that carry full contract detail (OCC symbol, strike, expiry). The live
# CP-API poll ("poll") is the lossy feed these supersede.
AUTHORITATIVE_SOURCES = frozenset({"flex", "flex_eae", "flex_import"})
_OPTION_TYPES = frozenset({"OPT", "FOP", "WAR"})


def _get(row, attr):
    """Read ``attr`` from a dict or an ORM object alike."""
    return row.get(attr) if isinstance(row, dict) else getattr(row, attr, None)


def is_authoritative(source: str | None) -> bool:
    return (source or "") in AUTHORITATIVE_SOURCES


def is_option(sec_type: str | None) -> bool:
    return (sec_type or "").upper() in _OPTION_TYPES


def content_key(*, conid, side, qty, price) -> tuple | None:
    """Feed-independent identity of an option fill, or None if not derivable.

    Same contract (conid), side, quantity and price ⇒ same execution, regardless
    of which feed reported it, what exec_id it minted, or whether it spelled the
    symbol out. Returns None when any component is missing — such a fill can't be
    safely cross-matched and is left as-is.
    """
    if conid is None or not side or price is None or qty is None:
        return None
    try:
        return (int(conid), str(side).upper(), round(abs(float(qty)), 4), round(float(price), 4))
    except (TypeError, ValueError):
        return None


def option_content_key(row) -> tuple | None:
    """``content_key`` for an option row/object; None for non-options."""
    if not is_option(_get(row, "sec_type")):
        return None
    return content_key(
        conid=_get(row, "conid"),
        side=_get(row, "side"),
        qty=_get(row, "qty"),
        price=_get(row, "price"),
    )


def is_superseded_poll_row(row, authoritative_keys) -> bool:
    """True if ``row`` is a poll-feed option fill already covered by an
    authoritative fill (so the poll copy should be skipped/dropped)."""
    if is_authoritative(_get(row, "source")):
        return False
    key = option_content_key(row)
    return key is not None and key in authoritative_keys


def superseded_poll_exec_ids(execs) -> list[str]:
    """exec_ids of poll-feed option rows that have an authoritative twin in the
    same set — i.e. the duplicates safe to delete (the authoritative copy stays).
    """
    authoritative_keys: set[tuple] = set()
    for e in execs:
        if is_authoritative(_get(e, "source")):
            key = option_content_key(e)
            if key is not None:
                authoritative_keys.add(key)

    return [
        _get(e, "exec_id")
        for e in execs
        if is_superseded_poll_row(e, authoritative_keys)
    ]
