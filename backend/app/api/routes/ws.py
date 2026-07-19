from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.state import manager, registry
from app.db import auth_repo
from app.db.base import AsyncSessionLocal
from app.core.security import hash_token

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Same-origin check + session-cookie auth, both before accept() — an
    # unauthenticated client never gets a handshake.
    #
    # Compare hostnames only, not host:port. Behind the reverse proxy the
    # browser's Origin carries the published port (e.g. host:1337) while nginx
    # forwards a Host header whose port has been stripped, so an exact netloc
    # match would reject every connection when the app is served on a
    # non-standard port. The hostname still has to match, so a genuinely
    # cross-site origin is still refused.
    origin = ws.headers.get("origin")
    host = ws.headers.get("host", "")
    if origin and urlparse(origin).hostname != host.split(":")[0]:
        await ws.close(code=4403)
        return

    token = ws.cookies.get("session")
    if not token:
        await ws.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        row = await auth_repo.get_session_by_hash(db, hash_token(token))
    if row is None or row.expires_at < datetime.now(timezone.utc):
        await ws.close(code=4401)
        return

    await manager.connect(ws)
    # Send a snapshot of every user's state immediately on connect.
    await ws.send_json({"type": "sessions", "data": registry.to_dict()})
    try:
        while True:
            # We don't expect client messages; this keeps the socket open and
            # detects disconnects.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
