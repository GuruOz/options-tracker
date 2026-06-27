"""Portfolio risk endpoint: beta-weighted stress move + assignment coverage."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.risk import compute_risk
from app.core.state import session_state
from app.db import repo
from app.db.base import get_session
from app.db.models import Setting
from app.schemas.responses import RiskOut

router = APIRouter(tags=["risk"])


@router.get("/risk", response_model=RiskOut | None)
async def get_risk(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return None

    positions = await repo.latest_positions(db, session_state.account_id)
    # Use the latest *priced* snapshot per symbol so a transient empty IBKR poll
    # (price=None) can't shadow a good spot and skew the beta-weighted scenario.
    markets = await repo.latest_priced_market(db)
    account = await repo.latest_account(db, session_state.account_id)
    settings_row = await db.get(Setting, 1)
    settings = settings_row.data if settings_row else None

    result = compute_risk(positions, markets, account, settings)
    result["equity_curve"] = await repo.account_series(db, session_state.account_id)
    return result
