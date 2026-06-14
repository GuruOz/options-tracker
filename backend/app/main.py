"""FastAPI application entrypoint.

Lifespan: configure logging -> seed settings -> open the IBKR client -> start
the scheduler. Migrations are applied separately by entrypoint.sh before boot.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.routes import ws
from app.clients.ibkr import IBKRClient
from app.core.config import get_settings
from app.core.constants import VERSION
from app.core.logging import configure_logging, get_logger
from app.db.seed import seed_settings
from app.poller.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("starting", version=VERSION)
    await seed_settings()

    client = IBKRClient(settings.ibkr_gateway_url, verify=settings.verify_ssl)
    app.state.ibkr = client
    start_scheduler(client, settings)
    try:
        yield
    finally:
        stop_scheduler()
        await client.close()
        log.info("stopped")


app = FastAPI(title="options-tracker", version=VERSION, lifespan=lifespan)
app.include_router(api_router, prefix="/api")
app.include_router(ws.router)  # /ws (same origin via nginx)
