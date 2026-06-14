"""CP Web API market-data snapshot field codes.

IBKR periodically renumbers these — centralised here so a renumber is a one-file
fix. The Greek codes (7308-7311) are well established. The implied-vol code
varies by build, so we request several IV candidates and the normalizer uses
whichever one the gateway actually populates (raw responses are persisted, so
this is verifiable against live data).
"""
from __future__ import annotations

FIELD_LAST = "31"
FIELD_BID = "84"
FIELD_ASK = "86"
FIELD_MARK = "7635"   # mark/model price used in P&L
FIELD_DELTA = "7308"
FIELD_GAMMA = "7309"
FIELD_THETA = "7310"
FIELD_VEGA = "7311"

# Tried in order; first present wins. Verify against persisted raw snapshots.
IV_FIELD_CANDIDATES = ["7283", "7633", "7607"]

GREEK_FIELD_CODES: list[str] = [
    FIELD_LAST,
    FIELD_BID,
    FIELD_ASK,
    FIELD_MARK,
    FIELD_DELTA,
    FIELD_GAMMA,
    FIELD_THETA,
    FIELD_VEGA,
    *IV_FIELD_CANDIDATES,
]

# Fields whose presence indicates the snapshot has "warmed up" for an option.
GREEK_PRESENCE_FIELDS: list[str] = [FIELD_DELTA, FIELD_GAMMA, FIELD_THETA, FIELD_VEGA]

# Underlying quote fields: last price + an implied-vol index (percent).
FIELD_HIST_VOL = "7087"   # historic volatility %
UNDERLYING_FIELD_CODES: list[str] = [FIELD_LAST, "7283", "7633", FIELD_HIST_VOL]
