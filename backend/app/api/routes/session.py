from fastapi import APIRouter

from app.core.constants import DISCLAIMER, VERSION
from app.core.state import session_state

router = APIRouter(tags=["session"])


@router.get("/session")
async def get_session() -> dict:
    """Current gateway/session state for the connection banner."""
    return session_state.to_dict()


@router.get("/meta")
async def get_meta() -> dict:
    return {"version": VERSION, "disclaimer": DISCLAIMER}
