"""Premium-income endpoint + the manual withdrawal/cashed-out overlay.

GET  /api/income                 — monthly -> YTD income summary (derived).
PUT  /api/income/adjustments     — upsert a month's cashed-out / withdrawal note.
"""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.income import compute_income
from app.core.state import session_state
from app.db import repo
from app.db.base import get_session
from app.db.models import IncomeAdjustment

router = APIRouter(tags=["income"])


@router.get("/income")
async def get_income(db: AsyncSession = Depends(get_session)) -> dict:
    if not session_state.account_id:
        return compute_income([], [])

    chains = await repo.all_roll_chains(db, session_state.account_id)
    adjustments = await repo.income_adjustments(db, session_state.account_id)
    account = await repo.latest_account(db, session_state.account_id)
    net_liq = (
        float(account.net_liquidation)
        if account and account.net_liquidation is not None
        else None
    )
    return compute_income(chains, adjustments, net_liquidation=net_liq)


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
    body: IncomeAdjustmentIn, db: AsyncSession = Depends(get_session)
) -> dict:
    if not session_state.account_id:
        return {"error": "Not logged in"}
    month = _parse_month(body.month)
    if month is None:
        return {"error": "month must be 'YYYY-MM'"}

    values = {
        "account_id": session_state.account_id,
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
