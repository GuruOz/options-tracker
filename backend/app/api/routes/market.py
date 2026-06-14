from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.base import get_session
from app.schemas.responses import MarketOut, SignalOut, SignalPointOut

router = APIRouter(tags=["market"])


@router.get("/market", response_model=list[MarketOut])
async def get_market(db: AsyncSession = Depends(get_session)):
    return await repo.latest_market(db)


@router.get("/signals", response_model=list[SignalOut])
async def get_signals(db: AsyncSession = Depends(get_session)):
    return await repo.latest_signals(db)


@router.get("/signal/history", response_model=list[SignalPointOut])
async def get_signal_history(conid: int, db: AsyncSession = Depends(get_session)):
    return await repo.signal_series(db, conid)
