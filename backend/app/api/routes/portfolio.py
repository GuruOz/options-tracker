from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state import session_state
from app.db import repo
from app.db.base import AsyncSessionLocal, get_session
from app.db.models import Execution
from app.schemas.responses import AccountSummaryOut, PositionOut, TradeOut

router = APIRouter(tags=["portfolio"])


from app.analytics.enrichment import enrich_positions

_DATA_SOURCE = "ibkr_live"
_CACHE_SOURCE = "cache"


def _source() -> str:
    return _DATA_SOURCE if session_state.user_logged_in else _CACHE_SOURCE


@router.get("/positions", response_model=list[PositionOut])
async def get_positions(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    
    positions = await repo.latest_positions(db, session_state.account_id)
    if not positions:
        return []
        
    options = [p for p in positions if p.sec_type in ("OPT", "FOP", "WAR")]
    if not options:
        return []
        
    markets = await repo.latest_priced_market(db)
    roll_chains = await repo.open_roll_chains(db, session_state.account_id)
    
    enriched = enrich_positions(options, markets, roll_chains)
    src = _source()
    for p in enriched:
        p.source = src
        p.last_updated = p.snapshot_ts
    return enriched


@router.get("/alerts", response_model=list[PositionOut])
async def get_alerts(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    positions = await repo.latest_positions(db, session_state.account_id)
    if not positions:
        return []
        
    options = [p for p in positions if p.sec_type in ("OPT", "FOP", "WAR")]
    if not options:
        return []
        
    markets = await repo.latest_priced_market(db)
    roll_chains = await repo.open_roll_chains(db, session_state.account_id)
    
    enriched = enrich_positions(options, markets, roll_chains)
    src = _source()
    for p in enriched:
        p.source = src
        p.last_updated = p.snapshot_ts
    return [p for p in enriched if p.status and p.status != "OPEN"]


@router.get("/account", response_model=AccountSummaryOut | None)
async def get_account(db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return None
    row = await repo.latest_account(db, session_state.account_id)
    if row:
        row.source = _source()
        row.last_updated = row.snapshot_ts
    return row


@router.get("/trades", response_model=list[TradeOut])
async def get_trades(limit: int = 100, db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    return await repo.recent_trades(db, session_state.account_id, limit)


@router.get("/trades/options", response_model=list[TradeOut])
async def get_option_trades(db: AsyncSession = Depends(get_session)):
    """All option trades (OPT/FOP/WAR), oldest first. No limit."""
    if not session_state.account_id:
        return []
    return await repo.all_option_trades(db, session_state.account_id)


@router.get("/chains", response_model=list[dict])
async def get_chains(status: str = "open", db: AsyncSession = Depends(get_session)):
    if not session_state.account_id:
        return []
    return await repo.roll_chain_summaries(db, session_state.account_id, status=status)


from pydantic import BaseModel
class LinkExecRequest(BaseModel):
    exec_id: str


async def _rebuild_chains() -> None:
    """Re-run the chain builder so a just-saved adjustment takes effect now."""
    from app.poller.jobs.rolls import build_rolls
    await build_rolls(None)


@router.post("/chains/{chain_id}/link")
async def link_chain_exec(chain_id: str, req: LinkExecRequest, db: AsyncSession = Depends(get_session)):
    """Merge the chain that owns `exec_id` into this chain (cross-strike roll)."""
    if not session_state.account_id:
        return {"error": "Not logged in"}

    from app.db.models import ChainAdjustment
    db.add(ChainAdjustment(
        chain_id=chain_id,
        adjustment_type="manual_link",
        exec_id=req.exec_id,
    ))
    await db.commit()
    await _rebuild_chains()
    return {"status": "ok"}


@router.post("/chains/{chain_id}/close")
async def close_chain_manual(chain_id: str, db: AsyncSession = Depends(get_session)):
    """Manually close a chain (e.g. an early close the trade feed can't show)."""
    if not session_state.account_id:
        return {"error": "Not logged in"}

    from datetime import datetime, timezone
    from app.db.models import ChainAdjustment
    db.add(ChainAdjustment(
        chain_id=chain_id,
        adjustment_type="manual_close",
        close_date=datetime.now(timezone.utc),
        close_reason="manual_close",
    ))
    await db.commit()
    await _rebuild_chains()
    return {"status": "ok"}



_COLUMNS_TRADES = {
    "exec_id", "account_id", "conid", "symbol", "sec_type", "side", "right",
    "strike", "expiry", "qty", "price", "commission", "realized_pnl",
    "exec_time", "source", "raw",
}


@router.post("/trades/upload")
async def upload_trades(file: UploadFile = File(...)) -> dict:
    """Upload an IBKR Activity Statement CSV. Idempotent by exec_id."""
    if not session_state.account_id:
        return {"status": "error", "message": "No account selected."}
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {"status": "error", "message": "Please upload a .csv file."}

    content = await file.read()
    from app.clients.ibkr.csv_import import parse_ibkr_csv
    trades = parse_ibkr_csv(content, session_state.account_id)
    if not trades:
        return {"status": "ok", "imported": 0, "message": "No trades found in file."}

    values = [{k: v for k, v in t.items() if k in _COLUMNS_TRADES} for t in trades]
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Execution)
            .values(values)
            .on_conflict_do_nothing(index_elements=["exec_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        inserted = result.rowcount

    return {
        "status": "ok",
        "parsed": len(trades),
        "inserted": inserted,
        "message": f"Imported {inserted} new trades ({len(trades) - inserted} already existed).",
    }
