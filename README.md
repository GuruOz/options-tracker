# Options Tracker

A **free, open-source, self-hosted** dashboard for options sellers — built for
people who systematically sell cash-secured puts on index ETFs and large-caps.
It connects **directly to your own Interactive Brokers account**, is **strictly
read-only** (it can never place, modify, or cancel an order or move funds), and
keeps **all your data on your own machine**.

> **Informational only — not investment advice.** The signal score, beta-weighted
> exposure, and any Black-Scholes fallback Greeks are estimates and may be wrong.

This is **one stack per user, per IBKR account**. A single IBKR gateway
authenticates exactly one account, so there is no multi-tenant SaaS — you clone
this repo and run it yourself.

---

## Architecture

```
browser ──HTTPS──▶ nginx ──/api,/ws──▶ backend ──┬─▶ ibkr-gateway ──read-only──▶ IBKR
 (your machine)   (frontend)          (FastAPI)  ├─▶ PostgreSQL
                                                 └─▶ Redis (optional)
```

Everything except the dashboard port runs on a **private Docker network**. The
browser never contacts IBKR directly. See the architecture proposal for details.

| Container | Role |
|-----------|------|
| `frontend` | nginx — serves the SPA and reverse-proxies `/api` + `/ws`. The only host-published port. |
| `backend` | FastAPI — polls the gateway, persists to Postgres, computes analytics, serves REST + WebSocket. |
| `ibkr-gateway` | [IBEAM](https://github.com/Voyz/ibeam) — runs the IBKR Client Portal Gateway headless and keeps the session alive. |
| `db` | PostgreSQL — durable storage on a named volume. |
| `redis` | *(optional)* cache / rate-limit buckets / job queue. Off by default. |

---

## Quick start

**Prerequisites:** Docker + Docker Compose, and an Interactive Brokers account
with the market-data subscriptions you need (see below).

```bash
cp .env.example .env
# edit .env — at minimum IBEAM_ACCOUNT, IBEAM_PASSWORD, POSTGRES_PASSWORD

docker compose up --build
```

Then open **http://127.0.0.1:8080**.

On first launch the gateway will try to log in. **If your account has 2FA, you
must approve the push notification in the IBKR mobile app.** Until you do, the
dashboard shows a *"Gateway disconnected — re-authenticate"* banner. This is
normal — once approved, polling resumes automatically.

To run with Redis enabled:

```bash
docker compose --profile redis up --build   # and set REDIS_URL in .env
```

---

## IBKR session behaviour (read this)

- **2FA on first login.** If enabled on your account, the first authentication of
  each session needs a manual approval on your phone. There is no way to make a
  2FA account fully unattended — that's an IBKR rule.
- **Daily forced re-auth.** IBKR expires the session around its daily maintenance
  window (plus weekly server resets). The app treats *disconnected* as a normal,
  recurring state: it pauses polling, shows the re-auth banner, and resumes
  automatically once the gateway is authenticated again.
- **Paper vs live.** This is chosen by **which IBKR username** you put in
  `IBEAM_ACCOUNT`. IBKR paper accounts have their own separate login. **Validate
  with your paper account first.**

---

## Required IBKR market-data subscriptions

Live prices, option Greeks (delta/gamma/theta/vega/IV), and IV/realized-vol
inputs require the relevant **market-data subscriptions** on your IBKR account
(e.g. US securities snapshot/streaming bundles, and options data for the
underlyings you track). Without them, affected fields show **"n/a"** rather than
guessed values. Configure subscriptions in IBKR Client Portal → Settings →
Market Data Subscriptions.

---

## Configuration

All runtime knobs live in `.env` (see `.env.example`). User-facing analytics
settings — signal weights/thresholds, the beta map, alert thresholds, tracked
underlyings — are stored in the database and editable at runtime via the
settings API (`GET`/`PUT /api/settings`); defaults reproduce the values in the
appendix below.

---

## Backup & restore

Your history lives in the `pgdata` Docker volume.

```bash
# Backup
docker compose exec -T db pg_dump -U options options > backup.sql

# Restore (into a running, empty db)
docker compose exec -T db psql -U options -d options < backup.sql
```

Adjust the user/db names if you changed them in `.env`.

---

## Security & privacy model

- IBKR credentials live only in `.env` / Docker secrets and are git-ignored.
- The gateway, database, and Redis are **never published to the host's public
  interface** — only `frontend` binds a port, on loopback (`127.0.0.1`) by default.
- The backend is **read-only to IBKR**: the API client exposes no order or
  funds-transfer endpoints.
- **No third-party servers, no telemetry.** All data stays in your stack.
- The gateway uses a self-signed cert on the internal network; verification is
  off by default (`IBKR_GATEWAY_VERIFY=false`) because that network is private.
  To harden, mount the gateway cert and point `IBKR_GATEWAY_VERIFY` at it.

---

## Troubleshooting

- **`Fernet key must be 32 url-safe base64-encoded bytes` in the gateway logs** —
  an empty `IBEAM_KEY` was passed. Don't set `IBEAM_KEY` unless you're using an
  encrypted password (it's commented out by default).
- **Backend banner stuck on "not authenticated" while IBEAM logs say
  "authenticated"** — the gateway is denying the backend's IP. The gateway only
  allows whitelisted IPs (`ips.allow` in [gateway/conf.yaml](gateway/conf.yaml)),
  which this repo widens to the private Docker ranges. If you changed the Compose
  network subnet, add it there and recreate the gateway.
- **No 2FA push appears** — the login is failing before the credential step
  (see the gateway logs). Fix the underlying error; the push only fires once
  IBKR receives your username/password.

## Development

```bash
# Backend
cd backend
pip install -r requirements.txt
pytest

# Frontend (Vite dev server proxies /api and /ws to localhost:8000)
cd frontend
npm install
npm run dev
```

---

## Roadmap (post-v1)

- Optional **multi-account** support via one gateway container per account.
- Celery + Redis workers if polling needs to scale horizontally.
- Signal backtest view and richer roll-chain analytics.

---

## Appendix — reference defaults

- **Signal weights:** IV-percentile 0.34, variance-premium 0.20, trend 0.26,
  RSI/drawdown 0.20. Thresholds: ≥66 FAVORABLE, 45–65 SELECTIVE, <45 WAIT.
- **Black-Scholes fallback** (only when a live Greek is missing): r = 4.5%, IBKR's IV.
- **Beta map (Nasdaq-equivalent):** TQQQ 3.0, QLD 2.0, SSO 1.7, QQQ/QQQM 1.0,
  SPY/VOO 0.85. Prefer live beta-weighted delta where available.
- **Alerts:** take-profit at ~70% premium captured, expiry at ≤2 DTE,
  near-strike at <3% cushion.
- All premium figures are **net of commissions**.
