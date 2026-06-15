# Options Tracker — Architecture

Self-hosted, open-source, **read-only** dashboard for options sellers. One Docker Compose stack per user per IBKR account — not multi-tenant SaaS. The IBKR gateway session is the only auth; no app-level accounts or payments.

---

## Stack (locked)

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12 + FastAPI (async); APScheduler (in-process); SQLAlchemy 2.0 async + Alembic; Pydantic |
| **Database** | PostgreSQL 16 (named Docker volume) |
| **Cache** | Redis — optional, off by default (`--profile redis`); backend runs without it (in-memory fallback) |
| **Frontend** | React 18 + TypeScript + Vite; TanStack Query; ECharts (gauge/analytics) + Lightweight-Charts (price/OHLC); Tailwind CSS; light theme, responsive/accessible |
| **Gateway** | [IBEAM](https://github.com/Voyz/ibeam) (`voyz/ibeam`) — headless CP Gateway auth + keepalive |
| **Edge** | nginx — serves the built SPA and reverse-proxies `/api` and `/ws` (single browser origin). Only container with a host-published port (loopback by default) |

Account scope v1: **single account**, but the schema is multi-ready — `account_id` FKs everywhere so a v2 per-account-gateway is additive.

---

## Hard invariants

- Browser **never** contacts IBKR directly.
- Backend ↔ gateway communication is server-side only, over the internal Compose network.
- Backend is strictly **read-only** to IBKR — no order, modify, cancel, or funds-transfer endpoints exist in the client (enforced by allowlist).
- Gateway, DB, and Redis are **never** published to the host's public interface.
- Secrets live only in `.env` / Docker secrets.

---

## Session lifecycle

- 2FA push on first login.
- IBKR forces a daily re-auth (~maintenance window).
- DISCONNECTED is a normal recurring state — heartbeat via `/tickle` + `/iserver/auth/status`; poller pauses on loss; a re-auth banner is surfaced over WebSocket; auto-resumes on `/sso/validate` OK.

---

## Poller jobs & cadences

Data jobs run in two phases (see `poller/scheduler.py`). They self-skip until the session is authenticated.

- **Startup burst:** every `POLL_BURST_SECONDS` (default 20 s) for the first `POLL_BURST_WINDOW_SECONDS` (default 300 s). Fills the UI fast and accumulates IV history quickly; because jobs self-skip until auth, frequent retries mean data appears the moment login (incl. 2FA) completes.
- **Steady state:** after the burst window each job is rescheduled (via `scheduler.reschedule_job`) to its configured cadence (default 300 s / 5 min).

| Job | Steady cadence | What it does |
|-----|---------|--------------|
| `session_heartbeat` | 45 s (fixed) | `/tickle` + auth status; broadcasts WS session events |
| `poll_positions` | 300 s | Fetches positions + Greek snapshot; upserts `position_snapshots` |
| `poll_account` | 300 s | Fetches portfolio summary; upserts `account_snapshots` |
| `poll_trades` | 300 s | Fetches recent trades; upserts `executions` (idempotent by exec id) |
| `poll_market` | 300 s | Fetches 1-year daily history + live snapshot for each tracked underlying; persists `market_snapshots` + `signal_history` |

**Tracked underlyings** come exclusively from `settings.underlyings` (user-configured via the in-app UI). The market job is a no-op if the list is empty.

---

## API surface

### Session / meta
- `GET /api/health`
- `GET /api/session`
- `GET /api/meta`

### Settings
- `GET /api/settings` — full settings object
- `PUT /api/settings` — replace full settings
- `POST /api/settings/underlyings` — add one underlying `{conid, symbol, description}`
- `DELETE /api/settings/underlyings/{conid}` — remove by conid

### Contract search
- `GET /api/contracts/search?q=QQQ` — proxies IBKR secdef search, returns STK entries `{conid, symbol, description}`

### Portfolio data
- `GET /api/positions`
- `GET /api/account`
- `GET /api/trades`

### Market & signals
- `GET /api/market` — latest market snapshot per tracked underlying
- `GET /api/signals` — latest signal per underlying
- `GET /api/signal/history?conid=…` — time-series signal history

### WebSocket
- `WS /ws` — pushes `{type, resource}` events (`session`, `data`, `market`, `signals`); frontend uses these to invalidate TanStack Query caches

---

## Database schema (key tables)

| Table | Purpose |
|-------|---------|
| `position_snapshots` | One row per position per poll; `symbol VARCHAR(64)`; option fields extracted from OSI contractDesc |
| `account_snapshots` | Net liq, available funds, margin, cash, etc. |
| `executions` | Trades; idempotent upsert by `exec_id`; `source` = `poll` or `flex` |
| `market_snapshots` | Price / IV / RV / RSI / SMA per underlying per poll |
| `signal_history` | Composite score + sub-scores + inputs + weights per underlying per poll |
| `settings` | Single row (id=1); JSONB blob with signal weights, alert thresholds, beta map, `underlyings` list |

All tables carry `account_id` FKs for future multi-account support.

---

## Key implementation details

### Greek field codes
- Delta `7308` · Gamma `7309` · Theta `7310` · Vega `7311`
- IV candidates (first present wins): `7283`, `7633`, `7607`
- Historic vol: `7087`

### IV percentile / rank
Computed by us from the persisted `market_snapshots.iv` series. Requires ≥ 5 observations (accumulates at poll cadence). Returns `null` until threshold is met. If IV is `null` after several polls, check IBKR market-data subscription — the gateway logs a warning per ticker.

### Black-Scholes fallback
Used **only** when IBKR does not return a Greek. `r = 4.5%`. Output labelled "est." in the UI.

### Option symbol parsing
Positions rows leave `putOrCall` / `strike` / `expiry` null for options. The underlying, right, strike, and expiry are extracted from the OSI-format `contractDesc` string (e.g. `QQQ JUL2026 715 P [QQQ 260702P00715000 100]`) via regex.

---

## Solved gotchas

| Issue | Fix |
|-------|-----|
| Empty `IBEAM_KEY` → Fernet crash | Removed `IBEAM_KEY` from compose; document it as optional |
| Gateway returns "Access Denied" to backend | `gateway/conf.yaml` widens `ips.allow` to `127.0.0.1` / `10.*` / `172.*` / `192.168.*` (covers Docker bridge networks) |
| Option `contractDesc` (48 chars) overflowed `symbol VARCHAR(32)` → silent batch rollback | Migration `0002_widen_symbol` → `VARCHAR(64)`; `parse_option_desc` stores only the short underlying ticker |
| IBEAM login timeout on slow connections | `IBEAM_PAGE_LOAD_TIMEOUT=30` set in compose |

---

## What's implemented (as of 2026-06-14)

- ✅ Full Docker Compose stack (db / ibkr-gateway / backend / frontend; redis optional)
- ✅ FastAPI backend with SQLAlchemy schema, Alembic migrations (0001 initial, 0002 widen symbol)
- ✅ IBKR CP client — rate-limited (~5 req/s), snapshot warm-up, paginated positions
- ✅ `normalize.py` — pure functions, 16 unit tests
- ✅ Poller jobs: positions (+ Greeks) / account / trades / market (history + signal)
- ✅ Analytics: `indicators.py`, `greeks.py` (BS fallback), `signal.py` — 35 tests total
- ✅ REST API: health / session / meta / settings / contracts-search / portfolio / market / signals
- ✅ WebSocket session + data push
- ✅ Frontend: HeaderBar (connection status + account summary), UnderlyingsPanel (search + add/remove), SignalPanel, MarketPanel, PositionsPanel

## What remains

- ⬜ Cockpit panel enrichment: DTE, % premium captured, cushion, extrinsic, decay curve, status pill, roll-chain grouping
- ⬜ Alerts panel: `/api/alerts` + AlertsPanel (threshold logic on current positions)
- ⬜ Portfolio risk panel: beta-weighted delta math → `/api/risk` + RiskPanel
- ⬜ Premium income panel: `/api/income` + IncomePanel + withdrawal/"cashed-out" tracking
- ⬜ Flex / CSV importer (backfill pre-first-run history into `executions`)
