"""Household net-worth aggregation across account kinds.

The finance-tracker home view needs one figure per person and a combined total,
summing IBKR (live), CPF and Endowus (statement upload) accounts and converting
every source into one display currency with the existing live-FX utility.

Owner resolution: an account's `owner` column is authoritative; an IBKR row that
predates the pivot (owner NULL) falls back to its gateway id, so a single-user
deployment still groups cleanly without any manual assignment.

Aggregates three sources per owner: IBKR (latest account net-liquidation), CPF
(latest OA/SA/MA balances), and Endowus (latest goal balances). The Endowus money
figure comes from goal balances, never from summing per-fund holdings, so a CPF
amount already invested via Endowus is not double-counted.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import fx
from app.core.gateways import runtime_for_account
from app.db import repo
from app.db.models import Account, AccountSnapshot, ExternalBalance, ExternalHolding

ALL = "all"


class OwnerInfo:
    __slots__ = ("owner", "label", "accounts")

    def __init__(self, owner: str, label: str) -> None:
        self.owner = owner
        self.label = label
        self.accounts: list[Account] = []


def resolve_owner(account: Account) -> tuple[str, str]:
    """(slug, display label) for an account.

    Explicit `owner` wins; otherwise an IBKR account inherits its gateway id +
    label; failing both it lands in a shared 'unassigned' bucket.
    """
    if account.owner:
        rt = runtime_for_account(account.account_id)
        label = rt.label if rt else account.owner.replace("_", " ").title()
        return account.owner, label
    rt = runtime_for_account(account.account_id)
    if rt is not None:
        return rt.gateway_id, rt.label
    return "unassigned", "Unassigned"


async def owner_map(db: AsyncSession) -> dict[str, OwnerInfo]:
    """Ordered {slug: OwnerInfo} over every known account."""
    owners: dict[str, OwnerInfo] = {}
    for account in await repo.all_accounts(db):
        slug, label = resolve_owner(account)
        info = owners.get(slug)
        if info is None:
            info = OwnerInfo(slug, label)
            owners[slug] = info
        info.accounts.append(account)
    return owners


async def _accounts_for_scope(db: AsyncSession, owner: str) -> list[Account]:
    owners = await owner_map(db)
    if owner == ALL or not owner:
        return [a for info in owners.values() for a in info.accounts]
    info = owners.get(owner)
    return info.accounts if info else []


def _to_iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


async def _fx_rates(currencies: set[str], target: str) -> dict[tuple[str, str], float]:
    pairs = {(c.upper(), target.upper()) for c in currencies if c}
    resolved = await fx.rate_map(pairs)
    return {k: v.rate for k, v in resolved.items()}


def _convert(value: float, src: str | None, target: str, rates: dict) -> float | None:
    if value is None:
        return None
    if not src or src.upper() == target.upper():
        return float(value)
    rate = rates.get((src.upper(), target.upper()))
    return float(value) * rate if rate is not None else None


async def _ibkr_source(
    db: AsyncSession, accounts: list[Account], target: str, rates: dict
) -> dict | None:
    """Latest net-liquidation per IBKR account, converted + folded."""
    ibkr = [a for a in accounts if a.kind == "ibkr"]
    if not ibkr:
        return None

    native_total = 0.0
    converted_total = 0.0
    convertible = True
    currencies: set[str] = set()
    latest: datetime | None = None
    seen = False

    for account in ibkr:
        snap = await repo.latest_account(db, account.account_id)
        if snap is None or snap.net_liquidation is None:
            continue
        seen = True
        value = float(snap.net_liquidation)
        ccy = account.base_currency or "USD"
        currencies.add(ccy.upper())
        native_total += value
        conv = _convert(value, ccy, target, rates)
        if conv is None:
            convertible = False
        else:
            converted_total += conv
        if snap.snapshot_ts is not None and (latest is None or snap.snapshot_ts > latest):
            latest = snap.snapshot_ts

    if not seen:
        return None

    single_ccy = next(iter(currencies)) if len(currencies) == 1 else None
    return {
        "value": native_total if single_ccy else (converted_total if convertible else None),
        "currency": single_ccy or target.upper(),
        "converted": converted_total if convertible else None,
        "as_of": _to_iso(latest),
    }


async def _latest_balances(db: AsyncSession, account_id: str) -> list[ExternalBalance]:
    """Every external balance at the most recent as_of for an account."""
    max_asof = (
        select(func.max(ExternalBalance.as_of))
        .where(ExternalBalance.account_id == account_id)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(ExternalBalance).where(
            ExternalBalance.account_id == account_id,
            ExternalBalance.as_of == max_asof,
        )
    )
    return list(rows.scalars().all())


async def _latest_holdings(db: AsyncSession, account_id: str) -> list[ExternalHolding]:
    max_asof = (
        select(func.max(ExternalHolding.as_of))
        .where(ExternalHolding.account_id == account_id)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(ExternalHolding).where(
            ExternalHolding.account_id == account_id,
            ExternalHolding.as_of == max_asof,
        )
    )
    return list(rows.scalars().all())


async def _external_source(
    db: AsyncSession, accounts: list[Account], kind: str, target: str, rates: dict
) -> dict | None:
    """Fold the latest balances of every account of `kind` into one source.

    CPF exposes an OA/SA/MA `breakdown`; Endowus additionally exposes
    `by_asset_class` / `by_funding_source` from its holdings. The money figure is
    the sum of balances (goal balances for Endowus — never the holdings).
    """
    matched = [a for a in accounts if a.kind == kind]
    if not matched:
        return None

    native_total = 0.0
    converted_total = 0.0
    convertible = True
    currencies: set[str] = set()
    breakdown: dict[str, float] = {}
    latest: date | None = None
    seen = False

    for account in matched:
        for bal in await _latest_balances(db, account.account_id):
            if bal.balance is None:
                continue
            seen = True
            value = float(bal.balance)
            ccy = (bal.currency or account.base_currency or "SGD").upper()
            currencies.add(ccy)
            native_total += value
            breakdown[bal.category] = breakdown.get(bal.category, 0.0) + value
            conv = _convert(value, ccy, target, rates)
            if conv is None:
                convertible = False
            else:
                converted_total += conv
            if bal.as_of is not None and (latest is None or bal.as_of > latest):
                latest = bal.as_of

    if not seen:
        return None

    single_ccy = next(iter(currencies)) if len(currencies) == 1 else None
    src: dict = {
        "value": native_total if single_ccy else (converted_total if convertible else None),
        "currency": single_ccy or target.upper(),
        "converted": converted_total if convertible else None,
        "as_of": _to_iso(latest),
        "breakdown": {k: round(v, 2) for k, v in breakdown.items()},
    }

    if kind == "endowus":
        by_asset: dict[str, float] = {}
        by_funding: dict[str, float] = {}
        for account in matched:
            for h in await _latest_holdings(db, account.account_id):
                if h.market_value is None:
                    continue
                ccy = (h.currency or account.base_currency or "SGD").upper()
                conv = _convert(float(h.market_value), ccy, target, rates)
                if conv is None:
                    continue
                if h.asset_class:
                    by_asset[h.asset_class] = by_asset.get(h.asset_class, 0.0) + conv
                if h.funding_source:
                    by_funding[h.funding_source] = by_funding.get(h.funding_source, 0.0) + conv
        src["by_asset_class"] = {k: round(v, 2) for k, v in by_asset.items()}
        src["by_funding_source"] = {k: round(v, 2) for k, v in by_funding.items()}

    return src


async def _all_currencies_in_scope(db: AsyncSession, accounts: list[Account]) -> set[str]:
    """Every currency that could appear: account base currencies + the currency
    actually recorded on each external account's latest balances."""
    currencies = {(a.base_currency or "USD").upper() for a in accounts}
    for a in accounts:
        if a.kind in ("cpf", "endowus"):
            for bal in await _latest_balances(db, a.account_id):
                if bal.currency:
                    currencies.add(bal.currency.upper())
    return currencies


async def net_worth(db: AsyncSession, owner: str, target: str) -> dict:
    """Assemble the net-worth payload for `owner` ('all' or a slug)."""
    target = target.upper()
    owners = await owner_map(db)
    if owner == ALL or not owner:
        scopes = [(info.owner, info.label, info.accounts) for info in owners.values()]
    else:
        info = owners.get(owner)
        scopes = [(info.owner, info.label, info.accounts)] if info else []

    all_accounts = [a for _, _, accounts in scopes for a in accounts]
    currencies = await _all_currencies_in_scope(db, all_accounts)
    rates = await _fx_rates(currencies, target)

    owner_payloads = []
    combined_total = 0.0
    combined_ok = True
    for slug, label, accounts in scopes:
        sources: dict[str, dict] = {}
        ibkr = await _ibkr_source(db, accounts, target, rates)
        if ibkr is not None:
            sources["ibkr"] = ibkr
        cpf = await _external_source(db, accounts, "cpf", target, rates)
        if cpf is not None:
            sources["cpf"] = cpf
        endowus = await _external_source(db, accounts, "endowus", target, rates)
        if endowus is not None:
            sources["endowus"] = endowus

        total = 0.0
        for src in sources.values():
            if src.get("converted") is None:
                combined_ok = False
            else:
                total += src["converted"]
        combined_total += total
        owner_payloads.append(
            {
                "owner": slug,
                "label": label,
                "total_converted": round(total, 2),
                "sources": sources,
            }
        )

    return {
        "as_of_generated": datetime.now(timezone.utc).isoformat(),
        "target_currency": target,
        "owners": owner_payloads,
        "combined": {
            "total_converted": round(combined_total, 2) if combined_ok else None,
        },
    }


# --- History + holdings -----------------------------------------------------

def _month_starts(months: int) -> list[date]:
    """First-of-month dates for the last `months` months, oldest -> newest."""
    today = date.today()
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    out.reverse()
    return out


def _month_end(first_of_month: date) -> date:
    y, m = first_of_month.year, first_of_month.month
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1)  # exclusive upper bound; compare with <


async def _ibkr_month_series(
    db: AsyncSession, account_id: str, months: list[date]
) -> list[float | None]:
    rows = await db.execute(
        select(AccountSnapshot.snapshot_ts, AccountSnapshot.net_liquidation)
        .where(AccountSnapshot.account_id == account_id)
        .order_by(AccountSnapshot.snapshot_ts)
    )
    points = [(ts.date(), float(nl)) for ts, nl in rows.all() if ts and nl is not None]
    out: list[float | None] = []
    for start in months:
        upper = _month_end(start)
        val = None
        for d, nl in points:
            if d < upper:
                val = nl
            else:
                break
        out.append(val)
    return out


async def _external_month_series(
    db: AsyncSession, account_id: str, months: list[date]
) -> list[float | None]:
    rows = await db.execute(
        select(ExternalBalance.as_of, ExternalBalance.category, ExternalBalance.balance)
        .where(ExternalBalance.account_id == account_id)
        .order_by(ExternalBalance.as_of)
    )
    data = [(d, cat, float(b)) for d, cat, b in rows.all() if b is not None]
    out: list[float | None] = []
    for start in months:
        upper = _month_end(start)
        # Latest balance per category on/before this month end -> sum.
        latest_per_cat: dict[str, float] = {}
        for d, cat, b in data:
            if d < upper:
                latest_per_cat[cat] = b
        out.append(sum(latest_per_cat.values()) if latest_per_cat else None)
    return out


async def history(db: AsyncSession, owner: str, target: str, months: int) -> dict:
    """Monthly net-worth series stacked by source (FX at current spot)."""
    target = target.upper()
    months = max(1, min(months, 120))
    buckets = _month_starts(months)

    owners = await owner_map(db)
    if owner == ALL or not owner:
        accounts = [a for info in owners.values() for a in info.accounts]
    else:
        info = owners.get(owner)
        accounts = info.accounts if info else []

    currencies = await _all_currencies_in_scope(db, accounts)
    rates = await _fx_rates(currencies, target)

    totals = {
        "ibkr": [0.0] * months,
        "cpf": [0.0] * months,
        "endowus": [0.0] * months,
    }
    for account in accounts:
        ccy = (account.base_currency or "SGD").upper()
        if account.kind == "ibkr":
            series = await _ibkr_month_series(db, account.account_id, buckets)
        elif account.kind in ("cpf", "endowus"):
            series = await _external_month_series(db, account.account_id, buckets)
        else:
            continue
        for i, val in enumerate(series):
            if val is None:
                continue
            conv = _convert(val, ccy, target, rates)
            if conv is not None:
                totals[account.kind][i] += conv

    series_out = []
    for i, start in enumerate(buckets):
        ibkr = round(totals["ibkr"][i], 2)
        cpf = round(totals["cpf"][i], 2)
        endowus = round(totals["endowus"][i], 2)
        series_out.append(
            {
                "month": start.isoformat(),
                "ibkr": ibkr,
                "cpf": cpf,
                "endowus": endowus,
                "total": round(ibkr + cpf + endowus, 2),
            }
        )
    return {"target_currency": target, "series": series_out}


async def holdings(db: AsyncSession, owner: str, target: str) -> dict:
    """Latest Endowus per-fund holdings across the owner scope + goal totals."""
    target = target.upper()
    owners = await owner_map(db)
    if owner == ALL or not owner:
        accounts = [a for info in owners.values() for a in info.accounts]
    else:
        info = owners.get(owner)
        accounts = info.accounts if info else []

    endowus_accounts = [a for a in accounts if a.kind == "endowus"]
    currencies = await _all_currencies_in_scope(db, endowus_accounts)
    rates = await _fx_rates(currencies, target)

    out_holdings = []
    goal_totals: dict[str, float] = {}
    for account in endowus_accounts:
        for h in await _latest_holdings(db, account.account_id):
            ccy = (h.currency or account.base_currency or "SGD").upper()
            mv = float(h.market_value) if h.market_value is not None else None
            converted = _convert(mv, ccy, target, rates) if mv is not None else None
            out_holdings.append(
                {
                    "account_id": account.account_id,
                    "owner": account.owner,
                    "goal_name": h.goal_name,
                    "fund_name": h.fund_name,
                    "asset_class": h.asset_class,
                    "funding_source": h.funding_source,
                    "units": float(h.units) if h.units is not None else None,
                    "nav": float(h.nav) if h.nav is not None else None,
                    "market_value": mv,
                    "converted": round(converted, 2) if converted is not None else None,
                    "allocation_pct": float(h.allocation_pct) if h.allocation_pct is not None else None,
                    "currency": ccy,
                    "as_of": _to_iso(h.as_of),
                }
            )
            if converted is not None and h.goal_name:
                goal_totals[h.goal_name] = goal_totals.get(h.goal_name, 0.0) + converted

    return {
        "target_currency": target,
        "holdings": out_holdings,
        "goal_totals": {k: round(v, 2) for k, v in goal_totals.items()},
    }
