#!/usr/bin/env bash
# Generates a local CA and a server certificate for the options-tracker
# frontend to terminate TLS with. Safe to re-run: the CA is reused if it
# already exists, and a fresh server cert is issued each time (picking up
# any change to EXTRA_SANS).
#
# If openssl is not installed locally, run this via Docker instead:
#   docker run --rm -v "$PWD/certs:/certs" -v "$PWD/scripts:/scripts:ro" \
#     -w /certs alpine/openssl sh /scripts/gen-certs.sh
#
# Extra Subject Alternative Names (e.g. a Tailscale IP or LAN hostname) can
# be added via the EXTRA_SANS env var, comma-separated:
#   EXTRA_SANS="IP:192.168.1.50,DNS:tracker.tailnet.ts.net" bash scripts/gen-certs.sh

set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p certs

# On Windows/Git-Bash, MSYS rewrites leading-slash args (like -subj values)
# into filesystem paths unless doubled ("//CN=..."). That form is accepted
# as-is by openssl on every platform, so it's used unconditionally below.

SAN="DNS:localhost,IP:127.0.0.1"
if [ -n "${EXTRA_SANS:-}" ]; then
    SAN="${SAN},${EXTRA_SANS}"
fi

if [ ! -f certs/ca.key ] || [ ! -f certs/ca.crt ]; then
    echo "[gen-certs] Generating local CA (certs/ca.key, certs/ca.crt)..."
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -days 3650 -nodes \
        -keyout certs/ca.key -out certs/ca.crt \
        -subj "//CN=options-tracker local CA"
else
    echo "[gen-certs] Reusing existing CA (certs/ca.key, certs/ca.crt)."
fi

echo "[gen-certs] Generating server key + certificate (SAN: ${SAN})..."
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout certs/server.key -out certs/server.csr \
    -subj "//CN=options-tracker"

# Written under certs/ (not the system temp dir) so it works the same way
# regardless of how the shell's temp-dir path gets mangled cross-platform.
extfile="certs/.server.ext.tmp"
trap 'rm -f "$extfile" certs/server.csr' EXIT
cat > "$extfile" <<EOF
subjectAltName=${SAN}
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF

openssl x509 -req -in certs/server.csr \
    -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial \
    -out certs/server.crt.tmp -days 825 -extfile "$extfile"

# server.crt = leaf cert + CA cert, so nginx serves the full chain.
cat certs/server.crt.tmp certs/ca.crt > certs/server.crt
rm -f certs/server.crt.tmp

chmod 600 certs/server.key certs/ca.key

echo
echo "[gen-certs] Done. Files written to ./certs:"
echo "  certs/ca.crt      - import this into your OS/browser/device trust store"
echo "  certs/ca.key      - CA private key, keep this safe, do not commit"
echo "  certs/server.crt  - server certificate chain (used by nginx)"
echo "  certs/server.key  - server private key (used by nginx)"
echo
echo "Trust import instructions:"
echo "  Windows : double-click certs/ca.crt -> Install Certificate -> Local"
echo "            Machine -> Trusted Root Certification Authorities."
echo "  macOS   : open certs/ca.crt in Keychain Access, add to System keychain,"
echo "            then set it to 'Always Trust'."
echo "  iOS     : AirDrop or email certs/ca.crt to the device, install the"
echo "            profile in Settings, then enable it under Settings > General"
echo "            > About > Certificate Trust Settings."
echo "  Android : Settings > Security > Encryption & credentials > Install a"
echo "            certificate > CA certificate, select certs/ca.crt."
