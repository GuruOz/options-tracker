# Security

This document covers the threat model, the risks accepted (deliberately, not
by oversight), the recommended exposure model, and operational runbooks. It
assumes you've read the [README](../README.md) quick start.

For the design history behind these controls, see
[SECURITY_HARDENING_PLAN.md](SECURITY_HARDENING_PLAN.md) — the phase-by-phase
implementation plan this document's controls came from.

---

## Threat model

**Assets:** your IBKR positions, trades, and account balances; the IBKR
session itself (a live gateway login can be used to place trades if the API
surface were ever extended); the Postgres database (full trade history);
backup files; the shared login credential.

**Adversaries assumed:**
- A LAN-adjacent attacker — another device on your home network, or on a
  network you've bridged into via Tailscale/WireGuard, that is compromised or
  malicious.
- An attacker who obtains a copy of the repo/backups (e.g. a stolen laptop, a
  leaked cloud backup) — covered by encrypted-at-rest backups and gitignored
  secrets.
- Not assumed: a fully compromised host running the Docker stack itself. If
  the host is owned, every control here is moot — this is a self-hosted
  single-tenant app, not a multi-tenant platform defending against its own
  operator.

**Entry points, in order of exposure:**
1. The published HTTPS port (`APP_PORT`, default 8443) — gated by TLS + the
   shared login (Phases 1-2).
2. The Docker socket, historically mounted directly into the backend — now
   mediated by `docker-proxy` with a minimal allowlist (Phase 3).
3. Parser input: IBKR Flex XML (auto-import), CSV upload, on-demand yfinance
   symbol lookups, the settings API (Phase 4).
4. Backups on disk (Phase 5) and the CI/supply-chain surface (Phase 6).

## Accepted-risk register

These are known trade-offs, kept deliberately rather than fixed, because the
fix costs more than the residual risk given this app's single-operator,
LAN/VPN-only exposure model:

| Risk | Why it's accepted |
|---|---|
| **Single shared credential** (one username/password for the whole household) | This is a household appliance, not a multi-tenant service — the people who share it already share the IBKR data it displays. Per-user accounts would add real complexity (RBAC, invite flows) for no threat this model actually faces. |
| **`IBKR_GATEWAY_VERIFY=false`** — the backend doesn't verify the gateway's self-signed TLS cert | The gateway is only reachable on the internal `docker-proxy`-isolated Docker network, never published. To harden anyway: build a PKCS12 keystore from the Phase-1 local CA, mount it over the gateway's `vertx.jks`, and set `IBKR_GATEWAY_VERIFY=/path/to/pem` (`backend/app/core/config.py:91-99` already accepts a CA-bundle path). |
| **IBEAM password stored plaintext by default** | The Fernet-encryption opt-in (`IBEAM_KEY` in `.env.example`) trades a marginal improvement (the key has to live somewhere too — usually the same `.env`) for meaningfully more operational fragility (an empty/wrong key silently breaks login). Plaintext is the safer default for a single-operator deployment; encrypt if your `.env` itself is at higher risk than usual (e.g. it's backed up somewhere less trusted). |
| **db-backup container runs as root** | `./backups` is a host bind mount so you can browse/rsync it directly; Docker creates that directory root-owned, and a fixed non-root uid can't reliably write to it across both a fresh clone and a pre-existing deployment. The container's blast radius is already minimized: `cap_drop: [ALL]`, `no-new-privileges`, and it only ever shells out to `pg_dump`/`age` against its own database — see the inline `trivy:ignore` comment in `backup/Dockerfile`. |
| **IBKR Flex token sent as a URL query parameter** | This is IBKR's own Flex Web Service protocol (`backend/app/clients/ibkr/flex_web.py`), not something this app controls — the request is HTTPS so the query string isn't visible in transit, only in things like proxy/access logs. Recommended mitigation: IP-restrict the Flex token in IBKR Account Management → Settings → Flex Web Service to your server's egress IP. |

## Exposure model

**Recommended:** `APP_BIND=127.0.0.1` (the default since Phase 1) plus a VPN
overlay — Tailscale or WireGuard — for access away from home. Add the overlay
interface's IP to `EXTRA_SANS` and rerun `scripts/gen-certs.sh` so the TLS cert
covers it:

```bash
EXTRA_SANS="IP:100.x.y.z" bash scripts/gen-certs.sh
docker compose restart frontend
```

Then reach the dashboard at `https://100.x.y.z:8443` from any device on your
tailnet/VPN.

**Never port-forward `APP_PORT` to the public internet.** The login page is
rate-limited and lockout-protected, but it is not a substitute for keeping the
app off the open internet entirely.

## Runbooks

### Rotate the shared password
```bash
docker compose run --rm --no-deps --entrypoint python backend -m app.cli.hash_password
# paste the printed hash into .env as AUTH_PASSWORD_HASH='...' (single quotes!)
docker compose up -d backend
# invalidate every existing session so old cookies stop working immediately:
docker compose exec db psql -U options -d options -c "DELETE FROM auth_sessions;"
```

### Renew the TLS certificate (yearly reminder — 825-day validity)
```bash
bash scripts/gen-certs.sh   # the CA persists; only the server cert is reissued
docker compose restart frontend
```

### Rotate the Postgres password
```bash
docker compose exec db psql -U options -d options -c "ALTER USER options WITH PASSWORD '<new password>';"
# update POSTGRES_PASSWORD in .env to match, then:
docker compose up -d backend db-backup
```

### Rotate the backup encryption key (age)
```bash
docker run --rm alpine:3 sh -c "apk add -q age && age-keygen"
# store the new private key off-server; update AGE_RECIPIENT in .env with the new public key
docker compose up -d db-backup
# old backups remain readable only with the OLD private key — keep it until you no longer need them
```

### Rotate an IBKR Flex token
Generate a new token in IBKR Account Management → Settings → Flex Web Service,
then update `IBKR_FLEX_TOKEN` (or `IBKR_USER{n}_FLEX_TOKEN`) in `.env` and
`docker compose up -d backend`.

### Rotate the IBEAM Fernet key (if you opted in)
Generate a new key, re-encrypt each `IBEAM_ACCOUNT`/`IBEAM_PASSWORD` pair with
it (see `.env.example`), update `.env`, then `docker compose up -d backend
ibkr-gateway ibkr-gateway-2`.

## Dependency cadence

- **Weekly:** review and merge Dependabot PRs after CI is green.
- **Monthly:** `docker compose pull && docker compose up -d --build` to pick
  up base-image patches for images not managed by Dependabot version pins
  (e.g. `postgres:16-alpine` floating on the minor tag).
- **Quarterly:** review the pinned digests/tags that don't auto-update via
  Dependabot — the IBEAM image digest, `tecnativa/docker-socket-proxy`,
  `nginxinc/nginx-unprivileged` — against upstream for newer stable releases.

## Audit trail

The backend logs structured JSON events (via structlog) for every request and
every auth action. Useful greps against `docker compose logs backend`:

| Event | Meaning |
|---|---|
| `auth_login_success` / `auth_login_failed` | A login attempt, with `client_ip` |
| `auth_logout` | A session was explicitly ended |
| `http_request` | Every API request (method, path, status, duration, client_ip) — `/api/health` is excluded, it fires every 15s |

```bash
docker compose logs backend | grep auth_login_failed   # brute-force attempts
docker compose logs backend | grep http_request         # full access log
```
