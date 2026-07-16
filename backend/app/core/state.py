"""In-memory gateway/session state plus a WebSocket broadcast manager.

Session lifecycle is user-driven: login → pull data → browse → manual logout.
No background keep-alive (no tickle, no auto-reauthenticate). A passive monitor
releases any stray authenticated session for mobile.

Multi-user: one `SessionState` per declared gateway, held in the `registry`.
States are strictly independent — one user's gateway going down, authenticating,
or being released must never move another's.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum


class GatewayStatus(str, Enum):
    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"
    AUTHENTICATED = "authenticated"
    PULLING = "pulling"
    LOGGING_IN = "logging_in"


@dataclass
class SessionState:
    gateway_id: str = "user1"
    label: str = "Primary"
    status: GatewayStatus = GatewayStatus.UNKNOWN
    authenticated: bool = False
    connected: bool = False
    competing: bool = False
    account_id: str | None = None
    message: str = "Starting up."
    last_checked: str | None = None
    user_logged_in: bool = False
    last_pull: str | None = None
    pull_source: str | None = None
    # ISO timestamp of the last user-initiated login click. Lets the passive
    # monitor distinguish a late-completing user login (to adopt) from a stray
    # session (to release) within a short window.
    login_requested_at: str | None = None

    def update(self, **changes) -> bool:
        """Apply changes; return True if anything user-visible changed."""
        before = (
            self.status, self.authenticated, self.connected,
            self.competing, self.account_id, self.message,
            self.user_logged_in, self.last_pull, self.pull_source,
        )
        for key, value in changes.items():
            setattr(self, key, value)
        self.last_checked = datetime.now(timezone.utc).isoformat()
        after = (
            self.status, self.authenticated, self.connected,
            self.competing, self.account_id, self.message,
            self.user_logged_in, self.last_pull, self.pull_source,
        )
        return before != after

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class SessionRegistry:
    """Every declared gateway's live session state, keyed by gateway_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def register(self, gateway_id: str, label: str) -> SessionState:
        state = SessionState(gateway_id=gateway_id, label=label)
        self._sessions[gateway_id] = state
        return state

    def get(self, gateway_id: str) -> SessionState | None:
        return self._sessions.get(gateway_id)

    def all(self) -> list[SessionState]:
        return list(self._sessions.values())

    def by_account(self, account_id: str) -> SessionState | None:
        for state in self._sessions.values():
            if state.account_id == account_id:
                return state
        return None

    def any_logged_in(self) -> bool:
        return any(s.user_logged_in for s in self._sessions.values())

    def to_dict(self) -> dict[str, dict]:
        return {gid: s.to_dict() for gid, s in self._sessions.items()}

    def clear(self) -> None:
        self._sessions.clear()


registry = SessionRegistry()


class ConnectionManager:
    """Tracks open WebSocket clients and fans out JSON messages to them."""

    def __init__(self) -> None:
        self.active: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    def disconnect(self, ws) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def broadcast_session(state: SessionState) -> None:
    await manager.broadcast({
        "type": "session",
        "gateway_id": state.gateway_id,
        "data": state.to_dict(),
    })


async def broadcast_event(resource: str, account_id: str | None = None) -> None:
    """Notify clients that a data resource changed so they can refetch.

    `account_id` is None for market-wide resources (market/signals), which are
    conid-keyed and shared by every account.
    """
    await manager.broadcast({
        "type": "data",
        "resource": resource,
        "account_id": account_id,
    })
