#!/usr/bin/env bash
#
# setup_tls.sh — put the Go API behind HTTPS with Caddy (one-time, on the server).
#
# The Go API (omega-api) serves PLAIN HTTP on 127.0.0.1:8080. Both the game client and
# the CMS website's server-side calls send credentials/JWTs, so the public hop must be
# encrypted. This installs Caddy as a TLS-terminating reverse proxy: it serves the
# domain on 443 with an automatic Let's Encrypt certificate and proxies to the API on
# localhost. Afterwards the direct 8080 port is closed at the firewall, so the API is
# reachable only through Caddy.
#
# PREREQUISITE: a DNS A/AAAA record for the domain must already point at THIS droplet —
# Caddy proves domain control to Let's Encrypt over ports 80/443. Without it, cert
# issuance fails and the site stays unreachable over HTTPS.
#
# Run ON the server as the deploy user:   sudo bash deployment/setup_tls.sh
# Override the domain:   sudo OMEGA_API_DOMAIN=api.example.com bash deployment/setup_tls.sh
# Idempotent — safe to re-run.
#
set -euo pipefail

DEPLOY_USER="deploy"
REPO_DIR="/home/${DEPLOY_USER}/omega-realm"
DOMAIN="${OMEGA_API_DOMAIN:-omega.marrowtech.app}"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash deployment/setup_tls.sh" >&2
  exit 1
fi
[[ -f "$REPO_DIR/deployment/Caddyfile" ]] || {
  echo "Caddyfile not found at $REPO_DIR/deployment/Caddyfile — is the repo cloned?" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
log "1/4  Install Caddy (official apt repo)"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
else
  echo "caddy already installed — skipping repo + install"
fi
caddy version

# ---------------------------------------------------------------------------
log "2/4  Install Caddyfile for ${DOMAIN} -> 127.0.0.1:8080"
install -d /etc/caddy
cp "$REPO_DIR/deployment/Caddyfile" /etc/caddy/Caddyfile
# Pin the domain into caddy's environment so the {$OMEGA_API_DOMAIN} placeholder
# resolves under systemd (the packaged caddy.service does not read this shell's env).
# A drop-in keeps the packaged unit itself untouched.
mkdir -p /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/10-omega-domain.conf <<EOF
[Service]
Environment=OMEGA_API_DOMAIN=${DOMAIN}
EOF
systemctl daemon-reload

# ---------------------------------------------------------------------------
log "3/4  Firewall: open 80/443, close direct 8080 (API only via Caddy now)"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp  comment 'HTTP (ACME challenge + redirect to HTTPS)'
  ufw allow 443/tcp comment 'HTTPS (Caddy -> Go API)'
  ufw delete allow 8080/tcp 2>/dev/null || true   # no longer exposed directly
  ufw status verbose | sed 's/^/   /'
else
  warn "ufw not found — open 80/443 and close 8080 in your firewall manually"
fi

# ---------------------------------------------------------------------------
log "4/4  Enable + (re)start Caddy"
systemctl enable caddy
systemctl restart caddy
sleep 2
if systemctl is-active --quiet caddy; then
  echo "caddy is active"
else
  warn "caddy is not active — check: journalctl -u caddy -n 50"
fi

cat <<EOF

$(printf '\033[1;32m==> TLS setup complete.\033[0m')

Verify (from your laptop):
  curl https://${DOMAIN}/health      # -> {"status":"healthy",...} over a valid cert

If the cert isn't issued yet, confirm DNS points at this box and watch issuance:
  journalctl -u caddy -f

Then point clients at https://${DOMAIN} (no :8080):
  - client/data/config/client_config.json  ->  "api_base_url": "https://${DOMAIN}"
  - Astro CMS server env                   ->  API_BASE_URL=https://${DOMAIN}
EOF
