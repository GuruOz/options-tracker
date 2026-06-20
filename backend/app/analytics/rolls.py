"""Roll-chain detection from execution history.

Pure functions that take unlinked executions and produce roll-chain groupings.
A roll is: buy-to-close an option + sell-to-open a new option on the same
underlying + right within a short time window. The chain tracks cumulative
credit across the entire lifecycle from initial open -> rolls -> final close.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Sequence

from app.db.models import Execution

ROLL_WINDOW_MINUTES = 5
OPTION_TYPES = {"OPT", "FOP", "WAR"}


def _chain_id() -> str:
    return f"rc_{uuid.uuid4().hex[:12]}"


def _is_option(sec_type: str | None) -> bool:
    return (sec_type or "").upper() in OPTION_TYPES


def _credit(exec: Execution) -> float:
    """Compute the dollar credit/debit of a single execution.

    Sell -> positive credit (premium received).
    Buy  -> negative debit  (cost to close).
    Each option contract has a 100-share multiplier.
    """
    qty = float(exec.qty or 0)
    price = float(exec.price or 0)
    comm = float(exec.commission or 0)
    gross = qty * price * 100.0
    if (exec.side or "").upper() == "S":
        return gross - comm
    else:
        return -(gross + comm)


def build_roll_chains(
    executions: Sequence[Execution],
    account_id: str,
    *,
    existing_open_chains: dict[int, dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build roll chains and legs from a list of unlinked option executions.

    Returns (chains, legs) where each is a list of dicts ready for DB insert.
    Executions should be sorted by exec_time asc and must not already be linked
    to any chain.

    existing_open_chains maps conid -> chain dict for chains that exist in the
    DB from prior runs. A BUY execution that closes an existing position will
    find its chain via its conid.
    """
    opts = [
        e for e in executions
        if _is_option(e.sec_type)
        and e.exec_time is not None
    ]
    opts.sort(key=lambda e: e.exec_time)  # type: ignore[arg-type]

    chains: list[dict] = []
    legs: list[dict] = []

    # conid -> chain dict. Seeded from DB so BUYs on subsequent runs can close
    # existing chains. Each open position's conid maps to its chain.
    open_by_conid: dict[int, dict] = {}
    for conid, c in (existing_open_chains or {}).items():
        open_by_conid[conid] = {**c}

    added_ids: set[str] = set()

    def _add_chain(c: dict) -> None:
        if c["chain_id"] not in added_ids:
            chains.append(c)
            added_ids.add(c["chain_id"])

    i = 0
    n = len(opts)
    while i < n:
        e = opts[i]
        side = (e.side or "").upper()
        conid = e.conid

        if side == "B":
            # Look AHEAD: a SELL within the roll window on the same underlying +
            # right means this buy-to-close is actually a roll, not a final close.
            # We must decide this here, before closing the chain, because the
            # next iteration's SELL would otherwise find the chain already gone.
            nxt = opts[i + 1] if i + 1 < n else None
            is_roll = (
                nxt is not None
                and (nxt.side or "").upper() == "S"
                and nxt.symbol == e.symbol
                and nxt.right == e.right
                and e.exec_time is not None
                and nxt.exec_time is not None
                and (nxt.exec_time - e.exec_time) <= timedelta(minutes=ROLL_WINDOW_MINUTES)  # type: ignore[operator]
            )

            if is_roll:
                # The BUY closes the position at its conid; the SELL re-opens on a
                # new conid. Both legs belong to the SAME chain, which stays open.
                chain = open_by_conid.pop(conid, None) if conid is not None else None
                if chain is None:
                    # Orphan roll: no known open chain to continue — start one.
                    chain = {
                        "chain_id": _chain_id(),
                        "account_id": account_id,
                        "underlying_symbol": e.symbol,
                        "underlying_conid": None,
                        "right": e.right,
                        "status": "open",
                        "opened_at": e.exec_time,
                        "closed_at": None,
                        "cumulative_credit": 0.0,
                        "meta": None,
                    }
                _add_chain(chain)
                # Close leg for the buy-to-close.
                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": e.exec_id,
                    "conid": e.conid,
                    "role": "close",
                })
                chain["cumulative_credit"] = float(chain["cumulative_credit"] or 0) + _credit(e)
                # Open leg for the rolled SELL — same chain, stays open.
                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": nxt.exec_id,
                    "conid": nxt.conid,
                    "role": "open",
                })
                chain["cumulative_credit"] = float(chain["cumulative_credit"] or 0) + _credit(nxt)
                chain["status"] = "open"
                chain["closed_at"] = None
                if nxt.conid is not None:
                    open_by_conid[nxt.conid] = chain
                i += 2  # both legs consumed
                continue

            # Plain buy-to-close: find the chain by conid and close it.
            chain = open_by_conid.pop(conid, None) if conid is not None else None
            if chain is not None:
                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": e.exec_id,
                    "conid": e.conid,
                    "role": "close",
                })
                chain["cumulative_credit"] = float(chain["cumulative_credit"] or 0) + _credit(e)
                chain["status"] = "closed"
                chain["closed_at"] = e.exec_time
                _add_chain(chain)
            else:
                # Orphaned buy — no open chain found by conid.
                chain = {
                    "chain_id": _chain_id(),
                    "account_id": account_id,
                    "underlying_symbol": e.symbol,
                    "underlying_conid": None,
                    "right": e.right,
                    "status": "closed",
                    "opened_at": e.exec_time,
                    "closed_at": e.exec_time,
                    "cumulative_credit": _credit(e),
                    "meta": None,
                }
                chains.append(chain)
                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": e.exec_id,
                    "conid": e.conid,
                    "role": "close",
                })
            i += 1
            continue

        elif side == "S":
            # A SELL reached directly (not consumed by a preceding BUY's roll
            # look-ahead) is a fresh open.
            chain = {
                "chain_id": _chain_id(),
                "account_id": account_id,
                "underlying_symbol": e.symbol,
                "underlying_conid": None,
                "right": e.right,
                "status": "open",
                "opened_at": e.exec_time,
                "closed_at": None,
                "cumulative_credit": 0.0,
                "meta": None,
            }
            _add_chain(chain)
            legs.append({
                "chain_id": chain["chain_id"],
                "exec_id": e.exec_id,
                "conid": e.conid,
                "role": "open",
            })
            chain["cumulative_credit"] = float(chain["cumulative_credit"] or 0) + _credit(e)
            if e.conid is not None:
                open_by_conid[e.conid] = chain
            i += 1
            continue

        else:
            i += 1

    return chains, legs
