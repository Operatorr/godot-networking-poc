#!/usr/bin/env bash
#
# server_sync.sh — fast, BUILD-FREE deploy, runs ON the server as `deploy`.
# Pulls master, restarts the systemd services, and health-checks — but does
# NOT recompile the Go API or Rust game server. Use it when the only changes
# are things read at runtime (e.g. deployment/server_config.{arena,sanctuary}.json)
# or other non-compiled assets; a restart picks them up without the multi-minute
# cargo/go build.
#
# Invoked over SSH by ./scripts/deploy.sh sync from your laptop (or run directly
# on the box). For code changes to api/ or rust/ use server_update.sh instead —
# this script leaves the existing binaries in place.
#
# Prereqs: deployment/provision_server.sh has been run once, and the binaries
# already exist (i.e. server_update.sh has run at least once). Idempotent.
#
set -euo pipefail

BRANCH="${OMEGA_BRANCH:-master}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="$(grep -E '^PORT=' /etc/omega-realm/api.env 2>/dev/null | cut -d= -f2 || true)"
API_PORT="${API_PORT:-8080}"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

cd "$REPO_DIR"

log "Fetching origin/${BRANCH}"
git fetch --prune origin "$BRANCH"
OLD_REV="$(git rev-parse --short HEAD)"
git reset --hard "origin/${BRANCH}"   # discards tracked build artifacts (e.g. api/bin/*)
NEW_REV="$(git rev-parse --short HEAD)"
ok "repo ${OLD_REV} -> ${NEW_REV}"

# Guard: sync does NOT rebuild, so if the pulled range touched compiled code the
# running binaries would be stale against the new source. Refuse and point at the
# full deploy. (Empty range / config-only changes pass straight through.)
if ! git diff --quiet "$OLD_REV" "$NEW_REV" -- api rust; then
  fail "compiled code under api/ or rust/ changed between ${OLD_REV} and ${NEW_REV} — sync does not rebuild, so the running binaries would be stale. Use the full deploy instead: ./scripts/deploy.sh"
fi

# Guard: never (re)start with placeholder secrets still in the installed env
# files. provision_server.sh copies *.env.example verbatim (DB_PASSWORD,
# JWT_SECRET_KEY, *_TOKEN = CHANGE_ME...); if the operator forgot to edit them
# the DB role and JWT signing would use known placeholders. Fail loudly instead.
log "Verifying installed env files have no placeholder secrets"
for env_file in /etc/omega-realm/api.env /etc/omega-realm/server.env; do
  if [[ -f "$env_file" ]] && grep -q 'CHANGE_ME' "$env_file"; then
    fail "placeholder secret (CHANGE_ME) still present in $env_file — edit it with real secrets before deploying (sudo nano $env_file)"
  fi
done
ok "env files contain no CHANGE_ME placeholders"

log "Restarting services (api + arena + sanctuary) — no rebuild"
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

$ok_all || fail "sync finished with unhealthy services (see journalctl above)"
ok "Sync complete: ${NEW_REV} live (no rebuild)."
