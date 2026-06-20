# Options Tracker — Implementation TODO

Living checklist of pending work. **Cross items off (`[x]`) as they land** and add a
one-line note on what was done. Source of truth for scope is [spec.md](spec.md)
(six panels + build order) and [architecture.md](architecture.md) ("What remains").

Conventions for new work:
- Backend analytics = pure functions in `backend/app/analytics/*.py` + unit tests in `backend/tests/`.
- New read endpoints go under `/api`, registered in `backend/app/api/__init__.py`.
- Pydantic response models in `backend/app/schemas/responses.py`; TS mirror in `frontend/src/api/types.ts`.
- Frontend panels are components under `frontend/src/components/`, fetched with TanStack Query, wired in `App.tsx`.
- WS pushes (`positions`/`account`/`market`/`signals`/`trades`) invalidate query keys in `frontend/src/api/useSession.ts` — add derived keys there for new panels.

---

## Done (recent)

- [x] **Bug-fix pass (2026-06-20)** — (1) roll detection rewritten from SELL look-back to BUY look-ahead: rolls no longer fragment into separate chains, the original chain stays open, and the buy-to-close is counted once (was double-counted); added `backend/tests/test_rolls.py` (7 cases). (2) `poll_market` now writes `source="ibkr"` (was `NULL`). (3) `rearm_burst()` re-anchors the startup burst to login time so on-demand logins get the fast poll window. (4) CSV importer derives buy/sell from the `Buy/Sell` column / sign of `Quantity` instead of the `Code` column; `qty` stored unsigned. (5) public-fallback IV path documented (yfinance has no IV → IV sub-scores intentionally absent). (6) cleanup: removed dead `poll_marketdata_seconds`, `csv_import` extractors/`_MONTH_MAP`/`import re`; clarified `account_series` docstring.
- [x] **Session refactor** — removed persistent keep-alive (tickle/reauth loops); added user-initiated login/logout via Docker start/stop + passive monitor gatekeeper; added yfinance public price fallback (`public_price_refresh` job); added freshness metadata (`source`/`last_updated`) to all response models; new `POST /api/session/login` and `/logout` endpoints; IBEAM maintenance disabled (`IBEAM_MAINTENANCE_INTERVAL=86400`); Docker socket mounted for container start/stop. `0003_add_market_source` alembic migration.
- [x] **Roll-chain grouping** — `backend/app/analytics/rolls.py`: detects rolls (buy-to-close + sell-to-open within 5 min on same underlying+right); keyed by `conid` for multi-chain accuracy; `poller/jobs/rolls.py`: periodic builder job with DB cross-batch awareness; `/api/chains?status=open|closed|all` endpoint; `PositionsPanel.tsx`: chain grouping with cumulative credit display + closed chain historical table; unique constraint on `roll_chain_legs(chain_id, exec_id)` (migration `0004`); version bumped to 0.2.0.
- [x] **Flex Web Service historical import** — standalone IBKR API client (`flex_web.py`); calls `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService` directly (no CP Gateway); two-step SendRequest → poll GetStatement; parses XML with existing `flex_parse.py`; auto-runs on every login + hourly via `import_flex_trades` job; idempotent upsert by exec_id. Requires `IBKR_FLEX_TOKEN` + `IBKR_FLEX_QUERY_ID` in `.env` (one-time IBKR Account Management setup).
- [x] **CSV upload** — `POST /api/trades/upload` for IBKR Activity Statement CSV; `csv_import.py` parser; "Import CSV" button in Option Trades section.
- [x] **Expose app to LAN** — set `APP_BIND=0.0.0.0` in `.env` (compose already templates `${APP_BIND:-127.0.0.1}`); `host: true` added to `frontend/vite.config.ts` for dev.
- [x] **Cockpit enrichment core** — DTE, cushion, % premium captured, intrinsic/extrinsic, status pill (`backend/app/analytics/enrichment.py`, `PositionsPanel.tsx`).
- [x] **Cushion logic reviewed** — formula `(spot−strike)/spot` (puts) confirmed correct.
- [x] **Intrinsic/Extrinsic fix** — no longer fabricates intrinsic=0 when underlying spot is unknown; returns `null` instead.
- [x] **Show underlying spot price** — new `underlying_price` field end-to-end + "Spot" column.
- [x] **Column header tooltips** — all PositionsPanel headers have `title` tooltips.
- [x] **Alerts panel** — `/api/alerts` + `AlertsPanel.tsx` (wired in `App.tsx`).
- [x] **Portfolio risk panel** — `/api/risk` + `RiskPanel.tsx`: beta-weighted −10% scenario, assignment coverage gauge, equity-curve sparkline.
- [x] **Removed MarketPanel** from dashboard.
- [x] **Manual refresh button** on PositionsPanel — invalidates positions/chains/trades/alerts/risk/account queries.
- [x] **IBEAM auth fixes** — Strategy A + `MANUAL_TWO_FA=true` + updated selectors (`silver` 2FA field, `button[type="submit"]`, `user_name`); NGINX `proxy_read_timeout: 180s`; login timeout 120s + 30s grace period.

---

## Pending — features

### 1. Premium income panel  _(spec panel 5, build step 8)_
- [ ] Backend `/api/income`: commission-net realized P&L from `executions` — month / YTD / all-time + monthly bar series, win rate, yield.
- [ ] Withdrawal / "cashed-out" / remaining-profit tracking (manual entries per month) — needs a new table + write endpoints (this is the one place the app accepts user input).
- [ ] `IncomePanel.tsx` replicating the Excel monthly → YTD layout (see spec "Excel tracker replication").
- [ ] Net **all** premium figures of commissions (spec calls out the prototype ignored these).

### 2. Per-position decay curve  _(spec panel 2)_
- [ ] Compute/serve a theta-decay curve per option (extrinsic value vs. time to expiry) and render a mini-chart in the cockpit row/expander.

### 3. Signal history chart + backtest  _(spec signal section)_
- [ ] Frontend time-series chart of composite score from `signal_history` (endpoint already exists).
- [ ] Simple backtest view replaying persisted scores against outcomes.

---

## Pending — polish / follow-ups

- [ ] **Break-even cushion option** — optionally measure cushion to break-even (`strike − premium`) instead of (or alongside) the strike. (User decision pending.)
- [ ] **VIX / market-context chart** — spec panel 6 wants a 6–12 month price chart with 50-day overlay + VIX. `echarts` and `lightweight-charts` are already in `package.json` but unused.
- [ ] **Assignment coverage basis** — currently `cash / obligation`; revisit whether `available_funds` or margin should factor in.

---

## Roadmap (post-v1, README)

- [ ] Optional **multi-account** support (one gateway container per account; schema already carries `account_id` FKs).
- [ ] Celery + Redis workers if polling needs to scale horizontally.
