#!/usr/bin/env bash
#
# deploy.sh — control the native (Docker-free) Omega Realm server FROM YOUR LAPTOP.
# SSHes into the VPS and drives the on-server scripts. Git is the deploy channel:
# the server pulls master and rebuilds.
#
# Usage:  ./scripts/deploy.sh [command]
#
# Commands:
#   all        ONE-SHOT: os-update -> deploy -> health. The single command that
#              updates the OS, pulls master, rebuilds, restarts, and verifies.
#   deploy     (default) ssh in, run server_update.sh (pull master, build, restart)
#   provision  one-time bootstrap (installs Go/Rust/Postgres/Redis, units, sudoers)
#   os-update  apt full-upgrade + cleanup on the server (forwards flags, e.g.
#              `os-update --reboot`, `os-update --release-upgrade`)
#   status     systemctl status of api + arena + sanctuary
#   logs       follow journald logs for all three services (Ctrl+C to stop)
#   health     curl the API /health and game metrics endpoints
#   restart    restart all services without rebuilding
#   ssh        open an interactive shell on the server
#
# Target config comes from deployment/deploy.env (git-ignored — your server IP never
# gets committed). Copy deployment/deploy.env.example -> deployment/deploy.env and set
# OMEGA_HOST. Shell env (e.g. `OMEGA_HOST=1.2.3.4 ./scripts/deploy.sh`) overrides the file.
#   OMEGA_HOST (required)  OMEGA_USER=deploy  OMEGA_BRANCH=master  OMEGA_REPO_DIR=/home/<user>/omega-realm
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${OMEGA_DEPLOY_ENV:-$SCRIPT_DIR/../deployment/deploy.env}"

C_B='\033[1;34m'; C_G='\033[1;32m'; C_R='\033[1;31m'; C_N='\033[0m'
info() { printf "${C_B}==> %s${C_N}\n" "$*"; }
ok()   { printf "${C_G}%s${C_N}\n" "$*"; }
die()  { printf "${C_R}error: %s${C_N}\n" "$*" >&2; exit 1; }

# Load deploy.env WITHOUT clobbering anything already set in the shell (env wins).
if [[ -f "$CONFIG_FILE" ]]; then
  while IFS='=' read -r key val; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue   # skip comments / blanks
    val="${val%$'\r'}"                                     # tolerate CRLF
    [[ -z "${!key:-}" ]] && export "$key=$val"
  done < "$CONFIG_FILE"
fi

HOST="${OMEGA_HOST:-}"
USER="${OMEGA_USER:-deploy}"
BRANCH="${OMEGA_BRANCH:-master}"
REPO_DIR="${OMEGA_REPO_DIR:-/home/${USER}/omega-realm}"
[[ -n "$HOST" ]] || die "OMEGA_HOST is not set. Create $CONFIG_FILE (cp deployment/deploy.env.example deployment/deploy.env) and set OMEGA_HOST, or run with OMEGA_HOST=<ip> ./scripts/deploy.sh"
TARGET="${USER}@${HOST}"

# Run a command on the server (TTY allocated so colors/logs stream nicely).
rexec() { ssh -t "$TARGET" "$@"; }

cmd_deploy() {
  info "Deploying ${BRANCH} to ${TARGET} (${REPO_DIR})"
  rexec "cd '${REPO_DIR}' && OMEGA_BRANCH='${BRANCH}' bash deployment/server_update.sh"
  ok "Done."
}

cmd_provision() {
  info "One-time provisioning on ${TARGET}"
  cat <<'NOTE'
This installs Go, Rust, PostgreSQL, Redis, swap, systemd units, and a sudoers
rule. It clones the repo if missing. You'll be prompted for deploy's sudo password.
NOTE
  rexec "test -d '${REPO_DIR}/.git' || git clone --branch '${BRANCH}' https://github.com/Operatorr/godot-networking-poc.git '${REPO_DIR}'"
  # Sync to the latest ${BRANCH} so a re-run picks up fixes to the provision
  # script itself (clone above is a no-op once the repo exists).
  rexec "cd '${REPO_DIR}' && git fetch origin '${BRANCH}' && git checkout '${BRANCH}' && git reset --hard 'origin/${BRANCH}'"
  rexec "cd '${REPO_DIR}' && sudo bash deployment/provision_server.sh"
  ok "Provisioned. Set secrets in /etc/omega-realm/*.env, then: ./scripts/deploy.sh"
}

SERVICES="omega-api omega-arena omega-sanctuary"
cmd_os_update() {
  info "OS maintenance on ${TARGET} (apt full-upgrade${1:+ $*})"
  echo "(you'll be prompted for deploy's sudo password — apt isn't in the narrow sudoers rule)"
  rexec "cd '${REPO_DIR}' && sudo bash deployment/update_os.sh $*"
  ok "OS update done."
}

cmd_all() {
  info "Full update of ${TARGET}: OS packages -> code (master) -> health"
  # OS update first (no --reboot here: a mid-run reboot would kill the deploy; if a
  # reboot is needed update_os.sh says so, and you can `os-update --reboot` after).
  cmd_os_update
  cmd_deploy
  cmd_health
  ok "Full update complete."
}

cmd_status()  { rexec "sudo systemctl status ${SERVICES} --no-pager"; }
cmd_logs()    { rexec "sudo journalctl -fu omega-api -u omega-arena -u omega-sanctuary"; }
cmd_restart() { rexec "for s in ${SERVICES}; do sudo systemctl restart \$s.service; done && echo restarted: ${SERVICES}"; }
cmd_ssh()     { ssh "$TARGET"; }

cmd_health() {
  info "Health of ${HOST}"
  rexec "set -e
    printf 'api      : '; curl -fsS http://localhost:8080/health && echo
    printf 'arena    : '; curl -fsS http://localhost:9100/metrics >/dev/null && echo 'metrics OK (8081)' || echo DOWN
    printf 'sanctuary: '; curl -fsS http://localhost:9101/metrics >/dev/null && echo 'metrics OK (8082)' || echo DOWN"
}

cmd="${1:-deploy}"; shift || true
case "$cmd" in
  all)       cmd_all ;;
  deploy)    cmd_deploy ;;
  provision) cmd_provision ;;
  os-update) cmd_os_update "$@" ;;
  status)    cmd_status ;;
  logs)      cmd_logs ;;
  health)    cmd_health ;;
  restart)   cmd_restart ;;
  ssh)       cmd_ssh ;;
  -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)         die "unknown command: $cmd (try --help)" ;;
esac
