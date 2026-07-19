"""FIRE plan settings + monthly cashflow.

GET/PUT /api/plan/settings?owner=  — the FIRE parameter blob (defaults filled)
GET     /api/cashflow?owner=&months=  — recent monthly income/expenses
PUT     /api/cashflow                  — upsert one month's figures

The FIRE projection maths live client-side (see frontend/src/lib/fire.ts); this
route only persists inputs.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import CashflowEntry, PlanSettings

router = APIRouter(tags=["planning"])

_DEFAULTS = {
    "current_age": 35,
    "retire_age": 55,
    "target_monthly_income": 5000,
    "swr_pct": 4.0,
    "expected_return_pct": 6.0,
    "pessimistic_return_pct": 4.0,
    "optimistic_return_pct": 8.0,
    "inflation_pct": 2.5,
    "monthly_savings_override": None,
}


@router.get("/plan/settings")
async def get_plan_settings(
    owner: str = Query("household"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await db.get(PlanSettings, owner)
    data = {**_DEFAULTS, **(row.data if row else {})}
    return {"owner": owner, "data": data}


@router.put("/plan/settings")
async def put_plan_settings(
    data: dict,
    owner: str = Query("household"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    # Only keep known keys so a stray client field can't bloat the blob.
    clean = {k: data[k] for k in _DEFAULTS if k in data}
    stmt = (
        pg_insert(PlanSettings)
        .values(owner=owner, data=clean)
        .on_conflict_do_update(index_elements=["owner"], set_={"data": clean})
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok", "data": {**_DEFAULTS, **clean}}


@router.get("/cashflow")
async def get_cashflow(
    owner: str = Query("household"),
    months: int = Query(24, ge=1, le=120),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await db.execute(
        select(CashflowEntry)
        .where(CashflowEntry.owner == owner)
        .order_by(desc(CashflowEntry.month))
        .limit(months)
    )
    entries = [
        {
            "month": e.month.isoformat(),
            "income": float(e.income) if e.income is not None else None,
            "expenses": float(e.expenses) if e.expenses is not None else None,
            "note": e.note,
        }
        for e in rows.scalars().all()
    ]
    entries.reverse()  # oldest -> newest for charting
    return {"owner": owner, "entries": entries}


class CashflowBody(BaseModel):
    month: date  # any day; normalised to first of month
    income: float | None = None
    expenses: float | None = None
    note: str | None = None


@router.put("/cashflow")
async def put_cashflow(
    body: CashflowBody,
    owner: str = Query("household"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    month = body.month.replace(day=1)
    stmt = (
        pg_insert(CashflowEntry)
        .values(
            owner=owner, month=month,
            income=body.income, expenses=body.expenses, note=body.note,
        )
        .on_conflict_do_update(
            constraint="uq_cashflow_owner_month",
            set_={"income": body.income, "expenses": body.expenses, "note": body.note},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}
