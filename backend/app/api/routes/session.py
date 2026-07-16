from fastapi import APIRouter, HTTPException

from app.core.constants import DISCLAIMER, VERSION
from app.core.gateways import get_runtime
from app.core.state import registry
from app.poller.jobs.session import orchestrate_login, orchestrate_logout

router = APIRouter(tags=["session"])


def _runtime_or_404(gateway_id: str):
    runtime = get_runtime(gateway_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail=f"Unknown gateway '{gateway_id}'.")
    return runtime


@router.get("/session")
async def get_session() -> dict:
    """Every user's gateway/session state, keyed by gateway id."""
    return registry.to_dict()


@router.get("/meta")
async def get_meta() -> dict:
    return {"version": VERSION, "disclaimer": DISCLAIMER}


@router.post("/session/{gateway_id}/login")
async def login(gateway_id: str) -> dict:
    """User-initiated login: restart that user's IBEAM, poll auth, batch-pull."""
    return await orchestrate_login(_runtime_or_404(gateway_id))


@router.post("/session/{gateway_id}/logout")
async def logout(gateway_id: str) -> dict:
    """User-initiated logout: release that user's IBKR session for mobile."""
    return await orchestrate_logout(_runtime_or_404(gateway_id))
