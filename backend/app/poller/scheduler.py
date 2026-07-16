"""APScheduler wiring.

Two phases for the data jobs (when user is logged in):
  * Startup burst — every `poll_burst_seconds` for `poll_burst_window_seconds`,
    so the UI populates fast. Jobs self-skip until `user_logged_in` is True.
  * Steady state — after the burst window each job is rescheduled to its
    configured cadence (default 5 min).

The session monitor runs at a fixed cadence, passively checking auth_status
and releasing any stray authenticated sessions. The public price refresh
runs independently of IBKR auth state.

Multi-user: there is still one job per job type — each job iterates the gateways
whose user is logged in. The burst likewise stays global: any user's login
re-arms it for every job, which at worst gives an already-logged-in user a
briefly faster cadence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings
from app.core.logging import get_logger
from app.poller.jobs.account import poll_account
from app.poller.jobs.flex_import import import_flex_trades
from app.poller.jobs.market import poll_market, refresh_public_prices
from app.poller.jobs.positions import poll_positions
from app.poller.jobs.rolls import build_rolls
from app.poller.jobs.session import monitor
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


# Data jobs that participate in the startup burst, mapped to their steady cadence
# field on Settings. Used to re-arm the burst on user login.
_BURST_JOBS: dict[str, str] = {
    "poll_positions": "poll_positions_seconds",
    "poll_account": "poll_positions_seconds",
    "poll_trades": "poll_trades_seconds",
    "poll_market": "poll_market_seconds",
}


def rearm_burst(settings: Settings) -> None:
    """Re-anchor the startup burst to *now* — called on user-initiated login.

    The burst is otherwise anchored to backend process start, which rarely
    coincides with an on-demand login (the user may log in hours later). Without
    re-arming, the data jobs are already at their slow steady cadence by the time
    the user logs in, so the UI repopulates slowly and IV history accumulates at
    5-min intervals. Re-arming restarts the fast burst window from now.
    """
    if not scheduler.running:
        return
    now = datetime.now(timezone.utc)
    burst = settings.poll_burst_seconds
    window = settings.poll_burst_window_seconds
    rearmed = 0
    for job_id, steady_field in _BURST_JOBS.items():
        steady_seconds = getattr(settings, steady_field)
        try:
            scheduler.reschedule_job(job_id, trigger="interval", seconds=burst)
        except JobLookupError:
            continue
        scheduler.add_job(
            _settle_job,
            trigger="date",
            run_date=now + timedelta(seconds=window),
            args=[job_id, steady_seconds],
            id=f"{job_id}_settle",
            max_instances=1,
            replace_existing=True,
        )
        rearmed += 1
    log.info("burst_rearmed", jobs=rearmed, burst_seconds=burst, window_seconds=window)


def start_scheduler(settings: Settings) -> None:
    now = datetime.now(timezone.utc)

    scheduler.add_job(
        monitor,
        trigger="interval",
        seconds=settings.poll_heartbeat_seconds,
        id="session_monitor",
        max_instances=1,
        coalesce=True,
        next_run_time=now,
    )

    scheduler.add_job(
        refresh_public_prices,
        trigger="interval",
        seconds=settings.poll_public_price_seconds,
        id="public_price_refresh",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=5),
    )

    scheduler.add_job(
        build_rolls,
        trigger="interval",
        seconds=settings.poll_trades_seconds,
        id="build_rolls",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=6),
    )

    scheduler.add_job(
        import_flex_trades,
        trigger="interval",
        seconds=3600,
        id="flex_import",
        max_instances=1,
        coalesce=True,
        next_run_time=now + timedelta(seconds=3),
    )

    burst = settings.poll_burst_seconds
    window = settings.poll_burst_window_seconds
    _add_data_job(
        poll_positions, "poll_positions",
        first_delay=8, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_positions_seconds,
    )
    _add_data_job(
        poll_account, "poll_account",
        first_delay=10, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_positions_seconds,
    )
    _add_data_job(
        poll_trades, "poll_trades",
        first_delay=12, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_trades_seconds,
    )
    _add_data_job(
        poll_market, "poll_market",
        first_delay=14, burst_seconds=burst, burst_window=window,
        steady_seconds=settings.poll_market_seconds,
    )

    scheduler.start()
    log.info(
        "scheduler_started",
        monitor_seconds=settings.poll_heartbeat_seconds,
        public_price_seconds=settings.poll_public_price_seconds,
        burst_seconds=burst,
        burst_window_seconds=window,
        steady_market_seconds=settings.poll_market_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
