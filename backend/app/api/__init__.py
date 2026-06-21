"""REST API router aggregation. Mounted under /api by main."""
from fastapi import APIRouter

from app.api.routes import (
    contracts,
    health,
    income,
    market,
    portfolio,
    risk,
    session,
    settings,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(session.router)
api_router.include_router(settings.router)
api_router.include_router(contracts.router)
api_router.include_router(portfolio.router)
api_router.include_router(market.router)
api_router.include_router(risk.router)
api_router.include_router(income.router)
