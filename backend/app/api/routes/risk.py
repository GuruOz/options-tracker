"""Portfolio risk endpoint: beta-weighted stress move + assignment coverage."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.risk import compute_risk
from app.api.deps import account_scope
from app.db import repo
from app.db.base import get_session
from app.db.models import Setting
from app.schemas.responses import RiskOut

router = APIRouter(tags=["risk"])


async def _risk_for(db: AsyncSession, account_id: str, settings: dict | None) -> dict:
    positions = await repo.latest_positions(db, account_id)
    # Use the latest *priced* snapshot per symbol so a transient empty IBKR poll
    # (price=None) can't shadow a good spot and skew the beta-weighted scenario.
    markets = await repo.latest_priced_market(db)
    account = await repo.latest_account(db, account_id)
    acct_row = await repo.account_by_id(db, account_id)

    result = compute_risk(
        positions, markets, account, settings,
        account_currency=acct_row.base_currency if acct_row else None,
    )
    result["equity_curve"] = await repo.account_series(db, account_id)
    return result


def _combine(per_account: list[dict]) -> dict:
    """Sum the household's exposure across accounts.

    Dollar exposures add up cleanly. Two caveats the UI states plainly:
    assignment coverage pools cash that isn't actually fungible across accounts,
    and the equity curves are NOT summed — each account's snapshots land on its
    own timestamps, so they are returned separately for the chart to overlay.
    """
    def total(key: str, source: list[dict]) -> float | None:
        vals = [r[key] for r in source if r.get(key) is not None]
        return sum(vals) if vals else None

    first = per_account[0]
    net_liq = total("net_liquidation", per_account)
    scenario_pnl = total("scenario_pnl", per_account)

    # A mismatch anywhere (one account's own position/base currencies
    # disagreeing, or two accounts simply having different base currencies)
    # taints any ratio built from the combined total.
    currencies = {r.get("exposure_currency") for r in per_account if r.get("exposure_currency")}
    currency_mismatch = (
        any(r.get("currency_mismatch") for r in per_account) or len(currencies) > 1
    )

    obligations = [r["assignment"] for r in per_account if r.get("assignment")]
    combined_assignment = {
        "total_obligation": total("total_obligation", obligations),
        "cash": total("cash", obligations),
        "coverage_ratio": None,
        "short_put_count": sum(a.get("short_put_count", 0) or 0 for a in obligations),
    }
    obligation = combined_assignment["total_obligation"]
    cash = combined_assignment["cash"]
    if obligation and cash is not None and not currency_mismatch:
        combined_assignment["coverage_ratio"] = cash / obligation

    return {
        "scenario_move": first["scenario_move"],
        "index_symbol": first.get("index_symbol"),
        "net_liquidation": net_liq,
        "beta_weighted_delta_dollars": total("beta_weighted_delta_dollars", per_account),
        "gross_delta_dollars": total("gross_delta_dollars", per_account),
        "scenario_pnl": scenario_pnl,
        "scenario_pnl_pct": (
            scenario_pnl / net_liq
            if scenario_pnl is not None and net_liq and not currency_mismatch
            else None
        ),
        "currency_mismatch": currency_mismatch,
        "exposure_currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "assignment": combined_assignment,
        "positions": [p for r in per_account for p in r.get("positions", [])],
        "equity_curve": [],
    }


@router.get("/risk")
async def get_risk(
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
) -> dict | None:
    settings_row = await db.get(Setting, 1)
    settings = settings_row.data if settings_row else None

    if not accounts:
        return None
    if len(accounts) == 1:
        return RiskOut.model_validate(await _risk_for(db, accounts[0], settings)).model_dump()

    labels = await repo.account_labels(db)
    per_account = []
    for account_id in accounts:
        result = await _risk_for(db, account_id, settings)
        result["account_id"] = account_id
        result["account_label"] = labels.get(account_id, account_id)
        per_account.append(result)

    combined = _combine(per_account)
    combined["per_account"] = per_account
    return combined
