"""CPF/Endowus statement upload + management.

POST   /api/statements/upload?source=cpf|endowus&owner=<slug>  — parse + persist
GET    /api/statements                                          — upload log
DELETE /api/statements/{statement_id}                           — drop a bad import

Follows the idempotent-upload pattern of ``portfolio.upload_trades``: chunked
read under a 10 MB cap, a content sha256 that makes a re-upload a no-op, and
``on_conflict_do_nothing`` inserts so a re-parse never duplicates rows.
"""
from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.statements.cpf_pdf import parse_cpf_pdf
from app.clients.statements.endowus_pdf import parse_endowus_pdf
from app.db.base import AsyncSessionLocal, get_session
from app.db.models import (
    Account,
    CpfTransaction,
    ExternalBalance,
    ExternalHolding,
    StatementUpload,
)

router = APIRouter(tags=["statements"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_OWNER_RE = re.compile(r"^[a-z0-9_]{1,24}$")


async def _read_capped(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="PDF too large (10 MB max).")
        chunks.append(chunk)
    return b"".join(chunks)


async def _ensure_account(
    session: AsyncSession, account_id: str, source: str, owner: str, currency: str
) -> None:
    label = f"{source.upper()} ({owner.replace('_', ' ').title()})"
    stmt = (
        pg_insert(Account)
        .values(
            account_id=account_id, kind=source, owner=owner,
            base_currency=currency, label=label,
        )
        .on_conflict_do_nothing(index_elements=["account_id"])
    )
    await session.execute(stmt)


def _insert_ignore(session: AsyncSession, model, rows: list[dict]):
    if not rows:
        return
    return session.execute(pg_insert(model).values(rows).on_conflict_do_nothing())


@router.post("/statements/upload")
async def upload_statement(
    source: str = Query(..., pattern=r"^(cpf|endowus)$"),
    owner: str = Query(...),
    file: UploadFile = File(...),
) -> dict:
    owner = owner.strip().lower()
    if not _OWNER_RE.match(owner):
        raise HTTPException(status_code=400, detail="Invalid owner slug.")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"status": "error", "message": "Please upload a .pdf file."}

    content = await _read_capped(file)
    sha = hashlib.sha256(content).hexdigest()
    account_id = f"{source.upper()}-{owner.upper()}"

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(StatementUpload.id).where(StatementUpload.file_sha256 == sha)
        )
        if existing.scalar_one_or_none() is not None:
            return {"status": "duplicate", "message": "This statement was already imported."}

        try:
            if source == "cpf":
                parsed = parse_cpf_pdf(content)
                # CPF is always SGD (Singapore government statement, no symbols).
                currency = "SGD"
                balances = [
                    {"account_id": account_id, "as_of": b.as_of, "category": b.category,
                     "balance": b.balance, "currency": currency}
                    for b in parsed.balances
                ]
                txns = [
                    {"account_id": account_id, "txn_date": t.txn_date, "code": t.code,
                     "for_month": t.for_month, "ref": t.ref, "oa_amount": t.oa_amount,
                     "sa_amount": t.sa_amount, "ma_amount": t.ma_amount, "row_hash": t.row_hash}
                    for t in parsed.transactions
                ]
                holdings: list[dict] = []
            else:
                parsed = parse_endowus_pdf(content)
                # Endowus display currency is per-statement (SGD or USD).
                currency = parsed.currency
                balances = [
                    {"account_id": account_id, "as_of": b.as_of, "category": b.category,
                     "balance": b.balance, "currency": b.currency}
                    for b in parsed.balances
                ]
                txns = []
                holdings = [
                    {"account_id": account_id, "as_of": h.as_of, "goal_name": h.goal_name,
                     "fund_name": h.fund_name, "asset_class": h.asset_class,
                     "funding_source": h.funding_source, "units": h.units, "nav": h.nav,
                     "avg_price": h.avg_price, "market_value": h.market_value,
                     "allocation_pct": h.allocation_pct, "currency": h.currency}
                    for h in parsed.holdings
                ]
        except Exception as exc:  # noqa: BLE001 — a malformed PDF is user error
            return {"status": "error", "message": f"Could not parse statement: {exc}"}

        if not balances and not txns and not holdings:
            return {"status": "error", "message": "No data found in statement."}

        await _ensure_account(session, account_id, source, owner, currency)

        summary = {
            "balances": len(balances),
            "transactions": len(txns),
            "holdings": len(holdings),
            "warnings": parsed.warnings[:20],
        }
        upload = StatementUpload(
            account_id=account_id, source=source,
            period_start=parsed.period_start, period_end=parsed.period_end,
            filename=file.filename[:256], file_sha256=sha, summary=summary,
        )
        session.add(upload)
        await session.flush()  # assign upload.id

        for rows in (balances, txns, holdings):
            for r in rows:
                r["upload_id"] = upload.id
        stmts = [
            _insert_ignore(session, ExternalBalance, balances),
            _insert_ignore(session, CpfTransaction, txns),
            _insert_ignore(session, ExternalHolding, holdings),
        ]
        for coro in stmts:
            if coro is not None:
                await coro
        await session.commit()

    return {
        "status": "ok",
        "account_id": account_id,
        "period": [
            parsed.period_start.isoformat() if parsed.period_start else None,
            parsed.period_end.isoformat() if parsed.period_end else None,
        ],
        **summary,
    }


@router.get("/statements")
async def list_statements(db: AsyncSession = Depends(get_session)) -> dict:
    rows = await db.execute(
        select(StatementUpload).order_by(desc(StatementUpload.uploaded_at))
    )
    return {
        "statements": [
            {
                "id": s.id,
                "account_id": s.account_id,
                "source": s.source,
                "filename": s.filename,
                "period_start": s.period_start.isoformat() if s.period_start else None,
                "period_end": s.period_end.isoformat() if s.period_end else None,
                "uploaded_at": s.uploaded_at.isoformat() if s.uploaded_at else None,
                "summary": s.summary,
            }
            for s in rows.scalars().all()
        ]
    }


@router.delete("/statements/{statement_id}")
async def delete_statement(
    statement_id: int, db: AsyncSession = Depends(get_session)
) -> dict:
    upload = await db.get(StatementUpload, statement_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Unknown statement.")
    for model in (ExternalBalance, CpfTransaction, ExternalHolding):
        await db.execute(delete(model).where(model.upload_id == statement_id))
    await db.delete(upload)
    await db.commit()
    return {"status": "ok"}
