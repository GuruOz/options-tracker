"""Settings API — a merged view over the global row and the per-account row.

Settings are split by what they actually govern:
  * per-account — `underlyings` (each user's watchlist) and `alerts` (each
    user's take-profit / expiry / cushion thresholds)
  * global — `signal` weights, the `bs` fallback rate and the `risk` beta map,
    all of which feed the conid-keyed market data every account shares

Clients see one flat dict either way, so the shape callers already depend on
(`data.underlyings`, `data.signal`, ...) is unchanged.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.defaults import DEFAULT_SETTINGS
from app.api.deps import ALL, account_scope, single_account
from app.db import repo
from app.db.base import get_session
from app.db.models import AccountSetting, Setting

router = APIRouter(tags=["settings"])

# Keys that live on the account row rather than the global one.
_PER_ACCOUNT_KEYS = ("underlyings", "alerts")


def _global_defaults() -> dict:
    return {k: v for k, v in DEFAULT_SETTINGS.items() if k not in _PER_ACCOUNT_KEYS}


def _account_defaults() -> dict:
    return {
        "underlyings": [],
        "alerts": dict(DEFAULT_SETTINGS["alerts"]),
    }


async def _get_or_create_global(db: AsyncSession) -> Setting:
    row = await db.get(Setting, 1)
    if row is None:
        row = Setting(id=1, data=_global_defaults())
        db.add(row)
    return row


async def _get_or_create_account(db: AsyncSession, account_id: str) -> AccountSetting:
    row = await db.get(AccountSetting, account_id)
    if row is None:
        row = AccountSetting(account_id=account_id, data=_account_defaults())
        db.add(row)
    return row


def _merge(global_data: dict, account_data: dict) -> dict:
    merged = {k: v for k, v in global_data.items() if k not in _PER_ACCOUNT_KEYS}
    defaults = _account_defaults()
    for key in _PER_ACCOUNT_KEYS:
        merged[key] = account_data.get(key, defaults[key])
    return merged


def _union_underlyings(rows: list[AccountSetting]) -> list[dict]:
    """Every tracked underlying across accounts, deduped by conid."""
    seen: dict[int, dict] = {}
    for row in rows:
        for u in (row.data or {}).get("underlyings", []):
            try:
                seen.setdefault(int(u["conid"]), u)
            except (KeyError, ValueError, TypeError):
                continue
    return list(seen.values())


@router.get("/settings")
async def read_settings(
    accounts: list[str] = Depends(account_scope),
    account_id: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    global_row = await db.get(Setting, 1)
    global_data = global_row.data if global_row else _global_defaults()

    # Combined view: the union watchlist, read-only (the UI disables editing).
    if account_id == ALL or len(accounts) != 1:
        rows = [
            r for r in (await repo.all_account_settings(db))
            if r.account_id in set(accounts)
        ]
        merged = _merge(global_data, {})
        merged["underlyings"] = _union_underlyings(rows)
        return merged

    account_row = await db.get(AccountSetting, accounts[0])
    return _merge(global_data, (account_row.data if account_row else {}) or {})


@router.put("/settings")
async def update_settings(
    payload: dict,
    account_id: str = Depends(single_account),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Save a merged settings dict, routing each key to its owning row."""
    global_row = await _get_or_create_global(db)
    account_row = await _get_or_create_account(db, account_id)

    global_row.data = {k: v for k, v in payload.items() if k not in _PER_ACCOUNT_KEYS}
    account_data = dict(account_row.data or {})
    for key in _PER_ACCOUNT_KEYS:
        if key in payload:
            account_data[key] = payload[key]
    account_row.data = account_data

    await db.commit()
    return _merge(global_row.data, account_row.data)


class UnderlyingIn(BaseModel):
    conid: int
    symbol: str
    description: str = ""


@router.post("/settings/underlyings")
async def add_underlying(
    body: UnderlyingIn,
    account_id: str = Depends(single_account),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await _get_or_create_account(db, account_id)
    data = dict(row.data or {})
    underlyings: list = list(data.get("underlyings", []))
    if not any(int(u.get("conid", 0)) == body.conid for u in underlyings):
        underlyings.append({
            "conid": body.conid,
            "symbol": body.symbol,
            "description": body.description,
        })
        data["underlyings"] = underlyings
        row.data = data
        await db.commit()

    global_row = await db.get(Setting, 1)
    return _merge(global_row.data if global_row else _global_defaults(), row.data)


@router.delete("/settings/underlyings/{conid}")
async def remove_underlying(
    conid: int,
    account_id: str = Depends(single_account),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await _get_or_create_account(db, account_id)
    data = dict(row.data or {})
    data["underlyings"] = [
        u for u in data.get("underlyings", []) if int(u.get("conid", 0)) != conid
    ]
    row.data = data
    await db.commit()

    global_row = await db.get(Setting, 1)
    return _merge(global_row.data if global_row else _global_defaults(), row.data)
