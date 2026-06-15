"""APScheduler wiring.

Two phases for the data jobs:
  * Startup burst — every `poll_burst_seconds` for `poll_burst_window_seconds`,
    so the UI populates fast and IV history accumulates quickly. Jobs self-skip
    until the session authenticates, so bursting also means data appears the
    moment auth completes rather than up to a steady-cadence later.
  * Steady state — after the burst window each job is rescheduled to its
    configured cadence (default 5 min).
The session heartbeat runs at a fixed cadence the whole time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.clients.ibkr import IBKRClient
from app.core.config import Settings
from app.core.logging import get_logger
from app.poller.jobs.account import poll_account
from app.poller.jobs.market import poll_market
from app.poller.jobs.positions import poll_positions
from app.poller.jobs.session import heartbeat
from app.poller.jobs.trades import poll_trades

log = get_logger("poller.scheduler")
scheduler = AsyncIOScheduler(timezone="UTC")


def _settle_job(job_id: str, steady_seconds: int) -> None:
    """Promote a bursting job to its steady cadence once the window elapses."""
    try:
        scheduler.reschedule_job(job_id, trigger="interval", seconds=steady_seconds)
        log.info("job_settled", job=job_id, steady_seconds=steady_seconds)
    except JobLookupError:
        pass


def _add_data_job(
    func,
    job_id: str,
    client: IBKRClient,
    *,
    first_delay: float,
    burst_seconds: int,
    burst_window: int,
    steady_seconds: int,
) -> None:
    now = datetime.now(timezone.utc)
    scheduler.add_job(
        func,
        trigger="interval",
        seconds=burst_seconds,
        args=[client],
        id=job_id,
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=first_delay),
    )
    scheduler.add_job(
        _settle_job,
        trigger="date",
        run_date=now + timedelta(seconds=first_delay + burst_window),
        args=[job_id, steady_seconds],
        id=f"{job_id}_settle",
        max_instances=1,
        replace_existing=True,
    )


def start_scheduler(client: IBKRClient, settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    scheduler.add_job(
        heartbeat,
        trigger="interval",
        seconds=settings.poll_heartbeat_seconds,
        args=[client],
        id="session_heartbeat",
        max_instances=1,
        coalesce=True,
        next_run_time=now,  # run immediately on boot
    )

    burst = settings.poll_burst_seconds
    window = settings.poll_burst_window_seconds
    # Stagger first runs a few seconds apart so the first heartbeat authenticates
    # first and the burst calls don't all fire in the same instant.
    _add_data_job(
        poll_positions, "poll_positions", client,
        first_delay=8, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_positions_seconds,
    )
    _add_data_job(
        poll_account, "poll_account", client,
        first_delay=10, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_positions_seconds,
    )
    _add_data_job(
        poll_trades, "poll_trades", client,
        first_delay=12, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_trades_seconds,
    )
    _add_data_job(
        poll_market, "poll_market", client,
        first_delay=14, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_market_seconds,
    )

    scheduler.start()
    log.info(
        "scheduler_started",
        heartbeat_seconds=settings.poll_heartbeat_seconds,
        burst_seconds=burst,
        burst_window_seconds=window,
        steady_market_seconds=settings.poll_market_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
