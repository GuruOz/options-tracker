"""Premium-income endpoint + the manual withdrawal/cashed-out overlay.

GET  /api/income                 — monthly -> YTD income summary (derived).
PUT  /api/income/adjustments     — upsert a month's cashed-out / withdrawal note.

In the combined view the derived numbers sum across accounts, but the manual
overlay does not: a "cashed out" flag or a withdrawal belongs to one account, so
`by_account` carries each user's own summary and writes must name an account.
"""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.income import compute_income
from app.api.deps import account_scope, single_account
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
    return compute_income(chains, adjustments, net_liquidation=net_liq)


def _combine(per_account: list[dict]) -> dict:
    """Sum every account's monthly/annual P&L into one household summary.

    The manual overlay (cashed_out / withdrawal / note) is deliberately dropped
    from the combined months — one account's withdrawal says nothing about the
    other's. The per-account summaries keep theirs.
    """
    monthly_pnl: dict[str, float] = defaultdict(float)
    monthly_count: dict[str, int] = defaultdict(int)
    for summary in per_account:
        for m in summary["months"]:
            monthly_pnl[m["month"]] += m["pnl"]
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
        for y in summary["years"]:
            year_pnl[y["year"]] += y["ytd"]
            year_withdrawn[y["year"]] += y["withdrawn"]
    years = [
        {
            "year": y,
            "ytd": round(year_pnl[y], 2),
            "withdrawn": round(year_withdrawn[y], 2),
            "remaining": round(year_pnl[y] - year_withdrawn[y], 2),
        }
        for y in sorted(year_pnl)
    ]

    all_time = round(sum(s["all_time"] for s in per_account), 2)
    closed = sum(s["closed_count"] for s in per_account)
    # Win rate is a ratio, so it has to be rebuilt from the underlying counts
    # rather than averaged across accounts of different sizes.
    wins = sum(
        (s["win_rate"] or 0.0) * s["closed_count"]
        for s in per_account if s["win_rate"] is not None
    )
    net_liqs = [
        s["net_liquidation"] for s in per_account if s["net_liquidation"] is not None
    ]
    net_liq = sum(net_liqs) if net_liqs else None

    return {
        "months": months,
        "years": years,
        "all_time": all_time,
        "realized": round(sum(s["realized"] for s in per_account), 2),
        "unrealized": round(sum(s["unrealized"] for s in per_account), 2),
        "win_rate": (wins / closed) if closed else None,
        "closed_count": closed,
        "open_count": sum(s["open_count"] for s in per_account),
        "net_liquidation": net_liq,
        "yield_pct": (all_time / net_liq) if net_liq else None,
    }


@router.get("/income")
async def get_income(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
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

    combined = _combine(per_account)
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
