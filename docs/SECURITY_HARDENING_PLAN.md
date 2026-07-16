# Security Hardening Plan — options-tracker

> **For the implementing AI:** Execute one phase per branch/PR, in order. Each phase is
> independently shippable and ends with verification steps — run them all before moving on.
> Do not skip the "Pitfalls" sections; they encode constraints discovered by reading this
> codebase. When a pinned version is marked "verify at implementation time", check the
> registry (PyPI/npm/Docker Hub) and use the current stable of that line.

## Context

This is a self-hosted options/finance dashboard (nginx SPA + FastAPI + Postgres + IBEAM IBKR gateways via Docker Compose) holding sensitive brokerage data. Today it has **zero authentication** — every endpoint (including ones that trigger real IBKR 2FA pushes, upload trades, and mutate settings) is open to anyone who can reach the published port, which defaults to `0.0.0.0:8080` over plain HTTP. Threat model: the app itself isn't internet-exposed, but other machines on the LAN run exposed services; a compromised LAN host must not be able to read financial data or pivot through this app (notably via the Docker socket mounted into the backend, which is root-equivalent on the host).

**Decisions (final, do not revisit):** in-app session auth with a **single shared login**; TLS at nginx with a local CA **plus** localhost-bind/VPN guidance; **full** infra scope (socket proxy, container hardening, encrypted backups, CI scanning).

**Verified facts the plan relies on:**
- Routers aggregate in `backend/app/api/__init__.py` (health included there); mounted at `/api` in `backend/app/main.py:83`; `/ws` mounted separately (`main.py:84`). No middleware exists today.
- Backend compose healthcheck curls `http://127.0.0.1:8000/api/health` directly (docker-compose.yml:168) → `/api/health` must stay unauthenticated.
- Frontend healthcheck hits `http://127.0.0.1:80/` (docker-compose.yml:189) → must be updated when TLS lands.
- nginx.conf is copied to `/etc/nginx/conf.d/default.conf` (frontend/Dockerfile:14) → it is included inside the `http{}` context, so `limit_req_zone`/`map` at top of the file are legal.
- Migrations are numbered `0001`–`0009`; next is `0010`. Pattern (see `0009_account_settings.py`): `revision`/`down_revision` strings, `has_table()` guard from `app.db.migration_utils` (fresh DBs get tables via baseline `create_all`).
- Session factory is `AsyncSessionLocal` in `backend/app/db/base.py:22`.
- `PYTHONDONTWRITEBYTECODE=1` already set in backend/Dockerfile:16.
- backend/Dockerfile has no `USER` directive (runs root); frontend Dockerfile uses `npm install` not `npm ci`.
- The operator's live `.env` currently sets `APP_PORT=1337`, `APP_BIND=0.0.0.0` — the operator must update it during rollout.

| Phase | Theme | Removes |
|---|---|---|
| 1 | Bind defaults + TLS + nginx headers/rate limits | LAN-wide plaintext exposure; enables Secure cookies |
| 2 | Authentication + CSRF + WS auth + audit logging | Unauthenticated access (the big one) |
| 3 | Docker socket proxy + container hardening | Container→host escape |
| 4 | Parser/input hardening | Malicious-input classes |
| 5 | Secrets + encrypted backups | At-rest exposure |
| 6 | CI security scanning + supply chain | Silent dependency/secret regressions |
| 7 | Docs + runbooks | Operator error |

---

## Phase 1 — Exposure defaults, TLS, nginx hardening

No backend changes. Must land **before** Phase 2 (Secure cookies require TLS).

### CREATE `scripts/gen-certs.sh`
Bash, `set -euo pipefail`, output dir `./certs`. Note at top: if openssl is missing, `docker run --rm -v "$PWD/certs:/certs" alpine/openssl` works as a fallback.
- CA (skip if `certs/ca.key` exists): `openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -days 3650 -nodes -keyout certs/ca.key -out certs/ca.crt -subj "/CN=options-tracker local CA"`.
- Server key + CSR signed by the CA, 825 days, SANs `DNS:localhost,IP:127.0.0.1` plus extras from env var `EXTRA_SANS` (comma-separated, e.g. `IP:192.168.1.50,DNS:tracker.tailnet.ts.net`). Use a temp extfile with `subjectAltName=...`, `keyUsage=digitalSignature,keyEncipherment`, `extendedKeyUsage=serverAuth`.
- Outputs: `certs/server.key`, `certs/server.crt` (server cert + ca.crt concatenated = chain), `certs/ca.crt` (to import into client trust stores).
- `chmod 600 certs/server.key certs/ca.key`; print trust-import instructions for Windows/iOS/Android.

### MODIFY `frontend/nginx.conf` — full rewrite
Use unprivileged ports 8080/8443 **now** so Phase 3's non-root nginx image needs no conf change:

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=login:10m rate=10r/m;
map $http_upgrade $connection_upgrade { default upgrade; "" close; }

# Plain-HTTP listener: container-internal healthcheck only (never published).
server {
    listen 8080;
    location = /healthz { access_log off; return 200 "ok\n"; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 8443 ssl;
    http2 on;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    ssl_certificate     /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    client_max_body_size 10m;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;

    # Stricter throttle for the Phase-2 login endpoint. location blocks do NOT
    # inherit proxy_* directives — repeat them.
    location = /api/auth/login {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /api/ {
        limit_req zone=api burst=60 nodelay;
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
    }

    location /ws {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }

    location / { try_files $uri $uri/ /index.html; }
}
```

### MODIFY `docker-compose.yml` (frontend service, ~lines 177-195)
- `ports: - "${APP_BIND:-127.0.0.1}:${APP_PORT:-8443}:8443"`
- Add volume `- ./certs:/etc/nginx/certs:ro`
- Healthcheck: `wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1`

### MODIFY `frontend/Dockerfile`
- `RUN npm install` → `RUN npm ci` (line 7; lockfile exists)
- `EXPOSE 8080 8443` (cosmetic)

### MODIFY `.env.example` (web-exposure block, ~lines 73-83)
`APP_BIND=127.0.0.1`, `APP_PORT=8443`; document: run `scripts/gen-certs.sh` before first `up`; recommended remote access = Tailscale/WireGuard on the host (set `APP_BIND=<tailscale-ip>` and add it to `EXTRA_SANS`); never port-forward.

### MODIFY `.gitignore`
Add `certs/`.

### Pitfalls
- nginx fails at boot if `./certs` is empty — docs must say gen-certs first; the healthcheck surfaces it.
- The internal 8080 listener must never be published.
- Keep ALL `add_header` at server level; adding any `add_header` inside a location silently drops the inherited ones.
- CSP: `style-src 'unsafe-inline'` is required (ECharts/inline style attributes). Do NOT add `'unsafe-inline'` to `script-src` — the Vite build has no inline scripts. If the app renders blank, check the browser console for CSP violations before touching the policy.
- Operator's live `.env` currently has `APP_PORT=1337` / `APP_BIND=0.0.0.0` — must be updated at rollout.

### Verification
1. `bash scripts/gen-certs.sh && docker compose up -d --build frontend`
2. `curl --cacert certs/ca.crt https://localhost:8443/` → 200 HTML (chain valid); `curl -k https://127.0.0.1:8443/api/health` → 200 JSON.
3. `curl -sk -D- https://127.0.0.1:8443/ -o /dev/null` → all 6 security headers present.
4. From another LAN machine: connection refused.
5. `for i in $(seq 1 100); do curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1:8443/api/health; done` → some 503s (rate limit works).
6. App loads in browser, WS live updates still work. `docker compose ps` → frontend healthy.

---

## Phase 2 — Authentication, CSRF, WS auth, audit logging

Single shared login; server-side sessions in Postgres; HttpOnly+Secure+SameSite=Strict cookie; CSRF header on mutating requests; `/ws` requires the cookie. Everything under `/api` requires auth **except** `/api/health` and `/api/auth/login`.

### Backend

**MODIFY `backend/requirements.txt`** — add `argon2-cffi==25.1.0` (verify current 25.x on PyPI; any ≥23.1.0 fine).

**MODIFY `backend/app/core/config.py`** — add to `Settings` (match existing lower_snake pattern; pydantic-settings maps `AUTH_USERNAME` etc. automatically):
```python
auth_username: str = "admin"
auth_password_hash: str = ""       # argon2 hash; empty => logins rejected with 503
auth_session_ttl_hours: int = 168  # 7 days
auth_cookie_secure: bool = True    # False only for plain-HTTP local dev
auth_max_failed_logins: int = 5
auth_lockout_seconds: int = 300
```

**CREATE `backend/app/core/security.py`**
- `hash_password(pw) -> str` / `verify_password(hash, pw) -> bool` via `argon2.PasswordHasher()` (catch `VerifyMismatchError`/`InvalidHashError` → False).
- `new_session_token() -> str` = `secrets.token_urlsafe(32)`; `hash_token(t) -> str` = sha256 hexdigest (store only hashes — a DB leak can't replay sessions); `new_csrf_token()` = `secrets.token_urlsafe(32)`.
- `FailedLoginTracker`: in-memory dict keyed by client IP; `is_locked(ip)` / `record_failure(ip)` / `reset(ip)` using the two settings above. Module-level singleton `login_tracker`.

**CREATE `backend/app/cli/__init__.py`** (empty) + **`backend/app/cli/hash_password.py`**: `getpass` twice, compare, print `hash_password(pw)`. Documented run command (ENTRYPOINT swallows args, so `--entrypoint` is required):
`docker compose run --rm --no-deps --entrypoint python backend -m app.cli.hash_password`

**MODIFY `backend/app/db/models.py`** — add:
```python
class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    client: Mapped[str | None] = mapped_column(String(255))  # truncated user-agent
```

**CREATE `backend/app/db/migrations/versions/0010_auth_sessions.py`** — copy `0009_account_settings.py` structure exactly: `revision="0010_auth_sessions"`, `down_revision="0009_account_settings"`, guard `if has_table("auth_sessions"): return`, `op.create_table(...)` matching the model, downgrade drops the table. `entrypoint.sh` already runs `alembic upgrade head` on boot.

**CREATE `backend/app/db/auth_repo.py`** (thin-repo style like `app/db/repo.py`): `create_session(db, token_hash, csrf_token, ttl_hours, client)`, `get_session_by_hash(db, token_hash)`, `delete_session(db, token_hash)`, `purge_expired(db)`.

**CREATE `backend/app/api/routes/auth.py`** — two routers: `public_router` (login) and `router` (logout + me, mounted behind auth).
- `POST /auth/login`, body `LoginIn(username, password)`:
  1. Client IP = first entry of `x-forwarded-for` header, else `request.client.host`.
  2. `login_tracker.is_locked(ip)` → 429.
  3. `not settings.auth_password_hash` → 503 ("Set AUTH_PASSWORD_HASH").
  4. Check `secrets.compare_digest(body.username, settings.auth_username)` AND `verify_password(...)`. **Always run verify_password even when the username mismatches** (verify against the configured hash and discard the result) so response timing is uniform.
  5. Failure: `record_failure(ip)`, structlog `log.warning("auth_login_failed", client_ip=ip)`, 401 with a generic message.
  6. Success: `login_tracker.reset(ip)`, `purge_expired`, create session row; `log.info("auth_login_success", client_ip=ip)`; set cookies:
     - `session` = raw token, `httponly=True, secure=settings.auth_cookie_secure, samesite="strict", path="/", max_age=ttl_hours*3600`
     - `csrf_token` = csrf token, same flags but `httponly=False`.
     - Return `{"status": "ok"}`.
- `POST /auth/logout` (protected): delete session row (`request.state.auth_session`), delete both cookies, `log.info("auth_logout")`.
- `GET /auth/me` (protected): `{"authenticated": true, "username": settings.auth_username}`.

**MODIFY `backend/app/api/deps.py`** — add:
```python
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

async def require_auth(request: Request, db: AsyncSession = Depends(get_session)) -> None:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    row = await auth_repo.get_session_by_hash(db, hash_token(token))
    if row is None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired.")
    if request.method in _MUTATING:
        header = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(header, row.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")
    request.state.auth_session = row
```

**MODIFY `backend/app/api/__init__.py`** — split:
```python
public_router = APIRouter()
public_router.include_router(health.router)       # compose healthcheck hits it directly
public_router.include_router(auth.public_router)  # /api/auth/login

api_router = APIRouter(dependencies=[Depends(require_auth)])
api_router.include_router(auth.router)
# ...all existing includes unchanged (session, settings, contracts, portfolio, market, risk, income, diagnostics)
```

**MODIFY `backend/app/main.py`**
- `app.include_router(public_router, prefix="/api")` before the existing `api_router` include.
- Add access-log middleware (structlog; skip `/api/health` — it fires every 15s): log method, path, status, duration_ms, client_ip (`x-forwarded-for` fallback `request.client.host`). Use the standard `@app.middleware("http")` pass-through pattern — do not buffer/replace responses (`POST /api/session/{id}/login` runs up to 120s).

**MODIFY `backend/app/api/routes/ws.py`** — validate BEFORE `accept()`:
```python
origin = ws.headers.get("origin"); host = ws.headers.get("host", "")
if origin and urlparse(origin).netloc != host:
    await ws.close(code=4403); return
token = ws.cookies.get("session")
if not token:
    await ws.close(code=4401); return
async with AsyncSessionLocal() as db:              # from app.db.base
    row = await auth_repo.get_session_by_hash(db, hash_token(token))
if row is None or row.expires_at < datetime.now(timezone.utc):
    await ws.close(code=4401); return
# ...existing connect/loop unchanged
```

**MODIFY `docker-compose.yml`** (backend environment) — add `AUTH_USERNAME`, `AUTH_PASSWORD_HASH`, `AUTH_SESSION_TTL_HOURS`, `AUTH_COOKIE_SECURE` with the defaults shown in config.py.

**MODIFY `.env.example`** — Authentication block: the hash CLI command above, and the critical note: **single-quote the hash** in `.env` (`AUTH_PASSWORD_HASH='$argon2id$v=19$...'`) — argon2 hashes contain `$` which compose otherwise interpolates.

### Frontend

**MODIFY `frontend/src/api/client.ts`** — single fetch wrapper:
- `readCookie(name)` helper; `export class AuthError extends Error {}`.
- `apiFetch(path, init)`: for non-GET methods set header `X-CSRF-Token: readCookie("csrf_token") ?? ""`; on `res.status === 401` dispatch `window.dispatchEvent(new Event("auth:unauthorized"))` and throw `AuthError`.
- Rebuild `getJSON`/`postJSON`/`deleteJSON` on top; add `putJSON` and `postForm(path, formData)` (no Content-Type — browser sets the multipart boundary — but CSRF header still attached).

**MODIFY raw-fetch call sites** so the CSRF header rides along: `frontend/src/components/PositionsPanel.tsx` (raw `fetch` at ~lines 249 CSV upload, 355/363 chain link/close) and `frontend/src/components/IncomePanel.tsx` (~line 204) → use `postForm`/`postJSON`/`putJSON`. Grep `fetch(` under `frontend/src` to catch any others (leave `useAuth`'s own calls).

**CREATE `frontend/src/hooks/useAuth.tsx`** — context provider modeled on `useAccount.tsx`: state `"loading" | "authed" | "anon"`; on mount plain `fetch("/api/auth/me")` (NOT via apiFetch — avoids event loops) → 200 = authed else anon; listens for `auth:unauthorized` → anon; `login(username, password)` posts `/api/auth/login` with plain fetch (no CSRF needed pre-session; surface 401/429/503 messages distinctly); `logout()` via `postJSON` then anon.

**CREATE `frontend/src/components/LoginPage.tsx`** — minimal Tailwind form (username, password, submit, error line, disabled while pending). No router needed.

**MODIFY `frontend/src/App.tsx`** — wrap in `AuthProvider`; anon → `LoginPage`, loading → spinner, authed → existing dashboard; add a Logout button (e.g., near the theme toggle in HeaderBar).

**MODIFY `frontend/src/api/useSession.ts`** — in `ws.onclose`: if close code is 4401, dispatch `auth:unauthorized` and do NOT schedule a reconnect; keep the existing 3s retry otherwise.

### Tests

**CREATE `backend/tests/test_security.py`** — unit: hash/verify round-trip; wrong password False; `hash_token` deterministic 64-hex; `FailedLoginTracker` locks after N and unlocks after window (monkeypatch time).

**CREATE `backend/tests/test_route_protection.py`** — uses `TestClient(app)` **without** a context manager so lifespan (scheduler/docker/seed) never runs; without a session cookie `require_auth` raises before any DB I/O, so no Postgres needed:
```python
PUBLIC = {"/api/health", "/api/auth/login"}
def test_all_api_routes_require_auth():
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in PUBLIC: continue
        method = next(iter(route.methods - {"HEAD", "OPTIONS"}))
        r = client.request(method, path.replace("{gateway_id}", "user1").replace("{chain_id}", "x").replace("{conid}", "1"))
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
```
Also assert `/api/health` → 200 and login with empty `AUTH_PASSWORD_HASH` → 503.

### Pitfalls
- Never put auth on `/api/health` (compose healthcheck curls backend:8000 directly, docker-compose.yml:168) or `/api/auth/login`.
- The in-process poller/scheduler never goes through HTTP — do not touch `app/poller/*`.
- The login endpoint deliberately has no CSRF check (no session exists yet; credentials are the proof).
- Cookies are host-scoped; the browser sends `session` automatically on same-origin `wss://` — no WS client change needed beyond close-code handling.
- Do not commit `AUTH_COOKIE_SECURE=false` anywhere.
- Starlette turns pre-accept `ws.close()` into a 403 handshake rejection — expected.

### Verification
1. `docker compose up -d --build`; `docker compose logs backend` shows migration 0010 applied.
2. `curl -k https://127.0.0.1:8443/api/positions` → 401; `/api/health` → 200.
3. Login via curl with a cookie jar → 200 + `session` (HttpOnly) + `csrf_token` cookies; subsequent `-b jar.txt` GET /api/positions → 200.
4. PUT /api/settings with cookie but no `X-CSRF-Token` → 403; with header → 200.
5. Six bad logins from one IP → 429 (and the nginx login zone throttles too).
6. Browser: login page → dashboard → WS updates live → CSV upload works → logout returns to login. A second device sees the login page.
7. `wscat -n --connect wss://127.0.0.1:8443/ws` without a cookie → handshake rejected.
8. `cd backend && pytest -q` all green.
9. `docker compose logs backend | grep http_request` shows JSON access lines; `grep auth_` shows login/logout audit events.

---

## Phase 3 — Docker socket proxy + container hardening

Do after Phase 2 so the login-flow regression check (2FA push via container restart) exists.

### MODIFY `docker-compose.yml`

1. New service + isolated network:
```yaml
  docker-proxy:
    image: tecnativa/docker-socket-proxy:0.3.0   # verify latest 0.x at implementation time
    restart: unless-stopped
    environment:
      CONTAINERS: 1      # GET /containers/* (list/inspect)
      POST: 1            # REQUIRED for the ALLOW_* write endpoints below
      ALLOW_START: 1
      ALLOW_STOP: 1
      ALLOW_RESTARTS: 1
      # everything else (IMAGES, EXEC, BUILD, VOLUMES, NETWORKS, INFO...) defaults to 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks: [docker-proxy-net]     # NOT on `internal`
    security_opt: ["no-new-privileges:true"]
    logging: *default-logging
    mem_limit: 64m
```
Top-level `networks:` gains `docker-proxy-net: {driver: bridge, internal: true}`.

2. Backend service: **delete** the `/var/run/docker.sock` volume (lines 158-159); add env `DOCKER_HOST: tcp://docker-proxy:2375` and `HOME: /tmp` (cache writes under read-only rootfs); `networks: [internal, docker-proxy-net]`; `depends_on: docker-proxy: condition: service_started`; add:
```yaml
    read_only: true
    tmpfs: [/tmp]
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
```
3. Frontend service: `read_only: true`, `tmpfs: [/tmp, /var/cache/nginx, /var/run]` (nginx-unprivileged writes temp/pid files — verify paths at implementation; drop `read_only` if it fights, keep the rest), `security_opt: ["no-new-privileges:true"]`, `cap_drop: [ALL]`.
4. `db` and `db-backup`: add `security_opt: ["no-new-privileges:true"]` only (postgres needs its caps/rootfs).
5. IBEAM gateways: unchanged (Chromium needs too much; internal-only).

### MODIFY `backend/Dockerfile`
After `COPY . .` / chmod: `RUN useradd --uid 10001 --no-create-home appuser` then `USER appuser`.

### MODIFY `frontend/Dockerfile`
Runtime base → `nginxinc/nginx-unprivileged:1.27-alpine` (uid 101; conf already listens on 8080/8443 from Phase 1; COPY destinations unchanged).

No Python changes — `docker.from_env()` (`backend/app/main.py:35`, `backend/app/poller/jobs/session.py:~343`) reads `DOCKER_HOST` automatically.

### Pitfalls
- `POST: 1` is mandatory alongside `ALLOW_START/STOP/RESTARTS` with tecnativa's proxy.
- `docker-proxy-net` must be `internal: true` and separate, so gateways/db can never reach the Docker API.
- The login flow restarts containers through the proxy — if START/STOP/RESTARTS aren't allowed, IBKR logins silently break. Test it.
- `alembic upgrade head` only reads app files and writes to Postgres — safe under a read-only rootfs.

### Verification
1. `docker compose up -d --build`; backend logs show `stopped_ibeam_on_startup` (list/stop via proxy works), no `docker_unavailable_on_startup`.
2. UI "Pull Fresh Data" → gateway restarts, 2FA push arrives, login completes.
3. Negative: `docker compose exec backend python -c "import docker; docker.from_env().images.list()"` → 403.
4. `docker compose exec backend id` → uid 10001; `touch /app/x` → read-only error. `docker compose exec frontend id` → uid 101.
5. Full regression: dashboard, poller writes, healthchecks green.

---

## Phase 4 — Parser and input hardening

### MODIFY `backend/requirements.txt`
Add `defusedxml==0.7.1`.

### MODIFY `backend/app/clients/ibkr/flex_web.py` + `flex_parse.py`
Replace `import xml.etree.ElementTree as ET` → `import defusedxml.ElementTree as ET`; add `import defusedxml.common`; widen `except ET.ParseError` → `except (ET.ParseError, defusedxml.common.DefusedXmlException)`.

### MODIFY `backend/app/api/routes/portfolio.py` (upload_trades, ~227-258)
Cap uploads (defense-in-depth behind nginx's 10m):
```python
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
chunks, total = [], 0
while chunk := await file.read(1024 * 1024):
    total += len(chunk)
    if total > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV too large (10 MB max).")
    chunks.append(chunk)
content = b"".join(chunks)
```

### MODIFY `backend/app/api/routes/market.py`
- `_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,12}$")`; `validate_symbol(symbol)` strips/uppercases, raises `HTTPException(400)` on mismatch. Call at the top of the by-symbol route (~line 111) — at the ROUTE, not only inside `_fetch_yf_bars`, so cached-DB reads are guarded too.
- Throttle on-demand yfinance: module-level last-fetch dict (skip if the same symbol was fetched <600s ago) + `asyncio.Semaphore(2)`; run the blocking `yf.Ticker(...).history` via `asyncio.to_thread` so it can't stall the event loop.

### MODIFY `backend/app/api/routes/settings.py`
Replace `update_settings(payload: dict)` (~line 99) with typed Pydantic models, `extra="forbid"` throughout, bounded fields (`take_profit_pct` 0–1, `expiry_dte` 0–60, `risk_free_rate` 0–0.25, weights 0–1, etc.). **The stored JSONB shape must stay byte-identical** — mirror the keys in `app/analytics/defaults.py:DEFAULT_SETTINGS`, use `payload.model_dump()` when persisting, and reuse the existing `UnderlyingIn` model.

### MODIFY `backend/app/api/routes/diagnostics.py`
`include_raw: bool = True` (line ~48) → default `False` (raw IBKR payloads now opt-in; auth already gates the route).

### MODIFY `gateway/conf.yaml`
`cors: origin.allowed: "*"` → `"https://localhost:5000"` (backend calls are server-side; CORS-irrelevant — this just closes the wildcard).

### CREATE `backend/tests/test_input_hardening.py`
- Billion-laughs XML into `parse_flex_xml` → raises a defusedxml exception (does NOT expand).
- `validate_symbol`: `AAPL`/`BRK.B`/`^VIX` pass; injection strings, >12 chars, lowercase-with-spaces fail.
- Settings model rejects unknown top-level keys and out-of-range values.

### Pitfalls
- The scheduler's hourly flex import shares `parse_flex_xml` — after deploy, run one "Pull Fresh Data" and confirm trades import.
- Settings `_merge` and the UI depend on the JSON shape — verify a settings save round-trips unchanged.

### Verification
1. `pytest -q` green.
2. `?symbol=%22%3Bls%22` → 400; `?symbol=QQQ` → 200.
3. 11 MB CSV → 413. `PUT /api/settings` with `{"evil":1}` → 422.
4. UI: settings save, watchlist add/remove, real CSV upload all work.

---

## Phase 5 — Secrets & encrypted backups

### CREATE `backup/Dockerfile`
```dockerfile
FROM postgres:16-alpine
RUN apk add --no-cache age
```

### MODIFY `docker-compose.yml` (db-backup)
`image: postgres:16-alpine` → `build: ./backup`; add `AGE_RECIPIENT: ${AGE_RECIPIENT:-}` to environment; in the entrypoint script (keep the existing `$$` escaping):
```sh
if [ -n "$${AGE_RECIPIENT}" ]; then
  out="/backups/options-$$ts.sql.gz.age"
  pg_dump | gzip | age -r "$${AGE_RECIPIENT}" > "$$out"
else
  out="/backups/options-$$ts.sql.gz"
  echo "[db-backup] WARNING: AGE_RECIPIENT unset - writing UNENCRYPTED backup" >&2
  pg_dump | gzip > "$$out"
fi
```
Widen the prune to `-name 'options-*.sql.gz*'`.

### MODIFY `.env.example`
- Backups block: generate a keypair `docker run --rm alpine:3 sh -c "apk add -q age && age-keygen"`; store the **private key OFF the server** (password manager); put the `age1...` public key in `AGE_RECIPIENT=`. Restore: `age -d -i key.txt backups/options-<ts>.sql.gz.age | gunzip | docker compose exec -T db psql -U options -d options`.
- `POSTGRES_PASSWORD`: instruct `openssl rand -base64 24` (live value is currently the weak default — rotate at rollout: `ALTER USER options WITH PASSWORD ...` then update `.env`, `docker compose up -d backend db-backup`).
- `chmod 600 .env` note for Linux hosts.
- IBEAM Fernet opt-in: generate a key `docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; encrypt each password with the matching one-liner; set ciphertexts as `IBEAM_PASSWORD`/`_2`; uncomment `IBEAM_KEY: ${IBEAM_KEY}` in docker-compose.yml (~line 59). Warning stays: an EMPTY key with the line uncommented breaks login — all-or-nothing.

### Verification
1. Set `AGE_RECIPIENT`, rebuild db-backup, trigger a cycle (`docker compose restart db-backup`) → `.sql.gz.age` file appears; `file` shows it is not gzip.
2. Round-trip decrypt with the private key → SQL text.
3. Unset recipient → WARNING line in logs.
4. With `IBEAM_KEY` configured, "Pull Fresh Data" still logs in.

---

## Phase 6 — CI security scanning + supply chain

### MODIFY `.github/workflows/ci.yml`
- Top-level `permissions: { contents: read }`.
- Pin every action to a full commit SHA with a `# vX.Y.Z` comment (look up via `git ls-remote https://github.com/<owner>/<repo> refs/tags/<tag>` at implementation time).
- New jobs:
  - **pip-audit**: python 3.12 → `pip install pip-audit` → `pip-audit -r backend/requirements.txt --strict` (add `--ignore-vuln <ID>` case-by-case only for unfixable advisories, with a comment).
  - **npm-audit**: node 20 → `cd frontend && npm ci && npm audit --audit-level=high`.
  - **eslint**: `cd frontend && npm ci && npm run lint`.
  - **gitleaks**: `gitleaks/gitleaks-action@<SHA> # v2`, checkout with `fetch-depth: 0`.
  - **trivy**: `aquasecurity/trivy-action@<SHA>` twice — `scan-type: fs` (`severity: HIGH,CRITICAL`, `exit-code: 1`, `ignore-unfixed: true`) and `scan-type: config` (Dockerfile/compose misconfig).

### CREATE `.github/workflows/codeql.yml`
Standard CodeQL v3: push to master/main + PRs + weekly schedule; job-level `permissions: { security-events: write, contents: read }`; matrix `language: [python, javascript-typescript]`; init → autobuild → analyze.

### CREATE `.github/dependabot.yml`
Weekly: `pip` (`/backend`), `npm` (`/frontend`), `docker` (`/backend`, `/frontend`, `/backup`), `github-actions` (`/`).

### CREATE `.gitleaks.toml`
Allowlist `gateway/conf.yaml` `sslPwd: "mywebapi"` with a comment (IBKR's public stock keystore password, not a secret).

### CREATE `frontend/eslint.config.js` + MODIFY `frontend/package.json`
Script `"lint": "eslint src --max-warnings 0"`. devDependencies: `eslint@^9`, `typescript-eslint@^8`, `eslint-plugin-react-hooks@^5`, `eslint-plugin-react-refresh@^0.4`, `eslint-plugin-security@^3`, `globals@^15`. Flat config: typescript-eslint recommended + react-hooks recommended + security/recommended on `src/**/*.{ts,tsx}`. Fix any findings it raises (expect a handful of hook-dep warnings).

### Verification
- Push a branch: all jobs green; CodeQL results under Security → Code scanning.
- On a scratch branch, commit a fake `AWS_SECRET_ACCESS_KEY=AKIA...` → gitleaks fails; drop the commit.
- `cd frontend && npm run lint` clean locally.

---

## Phase 7 — Documentation, threat model, runbooks

### CREATE `docs/SECURITY.md`
- **Threat model** (assets, adversaries, entry points) + **accepted-risk register**: single shared credential; `IBKR_GATEWAY_VERIFY=false` to the gateway's self-signed cert on the internal Docker network (optional hardening: build a PKCS12 keystore from the Phase-1 CA, mount over `vertx.jks`, set `IBKR_GATEWAY_VERIFY=/path/to/pem` — `config.py:91-99` already accepts a CA-bundle path); IBEAM plaintext-vs-Fernet trade-off; Flex token sent as a query param to IBKR over HTTPS (IBKR's protocol — recommend IP-restricting the token in IBKR Account Management).
- **Exposure model**: recommended = `APP_BIND=127.0.0.1` + Tailscale/WireGuard (access `https://<tailscale-ip>:8443` after adding the IP to `EXTRA_SANS` and re-running gen-certs). Never port-forward.
- **Runbooks**:
  - Rotate shared password: hash CLI → update `AUTH_PASSWORD_HASH` (single quotes!) → `docker compose up -d backend` → `docker compose exec db psql -U options -d options -c "DELETE FROM auth_sessions;"`.
  - Cert renewal (yearly reminder): re-run `scripts/gen-certs.sh` (CA persists) → `docker compose restart frontend`.
  - Rotate Postgres password / age key / Flex tokens / IBEAM key (per Phase 5).
- **Dependency cadence**: merge Dependabot weekly after green CI; monthly `docker compose pull && up -d --build`; quarterly review of pinned digests (ibeam, socket-proxy, nginx, postgres).
- **Audit trail**: event names (`auth_login_success/failed`, `auth_logout`, `http_request`) and how to grep them.

### MODIFY `README.md`
Update the network-access section: new default `https://localhost:8443`, gen-certs first-run step, hash-CLI + login step, `.age` restore command, link to docs/SECURITY.md. Fix the stale claim that the bind default is loopback (it will actually be true now).

### MODIFY `docs/architecture.md`
Add the auth/session flow and docker-proxy to the component description.

### Verification
Fresh-clone dry run following only the README: gen-certs → .env (incl. hash) → `docker compose up -d --build` → login at `https://localhost:8443` → data visible. Execute every runbook command once.

---

## Cross-phase notes for the implementer

1. **Sequencing**: 1 → 2 strictly (Secure cookies need TLS). 3 after 2 (login regression test exists). 4/5/6 independent. 7 last.
2. After each phase: `docker compose up -d --build` → `docker compose ps` all healthy → `cd backend && pytest -q` → the phase's checks. The two easiest things to silently break are the in-process poller and the "Pull Fresh Data" login flow — verify both whenever compose or `main.py` changed.
3. Never add auth to: `/api/health`, `/api/auth/login`, nginx `/healthz`.
4. New pins introduced: `argon2-cffi==25.1.0`, `defusedxml==0.7.1`, `tecnativa/docker-socket-proxy:0.3.0`, `nginxinc/nginx-unprivileged:1.27-alpine`, ESLint stack. Verify each is current stable at implementation time; behavior doesn't depend on exact minors.
5. Operator actions at rollout (not code): update the live `.env` (`APP_BIND`, `APP_PORT`, `AUTH_PASSWORD_HASH`, `AGE_RECIPIENT`, stronger `POSTGRES_PASSWORD`, optional `IBEAM_KEY`), run gen-certs, import `ca.crt` on client devices.
