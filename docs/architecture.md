# Options Tracker — Architecture

Self-hosted, open-source, **read-only** dashboard for options sellers. One Docker Compose stack per household — not multi-tenant SaaS. A single shared app-level login gates the dashboard; the IBKR gateway session is separate and per-user (see [Authentication](#authentication) and [Session lifecycle](#session-lifecycle)).

---

## Stack (locked)

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12 + FastAPI (async); APScheduler (in-process); SQLAlchemy 2.0 async + Alembic; Pydantic |
| **Database** | PostgreSQL 16 (named Docker volume) |
| **Cache** | Redis — optional, off by default (`--profile redis`); backend runs without it (in-memory fallback) |
| **Frontend** | React 18 + TypeScript + Vite; TanStack Query; ECharts (gauge/analytics) + Lightweight-Charts (price/OHLC); Tailwind CSS; light/dark theme, responsive |
| **Gateway** | [IBEAM](https://github.com/Voyz/ibeam) (`voyz/ibeam:latest`) — headless CP Gateway; auth is user-initiated, on-demand. The backend restarts it via `docker-proxy` (see below), never a mounted socket. |
| **Docker proxy** | [tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) — the backend's only path to the Docker API. Allowlists container list/inspect/start/stop/restart; everything else (images, exec, volumes...) is denied. Sits on its own `internal: true` network so the gateways/db can never reach it. |
| **Edge** | nginx — TLS termination, security headers, rate limiting, serves the built SPA, reverse-proxies `/api` and `/ws` (single browser origin). Only container with a host-published port (loopback by default) |

Account scope v1: **single account**, but the schema is multi-ready — `account_id` FKs everywhere so a v2 per-account-gateway is additive.

---

## Hard invariants

- Browser **never** contacts IBKR directly.
- Backend ↔ gateway communication is server-side only, over the internal Compose network.
- Backend is strictly **read-only** to IBKR — no order, modify, cancel, or funds-transfer endpoints exist in the client (enforced by allowlist).
- Gateway, DB, docker-proxy, and Redis are **never** published to the host's public interface.
- Secrets live only in `.env` / Docker secrets.
- The backend never holds the raw Docker socket — only `docker-proxy` does, read-only, on its own isolated network.
- Every `/api` route requires an authenticated session except `/api/health` (the compose healthcheck) and `/api/auth/login`.

---

## Authentication

Single shared login (`AUTH_USERNAME`/`AUTH_PASSWORD_HASH` in `.env`), not
per-person accounts — see [docs/SECURITY.md](SECURITY.md) for why that's an
accepted trade-off rather than a gap.

- **Password hashing:** argon2 (`app/core/security.py`). `app/cli/hash_password.py`
  prints a hash for `.env`; no plaintext password is ever stored.
- **Sessions:** server-side, in the `auth_sessions` table. The cookie holds
  only a random token; the DB stores its sha256 hash, so a DB leak alone can't
  be replayed as a live session. `HttpOnly` + `Secure` + `SameSite=Strict`.
- **CSRF:** a second, non-HttpOnly cookie carries a per-session CSRF token,
  echoed back via the `X-CSRF-Token` header on every mutating request
  (POST/PUT/PATCH/DELETE) and checked server-side in `app/api/deps.py`.
- **WebSocket:** `/ws` validates the session cookie (and same-origin) before
  `accept()` — an unauthenticated client never completes the handshake.
- **Brute-force lockout:** an in-memory per-IP counter locks out login
  attempts after `AUTH_MAX_FAILED_LOGINS` failures for `AUTH_LOCKOUT_SECONDS`.
- **Audit log:** `auth_login_success`/`auth_login_failed`/`auth_logout` and a
  per-request `http_request` line, as structured JSON via structlog.

This sits in front of, and is entirely independent from, the per-user IBKR
gateway session described below — logging into the dashboard does not log
into IBKR, and vice versa.

---

## Session lifecycle

The app is **unauthenticated by default**. No background keep-alive — neither
the backend nor IBEAM maintains a persistent brokerage session.

- **User-initiated login.** Clicking "Pull Fresh Data" in the UI calls
  `POST /api/session/login`. The backend **restarts** the IBEAM container via
  Docker SDK (a plain `start()` is a no-op when the container is already running,
  so a restart is what guarantees IBEAM re-runs its login flow and pushes a
  *fresh* 2FA notification — clicking again always sends a new request). Once
  approved, the backend polls `POST /iserver/auth/status` (every 2 s) until
  `authenticated:true`. All positions, balances, open orders, P&L, and market
  snapshots are batch-pulled and persisted in a single pass. The session stays
  active for browsing — no forced logout.
  - **Timeout:** 120 s (configurable via `PULL_LOGIN_TIMEOUT_SECONDS`),
    followed by a 30 s grace period where polling continues at 5 s intervals.
    Must exceed IBEAM startup (~120 s) and stay under the NGINX read timeout.
  - **Late approval.** If the 2FA push is approved *after* the request times out,
    the passive monitor adopts the now-authenticated session automatically
    (within a 5-min window of the login click) and pulls data — so a slow
    approval no longer gets logged straight back out.
  - **NGINX:** `proxy_read_timeout: 180s` on `/api/` location to accommodate the
    long-running login request.
- **Passive monitor.** A `session_monitor` job runs every 45 s and checks
  `auth_status()` only. It never calls `tickle()` or `reauthenticate()`. If it
  detects an authenticated session while no user is logged in, it calls
  `POST /logout` immediately to release it for IBKR mobile — **unless** the user
  requested a login within the last 5 minutes, in which case it adopts the
  session instead of releasing it. During active login (`LOGGING_IN` /
  `PULLING` status), the monitor skips logout entirely.
- **Manual logout.** The "Logout & Release" button calls
  `POST /api/session/logout`, which calls `POST /logout` and sets the session
  to DISCONNECTED. The IBKR mobile app is immediately available again.
- **Startup behavior.** On first boot, the backend stops the IBEAM container
  to prevent an unsolicited 2FA push. Login only occurs when the user explicitly
  clicks "Pull Fresh Data."
- **Public price fallback.** A `public_price_refresh` job runs independently
  of IBKR auth (default every 300 s), fetching prices and IV from yfinance and
  writing to `market_snapshots` with `source="public"`. Falls back to cached
  data on failure.

---

## IBEAM configuration

IBEAM handles the browser-based SSO/2FA login to IBKR's Client Portal. IBKR
periodically changes login page elements, which can break IBEAM. The current
working configuration in `docker-compose.yml`:

| Env var | Value | Why |
|---------|-------|-----|
| `IBEAM_MAINTENANCE_INTERVAL` | `86400` | Disable periodic auto-maintenance (24 h). Zero is treated as 1 s by IBEAM. |
| `IBEAM_RESTART_FAILED_SESSIONS` | `false` | Don't retry after login failure. |
| `IBEAM_MAX_FAILED_AUTH` | `1` | Give up after one failure to avoid IBKR lock-out. |
| `IBEAM_AUTHENTICATION_STRATEGY` | `A` | Older strategy that found the login form when strategy B failed. |
| `IBEAM_MANUAL_TWO_FA` | `true` | Skip browser-based 2FA detection; poll gateway auth status instead. |
| `IBEAM_PAGE_LOAD_TIMEOUT` | `60` | Seconds to wait for the login page to load and post-login elements. |
| `IBEAM_OAUTH_TIMEOUT` | `60` | Seconds to wait for the OAuth/SSO flow. |
| `IBEAM_ERROR_SCREENSHOTS` | `true` | Save PNG screenshots to `/srv/outputs/` on failure (debug aid). |
| `IBEAM_TWO_FA_INPUT_EL_ID` | `ID@@xyz-field-silver-response` | IBKR renamed the 2FA input from `bronze` to `silver` in 2026. |
| `IBEAM_USER_NAME_EL` | `NAME@@user_name` | Explicit username field selector. |
| `IBEAM_SUBMIT_EL` | `CSS_SELECTOR@@button[type="submit"]` | Resilient submit button selector independent of IBKR's changing class names. |

**Auth flow with IBEAM:** The backend starts IBEAM via `container_obj.start()`.
IBEAM loads the CP Gateway, opens the login page, enters credentials, submits
the form, and waits for 2FA. With `MANUAL_TWO_FA=true`, IBEAM polls the
gateway's `POST /iserver/auth/status` instead of trying to find 2FA elements
in the DOM. The user approves the push on their phone and IBEAM detects
`authenticated:true`.

---

## Poller jobs & cadences

Data jobs run in two phases (see `poller/scheduler.py`). They self-skip until
`user_logged_in` is True (i.e., the user has initiated a login and completed it).

- **Startup burst:** every `POLL_BURST_SECONDS` (default 20 s) for the first
  `POLL_BURST_WINDOW_SECONDS` (default 300 s). Fills the UI fast once the user
  logs in.
- **Steady state:** after the burst window each job is rescheduled to its
  configured cadence (default 300 s / 5 min).

| Job | Steady cadence | Requires auth | What it does |
|-----|---------|------|--------------|
| `session_monitor` | 45 s | No | Checks auth status only; calls `/logout` if a stray authenticated session is detected. Never tickles or reauthenticates. Broadcasts session state via WebSocket. |
| `public_price_refresh` | 300 s | No | Fetches underlying prices/IV from yfinance; persists `market_snapshots` (source=`public`) + `signal_history`. Falls back to cache on failure. |
| `import_flex_trades` | 3600 s | No | Calls IBKR Flex Web Service to pull full trade history. Idempotent upsert by exec_id. |
| `build_rolls` | 300 s | No | Scans unlinked executions and builds `roll_chains` + `roll_chain_legs`; detects rolls (buy-to-close + sell-to-open within 5 min on same underlying). Keys chains by `conid` for accuracy. |
| `poll_positions` | 300 s | Yes | Fetches positions + Greek snapshot; inserts `position_snapshots` |
| `poll_account` | 300 s | Yes | Fetches portfolio summary; inserts `account_snapshots` |
| `poll_trades` | 300 s | Yes | Fetches recent trades (~7-day window); upserts `executions` (idempotent by exec id) |
| `poll_market` | 300 s | Yes | Fetches 1-year daily history + live snapshot for each tracked underlying; persists `market_snapshots` (source=`ibkr`) + `signal_history` |

**Tracked underlyings** come exclusively from `settings.underlyings` (user-configured via the in-app UI). The market job is a no-op if the list is empty.

---

## API surface

### Session / meta
- `GET /api/health`
- `GET /api/session`
- `GET /api/meta`
- `POST /api/session/login` — user-initiated login: starts IBEAM, polls 2FA, batch-pulls data
- `POST /api/session/logout` — manual logout: releases session for IBKR mobile

### Settings
- `GET /api/settings` — full settings object
- `PUT /api/settings` — replace full settings
- `POST /api/settings/underlyings` — add one underlying `{conid, symbol, description}`
- `DELETE /api/settings/underlyings/{conid}` — remove by conid

### Contract search
- `GET /api/contracts/search?q=QQQ` — proxies IBKR secdef search, returns STK entries `{conid, symbol, description}`

### Portfolio data
- `GET /api/positions` — latest option positions enriched with Greeks, DTE, intrinsic/extrinsic, premium captured, cushion, status, chain_id, source, last_updated
- `GET /api/account` — latest account summary with source, last_updated
- `GET /api/alerts` — filtered positions where status != "OPEN"
- `GET /api/trades` — recent trades (default 100, configurable limit)
- `GET /api/trades/options` — all option trades (OPT/FOP/WAR), oldest first, no limit
- `POST /api/trades/upload` — upload IBKR Activity Statement CSV for historical import
- `GET /api/chains?status=open|closed|all` — roll-chain summaries (cumulative credit, leg count, opened/closed dates per chain). How a chain's P&L headline (banked to date / locked / if-worthless / gathered beyond the opener) is derived: [roll-chain-economics.md](roll-chain-economics.md)

### Market & signals
- `GET /api/market` — latest market snapshot per tracked underlying (with source column)
- `GET /api/signals` — latest signal per underlying (with derived source)
- `GET /api/signal/history?conid=…` — time-series signal history

### Risk
- `GET /api/risk` — beta-weighted delta, stress P&L, assignment coverage, equity curve

### WebSocket
- `WS /ws` — pushes `{type, resource}` events (`session`, `data`, `market`, `signals`, `positions`, `account`, `trades`); frontend uses these to invalidate TanStack Query caches

---

## Database schema (key tables)

| Table | Purpose |
|-------|---------|
| `position_snapshots` | One row per position per poll; `symbol VARCHAR(64)`; option fields extracted from OSI contractDesc |
| `account_snapshots` | Net liq, available funds, margin, cash, etc. |
| `executions` | Trades; idempotent upsert by `exec_id`; `source` = `poll` / `flex` / `flex_import` |
| `market_snapshots` | Price / IV / RV / RSI / SMA per underlying per poll; `source` column (`ibkr` / `public` / `cache`) tracks data provenance |
| `signal_history` | Composite score + sub-scores + inputs + weights per underlying per poll |
| `roll_chains` | One row per option position lifecycle; `chain_id` (unique), `status` (open/closed), `cumulative_credit` |
| `roll_chain_legs` | Individual executions grouped into chains; unique on `(chain_id, exec_id)`; `role` = open/close |
| `settings` | Single row (id=1); JSONB blob with the *global* signal weights, BS rate, and risk beta map |
| `account_settings` | One row per account; JSONB blob with that account's `underlyings` watchlist and `alerts` thresholds |

All history tables carry `account_id` FKs, and multi-user is live: one
`GatewayRuntime`/`SessionState` per declared user (`core/gateways.py`,
`core/state.py`), one IBEAM container per user, and API routes take
`?account_id=<id>|all` (see `api/deps.py`). See README § Multi-user (household)
setup.

---

## Key implementation details

### Greek field codes
- Delta `7308` · Gamma `7309` · Theta `7310` · Vega `7311`
- IV candidates (first present wins): `7283`, `7633`, `7607`
- Historic vol: `7087`

### IV percentile / rank
Computed by us from the persisted `market_snapshots.iv` series. Requires ≥ 5 observations (accumulates at poll cadence). Returns `null` until threshold is met.

### Black-Scholes fallback
Used **only** when IBKR does not return a Greek. `r = 4.5%`. Output labelled "est." in the UI.

### Option symbol parsing
Positions rows leave `putOrCall` / `strike` / `expiry` null for options. The underlying, right, strike, and expiry are extracted from the OSI-format `contractDesc` string (e.g. `QQQ JUL2026 715 P [QQQ 260702P00715000 100]`) via regex.

### Roll-chain detection
Pure function in `analytics/rolls.py`. Scans executions chronologically, keyed by `conid`:
- **SELL** (reached directly) → creates a new chain (status `open`) and maps its conid.
- **BUY** → **looks ahead one execution**: if the next fill is a SELL within 5 min on
  the same underlying + right, this is a **roll**, otherwise it's a plain close.
  - **Roll** → the buy-to-close and the sell-to-open share **one** chain; the old
    conid mapping is removed, the new conid added; the chain stays `open`. Both legs
    are consumed in this step so the following SELL is not re-processed as a fresh open.
  - **Plain close** → find the chain by the BUY's conid, add a close leg, mark `closed`.
    A BUY with no matching open chain becomes an orphan `closed` chain.
- Existing open chains from the DB are seeded before each run so cross-batch BUYs
  correctly close (or, when followed by a roll's SELL, continue) their chains.
- Cumulative credit: sell premium minus buy cost, net of commissions — each leg
  counted exactly once.

> The look-**ahead** at the BUY is deliberate: an earlier look-**back** from the SELL
> closed the chain in the BUY branch before the SELL could claim it, which fragmented
> every roll into separate chains and double-counted the buy-to-close. Covered by
> `backend/tests/test_rolls.py`.

### Historical trade import
Two mechanisms:
1. **Flex Web Service** (`import_flex_trades` job, hourly): Calls IBKR's standalone `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService` directly (no CP Gateway needed). Requires one-time setup: create an Activity Flex Query in IBKR Account Management, generate a token, set `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` in `.env`. Downloads XML with all trades since inception, parses via `flex_parse.py`, upserts into `executions` by `exec_id`.
2. **CSV upload** (`POST /api/trades/upload`): Manual upload of IBKR Activity Statement CSV via the "Import CSV" button in the Option Trades section. Parses symbol, date, quantity, price, commission, realized P&L. Source = `flex_import`.

### Freshness metadata
All API responses carry `source` (`ibkr_live` / `public` / `cache`) and `last_updated` fields so the UI can distinguish live data from stale cached data.

---

## Solved gotchas

| Issue | Fix |
|-------|-----|
| Empty `IBEAM_KEY` → Fernet crash | Removed `IBEAM_KEY` from compose; document it as optional |
| Gateway returns "Access Denied" to backend | `gateway/conf.yaml` widens `ips.allow` to `127.0.0.1` / `10.*` / `172.*` / `192.168.*` (covers Docker bridge networks) |
| Option `contractDesc` overflowed `symbol VARCHAR(32)` | Migration `0002_widen_symbol` → `VARCHAR(64)` |
| IBEAM sends unsolicited MFA on startup | Backend stops IBEAM container on boot; `restart: "no"`; `MAX_FAILED_AUTH=1` |
| IBEAM ignores `MAINTENANCE_INTERVAL=0` (runs every 1 s) | Set to `86400` (24 h) — zero is treated as 1 s by IBEAM |
| IBEAM login fails on live accounts (2026) | Strategy A + `MANUAL_TWO_FA=true` + updated selectors (`silver` 2FA field, `button[type="submit"]`, `user_name`); see `workinprogress.md` |
| NGINX kills login request at 60 s | `proxy_read_timeout: 180s` on `/api/` |
| `python-multipart` missing for CSV upload | Added to `requirements.txt` |
| Roll chains keyed by `(symbol, right)` overwrote multiple chains | Changed to key by `conid` (specific contract) |
| Closed chains had same open/close dates | Fixed by seeding `open_by_conid` from existing DB chains (cross-batch awareness) |
| Backend crashed on `import docker` at module level | Moved to lazy import inside lifespan function |
| IBEAM restart loop (docker restart policy) | Changed IBEAM `restart` from `unless-stopped` to `"no"` |
| Rolls fragmented into separate chains + double-counted the buy-to-close | Roll detection switched from SELL look-back to BUY look-ahead so the chain isn't closed before the roll's SELL can continue it; `test_rolls.py` added |
| `poll_market` wrote `source=NULL` (login path wrote `source="ibkr"`) | Set `source="ibkr"` on the recurring market snapshot too |
| Startup burst tied to backend boot, so on-demand logins missed it | `rearm_burst()` re-anchors the burst window to login time |
| CSV importer read buy/sell from IBKR's `Code` column (trade codes, not B/S) | Derive side from the `Buy/Sell` column or the sign of `Quantity` |
| Missed 2FA push couldn't be retried — `start()` is a no-op on an already-running container, and IBEAM gives up after one failed auth | Login **restarts** the IBEAM container so each click re-runs login and pushes a fresh 2FA |
| Late 2FA approval was auto-logged-out by the monitor (stray-session release) | Monitor adopts a freshly authenticated session if the user requested login within the last 5 min |
| Login timeout (45 s) was shorter than IBEAM startup, so logins timed out before approval | Raised `PULL_LOGIN_TIMEOUT_SECONDS` default to 120 s (under nginx's 180 s) |

---

## What's implemented (as of 2026-06-20)

- ✅ Full Docker Compose stack (db / ibkr-gateway / backend / frontend; redis optional)
- ✅ FastAPI backend with SQLAlchemy schema, Alembic migrations (0001–0004)
- ✅ IBKR CP client — rate-limited (~5 req/s), snapshot warm-up, paginated positions, `pull_all()` batch orchestrator
- ✅ Flex Web Service client — standalone IBKR API for full trade history import
- ✅ `normalize.py` — pure functions, 16 unit tests
- ✅ Poller jobs: positions (+ Greeks) / account / trades / market (history + signal) / session_monitor / public_price_refresh / import_flex_trades / build_rolls
- ✅ Analytics: `indicators.py`, `greeks.py` (BS fallback), `signal.py`, `enrichment.py`, `risk.py`, `rolls.py` — 40 tests
- ✅ REST API: health / session / meta / login / logout / settings / contracts-search / positions / account / alerts / trades (recent + all options + CSV upload) / chains / market / signals / signal history / risk
- ✅ WebSocket session + data push
- ✅ User-initiated session management — no persistent keep-alive; passive monitor releases stray sessions; manual login/logout; Docker-based container start/stop
- ✅ Public price fallback via yfinance → `market_snapshots.source = "public"`
- ✅ Freshness metadata: `source` and `last_updated` on all response models
- ✅ Roll-chain grouping: detection from executions, `roll_chains` + `roll_chain_legs` tables, `/api/chains` endpoint, UI with cumulative credit and closed chain history
- ✅ IBEAM login resilience: strategy A, manual 2FA, updated selectors, error screenshots
- ✅ Frontend: HeaderBar (login/logout buttons + freshness badges), UnderlyingsPanel, SignalPanel, PositionsPanel (enriched cockpit + roll-chain grouping + refresh button), AlertsPanel, RiskPanel

## What remains

- ⬜ Per-position decay curve (theta-decay mini-chart per option row)
- ⬜ Premium income panel: `/api/income` + IncomePanel + withdrawal/"cashed-out" tracking (new table + write endpoints)
- ⬜ Signal history chart + backtest view (frontend time-series chart from `signal_history`)
- ⬜ VIX / market-context chart (6–12 month price with 50-day overlay; echarts/lightweight-charts already deps)
