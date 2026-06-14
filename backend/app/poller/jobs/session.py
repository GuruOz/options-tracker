"""Session heartbeat job.

Polls /tickle + /iserver/auth/status, maintains `session_state`, auto-detects
the account, and broadcasts any user-visible change over WebSocket. Treats
DISCONNECTED as a normal, recoverable state (IBKR forces a daily re-auth).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.state import GatewayStatus, broadcast_session, session_state
from app.db.base import AsyncSessionLocal
from app.db.models import Account

log = get_logger("poller.session")
_settings = get_settings()

_RE_AUTH_MSG = (
    "Gateway disconnected — re-authenticate (approve the IBKR push if prompted)."
)


async def _detect_account(client: IBKRClient) -> str | None:
    if _settings.ibkr_account_id:
        return _settings.ibkr_account_id
    try:
        accounts = await client.iserver_accounts()
        selected = accounts.get("selectedAccount")
        if selected:
            return selected
        ids = accounts.get("accounts") or []
        if ids:
            return ids[0]
    except (IBKRError, IBKRAuthError):
        return None
    return None


async def _persist_account(account_id: str) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Account)
            .values(account_id=account_id)
            .on_conflict_do_nothing(index_elements=["account_id"])
        )
        await session.execute(stmt)
        await session.commit()


async def heartbeat(client: IBKRClient) -> None:
    changed = False
    try:
        await client.tickle()
        status = await client.auth_status()
        authenticated = bool(status.get("authenticated"))
        connected = bool(status.get("connected"))
        competing = bool(status.get("competing"))

        if authenticated and connected:
            account_id = session_state.account_id or await _detect_account(client)
            if account_id and account_id != session_state.account_id:
                await _persist_account(account_id)
            changed = session_state.update(
                status=GatewayStatus.AUTHENTICATED,
                authenticated=True,
                connected=connected,
                competing=competing,
                account_id=account_id,
                message="Connected to IBKR.",
            )
        elif competing:
            try:
                await client.reauthenticate()
            except (IBKRError, IBKRAuthError):
                pass
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                competing=True,
                message="Competing session detected — re-authenticating.",
            )
        else:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                connected=connected,
                message=_RE_AUTH_MSG,
            )
    except IBKRAuthError:
        changed = session_state.update(
            status=GatewayStatus.DISCONNECTED,
            authenticated=False,
            message="Gateway not authenticated yet — awaiting login/2FA.",
        )
    except IBKRError as exc:
        changed = session_state.update(
            status=GatewayStatus.DISCONNECTED,
            authenticated=False,
            message=f"Gateway unreachable: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — defensive: never let the job die
        log.warning("heartbeat_unexpected_error", error=str(exc))
        changed = session_state.update(
            status=GatewayStatus.DISCONNECTED,
            message="Gateway unreachable.",
        )

    if changed:
        log.info("session_state_changed", **session_state.to_dict())
        await broadcast_session()
