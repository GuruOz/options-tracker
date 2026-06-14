# Options Tracker — Product Spec (v1)

Self-hosted, read-only dashboard for an options seller (cash-secured puts on index ETFs / large caps). All data flows from IBKR via the Client Portal Gateway; the browser never contacts IBKR directly.

---

## Six panels (v1 scope)

All panels read from the Postgres cache the poller fills, giving unbounded history beyond IBKR's ~7-day live window.

| # | Panel | Purpose |
|---|-------|---------|
| 1 | **Signal gauge** | "Is now a good time to sell?" composite score per tracked underlying |
| 2 | **Open-positions cockpit** | DTE, % premium captured, cushion, extrinsic value, IBKR Greeks, capital-at-risk, per-position decay curve, status pill, roll-chain grouping |
| 3 | **Needs attention today** | Ranked alert list: take-profit triggered, expiry imminent, near-strike |
| 4 | **Portfolio risk** | Account summary, beta-weighted −10% scenario, assignment-coverage gauge, equity curve |
| 5 | **Premium income** | Commission-net realized P&L (month / YTD / all-time + monthly bar series), win rate, yield; plus per-month withdrawal / "cashed-out" / remaining-profit tracking (manual entries) |
| 6 | **Market context** | Price / IV / RV / IV-pct / RSI / SMA / VIX + 6–12 month chart with 50-day overlay |

A **Flex Query / activity-statement importer** (CSV or XML) backfills pre-first-run history into `executions` by exec id.

---

## Signal scorer

Configurable via `settings` (stored in Postgres, editable at runtime via `PUT /api/settings`).

**Weights (default):**
| Sub-score | Weight | Inputs |
|-----------|--------|--------|
| IV percentile | 0.34 | Persisted IV series vs. 252-day window |
| Variance premium | 0.20 | `(IV − RV) / RV`; +20% spread ≈ score 100 |
| Trend | 0.26 | Price vs. 50-day SMA |
| RSI / drawdown filter | 0.20 | RSI(14); drawdown from 126-day high |

**Verdict thresholds:** ≥ 66 → FAVORABLE · 45–65 → SELECTIVE · < 45 → WAIT

Every poll persists score + all sub-inputs + weights to `signal_history` → enables a signal-history chart and simple backtest. This is a **decision aid, not a recommendation**.

---

## Reference numbers

- **Black-Scholes fallback:** `r = 4.5%`, using IBKR IV. Used **only** when a live Greek is missing; label such values "est.".
- **Greeks source:** directly from IBKR `/iserver/marketdata/snapshot` (73xx field family). Do not BS-estimate when IBKR provides them.
- **IV rank / percentile:** computed by us from the persisted IV series (≥ 5 observations required).
- **Beta map (Nasdaq-equivalent):** TQQQ 3.0 · QLD 2.0 · SSO 1.7 · QQQ/QQQM 1.0 · SPY/VOO 0.85 · single-stock tech ~1.05–1.7 · long-bond ETFs negative. Prefer live beta-weighted delta where feasible. Label the −10% move a **LINEAR estimate**.
- **Alert thresholds:** take-profit ≥ 70% premium captured · expiry ≤ 2 DTE · near-strike < 3% cushion.
- **Commissions:** net ALL premium figures of commissions (the original prototype ignored commissions — must be corrected).
- **Underlyings:** user-chosen via the in-app contract search UI (`GET /api/contracts/search?q=…`). Do **not** hardcode any ticker.

---

## Premium-income panel — Excel tracker replication

The user's existing Excel tracker (`Options tracker - Guru.xlsx`) has:
- Monthly tabs (Jul 2025 – Jun 2026): Ticker / Date / Strike / Expiry / Event (Buy/Sell to Open/Close) / Price / Status (OPEN/CLOSED) / Total P&L
- A **Total P&L** tab: Month · Month P/L · Cashed out? (Yes/No) · YTD (2025 / 2026) · Withdrawal month + Amount + Remaining

The income panel must **replicate this monthly → YTD layout** and add a **withdrawal / "cashed out" / remaining-profit** tracking overlay (manual entries per month). This is a new item not in the original brief.

---

## Build order

1. ✅ Scaffold (Docker Compose, FastAPI, schema, Alembic, React shell)
2. ✅ Data ingestion (IBKR client, poller jobs, normalize, positions/account/trades APIs)
3. ✅ Analytics math (indicators, Greeks BS fallback, signal scorer — 35 tests)
4. ✅ Market context + Signal panels (market poller, `/api/market`, `/api/signals`)
5. ⬜ Cockpit enrichment (DTE / cushion / extrinsic / decay curve / status pill / roll-chain)
6. ⬜ Alerts panel (`/api/alerts` + AlertsPanel)
7. ⬜ Portfolio risk panel (beta-weighted delta math → `/api/risk` + RiskPanel)
8. ⬜ Premium income panel (`/api/income` + IncomePanel + withdrawal tracking)
9. ⬜ Flex / CSV importer
