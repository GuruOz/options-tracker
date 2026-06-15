from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.base import get_session
from app.db.models import Setting
from app.schemas.responses import MarketOut, SignalOut, SignalPointOut

router = APIRouter(tags=["market"])


@router.get("/market", response_model=list[MarketOut])
async def get_market(db: AsyncSession = Depends(get_session)):
    return await repo.latest_market(db)


@router.get("/signals", response_model=list[SignalOut])
async def get_signals(db: AsyncSession = Depends(get_session)):
    settings_row = await db.get(Setting, 1)
    tracked_conids = set()
    if settings_row:
        for u in (settings_row.data or {}).get("underlyings", []):
            try:
                tracked_conids.add(int(u["conid"]))
            except (KeyError, ValueError, TypeError):
                pass
    rows = await repo.latest_signals(db)
    return [r for r in rows if r.underlying_conid in tracked_conids]


@router.get("/signal/history", response_model=list[SignalPointOut])
async def get_signal_history(conid: int, db: AsyncSession = Depends(get_session)):
    return await repo.signal_series(db, conid)
