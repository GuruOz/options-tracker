from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state import session_state
from app.db import repo
from app.db.base import get_session
from app.schemas.responses import AccountSummaryOut, PositionOut, TradeOut

router = APIRouter(tags=["portfolio"])


@router.get("/positions", response_model=list[PositionOut])
async def get_positions(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    return await repo.latest_positions(db, session_state.account_id)


@router.get("/account", response_model=AccountSummaryOut | None)
async def get_account(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return None
    return await repo.latest_account(db, session_state.account_id)


@router.get("/trades", response_model=list[TradeOut])
async def get_trades(limit: int = 100, db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    return await repo.recent_trades(db, session_state.account_id, limit)
