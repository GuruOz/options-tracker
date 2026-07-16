"""Every /api route (except the public ones) must reject an unauthenticated
request. Uses TestClient without a context manager so the app's lifespan
(scheduler, Docker, seed) never runs — without a session cookie, require_auth
raises before any DB I/O, so no Postgres connection is needed either."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PUBLIC = {"/api/health", "/api/auth/login"}


def test_all_api_routes_require_auth():
    # Walking app.routes directly is fragile across FastAPI versions (recent
    # ones wrap included routers in lazy proxy objects with no flat .path) —
    # the OpenAPI schema is the version-independent source of resolved paths.
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api") or path in PUBLIC:
            continue
        method = next(iter(operations.keys())).upper()
        concrete = (
            path.replace("{gateway_id}", "user1")
            .replace("{chain_id}", "x")
            .replace("{conid}", "1")
        )
        r = client.request(method, concrete)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        checked += 1
    assert checked > 0  # sanity: the loop actually found protected routes


def test_health_is_public():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_login_rejected_when_password_hash_unset():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert r.status_code == 503
