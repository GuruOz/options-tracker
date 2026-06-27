"""Session monitor + user-initiated login/logout orchestrator.

Default mode: passive monitor observes auth_status only — never tickles or
reauthenticates. If a stray authenticated session appears (e.g. from IBEAM
startup) it is immediately released so the IBKR mobile app stays connected.

User-initiated login: restarts the IBEAM container to trigger browser login,
polls auth_status until 2FA is approved, batch-pulls all data, and leaves the
session active for browsing. Manual logout ends it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import docker

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.state import (
    GatewayStatus,
    broadcast_event,
    broadcast_session,
    session_state,
)
from app.db import repo
from app.db.base import AsyncSessionLocal
from app.db.models import (
    Account,
    AccountSnapshot,
    Execution,
    MarketSnapshot,
    PositionSnapshot,
)

log = get_logger("poller.session")
_settings = get_settings()

_MONITOR_MSG = "Logged out — session released for IBKR mobile."
_COMPETING_MSG = "Competing session detected (likely mobile) — backing off."

_COLUMNS_TRADES = {
    "exec_id", "account_id", "conid", "symbol", "sec_type", "side", "right",
    "strike", "expiry", "qty", "price", "commission", "realized_pnl",
    "exec_time", "source", "raw",
}


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


async def _persist_pull_result(pull: dict, account_id: str) -> None:
    """Write the batch-pull result to the database."""
    ts = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:

        positions = pull.get("positions", {})
        if positions.get("status") == "ok":
            objs: list[PositionSnapshot] = []
            greeks = positions.get("greeks") or {}
            for n in positions.get("rows", []):
                if n.get("conid") is None:
                    continue
                g = greeks.get(n["conid"])
                snap = PositionSnapshot(
                    account_id=account_id,
                    snapshot_ts=ts,
                    conid=n["conid"],
                    sec_type=n.get("sec_type"),
                    symbol=n.get("symbol"),
                    right=n.get("right"),
                    strike=n.get("strike"),
                    expiry=n.get("expiry"),
                    position=n.get("position"),
                    avg_cost=n.get("avg_cost"),
                    mark=n.get("mark"),
                    market_value=n.get("market_value"),
                    unrealized_pnl=n.get("unrealized_pnl"),
                    raw=n.get("raw"),
                )
                if g and g.get("has_greeks"):
                    snap.greeks_source = "ibkr"
                    for fld in ("delta", "gamma", "theta", "vega", "iv"):
                        setattr(snap, fld, g.get(fld))
                    if g.get("mark") is not None:
                        snap.mark = g["mark"]
                objs.append(snap)
            if objs:
                session.add_all(objs)
                await session.flush()

        account = pull.get("account", {})
        if account.get("status") == "ok":
            n = account["summary"]
            session.add(AccountSnapshot(
                account_id=account_id,
                snapshot_ts=ts,
                net_liquidation=n.get("net_liquidation"),
                available_funds=n.get("available_funds"),
                excess_liquidity=n.get("excess_liquidity"),
                maintenance_margin=n.get("maintenance_margin"),
                buying_power=n.get("buying_power"),
                leverage=n.get("leverage"),
                cash=n.get("cash"),
                raw=account.get("raw"),
            ))

        trades = pull.get("trades", {})
        if trades.get("status") == "ok":
            values = []
            for t in trades.get("rows", []):
                if not t.get("exec_id"):
                    continue
                values.append({k: v for k, v in t.items() if k in _COLUMNS_TRADES})
            if values:
                # Poll feed: skip option fills an authoritative feed already has.
                await repo.insert_poll_executions(session, values, account_id)

        market = pull.get("market", {})
        if market.get("status") == "ok":
            for q in market.get("rows", []):
                if q.get("conid") is None:
                    continue
                session.add(MarketSnapshot(
                    conid=q["conid"],
                    symbol=q.get("symbol"),
                    snapshot_ts=ts,
                    price=q.get("price"),
                    iv=q.get("iv"),
                    source="ibkr",
                    raw=q,
                ))

        await session.commit()


async def monitor(client: IBKRClient) -> None:
    """Passive gatekeeper: checks auth_status, releases stray sessions.

    NEVER calls tickle() or reauthenticate(). If the gateway is authenticated
    but no user is logged in, it calls logout() so the IBKR mobile app stays
    connected. Skips logout during LOGGING_IN or PULLING (login in progress).
    """
    changed = False
    try:
        status = await client.auth_status()
        authenticated = bool(status.get("authenticated"))
        connected = bool(status.get("connected"))
        competing = bool(status.get("competing"))

        login_in_progress = session_state.status in (
            GatewayStatus.LOGGING_IN, GatewayStatus.PULLING
        )

        if login_in_progress:
            return

        if authenticated and not session_state.user_logged_in:
            if _recent_login_intent():
                # The user just tried to log in and the gateway authenticated —
                # likely a 2FA push approved after the login request already
                # returned/timed out. Adopt the session instead of releasing it
                # (which is what would otherwise log the user straight back out).
                log.info("monitor_adopting_late_login")
                try:
                    await _finalize_authenticated_session(client)
                except Exception as exc:
                    log.warning("monitor_adopt_failed", error=str(exc))
                return  # finalize already broadcast the new state
            try:
                await client.logout()
                log.info("monitor_logged_out_stray_session")
            except (IBKRError, IBKRAuthError):
                pass
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                connected=connected,
                message=_MONITOR_MSG,
            )
        elif competing and not session_state.user_logged_in:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                competing=True,
                message=_COMPETING_MSG,
            )
        elif session_state.user_logged_in and not authenticated:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                connected=connected,
                message="Session lost — log in again to pull fresh data.",
            )
        elif not session_state.user_logged_in:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                connected=connected,
                message=_MONITOR_MSG,
            )
    except IBKRAuthError:
        if not session_state.user_logged_in:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                message=_MONITOR_MSG,
            )
    except IBKRError as exc:
        if not session_state.user_logged_in:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                message=f"Gateway unreachable: {exc}",
            )
    except Exception as exc:
        log.warning("monitor_unexpected_error", error=str(exc))
        if not session_state.user_logged_in:
            changed = session_state.update(
                status=GatewayStatus.DISCONNECTED,
                message="Gateway unreachable.",
            )

    if changed:
        log.info("session_state_changed", **session_state.to_dict())
        await broadcast_session()


# How long after a login click the monitor will still ADOPT a freshly
# authenticated gateway as the user's session (rather than releasing it). Covers
# the case where the user approves the 2FA push after the HTTP login request has
# already returned/timed out.
_LOGIN_ADOPT_WINDOW_SECONDS = 300


def _recent_login_intent(window_seconds: int = _LOGIN_ADOPT_WINDOW_SECONDS) -> bool:
    """True if the user clicked "Pull Fresh Data" within `window_seconds`."""
    ts = session_state.login_requested_at
    if not ts:
        return False
    try:
        requested = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - requested).total_seconds() <= window_seconds


def _restart_ibeam(container: str) -> str | None:
    """Restart the IBEAM container so it re-runs login and pushes a FRESH MFA.

    A plain start() on an already-running container is a no-op and would NOT
    trigger a new login attempt — so a user who missed the first 2FA push could
    never get another. IBEAM also gives up after one failed auth
    (RESTART_FAILED_SESSIONS=false, MAX_FAILED_AUTH=1), leaving the process
    idle. Restarting forces a clean login flow every time the user clicks.

    Returns an error message on failure, else None.
    """
    try:
        docker_client = docker.from_env()
        obj = docker_client.containers.get(container)
    except docker.errors.NotFound:
        log.error("docker_container_not_found", container=container)
        return f"Container {container} not found."
    except docker.errors.DockerException as exc:
        log.error("docker_connect_failed", error=str(exc))
        return f"Docker unavailable: {exc}"

    try:
        # restart() handles both running and stopped containers.
        obj.restart(timeout=10)
        log.info("ibeam_restarted", container=container)
        return None
    except docker.errors.APIError as exc:
        # Fallback for edge states (e.g. created-but-never-started).
        log.warning("ibeam_restart_failed_trying_start", error=str(exc))
        try:
            obj.start()
            log.info("ibeam_started_fallback", container=container)
            return None
        except docker.errors.DockerException as exc2:
            log.error("docker_start_failed", error=str(exc2))
            return f"Docker start failed: {exc2}"


async def _await_authentication(client: IBKRClient, timeout: float) -> bool:
    """Poll auth_status until authenticated or timeout (+ a slower grace period)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last_logged: dict = {}
    while loop.time() < deadline:
        try:
            status = await client.auth_status()
            authenticated = bool(status.get("authenticated"))
            connected = bool(status.get("connected"))
            competing = bool(status.get("competing"))

            cur = {"authenticated": authenticated, "connected": connected, "competing": competing}
            if cur != last_logged:
                log.info("auth_poll", **cur)
                last_logged = cur

            if authenticated:
                return True
            if connected and not authenticated:
                try:
                    await client.reauthenticate()
                except (IBKRError, IBKRAuthError):
                    pass
            if competing:
                session_state.update(
                    competing=True,
                    message="Competing session detected — logging in may interrupt mobile.",
                )
                await broadcast_session()
        except (IBKRError, IBKRAuthError):
            pass
        except Exception as exc:
            log.warning("auth_poll_error", error=str(exc))
        await asyncio.sleep(2)

    grace = 30
    session_state.update(
        message=f"Still waiting for 2FA approval ({grace}s grace period)...",
    )
    await broadcast_session()
    deadline2 = loop.time() + grace
    while loop.time() < deadline2:
        try:
            status = await client.auth_status()
            if bool(status.get("authenticated")):
                return True
        except (IBKRError, IBKRAuthError):
            pass
        await asyncio.sleep(5)
    return False


async def _finalize_authenticated_session(client: IBKRClient) -> dict:
    """Shared post-auth path: detect account, batch-pull + persist, mark logged in.

    Used both by the synchronous login and by the monitor when it adopts a
    session that authenticated after the HTTP login request already returned.
    """
    account_id = await _detect_account(client)
    if not account_id:
        session_state.update(
            status=GatewayStatus.DISCONNECTED,
            authenticated=False,
            message="Login succeeded but no account found.",
        )
        await broadcast_session()
        return {"status": "error", "message": "No account detected."}

    await _persist_account(account_id)
    session_state.update(
        status=GatewayStatus.PULLING,
        authenticated=True,
        account_id=account_id,
        message="Authenticated — pulling data...",
    )
    await broadcast_session()

    pull = await client.pull_all(account_id)
    await _persist_pull_result(pull, account_id)

    flex_token = _settings.ibkr_flex_token
    flex_query = _settings.ibkr_flex_query_id
    if flex_token and flex_query:
        try:
            from app.clients.ibkr.flex_web import fetch_flex_trades
            log.info("flex_web_request")
            flex_trades = await fetch_flex_trades(flex_token, flex_query)
            if flex_trades:
                for t in flex_trades:
                    t["account_id"] = account_id
                async with AsyncSessionLocal() as session:
                    stmt = (
                        pg_insert(Execution)
                        .values(flex_trades)
                        .on_conflict_do_nothing(index_elements=["exec_id"])
                    )
                    result = await session.execute(stmt)
                    await session.commit()
                    flex_count = result.rowcount
                log.info("flex_web_import", parsed=len(flex_trades), inserted=flex_count)
        except Exception as exc:
            log.warning("flex_web_failed", error=str(exc))

    session_state.update(
        status=GatewayStatus.AUTHENTICATED,
        authenticated=True,
        connected=True,
        account_id=account_id,
        user_logged_in=True,
        last_pull=pull["pull_ts"],
        pull_source="ibkr_live",
        login_requested_at=None,  # consumed
        message="Connected to IBKR — data is live.",
    )
    await broadcast_session()

    # Re-anchor the startup burst to now so the data jobs poll rapidly right
    # after login (the burst is otherwise tied to backend boot time).
    try:
        from app.poller.scheduler import rearm_burst
        rearm_burst(_settings)
    except Exception as exc:  # never let scheduling break the login
        log.warning("rearm_burst_failed", error=str(exc))

    for resource in ("positions", "account", "trades", "market", "signals"):
        await broadcast_event(resource)

    return {
        "status": "ok",
        "account_id": account_id,
        "pull_ts": pull["pull_ts"],
        "positions": pull["positions"]["status"],
        "account": pull["account"]["status"],
        "trades": pull["trades"]["status"],
        "market": pull["market"]["status"],
    }


async def orchestrate_login(client: IBKRClient) -> dict:
    """User-initiated login: restart IBEAM, poll auth, batch-pull, persist.

    Returns a result dict with per-resource status and timestamps. If the user
    approves the 2FA push after this request times out, the passive monitor
    adopts the session automatically (see `_recent_login_intent`).
    """
    container = _settings.docker_ibeam_container
    timeout = _settings.pull_login_timeout_seconds

    try:
        session_state.update(
            status=GatewayStatus.LOGGING_IN,
            competing=False,
            login_requested_at=datetime.now(timezone.utc).isoformat(),
            message="Starting gateway container — stand by for 2FA notification...",
        )
        await broadcast_session()

        err = _restart_ibeam(container)
        if err:
            session_state.update(
                status=GatewayStatus.DISCONNECTED, authenticated=False, message=err,
            )
            await broadcast_session()
            return {"status": "error", "message": err}

        session_state.update(
            message="Gateway starting — awaiting 2FA approval in IBKR mobile...",
        )
        await broadcast_session()

        if not await _await_authentication(client, timeout):
            session_state.update(
                status=GatewayStatus.DISCONNECTED,
                authenticated=False,
                message="Login timed out waiting for 2FA. If you approve the push "
                        "now, data will load automatically; otherwise click "
                        "Pull Fresh Data to send a new request.",
            )
            await broadcast_session()
            return {"status": "timeout", "message": "2FA not approved within timeout."}

        return await _finalize_authenticated_session(client)

    except Exception as exc:
        log.error("orchestrate_login_failed", error=str(exc))
        session_state.update(
            status=GatewayStatus.DISCONNECTED,
            authenticated=False,
            login_requested_at=None,
            message=f"Login failed: {exc}",
        )
        try:
            await client.logout()
        except Exception:
            pass
        await broadcast_session()
        return {"status": "error", "message": str(exc)}


async def orchestrate_logout(client: IBKRClient) -> dict:
    """User-initiated logout: release the session for IBKR mobile."""
    try:
        await client.logout()
        log.info("orchestrate_logout_ok")
    except (IBKRError, IBKRAuthError):
        log.warning("logout_call_failed_continuing")
    except Exception as exc:
        log.error("logout_unexpected", error=str(exc))

    session_state.update(
        status=GatewayStatus.DISCONNECTED,
        authenticated=False,
        user_logged_in=False,
        competing=False,
        login_requested_at=None,  # clear intent so the monitor won't re-adopt
        message="Logged out — session released for IBKR mobile.",
    )
    await broadcast_session()
    return {"status": "ok", "message": "Logged out."}
