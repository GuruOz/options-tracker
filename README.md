# Options Tracker

A **free, open-source, self-hosted** dashboard for options sellers — built for
people who systematically sell cash-secured puts on index ETFs and large-caps.
It connects **directly to your own Interactive Brokers account**, is **strictly
read-only** (it can never place, modify, or cancel an order or move funds), and
keeps **all your data on your own machine**.

> **Informational only — not investment advice.** The signal score, beta-weighted
> exposure, and any Black-Scholes fallback Greeks are estimates and may be wrong.

This is **one stack per household, self-hosted** — you clone this repo and run
it yourself, not a multi-tenant SaaS. A single stack can track more than one
IBKR login (e.g. you and a spouse): each person gets their own gateway
container and their own watchlist, with a switcher in the header to move
between accounts or view them combined. See
[Multi-user (household) setup](#multi-user-household-setup) below.

---

## Architecture

```
browser ──HTTPS──▶ nginx ──/api,/ws──▶ backend ──┬─▶ ibkr-gateway ──read-only──▶ IBKR
 (your machine)   (frontend)          (FastAPI)  ├─▶ PostgreSQL
                                                  ├─▶ Redis (optional)
                                                  └─▶ docker-proxy ──▶ Docker socket (restart gateway on demand)
```

Everything except the dashboard port runs on a **private Docker network**. The
browser never contacts IBKR directly. See the architecture proposal for details.

| Container | Role |
|-----------|------|
| `frontend` | nginx — serves the SPA and reverse-proxies `/api` + `/ws`. The only host-published port. |
| `backend` | FastAPI — polls the gateway on demand, persists to Postgres, computes analytics, serves REST + WebSocket. |
| `ibkr-gateway` | [IBEAM](https://github.com/Voyz/ibeam) — runs the IBKR Client Portal Gateway headless. Auth is user-initiated, not persistent. |
| `db` | PostgreSQL — durable storage on a named volume. |
| `redis` | *(optional)* cache / rate-limit buckets / job queue. Off by default. |

---

## Quick start

**Prerequisites:** Docker + Docker Compose, and an Interactive Brokers account
with the market-data subscriptions you need (see below).

```bash
cp .env.example .env
# edit .env — at minimum IBEAM_ACCOUNT, IBEAM_PASSWORD, POSTGRES_PASSWORD

# Generate a local CA + TLS certificate (the app only serves HTTPS):
bash scripts/gen-certs.sh

# Generate a login password hash and paste it into .env as AUTH_PASSWORD_HASH
# (single-quote it — the hash contains `$` characters):
docker compose build backend
docker compose run --rm --no-deps --entrypoint python backend -m app.cli.hash_password

docker compose up --build
```

Then import `certs/ca.crt` into your browser/OS trust store (see
[docs/SECURITY.md](docs/SECURITY.md) for per-platform instructions) and open
**https://localhost:8443**. Log in with the username (`admin` by default) and
password you just hashed.

Click **"Pull Fresh Data"** in the header bar when you want live IBKR data.
The gateway will restart, trigger IBKR's 2FA push, and the session comes up
once you approve the notification. See
[IBKR session behaviour](#ibkr-session-behaviour) below for the full flow.

**Paper vs. live** is chosen by which IBKR username you put in `IBEAM_ACCOUNT`.
IBKR paper accounts have their own separate login. Validate with your paper
account first.

To run with Redis enabled:

```bash
docker compose --profile redis up --build   # and set REDIS_URL in .env
```

---

## Network access (LAN / homelab)

`frontend` is the only service that publishes a port, and it's HTTPS-only. It
binds **`127.0.0.1` by default** (`APP_BIND` in `.env`) — reachable only from
the machine running it, at **https://localhost:8443**.

To reach it from other devices — another computer on your LAN, or over a VPN —
bind a different interface and regenerate the TLS cert to cover it:

```bash
APP_BIND=<lan-or-vpn-ip>
EXTRA_SANS="IP:<lan-or-vpn-ip>" bash scripts/gen-certs.sh
docker compose up -d frontend   # apply (frontend-only; does NOT log IBKR out)
```

Then import `certs/ca.crt` into each device's trust store — see
[docs/SECURITY.md](docs/SECURITY.md) for per-platform steps — and open
`https://<lan-or-vpn-ip>:8443`.

> Every route requires the login you set up in Quick start (`AUTH_USERNAME` /
> `AUTH_PASSWORD_HASH`), so a device on the same network still can't view your
> positions or trigger an IBKR login without that password. Still:
> - Prefer a VPN overlay (**Tailscale/WireGuard**) over binding your raw LAN
>   interface for access away from home.
> - **Never port-forward `APP_PORT` to the public internet.**
> - See [docs/SECURITY.md](docs/SECURITY.md) for the full threat model,
>   accepted-risk register, and security runbooks (password rotation, cert
>   renewal, backup key rotation).

Firewall: allow inbound TCP on `APP_PORT` (8443) on the server, if you've
bound beyond loopback. The gateway, backend, db, docker-proxy, and backups
stay on private Docker networks and are never published.

---

## Multi-user (household) setup

IBKR won't hold two Client Portal sessions on one login, so a second person
with their own IBKR account needs their own gateway container. The schema and
API were built for this from the start — adding a second user is additive, not
a migration.

1. In `.env`, fill in the `IBKR_USER1_*` and `IBKR_USER2_*` blocks (see the
   comments in `.env.example`), plus `IBEAM_ACCOUNT_2` / `IBEAM_PASSWORD_2` for
   the second person's IBKR login.
2. `docker compose up -d` — this creates a second `ibkr-gateway-2` container,
   idle until that user logs in.
3. In the dashboard header, a switcher appears with a segment per user plus
   **All**. Each person clicks their own **Pull Fresh Data** and gets their own
   2FA push on their own phone; both can be logged in at the same time.
4. Each user gets their own tracked-underlyings watchlist and alert thresholds.
   **All** shows a combined view: positions/trades/alerts merged with an
   account label, income and risk numbers summed across accounts (equity
   curves and assignment-coverage cash are *not* fungible across accounts, so
   those are shown per-account or flagged as approximate), and the watchlist as
   a read-only union. Editing anything — the watchlist, alert thresholds,
   income adjustments, CSV import — requires picking a specific account first.
5. The Flex Web Service historical-trade import is also per user
   (`IBKR_USER2_FLEX_TOKEN` / `IBKR_USER2_FLEX_QUERY_ID`) and optional — leave
   it blank until that person sets one up in IBKR Account Management.

Leave the whole `IBKR_USER*` section of `.env` blank for a single-user setup:
the backend falls back to the legacy `IBKR_GATEWAY_URL` / `IBEAM_ACCOUNT` /
`IBKR_FLEX_TOKEN` vars and behaves exactly as before.

---

## IBKR session behaviour

**Only one IBKR brokerage (iServer) session can be active at a time**, so a
persistently authenticated gateway locks you out of the IBKR mobile app. This app
is **unauthenticated by default** and only holds a session when you explicitly
ask for one.

- **No background keep-alive.** No recurring `POST /tickle`, no auto-reauth, no
  auto-login on startup. A passive monitor checks auth status but never contests
  the session — it releases any stray authenticated session immediately.
- **User-initiated login.** Click "Pull Fresh Data" in the dashboard header. The
  backend restarts the IBEAM container, which logs in and triggers IBKR's 2FA
  push. Approve the notification in your IBKR mobile app and the session comes up
  within seconds. All positions, balances, open orders, P&L, and IBKR-sourced
  market data are batch-pulled and persisted.
- **Session stays active** while you're browsing the dashboard. No forced logout.
- **Manual logout.** Click "Logout & Release" when you're done. The session is
  released and your IBKR mobile app works again immediately.
- **Public price fallback.** Prices and implied volatility for tracked underlyings
  refresh every 5 minutes from a free public source (yfinance) — no IBKR session
  needed. If the source is unreachable, the last cached values are served.
- **Data freshness.** Every API response carries a `source` field
  (`ibkr_live` / `public` / `cache`) and a `last_updated` timestamp so you can
  tell fresh data from stale at a glance.

### Login trigger mechanism

The backend needs to restart the IBEAM container to trigger a fresh browser-based
login. This requires mounting the Docker socket into the backend container (see
`docker-compose.yml`). For a self-hosted single-user app on a private network,
this is an accepted pattern. To harden, use a Docker socket proxy that limits
access to only the `ibkr-gateway` container's restart endpoint.

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

Key env vars for session behaviour:
- `IBEAM_MAINTENANCE_INTERVAL=86400` — effectively disables IBEAM's periodic auto-maintenance (auth is user-initiated; **never use `0`** — IBEAM treats it as 1 second)
- `POLL_PUBLIC_PRICE_SECONDS=300` — cadence for yfinance price refresh
- `PULL_LOGIN_TIMEOUT_SECONDS=120` — max seconds to wait for 2FA during login (must exceed IBEAM startup ~120s and stay under nginx's 180s proxy timeout)
- `DOCKER_IBEAM_CONTAINER` — container name for on-demand gateway restart

---

## Backup & restore

Your history lives in the `pgdata` Docker volume.

**Automated (default):** the `db-backup` service writes a gzipped `pg_dump` to
`./backups/` on the host nightly and prunes dumps older than 7 days. Tune with
`BACKUP_INTERVAL_SECONDS` / `BACKUP_KEEP_DAYS` in `.env`. The `backups/` dir is
git-ignored. Copy it off-box periodically — a backup on the same disk as `pgdata`
won't survive a disk failure.

```bash
# Restore the latest automated dump (into a running db)
gunzip -c backups/options-YYYYmmdd-HHMMSS.sql.gz | docker compose exec -T db psql -U options -d options

# Manual one-off backup
docker compose exec -T db pg_dump -U options options > backup.sql
```

Adjust the user/db names if you changed them in `.env`.

---

## Updating safely

This is a 24/7 stack — pull and redeploy deliberately.

```bash
git pull
docker compose up -d --build          # rebuilds backend/frontend; DB migrations
                                      # auto-apply on boot (alembic upgrade head)
```

- **A backend rebuild logs you out of IBKR** (the session is in-memory and the
  monitor releases it on restart). After redeploying, click **Pull Fresh Data**
  and approve the 2FA push to restore the session. Roll-chain/analytics rebuilds
  stay idle until you re-authenticate.
- **Dependencies are pinned** (`backend/requirements.txt` exact `==`, the gateway
  image by digest, the frontend `package-lock.json`). Bump versions deliberately
  and let **CI** (`.github/workflows/ci.yml`: backend `pytest` + frontend
  build + `docker compose config`) go green before deploying.
- **Migrations:** add a new Alembic revision under
  `backend/app/db/migrations/versions/`; it runs automatically on the next boot.
  Migrations are forward-only — back up first (see above) before a risky one.

---

## Known limitations (beta)

- **Single IBKR account / single user.** One gateway authenticates one account;
  there is no multi-tenant mode.
- **Re-login required after every redeploy** (see *Updating safely*).
- **IBEAM auth is brittle** — IBKR periodically changes its login page, which can
  break the gateway's selectors (see *Troubleshooting* + `docker-compose.yml`).
- **Manual cross-strike roll links** affect the next rebuild; a malformed link
  used to be able to stall the rebuild (fixed — rebuild is now FK-safe).
- **Market-data gaps show `n/a`**, not guesses, when you lack the IBKR
  subscription; public yfinance prices/IV are the fallback.
- Figures are **commission-net dollars** and reconcile to the Excel tracker as
  `points × 100 − commissions`; the only expected delta vs the sheet is
  commissions (the sheet omits them).

---

## License

[MIT](LICENSE) © GuruOz. Informational only — not investment advice.

---

## Security & privacy model

- IBKR credentials live only in `.env` / Docker secrets and are git-ignored.
- The dashboard is TLS-only and gated by a login (single shared account per
  household) — see [Quick start](#quick-start) to set the password.
- The gateway, database, docker-proxy, and Redis are **never published to the
  host's public interface** — only `frontend` binds a port, on loopback
  (`127.0.0.1`) by default.
- The backend never holds the raw Docker socket — a `docker-proxy` service
  mediates it, allowed only to list/inspect/start/stop/restart containers.
  Backend and frontend containers run as non-root with a read-only root
  filesystem and all Linux capabilities dropped.
- The backend is **read-only to IBKR**: the API client exposes no order or
  funds-transfer endpoints.
- **No third-party servers, no telemetry.** All data stays in your stack.
- The gateway uses a self-signed cert on the internal network; verification is
  off by default (`IBKR_GATEWAY_VERIFY=false`) because that network is private.
  To harden, mount the gateway cert and point `IBKR_GATEWAY_VERIFY` at it.
- Automated DB backups can be encrypted at rest with [age](https://age-encryption.org)
  (`AGE_RECIPIENT` in `.env.example`).

See [docs/SECURITY.md](docs/SECURITY.md) for the full threat model,
accepted-risk register, and operational runbooks (password/cert/key rotation).

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
