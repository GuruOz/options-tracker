"""Premium-income endpoint + the manual withdrawal/cashed-out overlay.

GET  /api/income                 — monthly -> YTD income summary (derived).
PUT  /api/income/adjustments     — upsert a month's cashed-out / withdrawal note.

In the combined view the derived numbers sum across accounts, but the manual
overlay does not: a "cashed out" flag or a withdrawal belongs to one account, so
`by_account` carries each user's own summary and writes must name an account.
"""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.income import compute_income
from app.api.deps import account_scope, single_account
from app.core import fx
from app.db import repo
from app.db.base import get_session
from app.db.models import IncomeAdjustment

router = APIRouter(tags=["income"])


async def _income_for(db: AsyncSession, account_id: str) -> dict:
    chains = await repo.all_roll_chains(db, account_id)
    adjustments = await repo.income_adjustments(db, account_id)
    account = await repo.latest_account(db, account_id)
    net_liq = (
        float(account.net_liquidation)
        if account and account.net_liquidation is not None
        else None
    )
    acct_row = await repo.account_by_id(db, account_id)
    base = acct_row.base_currency if acct_row else None
    mismatch = False
    if base:
        mismatch = await repo.account_has_foreign_currency_trades(db, account_id, base)

    # Premium (chain P&L) currency: the account's base unless its trades are in
    # one single foreign currency — then a live rate lets yield_pct be computed
    # instead of suppressed. Trades spanning several foreign currencies leave
    # no single premium currency, which also blocks the combined conversion.
    premium_ccy = base
    fx_rate = None
    fx_used: list[dict] = []
    ambiguous = False
    if mismatch and base:
        foreign = await repo.account_trade_currencies(db, account_id) - {base}
        if len(foreign) == 1:
            premium_ccy = next(iter(foreign))
            rate = await fx.get_rate(premium_ccy, base)
            if rate is not None:
                fx_rate = rate.rate
                fx_used = [rate.as_dict()]
        else:
            premium_ccy = None
            ambiguous = True

    summary = compute_income(
        chains, adjustments,
        net_liquidation=net_liq, currency_mismatch=mismatch, fx_rate=fx_rate,
    )
    summary["base_currency"] = base
    summary["premium_currency"] = premium_ccy
    summary["premium_ambiguous"] = ambiguous
    summary["fx_rates"] = fx_used
    return summary


def _combine(
    per_account: list[dict],
    display_currency: str | None = None,
    rates: dict[str, float] | None = None,
    fx_used: list[dict] | None = None,
) -> dict:
    """Sum every account's monthly/annual P&L into one household summary.

    When `rates` (source currency -> `display_currency`) covers every account's
    premium and base currency, figures are converted before summing (premium
    figures — chain P&L — with the premium rate; net liq and withdrawals with
    the base rate, withdrawals being assumed to be in the account's base
    currency). Historical months convert at the live spot rate — an accepted
    simplification. Missing rates degrade to raw sums with yield_pct
    suppressed whenever currencies mix.

    The manual overlay (cashed_out / withdrawal / note) is deliberately dropped
    from the combined months — one account's withdrawal says nothing about the
    other's. The per-account summaries keep theirs.
    """
    rates = rates or {}

    base_ccys = {s.get("base_currency") for s in per_account if s.get("base_currency")}
    premium_ccys = {
        s.get("premium_currency") for s in per_account if s.get("premium_currency")
    }
    needed = base_ccys | premium_ccys
    convertible = (
        bool(display_currency)
        and not any(s.get("premium_ambiguous") for s in per_account)
        and needed <= rates.keys()
    )

    def factor(s: dict, ccy_key: str) -> float:
        # No recorded currency counts as already-in-display — unknown isn't
        # evidence of a mismatch.
        ccy = s.get(ccy_key)
        if not convertible or ccy is None:
            return 1.0
        return rates[ccy]

    monthly_pnl: dict[str, float] = defaultdict(float)
    monthly_count: dict[str, int] = defaultdict(int)
    for summary in per_account:
        f = factor(summary, "premium_currency")
        for m in summary["months"]:
            monthly_pnl[m["month"]] += m["pnl"] * f
            monthly_count[m["month"]] += m["chain_count"]

    months = [
        {
            "month": mk,
            "pnl": round(monthly_pnl[mk], 2),
            "chain_count": monthly_count[mk],
            "cashed_out": False,
            "withdrawal": None,
            "note": None,
        }
        for mk in sorted(monthly_pnl)
    ]

    year_pnl: dict[int, float] = defaultdict(float)
    year_withdrawn: dict[int, float] = defaultdict(float)
    for summary in per_account:
        pf = factor(summary, "premium_currency")
        bf = factor(summary, "base_currency")
        for y in summary["years"]:
            year_pnl[y["year"]] += y["ytd"] * pf
            year_withdrawn[y["year"]] += y["withdrawn"] * bf
    years = [
        {
            "year": y,
            "ytd": round(year_pnl[y], 2),
            "withdrawn": round(year_withdrawn[y], 2),
            "remaining": round(year_pnl[y] - year_withdrawn[y], 2),
        }
        for y in sorted(year_pnl)
    ]

    all_time = round(
        sum(s["all_time"] * factor(s, "premium_currency") for s in per_account), 2
    )
    closed = sum(s["closed_count"] for s in per_account)
    # Win rate is a ratio, so it has to be rebuilt from the underlying counts
    # rather than averaged across accounts of different sizes.
    wins = sum(
        (s["win_rate"] or 0.0) * s["closed_count"]
        for s in per_account if s["win_rate"] is not None
    )
    net_liqs = [
        s["net_liquidation"] * factor(s, "base_currency")
        for s in per_account if s["net_liquidation"] is not None
    ]
    net_liq = sum(net_liqs) if net_liqs else None

    # A mismatch in any one account's own trades taints the combined yield, and
    # so do two accounts merely disagreeing on base or premium currency — the
    # sums above would mix units unless everything was converted.
    currency_mismatch = (
        any(s.get("currency_mismatch") for s in per_account)
        or len(base_ccys) > 1
        or len(premium_ccys) > 1
    )

    return {
        "months": months,
        "years": years,
        "all_time": all_time,
        "realized": round(
            sum(s["realized"] * factor(s, "premium_currency") for s in per_account), 2
        ),
        "unrealized": round(
            sum(s["unrealized"] * factor(s, "premium_currency") for s in per_account), 2
        ),
        "win_rate": (wins / closed) if closed else None,
        "closed_count": closed,
        "open_count": sum(s["open_count"] for s in per_account),
        "net_liquidation": round(net_liq, 2) if net_liq is not None else None,
        "yield_pct": (
            (all_time / net_liq)
            if net_liq and (convertible or not currency_mismatch)
            else None
        ),
        "currency_mismatch": currency_mismatch,
        "display_currency": display_currency if convertible else None,
        "fx_rates": (fx_used or []) if convertible else [],
    }


@router.get("/income")
async def get_income(
    currency: str = Query("USD", pattern=r"^[A-Z]{3}$"),
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """`currency` is the display currency for the combined household view only;
    a single account always reports in its own currencies."""
    if not accounts:
        return compute_income([], [])
    if len(accounts) == 1:
        return await _income_for(db, accounts[0])

    labels = await repo.account_labels(db)
    per_account = []
    for account_id in accounts:
        summary = await _income_for(db, account_id)
        summary["account_id"] = account_id
        summary["account_label"] = labels.get(account_id, account_id)
        per_account.append(summary)

    # One rate per source currency into the display currency (identity pairs
    # resolve to 1.0), so _combine can convert before summing.
    ccys = {
        c
        for s in per_account
        for c in (s.get("base_currency"), s.get("premium_currency"))
        if c
    }
    display_rates = await fx.rate_map({(c, currency) for c in ccys})
    combined = _combine(
        per_account,
        display_currency=currency,
        rates={src: r.rate for (src, _dst), r in display_rates.items()},
        fx_used=[r.as_dict() for r in display_rates.values() if r.source != "identity"],
    )
    combined["by_account"] = per_account
    return combined


class IncomeAdjustmentIn(BaseModel):
    month: str  # "YYYY-MM"
    cashed_out: bool = False
    withdrawal_amount: float | None = None
    note: str | None = None


def _parse_month(value: str) -> date | None:
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        return None


@router.put("/income/adjustments")
async def upsert_income_adjustment(
    body: IncomeAdjustmentIn,
    account_id: str = Depends(single_account),
    db: AsyncSession = Depends(get_session),
) -> dict:
    month = _parse_month(body.month)
    if month is None:
        return {"error": "month must be 'YYYY-MM'"}

    values = {
        "account_id": account_id,
        "month": month,
        "cashed_out": body.cashed_out,
        "withdrawal_amount": body.withdrawal_amount,
        "note": body.note,
    }
    stmt = (
        pg_insert(IncomeAdjustment)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_income_account_month",
            set_={
                "cashed_out": values["cashed_out"],
                "withdrawal_amount": values["withdrawal_amount"],
                "note": values["note"],
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}
