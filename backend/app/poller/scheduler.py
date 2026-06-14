"""APScheduler wiring. v1 runs the session heartbeat; data jobs are added in
the poller milestone at their configured cadences.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    # Data jobs self-skip until the session is authenticated; start a few
    # seconds after boot so the first heartbeat can authenticate first.
    scheduler.add_job(
        poll_positions,
        trigger="interval",
        seconds=settings.poll_positions_seconds,
        args=[client],
        id="poll_positions",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=8),
    )
    scheduler.add_job(
        poll_account,
        trigger="interval",
        seconds=settings.poll_positions_seconds,
        args=[client],
        id="poll_account",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=12),
    )
    scheduler.add_job(
        poll_trades,
        trigger="interval",
        seconds=settings.poll_trades_seconds,
        args=[client],
        id="poll_trades",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=16),
    )
    # History + signal: heavier, runs less often. First pass ~25s after boot,
    # once positions exist to derive tracked underlyings from.
    scheduler.add_job(
        poll_market,
        trigger="interval",
        seconds=settings.poll_market_seconds,
        args=[client],
        id="poll_market",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=25),
    )
    scheduler.start()
    log.info(
        "scheduler_started",
        heartbeat_seconds=settings.poll_heartbeat_seconds,
        positions_seconds=settings.poll_positions_seconds,
        trades_seconds=settings.poll_trades_seconds,
        market_seconds=settings.poll_market_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
