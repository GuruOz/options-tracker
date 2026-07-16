"""Application configuration, loaded from environment variables.

pydantic-settings maps UPPER_SNAKE env vars onto these lower_snake fields
case-insensitively (e.g. DATABASE_URL -> database_url).

Multi-user: each IBKR login needs its own IBEAM gateway container (IBKR does not
allow one login to hold two Client Portal sessions). Users are declared with
indexed env vars — IBKR_USER1_*, IBKR_USER2_*, ... — see `Settings.gateways()`.
"""
from __future__ import annotations

import os
from functools import cached_property, lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Highest IBKR_USER{n}_* index scanned for. Scanning stops at the first gap.
_MAX_GATEWAYS = 9


class GatewayConfig(BaseModel):
    """One user's IBEAM gateway: where it lives and how to drive it.

    The IBKR credentials themselves are deliberately absent — they are consumed
    only by the gateway container (IBEAM_ACCOUNT/IBEAM_PASSWORD), never read by
    the backend, which drives login by restarting the container.
    """

    gateway_id: str          # stable key used in API paths + WS events ("user1")
    label: str               # display name in the UI switcher ("Guru")
    gateway_url: str
    container: str
    account_id: str | None = None   # optional pin; blank => auto-detect
    flex_token: str | None = None
    flex_query_id: str | None = None


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database (async driver).
    database_url: str = "postgresql+asyncpg://options:options@db:5432/options"

    # IBKR Client Portal gateway (internal network). These legacy single-user
    # fields are the fallback when no IBKR_USER1_* block is declared — see
    # `gateways()`.
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
    poll_trades_seconds: int = 300
    poll_market_seconds: int = 300  # underlying history + signal

    # Startup burst: poll data jobs rapidly for the first window so the UI
    # populates quickly (and IV history accumulates) before settling to the
    # steady cadences above.
    poll_burst_seconds: int = 20
    poll_burst_window_seconds: int = 300

    # Public price refresh (yfinance) — runs independently of IBKR auth.
    poll_public_price_seconds: int = 300

    # Max seconds to wait for 2FA approval during user-initiated login.
    # IBEAM gateway startup + page load + form submit + MFA approval can take 60-90s.
    pull_login_timeout_seconds: int = 120

    # Docker container name of the ibkr-gateway service, for on-demand restart.
    docker_ibeam_container: str = "options-tracker-ibkr-gateway-1"

    # IBKR Flex Web Service — pulls all historical trades directly from IBKR.
    # Set these once (see README) and the app auto-imports on every login.
    ibkr_flex_token: str | None = None
    ibkr_flex_query_id: str | None = None

    # In-app authentication — single shared login gating every /api route
    # (except /api/health and /api/auth/login) plus /ws. See app/core/security.py.
    auth_username: str = "admin"
    auth_password_hash: str = ""       # argon2 hash; empty => logins rejected with 503
    auth_session_ttl_hours: int = 168  # 7 days
    auth_cookie_secure: bool = True    # False only for plain-HTTP local dev
    auth_max_failed_logins: int = 5
    auth_lockout_seconds: int = 300

    @property
    def verify_ssl(self) -> bool | str:
        """Return False, True, or a CA-bundle path for httpx's `verify`."""
        v = (self.ibkr_gateway_verify or "").strip().lower()
        if v in ("false", "0", "no", ""):
            return False
        if v in ("true", "1", "yes"):
            return True
        return self.ibkr_gateway_verify

    @cached_property
    def gateways(self) -> list[GatewayConfig]:
        """Declared users, in order, one per IBEAM gateway container.

        Scans IBKR_USER{n}_GATEWAY_URL for n=1.. and stops at the first gap, so
        users are always contiguous. With no IBKR_USER1_* block declared, this
        synthesizes a single "user1" from the legacy single-user fields, which
        keeps an existing .env working untouched.

        pydantic-settings has no native support for indexed groups like this, so
        the block is read straight from the environment.
        """
        found: list[GatewayConfig] = []
        for n in range(1, _MAX_GATEWAYS + 1):
            url = _env(f"IBKR_USER{n}_GATEWAY_URL")
            if not url:
                break
            found.append(GatewayConfig(
                gateway_id=f"user{n}",
                label=_env(f"IBKR_USER{n}_LABEL") or f"User {n}",
                gateway_url=url,
                container=(
                    _env(f"IBKR_USER{n}_CONTAINER")
                    or f"options-tracker-ibkr-gateway-{'' if n == 1 else f'{n}-'}1"
                ),
                account_id=_env(f"IBKR_USER{n}_ACCOUNT_ID"),
                flex_token=_env(f"IBKR_USER{n}_FLEX_TOKEN"),
                flex_query_id=_env(f"IBKR_USER{n}_FLEX_QUERY_ID"),
            ))
        if found:
            return found

        return [GatewayConfig(
            gateway_id="user1",
            label="Primary",
            gateway_url=self.ibkr_gateway_url,
            container=self.docker_ibeam_container,
            account_id=self.ibkr_account_id or None,
            flex_token=self.ibkr_flex_token or None,
            flex_query_id=self.ibkr_flex_query_id or None,
        )]


@lru_cache
def get_settings() -> Settings:
    return Settings()
