from fastapi import APIRouter

from app.core.state import registry

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe. Always 200 if the API process is up; reports gateway state."""
    return {
        "status": "ok",
        "gateways": {gid: s["status"] for gid, s in registry.to_dict().items()},
    }
