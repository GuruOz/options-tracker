"""Live FX rates for the header's client-side household totals.

GET /api/fx?target=USD — one rate per known account base currency into the
target display currency, so the frontend can convert each account's summary
figures before summing them. Unresolvable currencies are simply omitted; the
frontend treats a missing entry as "can't convert".
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import fx
from app.db import repo
from app.db.base import get_session

router = APIRouter(tags=["fx"])


@router.get("/fx")
async def get_fx(
    target: str = Query("USD", pattern=r"^[A-Z]{3}$"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    accounts = await repo.all_accounts(db)
    currencies = {a.base_currency for a in accounts if a.base_currency}
    currencies.add(target)  # identity entry so every lookup can succeed

    rates = await fx.rate_map({(c, target) for c in currencies})
    return {
        "target": target,
        "rates": [
            {"currency": src, **r.as_dict()}
            for (src, _dst), r in sorted(rates.items())
        ],
    }
