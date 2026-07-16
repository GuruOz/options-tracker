from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.enrichment import enrich_positions
from app.api.deps import account_scope, single_account
from app.core.gateways import runtime_for_account
from app.db import repo
from app.db.base import AsyncSessionLocal, get_session
from app.db.models import AccountSetting, Execution
from app.schemas.responses import AccountOut, AccountSummaryOut, PositionOut, TradeOut

router = APIRouter(tags=["portfolio"])

_DATA_SOURCE = "ibkr_live"
_CACHE_SOURCE = "cache"


def _source(account_id: str) -> str:
    """Live only while that account's own gateway is logged in."""
    runtime = runtime_for_account(account_id)
    return _DATA_SOURCE if runtime and runtime.state.user_logged_in else _CACHE_SOURCE


async def _enriched_options(db: AsyncSession, accounts: list[str]) -> list[PositionOut]:
    """Every scoped account's option positions, enriched and tagged by owner.

    Enrichment runs per account: chains, and the alert thresholds that judge
    them, belong to one account and must not be pooled across users.
    """
    markets = await repo.latest_priced_market(db)  # conid-keyed, shared
    labels = await repo.account_labels(db)

    out: list[PositionOut] = []
    for account_id in accounts:
        positions = await repo.latest_positions(db, account_id)
        options = [p for p in positions if p.sec_type in ("OPT", "FOP", "WAR")]
        if not options:
            continue

        roll_chains = await repo.open_roll_chains(db, account_id)
        settings_row = await db.get(AccountSetting, account_id)
        alerts = (settings_row.data or {}).get("alerts") if settings_row else None

        enriched = enrich_positions(options, markets, roll_chains, alerts)
        src = _source(account_id)
        for p in enriched:
            p.source = src
            p.last_updated = p.snapshot_ts
            p.account_id = account_id
            p.account_label = labels.get(account_id, account_id)
        out.extend(enriched)
    return out


@router.get("/positions", response_model=list[PositionOut])
async def get_positions(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    return await _enriched_options(db, accounts)


@router.get("/alerts", response_model=list[PositionOut])
async def get_alerts(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    enriched = await _enriched_options(db, accounts)
    return [p for p in enriched if p.status and p.status != "OPEN"]


@router.get("/accounts", response_model=list[AccountOut])
async def get_accounts(db: AsyncSession = Depends(get_session)):
    """Every known account with its latest summary — powers the user switcher."""
    out: list[AccountOut] = []
    for account in await repo.all_accounts(db):
        snap = await repo.latest_account(db, account.account_id)
        runtime = runtime_for_account(account.account_id)
        out.append(AccountOut(
            account_id=account.account_id,
            label=account.label or account.account_id,
            base_currency=account.base_currency,
            gateway_id=runtime.gateway_id if runtime else None,
            snapshot_ts=snap.snapshot_ts if snap else None,
            net_liquidation=snap.net_liquidation if snap else None,
            available_funds=snap.available_funds if snap else None,
            excess_liquidity=snap.excess_liquidity if snap else None,
            maintenance_margin=snap.maintenance_margin if snap else None,
            buying_power=snap.buying_power if snap else None,
            cash=snap.cash if snap else None,
            leverage=snap.leverage if snap else None,
            source=_source(account.account_id),
        ))
    return out


@router.get("/account", response_model=AccountSummaryOut | None)
async def get_account(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    """One account's latest summary. For the combined view use /accounts."""
    if len(accounts) != 1:
        return None
    row = await repo.latest_account(db, accounts[0])
    if row:
        row.source = _source(accounts[0])
        row.last_updated = row.snapshot_ts
    return row


@router.get("/trades", response_model=list[TradeOut])
async def get_trades(
    limit: int = 100,
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    out: list[TradeOut] = []
    labels = await repo.account_labels(db)
    for account_id in accounts:
        for row in await repo.recent_trades(db, account_id, limit):
            trade = TradeOut.model_validate(row)
            trade.account_id = account_id
            trade.account_label = labels.get(account_id, account_id)
            out.append(trade)
    # Merging two accounts' feeds would otherwise interleave by account, not time.
    out.sort(key=lambda t: (t.exec_time is None, t.exec_time), reverse=True)
    return out[:limit]


@router.get("/trades/options", response_model=list[TradeOut])
async def get_option_trades(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    """All option trades (OPT/FOP/WAR), oldest first. No limit."""
    out: list[TradeOut] = []
    labels = await repo.account_labels(db)
    for account_id in accounts:
        for row in await repo.all_option_trades(db, account_id):
            trade = TradeOut.model_validate(row)
            trade.account_id = account_id
            trade.account_label = labels.get(account_id, account_id)
            out.append(trade)
    out.sort(key=lambda t: (t.exec_time is None, t.exec_time))
    return out


@router.get("/chains", response_model=list[dict])
async def get_chains(
    status: str = "open",
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
):
    labels = await repo.account_labels(db)
    out: list[dict] = []
    for account_id in accounts:
        for chain in await repo.roll_chain_summaries(db, account_id, status=status):
            chain["account_id"] = account_id
            chain["account_label"] = labels.get(account_id, account_id)
            out.append(chain)
    return out


from pydantic import BaseModel
class LinkExecRequest(BaseModel):
    exec_id: str


async def _rebuild_chains() -> None:
    """Re-run the chain builder so a just-saved adjustment takes effect now."""
    from app.poller.jobs.rolls import build_rolls
    await build_rolls()


async def _chain_or_404(db: AsyncSession, chain_id: str) -> None:
    """A chain id already identifies its account, so existence is the only check."""
    if await repo.chain_exists(db, chain_id):
        return
    raise HTTPException(status_code=404, detail=f"Unknown chain '{chain_id}'.")


@router.post("/chains/{chain_id}/link")
async def link_chain_exec(
    chain_id: str, req: LinkExecRequest, db: AsyncSession = Depends(get_session)
):
    """Merge the chain that owns `exec_id` into this chain (cross-strike roll)."""
    await _chain_or_404(db, chain_id)

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
    await _chain_or_404(db, chain_id)

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
    "strike", "expiry", "qty", "price", "commission", "realized_pnl", "currency",
    "exec_time", "source", "raw",
}


@router.post("/trades/upload")
async def upload_trades(
    file: UploadFile = File(...),
    account_id: str = Depends(single_account),
) -> dict:
    """Upload an IBKR Activity Statement CSV. Idempotent by exec_id."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {"status": "error", "message": "Please upload a .csv file."}

    # Defense-in-depth behind nginx's client_max_body_size 10m.
    _MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="CSV too large (10 MB max).")
        chunks.append(chunk)
    content = b"".join(chunks)

    from app.clients.ibkr.csv_import import parse_ibkr_csv
    trades = parse_ibkr_csv(content, account_id)
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
