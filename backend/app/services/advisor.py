"""AI advisor: BYO-key suggested-moves generation.

Assembles an *anonymized* financial summary (no account ids, gateway labels, or
personal names) and asks the user's chosen model (Anthropic or any
OpenAI-compatible endpoint) for prioritized, Singapore + US-aware suggestions.
The output is framed as educational information, not financial advice.

The API key is stored Fernet-encrypted (see `_fernet`) and never leaves the
server in plaintext or in any API response.
"""
from __future__ import annotations

import base64
import hashlib

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.income import compute_income
from app.core import fx
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import repo
from app.services import networth as nw

log = get_logger("services.advisor")

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"


# --- key encryption ---------------------------------------------------------

def _fernet() -> Fernet:
    """A Fernet key derived from a stable per-deployment secret. Uses the auth
    password hash as key material so no new secret needs configuring; rotating
    the password invalidates a stored key (the user just re-enters it)."""
    settings = get_settings()
    material = (settings.auth_password_hash or "options-tracker-fallback").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
    return Fernet(key)


def encrypt_key(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_key(token: bytes) -> str | None:
    try:
        return _fernet().decrypt(token).decode()
    except (InvalidToken, ValueError):
        return None


# --- anonymized summary -----------------------------------------------------

async def _options_premium_all_time(db: AsyncSession, accounts, target: str) -> float | None:
    """Best-effort household options premium (all-time), converted to target."""
    total = 0.0
    seen = False
    for a in accounts:
        if a.kind != "ibkr":
            continue
        try:
            chains = await repo.all_roll_chains(db, a.account_id)
            adj = await repo.income_adjustments(db, a.account_id)
            summary = compute_income(chains, adj, net_liquidation=None)
            val = summary.get("all_time")
            if val is None:
                continue
            rate = await fx.get_rate((a.base_currency or "USD"), target)
            if rate is None:
                continue
            total += float(val) * rate.rate
            seen = True
        except Exception as exc:  # noqa: BLE001 — advisor context is best-effort
            log.debug("options_premium_failed", account=a.account_id, error=str(exc))
    return round(total, 2) if seen else None


async def build_summary(db: AsyncSession, owner: str, target: str = "SGD") -> dict:
    """Anonymized household financial snapshot for the model.

    Deliberately omits account ids, gateway/account labels, and person names —
    only aggregate figures and asset/funding mixes (fund names are public).
    """
    net = await nw.net_worth(db, owner, target)

    # Fold sources across owners so no per-person labels leak.
    by_source: dict[str, float] = {}
    cpf_breakdown: dict[str, float] = {}
    endowus_assets: dict[str, float] = {}
    endowus_funding: dict[str, float] = {}
    for o in net["owners"]:
        for kind, src in o["sources"].items():
            if src.get("converted") is not None:
                by_source[kind] = by_source.get(kind, 0.0) + src["converted"]
            for c, v in (src.get("breakdown") or {}).items():
                if kind == "cpf":
                    cpf_breakdown[c] = cpf_breakdown.get(c, 0.0) + v
            for c, v in (src.get("by_asset_class") or {}).items():
                endowus_assets[c] = endowus_assets.get(c, 0.0) + v
            for c, v in (src.get("by_funding_source") or {}).items():
                endowus_funding[c] = endowus_funding.get(c, 0.0) + v

    accounts = [a for info in (await nw.owner_map(db)).values() for a in info.accounts]
    if owner not in ("all", "", None):
        info = (await nw.owner_map(db)).get(owner)
        accounts = info.accounts if info else []

    plan = await repo_plan_settings(db, owner)
    cashflow = await repo_latest_cashflow(db, owner)

    return {
        "currency": target,
        "net_worth_total": net["combined"]["total_converted"],
        "net_worth_by_source": {k: round(v, 2) for k, v in by_source.items()},
        "cpf_balances": {k: round(v, 2) for k, v in cpf_breakdown.items()},
        "endowus_by_asset_class": {k: round(v, 2) for k, v in endowus_assets.items()},
        "endowus_by_funding_source": {k: round(v, 2) for k, v in endowus_funding.items()},
        "options_premium_all_time": await _options_premium_all_time(db, accounts, target),
        "fire": plan,
        "monthly_cashflow": cashflow,
        "num_people": len(net["owners"]),
    }


async def repo_plan_settings(db: AsyncSession, owner: str) -> dict | None:
    from app.db.models import PlanSettings
    row = await db.get(PlanSettings, owner if owner not in ("", None) else "household")
    if row is None:
        row = await db.get(PlanSettings, "household")
    return row.data if row else None


async def repo_latest_cashflow(db: AsyncSession, owner: str) -> dict | None:
    from sqlalchemy import desc, select
    from app.db.models import CashflowEntry
    key = owner if owner not in ("", None) else "household"
    rows = await db.execute(
        select(CashflowEntry)
        .where(CashflowEntry.owner == key)
        .order_by(desc(CashflowEntry.month))
        .limit(1)
    )
    e = rows.scalar_one_or_none()
    if e is None:
        return None
    income = float(e.income) if e.income is not None else None
    expenses = float(e.expenses) if e.expenses is not None else None
    savings = income - expenses if income is not None and expenses is not None else None
    return {"income": income, "expenses": expenses, "savings": savings}


# --- prompt + LLM call ------------------------------------------------------

_SYSTEM = """You are a financial-education assistant for a Singapore-based \
household with US market exposure. You produce concise, prioritized "suggested \
moves" as Markdown.

Important framing:
- This is educational information, NOT personalised financial advice. Begin your \
response with a one-line disclaimer to that effect.
- Consider Singapore context: CPF (OA ~2.5%, SA ~4%+ floors), CPF top-ups and \
their tax relief and ceilings, SRS for tax relief, and typical emergency-fund \
guidance.
- Consider US-exposure context for a non-US person: Ireland-domiciled UCITS ETFs \
reduce dividend withholding tax (15% treaty vs 30% on US-domiciled funds) and \
mitigate US estate-tax exposure on US-situs assets.
- Base every suggestion on the figures provided. Give each a one-line rationale. \
Order by likely impact. Keep it under ~400 words.
"""


def _user_prompt(summary: dict) -> str:
    import json
    return (
        "Here is an anonymized snapshot of the household's finances (amounts in "
        f"{summary.get('currency')}). Suggest prioritized moves.\n\n"
        + json.dumps(summary, indent=2)
    )


async def _generate_anthropic(api_key: str, model: str, summary: dict) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key, timeout=60.0)
    msg = await client.messages.create(
        model=model or DEFAULT_ANTHROPIC_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{"role": "user", "content": _user_prompt(summary)}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


async def _generate_openai_compat(
    api_key: str, base_url: str, model: str, summary: dict
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _user_prompt(summary)},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def generate(
    provider: str, api_key: str, base_url: str | None, model: str | None, summary: dict
) -> str:
    if provider == "anthropic":
        return await _generate_anthropic(api_key, model or DEFAULT_ANTHROPIC_MODEL, summary)
    if provider == "openai_compat":
        if not base_url:
            raise ValueError("base_url is required for an OpenAI-compatible provider.")
        return await _generate_openai_compat(api_key, base_url, model or "gpt-4o", summary)
    raise ValueError(f"Unknown provider '{provider}'.")
