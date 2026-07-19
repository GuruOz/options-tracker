"""Household net-worth + owner grouping for the finance-tracker home view.

GET /api/owners      — the people the household net-worth view groups by.
GET /api/networth    — net worth per owner + combined, in one display currency.

Owner scoping mirrors the account scoping in `deps.py`: `?owner=all` (or omitted)
covers the whole household, otherwise a single owner slug from /api/owners.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.services import networth as nw_service

router = APIRouter(tags=["networth"])


@router.get("/owners")
async def get_owners(db: AsyncSession = Depends(get_session)) -> dict:
    owners = await nw_service.owner_map(db)
    return {
        "owners": [
            {
                "owner": info.owner,
                "label": info.label,
                "accounts": [
                    {"account_id": a.account_id, "kind": a.kind, "label": a.label or a.account_id}
                    for a in info.accounts
                ],
            }
            for info in owners.values()
        ]
    }


@router.get("/networth")
async def get_networth(
    owner: str = Query("all"),
    target: str = Query("USD", pattern=r"^[A-Za-z]{3}$"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await nw_service.net_worth(db, owner, target)


@router.get("/networth/history")
async def get_networth_history(
    owner: str = Query("all"),
    target: str = Query("USD", pattern=r"^[A-Za-z]{3}$"),
    months: int = Query(36, ge=1, le=120),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await nw_service.history(db, owner, target, months)


@router.get("/holdings")
async def get_holdings(
    owner: str = Query("all"),
    target: str = Query("USD", pattern=r"^[A-Za-z]{3}$"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await nw_service.holdings(db, owner, target)
