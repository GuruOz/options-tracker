from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.state import manager, session_state

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    # Send a snapshot of current state immediately on connect.
    await ws.send_json({"type": "session", "data": session_state.to_dict()})
    try:
        while True:
            # We don't expect client messages; this keeps the socket open and
            # detects disconnects.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
