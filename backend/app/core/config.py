"""Application configuration, loaded from environment variables.

pydantic-settings maps UPPER_SNAKE env vars onto these lower_snake fields
case-insensitively (e.g. DATABASE_URL -> database_url).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database (async driver).
    database_url: str = "postgresql+asyncpg://options:options@db:5432/options"

    # IBKR Client Portal gateway (internal network).
    ibkr_gateway_url: str = "https://ibkr-gateway:5000/v1/api"
    # "false"/"true" or a path to a CA bundle for the gateway's self-signed cert.
    ibkr_gateway_verify: str = "false"
    # Optional pinned account id; blank => auto-detect the first available one.
    ibkr_account_id: str | None = None

    # Optional Redis (blank => in-memory fallback).
    redis_url: str | None = None

    log_level: str = "INFO"

    # Poller cadences (seconds) — steady state after the startup burst.
    poll_heartbeat_seconds: int = 45
    poll_positions_seconds: int = 300
    poll_marketdata_seconds: int = 300
    poll_trades_seconds: int = 300
    poll_market_seconds: int = 300  # underlying history + signal

    # Startup burst: poll data jobs rapidly for the first window so the UI
    # populates quickly (and IV history accumulates) before settling to the
    # steady cadences above.
    poll_burst_seconds: int = 20
    poll_burst_window_seconds: int = 300

    @property
    def verify_ssl(self) -> bool | str:
        """Return False, True, or a CA-bundle path for httpx's `verify`."""
        v = (self.ibkr_gateway_verify or "").strip().lower()
        if v in ("false", "0", "no", ""):
            return False
        if v in ("true", "1", "yes"):
            return True
        return self.ibkr_gateway_verify


@lru_cache
def get_settings() -> Settings:
    return Settings()
