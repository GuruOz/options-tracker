"""Diagnostic dumps for reconciling IBKR data against the Excel tracker.

The Excel sheet (`docs/Sample Options tracker - Guru.xlsx`) is the source of
truth. We can't otherwise see what IBKR actually returned, so this endpoint
surfaces the parsed `executions` (including the raw IBKR payload) and the credit
the P&L logic derives from each one — letting the numbers be compared
field-by-field against the sheet. Read-only; intended for debugging.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.rolls import _credit, _underlying_ticker
from app.api.deps import account_scope
from app.db import repo
from app.db.base import get_session

router = APIRouter(tags=["diagnostics"])


def _exec_dump(e) -> dict:
    """One execution as the parser stored it + the credit P&L derives from it."""
    return {
        "exec_id": e.exec_id,
        "account_id": e.account_id,
        "exec_time": e.exec_time.isoformat() if e.exec_time else None,
        "symbol": e.symbol,
        "underlying": _underlying_ticker(e.symbol),
        "sec_type": e.sec_type,
        "side": e.side,
        "right": e.right,
        "strike": e.strike,
        "expiry": e.expiry.isoformat() if e.expiry else None,
        "qty": e.qty,
        "price": e.price,
        "commission": e.commission,
        "realized_pnl": e.realized_pnl,
        "source": e.source,
        # The dollar credit (+) / debit (−) the roll-chain math assigns to this
        # leg, net of commission. Sum these per underlying to reconcile.
        "derived_credit": round(_credit(e), 2),
        "raw": e.raw,
    }


@router.get("/diagnostics/executions")
async def dump_executions(
    include_raw: bool = False,
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Dump every parsed execution + per-underlying credit rollup.

    `include_raw=false` omits the raw IBKR payloads for a terser view.
    """
    if not accounts:
        return {"status": "error", "message": "No account selected.", "executions": []}

    rows = []
    for account_id in accounts:
        rows.extend(await repo.all_executions(db, account_id))
    dumps = [_exec_dump(e) for e in rows]
    if not include_raw:
        for d in dumps:
            d.pop("raw", None)

    # Per-underlying credit rollup — compare to the Excel chain/month totals.
    by_underlying: dict[str, float] = defaultdict(float)
    by_source: dict[str, int] = defaultdict(int)
    for e in rows:
        by_underlying[_underlying_ticker(e.symbol) or "?"] += _credit(e)
        by_source[e.source or "?"] += 1

    return {
        "status": "ok",
        "account_ids": accounts,
        "count": len(rows),
        "by_source": dict(by_source),
        "credit_by_underlying": {k: round(v, 2) for k, v in sorted(by_underlying.items())},
        "total_credit": round(sum(by_underlying.values()), 2),
        "executions": dumps,
    }
