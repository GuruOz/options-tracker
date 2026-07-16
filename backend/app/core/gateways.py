"""Gateway runtimes — the per-user triple of config, IBKR client, and session.

One `GatewayRuntime` per declared user (see `Settings.gateways`). Everything that
talks to IBKR does so through a runtime, so a job or route always knows *whose*
gateway it is driving. Built once at startup by `init_runtimes`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.clients.ibkr import IBKRClient
from app.core.config import GatewayConfig, Settings
from app.core.logging import get_logger
from app.core.state import SessionState, registry

log = get_logger("core.gateways")

_runtimes: dict[str, "GatewayRuntime"] = {}


@dataclass
class GatewayRuntime:
    config: GatewayConfig
    client: IBKRClient
    state: SessionState

    @property
    def gateway_id(self) -> str:
        return self.config.gateway_id

    @property
    def label(self) -> str:
        return self.config.label


def init_runtimes(settings: Settings) -> list[GatewayRuntime]:
    """Build one runtime per declared user. Replaces any previous set."""
    _runtimes.clear()
    registry.clear()
    for cfg in settings.gateways:
        state = registry.register(cfg.gateway_id, cfg.label)
        _runtimes[cfg.gateway_id] = GatewayRuntime(
            config=cfg,
            client=IBKRClient(cfg.gateway_url, verify=settings.verify_ssl),
            state=state,
        )
    log.info(
        "gateways_initialized",
        count=len(_runtimes),
        gateways=[f"{c.gateway_id}:{c.label}" for c in settings.gateways],
    )
    return list(_runtimes.values())


def get_runtime(gateway_id: str) -> GatewayRuntime | None:
    return _runtimes.get(gateway_id)


def all_runtimes() -> list[GatewayRuntime]:
    return list(_runtimes.values())


def active_runtimes() -> list[GatewayRuntime]:
    """Runtimes whose user is logged in and whose account is known — i.e. the
    ones the data pollers should be pulling for."""
    return [
        rt for rt in _runtimes.values()
        if rt.state.user_logged_in and rt.state.account_id
    ]


def runtime_for_account(account_id: str) -> GatewayRuntime | None:
    for rt in _runtimes.values():
        if rt.state.account_id == account_id:
            return rt
    return None


def any_authenticated_client() -> IBKRClient | None:
    """A client from any logged-in gateway, for account-agnostic market calls.

    Market data is conid-keyed and identical whoever asks, so any authenticated
    session can serve it.
    """
    for rt in _runtimes.values():
        if rt.state.user_logged_in and rt.state.authenticated:
            return rt.client
    return None


async def close_all() -> None:
    for rt in _runtimes.values():
        try:
            await rt.client.close()
        except Exception as exc:
            log.warning("client_close_failed", gateway=rt.gateway_id, error=str(exc))
