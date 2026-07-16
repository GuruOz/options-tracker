#!/usr/bin/env bash
set -e

echo "==========================================================="
echo " Updating Options Tracker to the latest version..."
echo "==========================================================="

echo "1. Pulling latest code from GitHub..."
git pull origin master

echo ""
echo "2. Checking for a .env file..."
if [ ! -f .env ]; then
    echo "   ERROR: no .env found. Copy one over from a working deployment"
    echo "   (or run 'cp .env.example .env' and fill it in) before continuing."
    exit 1
fi
if ! grep -q '^AUTH_PASSWORD_HASH=.\+' .env; then
    echo "   WARNING: AUTH_PASSWORD_HASH is empty in .env - the login page will"
    echo "   reject every attempt with a 503 until it's set. Generate one with:"
    echo "     docker compose run --rm --no-deps --entrypoint python backend -m app.cli.hash_password"
    echo "   then paste the hash into .env as AUTH_PASSWORD_HASH='...' (single quotes)."
fi

echo ""
echo "3. Ensuring TLS certificates exist..."
# certs/ is gitignored (machine-specific) so a server that's never run this
# stack before won't have it yet - nginx refuses to boot without it.
if [ ! -f certs/server.crt ] || [ ! -f certs/server.key ]; then
    echo "   No certs found - generating a local CA + server certificate."
    bash scripts/gen-certs.sh
else
    echo "   Certs already present, skipping."
fi

echo ""
echo "4. Rebuilding and restarting containers..."
# Rebuild the backend and frontend images, and restart only what changed
docker compose up -d --build

echo ""
echo "5. Restarting frontend..."
# nginx resolves the backend's IP once at its own startup. If step 4 only
# recreated the backend (its own image/config unchanged), frontend is still
# proxying to the backend's OLD address and every /api request 502s until
# frontend itself is restarted too.
docker compose restart frontend

echo ""
echo "6. Waiting for services to come up..."
sleep 5
docker compose ps

echo ""
echo "==========================================================="
echo " Update complete! Check above - every service should show"
echo " \"healthy\" (or \"running\" for db-backup, which has no healthcheck)."
echo "==========================================================="
