#!/usr/bin/env bash
#
# server_update.sh — recurring native deploy, runs ON the server as `deploy`.
# Pulls master, rebuilds the Go API + Rust game server, restarts the systemd
# services, and health-checks. Invoked over SSH by ./scripts/deploy.sh from
# your laptop (or run it directly on the box).
#
# Prereqs: deployment/provision_server.sh has been run once (toolchains, DB,
# units, sudoers). Idempotent.
#
set -euo pipefail

BRANCH="${OMEGA_BRANCH:-master}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="$(grep -E '^PORT=' /etc/omega-realm/api.env 2>/dev/null | cut -d= -f2 || true)"
API_PORT="${API_PORT:-8080}"

# SSH non-login shells don't get these on PATH — add them explicitly.
export PATH="/usr/local/go/bin:$HOME/.cargo/bin:$PATH"
[[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v go    >/dev/null || fail "go not on PATH — run provision_server.sh first"
command -v cargo >/dev/null || fail "cargo not on PATH — run provision_server.sh first"

cd "$REPO_DIR"

log "Fetching origin/${BRANCH}"
git fetch --prune origin "$BRANCH"
OLD_REV="$(git rev-parse --short HEAD)"
git reset --hard "origin/${BRANCH}"   # discards tracked build artifacts (e.g. api/bin/*)
NEW_REV="$(git rev-parse --short HEAD)"
ok "repo ${OLD_REV} -> ${NEW_REV}"

log "Building Go API (release)"
( cd api && go build -o bin/server ./cmd/server )
ok "api -> api/bin/server"

log "Building Rust omega-server (release)"
( cd rust && cargo build --release -p omega-server )
ok "server -> rust/target/release/omega-server"

log "Restarting services (api + arena + sanctuary)"
sudo systemctl restart omega-api.service
sudo systemctl restart omega-arena.service
sudo systemctl restart omega-sanctuary.service

# ---- health checks ----
log "Health check"
ok_all=true
for _ in $(seq 1 15); do
  curl -fsS "http://localhost:${API_PORT}/health" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS "http://localhost:${API_PORT}/health" >/dev/null 2>&1; then
  ok "API healthy on :${API_PORT}"
else
  ok_all=false; echo "[error] API not healthy — journalctl -u omega-api -n 50" >&2
fi

# Each game instance: systemd active + its Prometheus exporter responding
# (the exporter is the liveness probe; arena=9100, sanctuary=9101).
check_game() {  # $1 unit  $2 metrics_port  $3 label
  if systemctl is-active --quiet "$1"; then
    ok "$3 active"
  else
    ok_all=false; echo "[error] $3 not active — journalctl -u $1 -n 50" >&2; return
  fi
  if curl -fsS "http://localhost:$2/metrics" >/dev/null 2>&1; then
    ok "$3 metrics on :$2"
  else
    echo "[warn] $3 :$2/metrics not responding yet (may still be starting)" >&2
  fi
}
check_game omega-arena.service     9100 "arena (8081)"
check_game omega-sanctuary.service 9101 "sanctuary (8082)"

$ok_all || fail "deploy finished with unhealthy services (see journalctl above)"
ok "Deploy complete: ${NEW_REV} live."
