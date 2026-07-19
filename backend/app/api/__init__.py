"""REST API router aggregation. Mounted under /api by main.

Split in two: `public_router` (health + login) needs no session cookie —
the compose healthcheck curls /api/health directly, and login is how a
cookie gets minted in the first place. Everything else sits behind
`require_auth` via `api_router`'s dependency.
"""
from fastapi import APIRouter, Depends

from app.api.deps import require_auth
from app.api.routes import (
    auth,
    contracts,
    diagnostics,
    fx,
    health,
    income,
    market,
    portfolio,
    risk,
    session,
    settings,
)

public_router = APIRouter()
public_router.include_router(health.router)
public_router.include_router(auth.public_router)

api_router = APIRouter(dependencies=[Depends(require_auth)])
api_router.include_router(auth.router)
api_router.include_router(session.router)
api_router.include_router(settings.router)
api_router.include_router(contracts.router)
api_router.include_router(portfolio.router)
api_router.include_router(market.router)
api_router.include_router(risk.router)
api_router.include_router(income.router)
api_router.include_router(fx.router)
api_router.include_router(diagnostics.router)
