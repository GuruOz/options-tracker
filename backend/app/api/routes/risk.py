"""Portfolio risk endpoint: beta-weighted stress move + assignment coverage."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.risk import compute_risk
from app.api.deps import account_scope
from app.core import fx
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
    base_ccy = acct_row.base_currency if acct_row else None

    # Rates turning each position currency into the account's base currency let
    # compute_risk compute (rather than suppress) cross-currency ratios.
    pos_ccys = {p.currency for p in positions if p.currency}
    pairs = {(c, base_ccy) for c in pos_ccys if base_ccy and c != base_ccy}
    rates = await fx.rate_map(pairs)

    result = compute_risk(
        positions, markets, account, settings,
        account_currency=base_ccy,
        fx_rates={k: r.rate for k, r in rates.items()},
    )
    result["base_currency"] = base_ccy
    result["fx_rates"] = [r.as_dict() for r in rates.values()]
    result["equity_curve"] = await repo.account_series(db, account_id)
    return result


def _combine(
    per_account: list[dict],
    display_currency: str | None = None,
    rates: dict[str, float] | None = None,
    fx_used: list[dict] | None = None,
) -> dict:
    """Sum the household's exposure across accounts.

    When `rates` (source currency -> `display_currency`) covers every currency
    backing a figure, each account's values are converted before summing and
    the ratios are computed in the display currency. Missing rates degrade to
    the old behavior: raw sums with cross-currency ratios suppressed. Two
    caveats the UI states plainly either way: assignment coverage pools cash
    that isn't actually fungible across accounts, and the equity curves are
    NOT summed — each account's snapshots land on its own timestamps, so they
    are returned separately for the chart to overlay.
    """
    rates = rates or {}

    def base_ccy(r: dict) -> str | None:
        return r.get("base_currency")

    def exp_ccy(r: dict) -> str | None:
        # Position-derived figures are in the exposure currency when known;
        # an account whose book didn't report one falls back to its base.
        return r.get("exposure_currency") or r.get("base_currency")

    # Currencies actually backing a non-None figure; conversion happens only
    # when every one of them has a rate.
    needed: set[str] = set()
    for r in per_account:
        a = r.get("assignment") or {}
        if base_ccy(r) and (
            r.get("net_liquidation") is not None or a.get("cash") is not None
        ):
            needed.add(base_ccy(r))
        if exp_ccy(r) and (
            a.get("total_obligation") is not None
            or any(
                r.get(k) is not None
                for k in ("scenario_pnl", "beta_weighted_delta_dollars", "gross_delta_dollars")
            )
        ):
            needed.add(exp_ccy(r))
    # A book that mixes currencies within one account has no single exposure
    # currency, so no one rate converts its figures — that account poisons the
    # conversion (unlike an account that simply didn't record a currency).
    ambiguous = any(
        r.get("currency_mismatch") and not r.get("exposure_currency") for r in per_account
    )
    convertible = bool(display_currency) and not ambiguous and needed <= rates.keys()

    def cv(value: float | None, ccy: str | None) -> float | None:
        # An account with no recorded currency counts as already-in-display —
        # unknown isn't evidence of a mismatch (compute_risk's stance too).
        if value is None:
            return None
        if not convertible or ccy is None:
            return float(value)
        return float(value) * rates[ccy]

    def total(values: list[float | None]) -> float | None:
        vals = [v for v in values if v is not None]
        return sum(vals) if vals else None

    first = per_account[0]
    net_liq = total([cv(r.get("net_liquidation"), base_ccy(r)) for r in per_account])
    scenario_pnl = total([cv(r.get("scenario_pnl"), exp_ccy(r)) for r in per_account])

    # A mismatch anywhere (one account's own position/base currencies
    # disagreeing, or two accounts simply having different base currencies)
    # taints any ratio built from the combined total — unless everything was
    # converted into one display currency above.
    currencies = {r.get("exposure_currency") for r in per_account if r.get("exposure_currency")}
    currency_mismatch = (
        any(r.get("currency_mismatch") for r in per_account) or len(currencies) > 1
    )
    ratios_ok = convertible or not currency_mismatch

    assignments = [(r, r.get("assignment") or {}) for r in per_account]
    combined_assignment = {
        "total_obligation": total([cv(a.get("total_obligation"), exp_ccy(r)) for r, a in assignments]),
        "cash": total([cv(a.get("cash"), base_ccy(r)) for r, a in assignments]),
        "coverage_ratio": None,
        "short_put_count": sum(a.get("short_put_count", 0) or 0 for _, a in assignments),
    }
    obligation = combined_assignment["total_obligation"]
    cash = combined_assignment["cash"]
    if obligation and cash is not None and ratios_ok:
        combined_assignment["coverage_ratio"] = cash / obligation

    return {
        "scenario_move": first["scenario_move"],
        "index_symbol": first.get("index_symbol"),
        "net_liquidation": net_liq,
        "beta_weighted_delta_dollars": total(
            [cv(r.get("beta_weighted_delta_dollars"), exp_ccy(r)) for r in per_account]
        ),
        "gross_delta_dollars": total(
            [cv(r.get("gross_delta_dollars"), exp_ccy(r)) for r in per_account]
        ),
        "scenario_pnl": scenario_pnl,
        "scenario_pnl_pct": (
            scenario_pnl / net_liq
            if scenario_pnl is not None and net_liq and ratios_ok
            else None
        ),
        "currency_mismatch": currency_mismatch,
        "exposure_currency": (
            display_currency if convertible
            else next(iter(currencies)) if len(currencies) == 1 else None
        ),
        "display_currency": display_currency if convertible else None,
        "fx_rates": (fx_used or []) if convertible else [],
        "assignment": combined_assignment,
        "positions": [p for r in per_account for p in r.get("positions", [])],
        "equity_curve": [],
    }


@router.get("/risk")
async def get_risk(
    currency: str = Query("USD", pattern=r"^[A-Z]{3}$"),
    accounts: list[str] = Depends(account_scope),
    db: AsyncSession = Depends(get_session),
) -> dict | None:
    """`currency` is the display currency for the combined household view only;
    a single account always reports in its own currencies."""
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

    # One rate per source currency into the display currency (identity pairs
    # resolve to 1.0), so _combine can convert before summing.
    ccys = {c for r in per_account for c in (r.get("base_currency"), r.get("exposure_currency")) if c}
    display_rates = await fx.rate_map({(c, currency) for c in ccys})
    combined = _combine(
        per_account,
        display_currency=currency,
        rates={src: r.rate for (src, _dst), r in display_rates.items()},
        fx_used=[r.as_dict() for r in display_rates.values() if r.source != "identity"],
    )
    combined["per_account"] = per_account
    return combined
