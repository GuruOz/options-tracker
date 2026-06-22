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

- [x] **Data-correctness pass — P&L reconciles to the Excel (2026-06-21)** — cleared the whole "bugs & data correctness" section. Two credit bugs fixed: (1) flex stored *signed* quantity (everything else stores unsigned magnitude + `side`) → `abs()` in `flex_parse.py`; (2) `_credit()` treated IBKR's *negative* commission as a positive magnitude, adding it instead of subtracting → `abs(comm)`. Pinned to the source of truth via `test_excel_reconciliation.py` (Aug 2025 = 1267, Feb 2026 = 3153 reproduce the sheet ×100). Income panel inherits the fix. New `GET /api/diagnostics/executions` for field-by-field reconciliation against the sheet. Decided with the user: keep dollars/commission-net, reconcile (don't display points). PositionsPanel: Closed-chains moved above Option-trades, both collapsible.
- [x] **Roll-Chain Redesign bug-fix pass (2026-06-21)** — fixed five issues found in review: (1) builder keyed chains by the full OCC `symbol` (expiry-encoded) so rolling the same strike to a new expiry fragmented into separate chains — now keys on the underlying *ticker* (`_underlying_ticker`) and stores the ticker as `underlying_symbol`; (2) assignment/stock-close matching failed for the same reason (option OCC symbol vs stock ticker) — now matches; (3) manual `/chains/{id}/link` & `/close` endpoints crashed (`ChainAdjustment(action=…)` — no such column) and adjustments were never applied — fixed the constructor, implemented `_apply_adjustments` (manual_close + cross-strike manual_link merge), and the endpoints now trigger an immediate rebuild; (4) flex `OptionEAE` expirations were labeled `bought_back` — now labeled `expired`; (5) cross-strike merged label derived from legs (real `216→210P`). Also: synthetic-expiry leg timestamps use the expiry date (were the open date); leg-credit in `roll_chain_summaries` reuses `_credit` (guards `qty=None`). Tests use realistic OCC symbols now (the old `QQQ`-only tests masked #1/#2); 12 cases pass.
- [x] **Roll-Chain Redesign (Point 3)** — Deterministic builder with strike-scoped grouping, 60-day continuation rule, synthetic expirations via `OptionEAE` flex data, and assignment handling. Added cross-strike merged labels (`NVDA 216→210P`), close reason pills, and expandable leg history in the UI.
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

## Pending — bugs & data correctness  _(2026-06-21 user feedback — high priority)_

All cleared 2026-06-21. Unit target decided with the user: **keep dollars, commission-net**; the webapp *reconciles* to the Excel (points×100 − commissions), it does not display points.

- [x] **P&L Stock Assignment accounting** — fixed 2026-06-21. Modified `_credit()` to correctly return dollar P&L for STK legs, fixing the issue where P&L was skewed by omitting stock assignment costs and stock sale revenue.
- [x] **Expandable Roll Chain UI stock labels** — fixed 2026-06-21. UI now maps STK leg roles to human readable strings like "Stock Assigned" and "Stock Sold", and map loop syntax error resolved.
- [x] **IBKR 500 API Gateway errors** — fixed 2026-06-21. Re-mapped `httpx` and `IBKRServerError` retries so transient 500 API errors from `iserver` are retried instead of bombing the poller.
- [x] **Closed chains placement + collapsible option trades** — done 2026-06-21. Moved the **Closed chains** section *above* **Option trades** in `PositionsPanel.tsx`; Option-trades now uses the same collapsible disclosure (default collapsed, ▶ caret + count). `tsc` clean.
- [x] **Cumulative credit sign** — fixed 2026-06-21. Confirmed root cause: `flex_parse.py` stored the quantity *signed* while `csv_import`/`normalize`(poll)/`OptionEAE` all store the unsigned magnitude, and both `_credit()` and the `_opt_pos` position tracking in `rolls.py` assume unsigned (direction from `side`). A flex SELL got `qty<0` AND `side="S"` → credit flipped. Fix: `abs()` the quantity in `flex_parse.py` (the lone offender).
- [x] **Verify cumulative-credit calculation** — done 2026-06-21. Found a *second* bug: `_credit()` did `gross - comm` / `-(gross + comm)` treating commission as a positive magnitude, but IBKR reports `ibCommission`/`Comm/Fee` **negative** → commissions were being *added*. Now `abs(comm)` (and `abs(qty)` defensively). Added `backend/tests/test_excel_reconciliation.py`: Aug 2025 (QQQM 350 + QQQ 917 = 1267) and Feb 2026 (3153) chains transcribed from the Excel reproduce the sheet totals exactly (×100, zero commission).
- [x] **Income panel P&L** — resolved 2026-06-21 by the credit-sign fix; `analytics/income.py` just aggregates chain `cumulative_credit` by open month. Audited it: no separate sign/aggregation bug, `test_income` passes, and attribution-by-open-month matches how the Excel assigns chains to monthly tabs.
- [x] **Excel tracker as source of truth + IBKR raw-data logging** — done 2026-06-21. (a) Excel chains encoded as reconciliation unit tests (above). (b) New `GET /api/diagnostics/executions` (`api/routes/diagnostics.py`) dumps every parsed execution with its raw IBKR payload + the derived per-leg credit + a per-underlying credit rollup, so live IBKR data can be compared field-by-field against the sheet. `repo.all_executions()` added.

## Pending — features

### 1. Premium income panel  _(spec panel 5, build step 8)_ — ✅ done 2026-06-21
- [x] Backend `/api/income`: commission-net P&L aggregated from roll chains — month / YTD per year / all-time + monthly bar series, realized vs unrealized split, win rate, yield (`analytics/income.py`, `routes/income.py`). Attribution is by the chain's *open* month (matches the Excel tabs).
- [x] Withdrawal / "cashed-out" / remaining-profit tracking — `income_adjustments` table (migration `0006`) + `PUT /api/income/adjustments` upsert (one row per account+month; the only user-entered data in the app).
- [x] `IncomePanel.tsx` replicating the Excel monthly → YTD layout: stat cards, monthly bar chart, per-year YTD/withdrawn/remaining cards, and an editable monthly table (cashed-out checkbox, withdrawal, note). Wired in `App.tsx`; `["income"]` invalidated on positions/trades pushes.
- [x] Net **all** premium figures of commissions — chain `cumulative_credit` is already commission-net, so the income rollup inherits it.
- [x] Follow-up (decided 2026-06-21): keep **dollars**, commission-net. The webapp reconciles to the Excel as points×100 − commissions (the only expected delta vs the sheet is commissions, which the sheet omits). No points toggle for now.
- [ ] **Label income charts by month — no gaps** _(2026-06-22 user feedback)_ — the monthly bar chart must show every month on the axis (Jan…Dec, or a continuous month range), including months with zero activity, instead of skipping months that have no chains. Build a dense month axis and zero-fill missing months so the timeline reads continuously.

### 2. Per-position decay curve  _(spec panel 2)_ — ✅ done 2026-06-22
- [x] **Backend + plumbing done (2026-06-22)** — `analytics/decay.py` (Black-Scholes extrinsic, IV percent/decimal guard, curve anchored to the position's real extrinsic so it matches the table) feeds a `decay_curve` field on `PositionOut` via `enrich_positions`. Rides the existing `/api/positions` payload + invalidation (no new endpoint/query key). Tests in `test_decay.py` (parity, monotonic decay, anchor, IV-scale, None guards, **Decimal inputs**). NOTE: live `iv`/`strike`/`mark` arrive as `decimal.Decimal` — inputs are coerced to float at the boundary (the float-only unit tests originally masked this; fixed + regression-tested). Reminder: backend image bakes source in (no source volume / `--reload`) → code changes need `docker compose up -d --build backend`.
- [x] **Chart UX redesign (2026-06-22)** — replaced the buried inline row-sparkline with a **dedicated `DecayPanel`** below the positions table (decided with the user: dedicated panel + row selector, "time value remaining ($)" framing, hover readout). Selection state lifted to `App.tsx` (`decayConid`) and shared between `PositionsPanel` (clicking a chartable row selects it; rows show a mini line-chart glyph + highlight when active; `PositionsPanel` auto-selects the first chartable row on load via effect) and `DecayPanel` (also has its own clickable position chips; reads the shared `["positions"]` query so no extra fetch). Chart: large SVG with $ y-axis ticks, time flowing today→expiry left→right, today marker, calendar dates on the axis, and a **mouse-tracking hover tooltip** (value, date, days left, % of today's value, $ decayed). Removed the old `DecayCurve` component + its `DecayPoint` import from `PositionsPanel`. `tsc` + `vite build` clean. To see it live: `npm run dev` in `frontend/` (HMR; no backend rebuild needed for FE-only changes).
- [x] **ITM zero-anchor bug (2026-06-22)** — found while reviewing the live chart: an ITM put (NVDA 215P, spot 205.42 < strike 215) rendered as a flat $0 line with an all-`$0` axis, despite a non-zero Θ. Root cause: when the option's mark is at/below intrinsic (stale/crossed quote — here mark $7.85 < intrinsic $9.58), `enrich_positions` clamps `extrinsic_value` to `0`, and `decay.py` then scaled the whole modeled curve by `anchor/modeled = 0` → every point zeroed. Fix: in `theta_decay_curve`, only anchor when `anchor_extrinsic > 1e-9`; a non-positive anchor is ignored and the unscaled Black-Scholes curve is returned as a **modeled estimate** (NVDA case now shows ~$126/contract decaying to 0). Frontend `DecayPanel`: (a) amber "Modeled estimate — mark below intrinsic" caveat + "Now (modeled): ≈$X" label when `extrinsic_value <= 0`; (b) empty-state ("no measurable time value") when the curve is negligible (`todayVal < $0.5`) so a degenerate flat chart never renders. Regression test `test_zero_anchor_falls_back_to_model_curve` in `test_decay.py` (9 pass). NOTE: the positions table's **Extrinsic ($)** column also shows `$0` for the same clamp reason — a data-quality artifact of mark-below-intrinsic, not fixed here.

### 3. Signal history chart + backtest  _(spec signal section)_
- [x] Frontend time-series chart of composite score from `signal_history` — per-underlying sparkline in `SignalPanel.tsx` (`ScoreHistory`), with FAVORABLE (66) / SELECTIVE (45) guide lines, fed by the existing `/api/signal/history` endpoint; `["signal","history"]` invalidated on market/signals pushes. (2026-06-21)
- [ ] Simple backtest view replaying persisted scores against outcomes.

### 4. Profit/loss projection panel  _(broker-style what-if grid)_ — ✅ done 2026-06-22
- [x] **`ProfitPanel.tsx` + `lib/options.ts` (2026-06-22)** — user-requested P&L "what-if" matrix like the tastytrade/OptionStrat grid. Per **selected position** (reuses the shared `selectedConid` that also drives the decay panel; has its own position chips). Pure **client-side** compute (`lib/options.ts`: Black–Scholes `bsPrice`/`normCdf`/`intrinsic`/`normalizeIv` + an `impliedVol` bisection solver) so the controls recompute instantly with no endpoint. Grid: rows = underlying price (high→low, "nice" round steps), columns = dates today→expiry (+ "Exp"), cells = color-coded $ P&L (green/red, intensity ∝ |P&L|), right-hand +/-% column, current-spot row highlighted, click a cell for an exit readout. **Full controls**: IV-change select (±%), Grid/Curve toggle, $ P/L vs % return, editable price range. Also a **line risk-graph** (Curve view): T+0 (solid) vs expiry (dashed) payoff, profit/loss shading via clipPaths, breakeven + spot markers, hover readout. P&L basis = `qty × (value×100 − avg_cost)` (sign verified against enrichment's `premium_captured` formula). Calibrates to the live mark via implied vol so "today @ spot" ≈ real unrealized P&L; falls back to quoted IV with an amber caveat when mark ≤ intrinsic. `tsc` + `vite build` clean (92 modules). NOTE: single-position basis — rolled chains aren't combined (deferred). Live numeric cross-check pending (IBKR session/positions feed was empty at build time).

---

## Pending — polish / follow-ups

- [x] **Roll-chain edge cases**: Partial closes now handled — the builder tracks the running option position (`_opt_pos`), so buying back 1 of 2 contracts leaves the chain open until it's flat. (2026-06-21)
- [x] **Manual cross-strike roll UI**: the `/chains/{id}/link` endpoint works (merges a chain into another by `exec_id`), and is now wired to the frontend via a "Link cross-strike" button in the ChainGroup that allows picking a leg from another chain on the same underlying.
- [x] **Verify flex `OptionEAE` quantity sign**: Confirmed that IBKR reports a negative quantity (`qty < 0`) for short positions in the Flex Query `OptionEAE` section. The builder's assumption (`qty < 0` = buy-to-close) is correct.
- [ ] **Closed-chain click-through history timeline** _(2026-06-22 user feedback)_ — in the Closed-chains table, make each row clickable to expand the *full event history* of that chain, told as a narrative sequence: sold the put → rolled → stock assigned → cleared/sold the assigned stock → sold the put again → … → expired worthless or bought-to-close. The leg data already exists (`roll_chain_summaries` returns ordered `legs` with role/date/strike/price/credit, and the open-chain `ChainGroup` already renders an expandable leg table) — reuse that expander for closed chains, ordered chronologically with the human-readable role labels so the user can read the whole lifecycle of events they took.
- [ ] **Break-even cushion option** — optionally measure cushion to break-even (`strike − premium`) instead of (or alongside) the strike. (User decision pending.)
- [ ] **VIX / market-context chart** — spec panel 6 wants a 6–12 month price chart with 50-day overlay + VIX. `echarts` and `lightweight-charts` are already in `package.json` but unused.
- [ ] **Assignment coverage basis** — currently `cash / obligation`; revisit whether `available_funds` or margin should factor in.

---

## Pending — code cleanup

- [x] Remove unused `flex_request()`, `flex_status()`, `flex_download()` from `client.py` if they weren't already removed (check current state).
- [x] Remove `SessionBanner.tsx` — dead component, replaced by HeaderBar.
- [x] Remove `AccountPanel.tsx` — dead component, replaced by HeaderBar stats.
- [x] Remove `MarketPanel.tsx` — dead component, removed from App.tsx but file still exists.

---

## Roadmap (post-v1)

- [ ] Optional **multi-account** support (one gateway container per account; schema already carries `account_id` FKs).
- [ ] Celery + Redis workers if polling needs to scale horizontally.
- [ ] Docker socket mount security: use a Docker socket proxy (e.g., `tecnativa/docker-socket-proxy`) that limits access or use `docker compose` subprocess calls instead of direct socket access.

---

## Known Issues / Operations

### IBEAM authentication instability
**Status:** Resolved for now (2026-06-20), but fragile.
**Risk:** IBKR periodically updates their login page HTML, breaking IBEAM's hardcoded CSS selectors.
If login breaks:
1. Check `gateway/outputs/` for failure screenshots (mounted volume).
2. Inspect the login page HTML to find current element IDs/names.
3. Update the selectors in `docker-compose.yml` under `ibkr-gateway` environment.

### Flex Web Service — one-time setup required
The `import_flex_trades` job calls IBKR's Flex Web Service directly. For this to work, the user must:
1. Log into IBKR Client Portal → Settings → Flex Web Service → Enable → Generate token
2. Reports → Flex Queries → Create Activity Flex Query (Sections: Trades + Option Exercises, Assignments and Expirations, Format: XML, Period: Since Inception, Breakout by Day: No)
3. Copy the token to `IBKR_FLEX_TOKEN=` in `.env`
4. Copy the query ID to `IBKR_FLEX_QUERY_ID=` in `.env`

### CSV upload parser — IBKR format sensitivity
The `csv_import.py` parser handles the standard IBKR Activity Statement CSV format, but IBKR may change column headers or date formats. If the CSV import fails, check the column headers in the downloaded file against the parser's expected keys.

### `flex_parse.py` note
The file `backend/app/clients/ibkr/flex_parse.py` handles the XML format from IBKR's Flex Web Service and IS used by `flex_web.py`. **Do not delete** — it is actively imported by `flex_web.py:fetch_flex_trades()`.
