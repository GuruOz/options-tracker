"""In-memory gateway/session state plus a WebSocket broadcast manager.

The session lifecycle (see README) treats DISCONNECTED as a normal recurring
state. The poller updates `session_state` and broadcasts changes so the UI can
show a clear re-authenticate banner without polling the backend.
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
    POLLING = "polling"


@dataclass
class SessionState:
    status: GatewayStatus = GatewayStatus.UNKNOWN
    authenticated: bool = False
    connected: bool = False
    competing: bool = False
    account_id: str | None = None
    message: str = "Starting up."
    last_checked: str | None = None

    def update(self, **changes) -> bool:
        """Apply changes; return True if anything user-visible changed."""
        before = (self.status, self.authenticated, self.connected,
                  self.competing, self.account_id, self.message)
        for key, value in changes.items():
            setattr(self, key, value)
        self.last_checked = datetime.now(timezone.utc).isoformat()
        after = (self.status, self.authenticated, self.connected,
                 self.competing, self.account_id, self.message)
        return before != after

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


session_state = SessionState()


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


async def broadcast_session() -> None:
    await manager.broadcast({"type": "session", "data": session_state.to_dict()})


async def broadcast_event(resource: str) -> None:
    """Notify clients that a data resource changed so they can refetch."""
    await manager.broadcast({"type": "data", "resource": resource})
