"""Roll-chain detection from execution history.

Pure functions that take executions and produce roll-chain groupings. A chain is
the lifecycle of a continuously-short option position on one
(underlying ticker, right, strike), tracked across rolls, expirations and
assignments. Cumulative credit accrues over the whole lifecycle. A chain that
goes flat is re-opened by the next same-key sell within CHAIN_CONTINUATION_DAYS.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Sequence

from app.db.models import Execution

OPTION_TYPES = {"OPT", "FOP", "WAR"}
CHAIN_CONTINUATION_DAYS = 60


def _chain_id(exec_id: str | None) -> str:
    """Deterministic chain id from the opening exec, so rebuilds are stable."""
    if not exec_id:
        return f"rc_{uuid.uuid4().hex[:12]}"
    h = hashlib.sha256(exec_id.encode()).hexdigest()[:12]
    return f"rc_{h}"


def _is_option(sec_type: str | None) -> bool:
    return (sec_type or "").upper() in OPTION_TYPES


def _underlying_ticker(symbol: str | None) -> str | None:
    """Strip an option/OCC symbol down to its underlying ticker.

    'NVDA 260618P00216000' -> 'NVDA'; 'NVDA' -> 'NVDA'. The execution `symbol`
    holds the full OCC string (which encodes the expiry), so chains MUST be keyed
    by the ticker — otherwise rolling the same strike to a new expiry would land
    in a different chain.
    """
    if not symbol:
        return None
    parts = symbol.strip().split()
    return parts[0] if parts else None


def _credit(exec_obj: Execution) -> float:
    """Dollar credit (+) / debit (−) of a single execution, net of commission.

    `qty` is unsigned by convention (direction comes from `side`); abs() guards
    against any feed that slips through signed. `commission` is always a cost, so
    we subtract its magnitude regardless of the feed's sign — IBKR reports
    `ibCommission`/`Comm/Fee` as NEGATIVE, so a naive `- comm` would *add* it.
    """
    qty = abs(float(exec_obj.qty or 0))
    price = float(exec_obj.price or 0)
    comm = abs(float(exec_obj.commission or 0))
    mult = 100.0 if _is_option(exec_obj.sec_type) else 1.0
    gross = qty * price * mult
    if (exec_obj.side or "").upper() == "S":
        return gross - comm
    else:
        return -(gross + comm)


def build_roll_chains(
    executions: Sequence[Execution],
    account_id: str,
    *,
    adjustments: list | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build roll chains and legs from a list of all executions.

    Groups executions chronologically by (underlying ticker, right, strike) and
    handles expirations and assignments. Returns (chains, legs) dicts ready for
    DB insert. `adjustments` are user overrides applied last (see
    `_apply_adjustments`).
    """
    exs = [e for e in executions if e.exec_time is not None]
    exs.sort(key=lambda e: e.exec_time)

    chains: list[dict] = []
    legs: list[dict] = []

    # (ticker, right, strike) -> chain dict
    active_chains: dict[tuple[str, str, float], dict] = {}

    for e in exs:
        sec_type = (e.sec_type or "").upper()
        symbol = e.symbol or ""
        side = (e.side or "").upper()

        if _is_option(sec_type):
            right = e.right or ""
            strike = float(e.strike) if e.strike else 0.0
            underlying = _underlying_ticker(symbol) or symbol
            key = (underlying, right, strike)
            chain = active_chains.get(key)

            # Synthetic expiry: an open short whose expiry has already passed by
            # the time the next trade on this (ticker, right, strike) arrives.
            if chain and chain["_opt_pos"] < -1e-6 and chain["_current_expiry"]:
                if e.exec_time.date() > chain["_current_expiry"]:
                    exp_dt = datetime.combine(
                        chain["_current_expiry"], datetime.min.time(),
                        tzinfo=e.exec_time.tzinfo,
                    )
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": None,
                        "conid": chain["_last_conid"],
                        "role": "expired",
                        "created_at": exp_dt,
                    })
                    chain["_opt_pos"] = 0
                    if chain["_stk_pos"] == 0:
                        chain["status"] = "closed"
                        chain["closed_at"] = exp_dt
                        chain["close_reason"] = "expired"

            if side == "S":
                # Sell to open / continue. A closed chain re-opens only if the
                # new sell lands within the continuation window.
                if chain is not None and chain["status"] == "closed":
                    days_diff = (e.exec_time - chain["closed_at"]).days
                    if days_diff <= CHAIN_CONTINUATION_DAYS:
                        chain["status"] = "open"
                        chain["closed_at"] = None
                        chain["close_reason"] = None
                    else:
                        chain = None

                if chain is None:
                    chain = {
                        "chain_id": _chain_id(e.exec_id),
                        "account_id": account_id,
                        "underlying_symbol": underlying,
                        "underlying_conid": None,
                        "right": right,
                        "strike": strike,
                        "status": "open",
                        "close_reason": None,
                        "opened_at": e.exec_time,
                        "closed_at": None,
                        "cumulative_credit": 0.0,
                        "meta": None,
                        "_opt_pos": 0,
                        "_stk_pos": 0,
                        "_current_expiry": e.expiry,
                        "_last_conid": e.conid,
                    }
                    chains.append(chain)
                    active_chains[key] = chain
                else:
                    chain["_current_expiry"] = e.expiry
                    chain["_last_conid"] = e.conid

                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": e.exec_id,
                    "conid": e.conid,
                    "role": "open",
                    "created_at": e.exec_time,
                })
                chain["cumulative_credit"] += _credit(e)
                chain["_opt_pos"] -= float(e.qty or 0)

            elif side == "B":
                # A buy from the flex OptionEAE feed is a worthless expiry, not a
                # discretionary buy-to-close — label it accordingly.
                is_expiry = (e.source or "") == "flex_eae"
                role = "expired" if is_expiry else "close"
                reason = "expired" if is_expiry else "bought_back"

                if chain is not None:
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": role,
                        "created_at": e.exec_time,
                    })
                    chain["cumulative_credit"] += _credit(e)
                    chain["_opt_pos"] += float(e.qty or 0)

                    if chain["_opt_pos"] >= -1e-6 and chain["_stk_pos"] == 0:
                        chain["status"] = "closed"
                        chain["closed_at"] = e.exec_time
                        chain["close_reason"] = reason
                else:
                    # Orphan buy — no open chain to close.
                    chain = {
                        "chain_id": _chain_id(e.exec_id),
                        "account_id": account_id,
                        "underlying_symbol": underlying,
                        "underlying_conid": None,
                        "right": right,
                        "strike": strike,
                        "status": "closed",
                        "close_reason": reason,
                        "opened_at": e.exec_time,
                        "closed_at": e.exec_time,
                        "cumulative_credit": _credit(e),
                        "meta": None,
                        "_opt_pos": float(e.qty or 0),
                        "_stk_pos": 0,
                        "_current_expiry": e.expiry,
                        "_last_conid": e.conid,
                    }
                    chains.append(chain)
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": role,
                        "created_at": e.exec_time,
                    })

        elif sec_type == "STK":
            is_assignment = bool(e.raw) and (
                e.raw.get("notes") == "A" or e.raw.get("code") == "A"
            )
            qty = float(e.qty or 0)
            price = float(e.price or 0)
            underlying = _underlying_ticker(symbol) or symbol

            if is_assignment:
                # Short put assigned -> you BUY stock; short call -> you SELL.
                right = "P" if side == "B" else "C"
                key = (underlying, right, price)
                chain = active_chains.get(key)
                if chain and chain["_opt_pos"] < -1e-6:
                    # Close the option leg…
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": None,
                        "conid": chain["_last_conid"],
                        "role": "assignment",
                        "created_at": e.exec_time,
                    })
                    chain["_opt_pos"] = 0
                    # …and record the resulting stock leg.
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": "assignment_stock",
                        "created_at": e.exec_time,
                    })
                    chain["cumulative_credit"] += _credit(e)
                    chain["_stk_pos"] += qty if side == "B" else -qty
            else:
                stk_qty_signed = qty if side == "B" else -qty
                for chain in active_chains.values():
                    if chain["underlying_symbol"] == underlying and chain["_stk_pos"] != 0:
                        if (chain["_stk_pos"] > 0 and side == "S") or (chain["_stk_pos"] < 0 and side == "B"):
                            legs.append({
                                "chain_id": chain["chain_id"],
                                "exec_id": e.exec_id,
                                "conid": e.conid,
                                "role": "stock_close",
                                "created_at": e.exec_time,
                            })
                            chain["cumulative_credit"] += _credit(e)
                            chain["_stk_pos"] += stk_qty_signed

                            if abs(chain["_stk_pos"]) < 1e-6 and chain["_opt_pos"] >= -1e-6:
                                chain["status"] = "closed"
                                chain["closed_at"] = e.exec_time
                                chain["close_reason"] = "assigned_closed"
                            break

    # End-of-data expiry pass: close anything still short past its expiry.
    now_date = datetime.now().date()
    for chain in active_chains.values():
        if chain["status"] == "open" and chain["_opt_pos"] < -1e-6 and chain["_current_expiry"]:
            if chain["_current_expiry"] < now_date:
                exp_dt = datetime.combine(
                    chain["_current_expiry"], datetime.min.time(),
                    tzinfo=chain["opened_at"].tzinfo,
                )
                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": None,
                    "conid": chain["_last_conid"],
                    "role": "expired",
                    "created_at": exp_dt,
                })
                chain["_opt_pos"] = 0
                if chain["_stk_pos"] == 0:
                    chain["status"] = "closed"
                    chain["closed_at"] = exp_dt
                    chain["close_reason"] = "expired"

    # Drop internal bookkeeping; normalize floats.
    for c in chains:
        c.pop("_opt_pos", None)
        c.pop("_stk_pos", None)
        c.pop("_current_expiry", None)
        c.pop("_last_conid", None)
        c["cumulative_credit"] = float(c["cumulative_credit"])

    if adjustments:
        _apply_adjustments(chains, legs, adjustments)

    return chains, legs


def _last_leg_dt(legs: list[dict], chain_id: str):
    times = [l["created_at"] for l in legs if l["chain_id"] == chain_id and l.get("created_at")]
    return max(times) if times else None


def _apply_adjustments(chains: list[dict], legs: list[dict], adjustments: list) -> None:
    """Overlay user overrides on the auto-built chains (re-applied every rebuild).

    - manual_close: force a chain closed (e.g. an early close the feed can't show).
    - manual_link:  merge the chain that owns `exec_id` into the target chain
      (the rare cross-strike roll).
    """
    by_id = {c["chain_id"]: c for c in chains}
    for adj in adjustments:
        atype = (getattr(adj, "adjustment_type", None) or "").lower()
        target = by_id.get(getattr(adj, "chain_id", None))
        if target is None:
            continue

        if atype == "manual_close":
            if target["status"] != "closed":
                target["status"] = "closed"
                target["close_reason"] = getattr(adj, "close_reason", None) or "manual_close"
                target["closed_at"] = getattr(adj, "close_date", None) or _last_leg_dt(legs, target["chain_id"])

        elif atype == "manual_link":
            exec_id = getattr(adj, "exec_id", None)
            if not exec_id:
                continue
            src_id = next((l["chain_id"] for l in legs if l.get("exec_id") == exec_id), None)
            if not src_id or src_id == target["chain_id"]:
                continue
            src = by_id.get(src_id)
            if src is None:
                continue
            for l in legs:
                if l["chain_id"] == src_id:
                    l["chain_id"] = target["chain_id"]
            target["cumulative_credit"] = float(target["cumulative_credit"]) + float(src["cumulative_credit"])
            if src["status"] == "open":
                target["status"] = "open"
                target["closed_at"] = None
                target["close_reason"] = None
            elif src["closed_at"] and (target["closed_at"] is None or src["closed_at"] > target["closed_at"]):
                target["closed_at"] = src["closed_at"]
                target["close_reason"] = src["close_reason"]
            chains[:] = [c for c in chains if c is not src]
            del by_id[src_id]
