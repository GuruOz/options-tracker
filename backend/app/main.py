"""FastAPI application entrypoint.

Lifespan: configure logging -> seed settings -> build the per-user gateway
runtimes -> start the scheduler -> stop every IBEAM container (to prevent
unsolicited MFA on first build). Migrations are applied separately by
entrypoint.sh before boot.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api import api_router, public_router
from app.api.routes import ws
from app.core.config import get_settings
from app.core.constants import VERSION
from app.core.gateways import all_runtimes, close_all, init_runtimes
from app.core.logging import configure_logging, get_logger
from app.db.seed import seed_settings
from app.poller.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
log = get_logger("app")


def _stop_ibeam_containers() -> None:
    """Stop every gateway container so no user gets an unsolicited MFA push.

    A gateway a user never declared (or hasn't created yet) is simply absent —
    warn and carry on rather than failing the other users' startup.
    """
    try:
        import docker
        dc = docker.from_env()
    except Exception as exc:
        log.warning("docker_unavailable_on_startup", error=str(exc))
        return

    for rt in all_runtimes():
        container_name = rt.config.container
        try:
            c = dc.containers.get(container_name)
            if c.status == "running":
                c.stop()
                log.info(
                    "stopped_ibeam_on_startup",
                    gateway=rt.gateway_id, container=container_name,
                )
        except docker.errors.NotFound:
            log.warning(
                "ibeam_container_not_found",
                gateway=rt.gateway_id, container=container_name,
            )
        except Exception as exc:
            log.warning(
                "ibeam_stop_failed",
                gateway=rt.gateway_id, container=container_name, error=str(exc),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("starting", version=VERSION)
    await seed_settings()

    runtimes = init_runtimes(settings)
    app.state.gateways = runtimes
    start_scheduler(settings)

    _stop_ibeam_containers()

    try:
        yield
    finally:
        stop_scheduler()
        await close_all()
        log.info("stopped")


app = FastAPI(title="options-tracker", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    # /api/health fires every 15s (compose healthcheck) — too noisy to log.
    if request.url.path == "/api/health":
        return await call_next(request)
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        client_ip=client_ip,
    )
    return response


app.include_router(public_router, prefix="/api")
app.include_router(api_router, prefix="/api")
app.include_router(ws.router)  # /ws (same origin via nginx)