from fastapi import APIRouter

from app.core.state import session_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe. Always 200 if the API process is up; reports gateway state."""
    return {"status": "ok", "gateway": session_state.status.value}
