"""Async client for the IBKR Client Portal Web API (read-only).

Read-only guarantee: this client deliberately exposes NO order, modify, cancel,
or funds-transfer endpoints. There is no code path here that can place a trade.
"""
from __future__ import annotations

import asyncio
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.clients.ibkr.fields import GREEK_FIELD_CODES
from app.clients.ibkr.normalize import snapshot_has_greeks
from app.core.logging import get_logger

log = get_logger("ibkr.client")


class _RateLimiter:
    """Serialises requests to at most `rate_per_sec` to respect CP pacing."""

    def __init__(self, rate_per_sec: float):
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            wait = self._last + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class IBKRError(Exception):
    """Generic gateway/transport error."""


class IBKRAuthError(IBKRError):
    """Gateway reachable but the session is not authenticated (401)."""


class IBKRServerError(IBKRError):
    """Gateway returned a 5xx error."""


_RETRYABLE = retry_if_exception_type((httpx.TransportError, IBKRServerError))


class IBKRClient:
    def __init__(
        self,
        base_url: str,
        verify: bool | str = False,
        timeout: float = 15.0,
        rate_per_sec: float = 5.0,
    ):
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(verify=verify, timeout=timeout)
        self._rl = _RateLimiter(rate_per_sec)

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        retry=_RETRYABLE,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs):
        await self._rl.acquire()
        url = f"{self._base}/{path.lstrip('/')}"
        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code in (401, 403):
            raise IBKRAuthError(f"{resp.status_code} from {path}")
        # Before login, the gateway answers API calls with 404 "Access Denied".
        if resp.status_code == 404 and "access denied" in resp.text.lower():
            raise IBKRAuthError(f"not authenticated ({path}: access denied)")
        if resp.status_code >= 500:
            raise IBKRServerError(f"{resp.status_code} from {path}")
        if resp.status_code >= 400:
            raise IBKRError(f"{resp.status_code} from {path}: {resp.text[:200]}")
        if not resp.content:
            return {}
        return resp.json()

    async def _get(self, path: str, **kwargs):
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs):
        return await self._request("POST", path, **kwargs)

    # ---- session / auth -------------------------------------------------
    async def tickle(self) -> dict:
        return await self._post("tickle")

    async def auth_status(self) -> dict:
        return await self._post("iserver/auth/status")

    async def validate_sso(self) -> dict:
        return await self._get("sso/validate")

    async def reauthenticate(self) -> dict:
        return await self._post("iserver/reauthenticate")

    async def logout(self) -> dict:
        return await self._post("logout")

    # ---- accounts -------------------------------------------------------
    async def iserver_accounts(self) -> dict:
        return await self._get("iserver/accounts")

    async def portfolio_accounts(self) -> list:
        return await self._get("portfolio/accounts")

    # ---- portfolio data (implemented in the poller milestone) -----------
    async def positions(self, account_id: str, page: int = 0) -> list:
        return await self._get(f"portfolio/{account_id}/positions/{page}")

    async def portfolio_summary(self, account_id: str) -> dict:
        return await self._get(f"portfolio/{account_id}/summary")

    async def trades(self) -> list:
        return await self._get("iserver/account/trades")

    async def market_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list:
        fields = fields or GREEK_FIELD_CODES
        params = {"conids": ",".join(str(c) for c in conids), "fields": ",".join(fields)}
        return await self._get("iserver/marketdata/snapshot", params=params)

    async def market_history(self, conid: int, period: str = "6m", bar: str = "1d") -> dict:
        params = {"conid": conid, "period": period, "bar": bar}
        return await self._get("iserver/marketdata/history", params=params)

    async def secdef_search(self, symbol: str) -> list:
        return await self._post("iserver/secdef/search", json={"symbol": symbol})

    # ---- higher-level helpers ------------------------------------------
    async def all_positions(self, account_id: str, max_pages: int = 10) -> list:
        """Page through all positions. CP returns up to 100 rows per page."""
        # Touch /portfolio/accounts first to (re)initialise the portfolio session.
        try:
            await self.portfolio_accounts()
        except IBKRError:
            pass
        out: list = []
        for page in range(max_pages):
            rows = await self.positions(account_id, page)
            if not isinstance(rows, list) or not rows:
                break
            out.extend(rows)
            if len(rows) < 100:
                break
        return out

    async def pull_all(self, account_id: str) -> dict:
        """Batch-pull every auth-required resource and return a result dict.

        Each section is pulled independently so one failure doesn't block
        the rest. Returns per-resource status, timestamps, and raw payloads.
        """
        from datetime import datetime, timezone
        from app.clients.ibkr.normalize import (
            normalize_position, normalize_summary, normalize_trade,
            parse_snapshot_row, parse_underlying_quote,
        )
        from app.clients.ibkr.fields import UNDERLYING_FIELD_CODES

        result: dict = {
            "pull_ts": datetime.now(timezone.utc).isoformat(),
            "positions": {"status": "skipped", "count": 0, "options": 0},
            "account": {"status": "skipped"},
            "trades": {"status": "skipped", "count": 0},
            "market": {"status": "skipped", "count": 0},
        }

        try:
            raw_positions = await self.all_positions(account_id)
            normalized = [normalize_position(p) for p in raw_positions]
            option_conids = [
                n["conid"]
                for n in normalized
                if n["conid"] and (n.get("sec_type") or "").upper() in ("OPT", "FOP", "WAR")
            ]
            greeks: dict[int, dict] = {}
            if option_conids:
                try:
                    rows = await self.snapshot_with_warmup(option_conids)
                    for row in rows:
                        c = row.get("conid")
                        if c is not None:
                            greeks[int(c)] = parse_snapshot_row(row)
                except (IBKRError, IBKRAuthError):
                    pass
            result["positions"] = {
                "status": "ok",
                "count": len(normalized),
                "options": len(option_conids),
                "greeks_count": len(greeks),
                "rows": normalized,
                "greeks": greeks,
            }
        except (IBKRAuthError, IBKRError) as exc:
            result["positions"]["status"] = "failed"
            result["positions"]["error"] = str(exc)

        try:
            raw_acct = await self.portfolio_summary(account_id)
            if isinstance(raw_acct, dict):
                result["account"] = {
                    "status": "ok",
                    "summary": normalize_summary(raw_acct),
                    "raw": raw_acct,
                }
            else:
                result["account"]["status"] = "empty"
        except (IBKRAuthError, IBKRError) as exc:
            result["account"]["status"] = "failed"
            result["account"]["error"] = str(exc)

        try:
            raw_trades = await self.trades()
            if isinstance(raw_trades, list):
                normalized_trades = [
                    normalize_trade(t, account_id=account_id)
                    for t in raw_trades
                ]
                result["trades"] = {
                    "status": "ok",
                    "count": len(normalized_trades),
                    "rows": normalized_trades,
                }
            else:
                result["trades"]["status"] = "empty"
        except (IBKRAuthError, IBKRError) as exc:
            result["trades"]["status"] = "failed"
            result["trades"]["error"] = str(exc)

        try:
            from app.db.base import AsyncSessionLocal
            from app.db.models import Setting
            async with AsyncSessionLocal() as session:
                settings_row = await session.get(Setting, 1)
            tracked = []
            if settings_row and settings_row.data:
                for u in settings_row.data.get("underlyings", []):
                    try:
                        tracked.append((int(u["conid"]), u.get("symbol") or str(u["conid"])))
                    except (KeyError, ValueError, TypeError):
                        continue
            if tracked:
                conids = [t[0] for t in tracked]
                snaps = await self.market_snapshot(conids, UNDERLYING_FIELD_CODES)
                quotes = []
                for row in snaps:
                    q = parse_underlying_quote(row)
                    q["conid"] = row.get("conid")
                    q["symbol"] = next(
                        (s for c, s in tracked if c == row.get("conid")), None
                    )
                    quotes.append(q)
                result["market"] = {
                    "status": "ok",
                    "count": len(quotes),
                    "rows": quotes,
                }
            else:
                result["market"]["status"] = "empty"
        except (IBKRAuthError, IBKRError) as exc:
            result["market"]["status"] = "failed"
            result["market"]["error"] = str(exc)

        return result

    async def snapshot_with_warmup(
        self,
        conids: list[int],
        fields: list[str] | None = None,
        attempts: int = 3,
        delay: float = 0.4,
    ) -> list:
        """First snapshot call for a conid is often partial; re-request until the
        Greek fields populate (bounded), then return whatever arrived."""
        fields = fields or GREEK_FIELD_CODES
        rows: list = []
        for _ in range(max(1, attempts)):
            rows = await self.market_snapshot(conids, fields)
            if rows and all(snapshot_has_greeks(r) for r in rows):
                break
            await asyncio.sleep(delay)
        return rows
