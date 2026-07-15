"""Roll-chain detection from execution history.

Pure functions that take executions and produce roll-chain groupings. A chain is
the lifecycle of a continuously-short option position on one
(underlying ticker, right, strike), tracked across rolls, expirations and
assignments. Cumulative credit accrues over the whole lifecycle. A chain that
goes flat is re-opened by the next same-key sell within CHAIN_CONTINUATION_DAYS.

Beyond the running credit, each chain carries the economics of its current
*cycle* — the stretch from a sale to the moment that short is finally gone. A
roll doesn't bank the new leg's credit; it swaps one open leg for another and
banks only the decay on the leg it replaced, leaving the cycle's premium target
unchanged. So a chain tracks `open_credit` (locked in the leg open right now),
`initial_credit` (the sale the cycle is working toward) and `cycle_base_credit`
(where cumulative credit stood when the cycle began). Everything the cockpit
reports about an open chain — what's banked, what closing now would net, how
much of the target is captured — is derived from those three.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Sequence

from app.core.occ import parse_occ_symbol
from app.db.models import Execution

OPTION_TYPES = {"OPT", "FOP", "WAR"}
CHAIN_CONTINUATION_DAYS = 60
# A roll's buy-to-close and the new sell-to-open land in the same session, so a
# same-day flat-then-sell on a *different* strike of the same (underlying, right)
# is treated as one rolled chain rather than a close + a brand-new chain.
ROLL_WINDOW_DAYS = 1


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


def _is_assignment(exec_obj: Execution) -> bool:
    """True if an execution is an assignment.

    The live CP-API poll reports assignments with a dedicated ``side == "A"``
    (it does not carry the Flex ``notes``/``code`` markers), while the Flex/CSV
    feeds tag the row with ``notes == "A"`` or ``code == "A"``. Recognise both.
    """
    if (exec_obj.side or "").upper() == "A":
        return True
    raw = exec_obj.raw
    return bool(raw) and (raw.get("notes") == "A" or raw.get("code") == "A")


def _find_open_chain_by_conid(active_chains: dict, conid: int | None) -> dict | None:
    """Re-attach an assignment row to its chain by contract id.

    The poll's assignment row often arrives with a null strike, so the
    ``(ticker, right, strike)`` key won't match. The ``conid`` still pins the
    short option, so match the open chain whose last leg shares it.
    """
    if conid is None:
        return None
    for ch in active_chains.values():
        if ch["_last_conid"] == conid and ch["_opt_pos"] < -1e-6:
            return ch
    return None


def _find_open_chain_by_underlying_right(
    active_chains: dict, underlying: str | None, right: str | None
) -> dict | None:
    """Last-resort match for an assignment: an open short chain on the same
    underlying and right (used when both strike and conid are unusable)."""
    if not underlying:
        return None
    for ch in active_chains.values():
        if (
            ch["underlying_symbol"] == underlying
            and ch["_opt_pos"] < -1e-6
            and (right is None or ch["right"] == right)
        ):
            return ch
    return None


def _find_roll_candidate(
    active_chains: dict, underlying: str, right: str, new_strike: float, when
) -> dict | None:
    """The closing leg of a cross-strike roll.

    A chain on the same (underlying, right) that just went flat via a buy-to-close
    on the *same day* at a different strike — i.e. the new sell-to-open is the
    far side of a roll, not a fresh chain. Picks the most recently closed match.
    """
    best = None
    for ch in active_chains.values():
        if (
            ch["underlying_symbol"] == underlying
            and ch["right"] == right
            and ch["strike"] != new_strike
            and abs(ch["_opt_pos"]) < 1e-6
            and ch["_stk_pos"] == 0
            and ch["status"] == "closed"
            and ch["close_reason"] in (None, "bought_back")
            and ch["closed_at"] is not None
            and ch["closed_at"].date() == when.date()
        ):
            if best is None or ch["closed_at"] > best["closed_at"]:
                best = ch
    return best


def _is_roll(chain: dict, when) -> bool:
    """True if a sell is the far side of a roll rather than a standalone trade.

    A roll's buy-to-close and sell-to-open land together, so a short bought back
    a moment ago is being *extended*. One bought back and then left alone for
    days is simply finished, and so is one that expired or was assigned.
    """
    if chain["_flat_reason"] != "bought_back" or chain["_flat_at"] is None:
        return False
    return (when - chain["_flat_at"]).days <= ROLL_WINDOW_DAYS


def _short_reduced(chain: dict, pos_before: float, when, reason: str) -> None:
    """Sync cycle bookkeeping after a buy/expiry/assignment shrinks the short.

    `open_credit` is the credit riding on the leg that's still open, so it scales
    down with the position and reaches zero once the short is gone. `when`/
    `reason` record how the short last went flat — that's what tells the next
    sell whether it's rolling this cycle onward or starting a fresh one.
    """
    after = chain["_opt_pos"]
    if after >= -1e-6:
        chain["open_credit"] = 0.0
        chain["_flat_at"] = when
        chain["_flat_reason"] = reason
    elif pos_before < -1e-6:
        chain["open_credit"] *= abs(after) / abs(pos_before)


def _relabel_last_close_as_roll(legs: list[dict], chain_id: str) -> None:
    """Relabel a chain's most recent 'close' leg as 'roll' — the buy side of a
    cross-strike roll that we've now recognised as a continuation."""
    for leg in reversed(legs):
        if leg["chain_id"] == chain_id and leg["role"] == "close":
            leg["role"] = "roll"
            return


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
    # Options before stock (so an assignment closes the option before its shares
    # land), and on a tied timestamp buys before sells — flex date-only rows for a
    # roll collide at midnight, and the buy-to-close must be seen before the new
    # sell for the roll to be recognised as a continuation.
    exs.sort(
        key=lambda e: (
            e.exec_time,
            0 if _is_option(e.sec_type) else 1,
            0 if (e.side or "").upper() == "B" else 1,
        )
    )

    chains: list[dict] = []
    legs: list[dict] = []

    # (ticker, right, strike) -> chain dict
    active_chains: dict[tuple[str, str, float], dict] = {}

    # Underlyings that have a real STK assignment execution. When present, the
    # STK branch books the delivered shares, so the option-assignment branch must
    # NOT also synthesize a stock leg (that would double-count the shares).
    stk_assignment_underlyings = {
        _underlying_ticker(x.symbol) or (x.symbol or "")
        for x in exs
        if (x.sec_type or "").upper() == "STK" and _is_assignment(x)
    }

    for e in exs:
        sec_type = (e.sec_type or "").upper()
        symbol = e.symbol or ""
        side = (e.side or "").upper()

        if _is_option(sec_type):
            # Feeds sometimes leave strike/right empty; the OSI symbol still
            # encodes them. Without this, distinct strikes with a null strike all
            # key to 0.0 and collapse into one bogus chain.
            occ = parse_occ_symbol(symbol)
            right = e.right or occ["right"] or ""
            strike = float(e.strike) if e.strike else (occ["strike"] or 0.0)
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
                    pos_before = chain["_opt_pos"]
                    chain["_opt_pos"] = 0
                    _short_reduced(chain, pos_before, exp_dt, "expired")
                    if chain["_stk_pos"] == 0:
                        chain["status"] = "closed"
                        chain["closed_at"] = exp_dt
                        chain["close_reason"] = "expired"

            # An OptionEAE Expiration only ever CLOSES the open leg. IBKR's EAE
            # `quantity` sign is unreliable (+1 for puts, −1 for calls), so the
            # normalized `side` can't be trusted — never let it open a position.
            # If the contract is already flat it's a duplicate of an
            # already-booked close: no-op.
            if (e.source or "") == "flex_eae":
                if chain is not None and abs(chain["_opt_pos"]) > 1e-6:
                    qd = abs(float(e.qty or 0))
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": "expired",
                        "created_at": e.exec_time,
                    })
                    pos_before = chain["_opt_pos"]
                    chain["_opt_pos"] += qd if chain["_opt_pos"] < 0 else -qd
                    chain["cumulative_credit"] += _credit(e)
                    _short_reduced(chain, pos_before, e.exec_time, "expired")
                    if abs(chain["_opt_pos"]) < 1e-6 and chain["_stk_pos"] == 0:
                        chain["status"] = "closed"
                        chain["closed_at"] = e.exec_time
                        chain["close_reason"] = "expired"
                continue

            if side == "S":
                # Sell to open / continue. A closed chain re-opens only if the
                # new sell lands within the continuation window.
                sto_role = "open"
                # Had this chain fully settled — no short, no assigned shares —
                # before this sell? Read it now: the re-open below rewrites
                # `status`. A sell into a settled chain is a new trade with its
                # own premium target; a sell into a chain that's still live
                # carries the existing one on.
                was_settled = chain is None or chain["status"] == "closed"
                if chain is not None and chain["status"] == "closed":
                    days_diff = (e.exec_time - chain["closed_at"]).days
                    if days_diff <= CHAIN_CONTINUATION_DAYS:
                        chain["status"] = "open"
                        chain["closed_at"] = None
                        chain["close_reason"] = None
                    else:
                        chain = None

                # Cross-strike roll: a same-day buy-to-close on another strike of
                # this (underlying, right) followed by this sell is one rolled
                # chain (matching how the tracker sheet models rolls), not a fresh
                # chain. Revive the candidate and move it to the new strike key.
                if chain is None:
                    cand = _find_roll_candidate(
                        active_chains, underlying, right, strike, e.exec_time
                    )
                    if cand is not None:
                        _relabel_last_close_as_roll(legs, cand["chain_id"])
                        old_key = (cand["underlying_symbol"], cand["right"], cand["strike"])
                        active_chains.pop(old_key, None)
                        cand["status"] = "open"
                        cand["closed_at"] = None
                        cand["close_reason"] = None
                        cand["strike"] = strike
                        cand["right"] = right
                        cand["_current_expiry"] = e.expiry
                        cand["_last_conid"] = e.conid
                        active_chains[key] = cand
                        chain = cand
                        sto_role = "roll"

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
                        "open_credit": 0.0,
                        "initial_credit": None,
                        "cycle_base_credit": 0.0,
                        "meta": None,
                        "_opt_pos": 0,
                        "_stk_pos": 0,
                        "_current_expiry": e.expiry,
                        "_last_conid": e.conid,
                        "_flat_at": None,
                        "_flat_reason": None,
                    }
                    chains.append(chain)
                    active_chains[key] = chain
                else:
                    chain["_current_expiry"] = e.expiry
                    chain["_last_conid"] = e.conid

                # Does this sell carry the current cycle on, or start a new one?
                credit = _credit(e)
                if chain["_opt_pos"] < -1e-6:
                    # Selling on top of an existing short scales this cycle up
                    # rather than starting another one.
                    chain["open_credit"] += credit
                    chain["initial_credit"] = (chain["initial_credit"] or 0.0) + credit
                else:
                    rolling = _is_roll(chain, e.exec_time)
                    if rolling and sto_role == "open":
                        # Same-key roll (the cross-strike path labels its own pair).
                        sto_role = "roll"
                        _relabel_last_close_as_roll(legs, chain["chain_id"])

                    # The cycle survives a roll, and survives a chain that never
                    # settled — selling a fresh put against shares you were
                    # assigned is the same trade grinding on, not a new one. Only
                    # a sale into a settled chain starts a cycle of its own, and
                    # a settled chain has no stock left to book, so the credit it
                    # has banked is final and safe to measure the new cycle from.
                    if not chain["initial_credit"] or (was_settled and not rolling):
                        chain["initial_credit"] = credit
                        chain["cycle_base_credit"] = chain["cumulative_credit"]
                    chain["open_credit"] = credit

                legs.append({
                    "chain_id": chain["chain_id"],
                    "exec_id": e.exec_id,
                    "conid": e.conid,
                    "role": sto_role,
                    "created_at": e.exec_time,
                })
                chain["cumulative_credit"] += credit
                chain["_opt_pos"] -= abs(float(e.qty or 0))

            elif side in ("B", "A"):
                # flex_eae expirations are intercepted above, so a buy here is
                # either an assignment or a discretionary buy-to-close.
                is_assignment = _is_assignment(e)
                zero_price = float(e.price or 0) == 0.0

                # A $0 buy with no open short to close is a duplicate expiry
                # record (IBKR sometimes reports an expiry as both a regular $0
                # buy and an OptionEAE row). Skip it so it can't reopen a chain or
                # spawn a phantom — regardless of intra-day ordering.
                if not is_assignment and zero_price and (
                    chain is None or chain["_opt_pos"] >= -1e-6
                ):
                    continue

                if is_assignment:
                    role = "assignment"
                    reason = "assigned"
                else:
                    role = "close"
                    # A $0 buy-to-close is economically an expiry.
                    reason = "expired" if zero_price else "bought_back"

                # The poll's assignment row carries a null strike, so the key
                # match above fails. Recover the chain by conid (then by
                # underlying+right) before treating it as an orphan.
                if chain is None and is_assignment:
                    chain = _find_open_chain_by_conid(active_chains, e.conid) \
                        or _find_open_chain_by_underlying_right(active_chains, underlying, right)

                if chain is not None:
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": role,
                        "created_at": e.exec_time,
                    })
                    chain["cumulative_credit"] += _credit(e)
                    pos_before = chain["_opt_pos"]
                    chain["_opt_pos"] += abs(float(e.qty or 0))
                    _short_reduced(chain, pos_before, e.exec_time, reason)

                    if is_assignment:
                        # A put assigned delivers shares; a call assigned has them
                        # called away. The poll reports only this option row, so
                        # synthesize the resulting stock leg — unless a real STK
                        # assignment execution will book it (Flex), which would
                        # otherwise double-count the shares.
                        ch_right = chain["right"] or right
                        if underlying not in stk_assignment_underlyings:
                            contracts = abs(float(e.qty or 0))
                            shares = contracts * 100.0
                            ch_strike = chain["strike"] or (strike or 0.0)
                            buy = ch_right == "P"
                            legs.append({
                                "chain_id": chain["chain_id"],
                                "exec_id": None,
                                "conid": chain["_last_conid"],
                                "role": "assignment_stock",
                                "created_at": e.exec_time,
                            })
                            # Buying shares is a debit, having them called away a
                            # credit. Commission rides on the option row's price=0.
                            stock_value = shares * float(ch_strike)
                            chain["cumulative_credit"] += -stock_value if buy else stock_value
                            chain["_stk_pos"] += shares if buy else -shares
                        chain["status"] = "open"
                        chain["closed_at"] = None
                        chain["close_reason"] = None
                    elif chain["_opt_pos"] >= -1e-6 and chain["_stk_pos"] == 0:
                        chain["status"] = "closed"
                        chain["closed_at"] = e.exec_time
                        chain["close_reason"] = reason
                elif is_assignment:
                    # An assignment with no open short to close is a duplicate of
                    # one already booked from another feed (the live poll reports
                    # the same assignment as `side A` that Flex reports as `side B`
                    # + `notes A`, and the two can't be cross-deduped). Skip it —
                    # turning it into an orphan would mint a phantom strike-0 chain.
                    continue
                else:
                    # Orphan buy — no open chain to close. It never sold anything,
                    # so there's no cycle here for a later sell to continue.
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
                        "open_credit": 0.0,
                        "initial_credit": None,
                        "cycle_base_credit": 0.0,
                        "meta": None,
                        "_opt_pos": abs(float(e.qty or 0)),
                        "_stk_pos": 0,
                        "_current_expiry": e.expiry,
                        "_last_conid": e.conid,
                        "_flat_at": None,
                        "_flat_reason": None,
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
            is_assignment = _is_assignment(e)
            qty = abs(float(e.qty or 0))
            price = float(e.price or 0)
            underlying = _underlying_ticker(symbol) or symbol

            if is_assignment:
                # Short put assigned -> you BUY stock; short call -> you SELL.
                # The poll's bare "A" side doesn't say which, so infer the right
                # from the open short option chain on this underlying.
                if side == "B":
                    right = "P"
                elif side == "S":
                    right = "C"
                else:
                    inferred = _find_open_chain_by_underlying_right(active_chains, underlying, None)
                    right = (inferred["right"] if inferred else None) or "P"
                buy = right == "P"
                key = (underlying, right, price)
                chain = active_chains.get(key) or _find_open_chain_by_underlying_right(
                    active_chains, underlying, right
                )
                if chain:
                    if chain["_opt_pos"] < -1e-6:
                        # Close the option leg…
                        legs.append({
                            "chain_id": chain["chain_id"],
                            "exec_id": None,
                            "conid": chain["_last_conid"],
                            "role": "assignment",
                            "created_at": e.exec_time,
                        })
                        pos_before = chain["_opt_pos"]
                        chain["_opt_pos"] = 0
                        _short_reduced(chain, pos_before, e.exec_time, "assigned")
                    # …and record the resulting stock leg.
                    legs.append({
                        "chain_id": chain["chain_id"],
                        "exec_id": e.exec_id,
                        "conid": e.conid,
                        "role": "assignment_stock",
                        "created_at": e.exec_time,
                    })
                    chain["cumulative_credit"] += _credit(e)
                    chain["_stk_pos"] += qty if buy else -qty
                    chain["status"] = "open"
                    chain["closed_at"] = None
                    chain["close_reason"] = None
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
                pos_before = chain["_opt_pos"]
                chain["_opt_pos"] = 0
                _short_reduced(chain, pos_before, exp_dt, "expired")
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
        c.pop("_flat_at", None)
        c.pop("_flat_reason", None)
        c["cumulative_credit"] = float(c["cumulative_credit"])
        c["open_credit"] = float(c["open_credit"])
        c["cycle_base_credit"] = float(c["cycle_base_credit"])
        if c["initial_credit"] is not None:
            c["initial_credit"] = float(c["initial_credit"])

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
                # The trade is over, so nothing is riding on an open leg any more.
                target["open_credit"] = 0.0

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
            # A manual link says "these are one rolled trade": the locked credit
            # of whichever side is still open carries over, while the premium
            # target stays the one the earlier chain set — that's the sale the
            # whole roll is working toward.
            target["open_credit"] = float(target["open_credit"]) + float(src["open_credit"])
            if not target["initial_credit"]:
                target["initial_credit"] = src["initial_credit"]
                target["cycle_base_credit"] = src["cycle_base_credit"]
            if src["status"] == "open":
                target["status"] = "open"
                target["closed_at"] = None
                target["close_reason"] = None
            elif src["closed_at"] and (target["closed_at"] is None or src["closed_at"] > target["closed_at"]):
                target["closed_at"] = src["closed_at"]
                target["close_reason"] = src["close_reason"]
            chains[:] = [c for c in chains if c is not src]
            del by_id[src_id]
