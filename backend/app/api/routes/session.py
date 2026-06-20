from fastapi import APIRouter, Request

from app.core.constants import DISCLAIMER, VERSION
from app.core.state import session_state
from app.poller.jobs.session import orchestrate_login, orchestrate_logout

router = APIRouter(tags=["session"])


@router.get("/session")
async def get_session() -> dict:
    """Current gateway/session state for the connection banner."""
    return session_state.to_dict()


@router.get("/meta")
async def get_meta() -> dict:
    return {"version": VERSION, "disclaimer": DISCLAIMER}


@router.post("/session/login")
async def login(request: Request) -> dict:
    """User-initiated login: restart IBEAM, poll auth, batch-pull data."""
    from app.clients.ibkr import IBKRClient
    client: IBKRClient = request.app.state.ibkr
    return await orchestrate_login(client)


@router.post("/session/logout")
async def logout(request: Request) -> dict:
    """User-initiated logout: release the IBKR session for mobile."""
    from app.clients.ibkr import IBKRClient
    client: IBKRClient = request.app.state.ibkr
    return await orchestrate_logout(client)
