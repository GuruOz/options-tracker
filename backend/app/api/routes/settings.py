from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.defaults import DEFAULT_SETTINGS
from app.db.base import get_session
from app.db.models import Setting

router = APIRouter(tags=["settings"])


async def _get_or_create(db: AsyncSession) -> Setting:
    row = await db.get(Setting, 1)
    if row is None:
        row = Setting(id=1, data=dict(DEFAULT_SETTINGS))
        db.add(row)
    return row


@router.get("/settings")
async def read_settings(db: AsyncSession = Depends(get_session)) -> dict:
    row = await db.get(Setting, 1)
    return row.data if row else DEFAULT_SETTINGS


@router.put("/settings")
async def update_settings(
    payload: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    row = await _get_or_create(db)
    row.data = payload
    await db.commit()
    return payload


class UnderlyingIn(BaseModel):
    conid: int
    symbol: str
    description: str = ""


@router.post("/settings/underlyings")
async def add_underlying(
    body: UnderlyingIn, db: AsyncSession = Depends(get_session)
) -> dict:
    row = await _get_or_create(db)
    data = dict(row.data)
    underlyings: list = list(data.get("underlyings", []))
    if any(int(u.get("conid", 0)) == body.conid for u in underlyings):
        return data  # already present
    underlyings.append({"conid": body.conid, "symbol": body.symbol, "description": body.description})
    data["underlyings"] = underlyings
    row.data = data
    await db.commit()
    return data


@router.delete("/settings/underlyings/{conid}")
async def remove_underlying(
    conid: int, db: AsyncSession = Depends(get_session)
) -> dict:
    row = await _get_or_create(db)
    data = dict(row.data)
    underlyings = [u for u in data.get("underlyings", []) if int(u.get("conid", 0)) != conid]
    data["underlyings"] = underlyings
    row.data = data
    await db.commit()
    return data
