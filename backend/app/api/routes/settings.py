from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.defaults import DEFAULT_SETTINGS
from app.db.base import get_session
from app.db.models import Setting

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def read_settings(db: AsyncSession = Depends(get_session)) -> dict:
    row = await db.get(Setting, 1)
    return row.data if row else DEFAULT_SETTINGS


@router.put("/settings")
async def update_settings(
    payload: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    row = await db.get(Setting, 1)
    if row is None:
        row = Setting(id=1, data=payload)
        db.add(row)
    else:
        row.data = payload
    await db.commit()
    return payload
