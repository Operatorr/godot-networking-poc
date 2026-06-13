#!/usr/bin/env bash
#
# provision_server.sh — ONE-TIME native bootstrap for the Omega Realm VPS.
# Installs Go + Rust + PostgreSQL + Redis natively (no Docker), creates the
# database, lays down /etc/omega-realm/*.env, installs the systemd units, and
# grants the deploy user a narrow passwordless `systemctl` rule for the two
# Omega services (so recurring deploys never need an interactive sudo).
#
# Run ON the server as the deploy user:   sudo bash deployment/provision_server.sh
# Idempotent — safe to re-run.
#
# After this, deploy code with:  ./scripts/deploy.sh        (from your laptop)
#
set -euo pipefail

DEPLOY_USER="deploy"
REPO_DIR="/home/${DEPLOY_USER}/omega-realm"
REPO_URL="https://github.com/Operatorr/godot-networking-poc.git"
BRANCH="master"
ETC_DIR="/etc/omega-realm"
DB_NAME="omega_db"
DB_USER="omega"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash deployment/provision_server.sh" >&2
  exit 1
fi
id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "user '$DEPLOY_USER' does not exist" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
ARCH="$(dpkg --print-architecture)"   # amd64 / arm64

# ---------------------------------------------------------------------------
log "1/9  Base packages (git, build tools, postgresql, redis)"
apt-get update -y
apt-get install -y --no-install-recommends \
  git curl ca-certificates build-essential pkg-config libssl-dev \
  postgresql postgresql-contrib redis-server

# ---------------------------------------------------------------------------
log "2/9  Swap (2G) — the build/runtime safety net on a 1 GB box"
if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  echo "swap already present — skipping"
fi

# ---------------------------------------------------------------------------
log "3/9  Go toolchain (official tarball — apt's Go is too old for go 1.24)"
# Capture the body, THEN take the first line — go.dev/VERSION returns two lines
# ("go1.26.4\ntime ..."); a guard surfaces a network failure instead of dying
# silently under `set -e`.
GO_VERSION_BODY="$(curl -fsSL 'https://go.dev/VERSION?m=text')" || {
  echo "could not reach go.dev to resolve the Go version (network/DNS?)" >&2; exit 1; }
GO_WANT="${GO_VERSION_BODY%%$'\n'*}"   # first line only — e.g. go1.26.4
if ! command -v go >/dev/null 2>&1 || [[ "$(go version 2>/dev/null | awk '{print $3}')" != "$GO_WANT" ]]; then
  GO_TARBALL="${GO_WANT}.linux-${ARCH}.tar.gz"
  # Pull the official SHA256 for this exact tarball from go.dev's release index
  # and verify before extracting (the download is otherwise unauthenticated).
  GO_DL_JSON="$(curl -fsSL 'https://go.dev/dl/?mode=json&include=all')" || {
    echo "could not reach go.dev/dl to resolve the Go SHA256" >&2; exit 1; }
  # Scan with awk, NOT `grep -A<n>`: the fields between "filename" and "sha256"
  # (os/arch/version) make any fixed line window brittle. awk finds the first
  # sha256 in the matched object regardless of field order. Crucially it does
  # NOT `exit` on match — an early exit closes the pipe while `printf` is still
  # writing the ~2 MB body, `printf` takes SIGPIPE (rc 141), and under
  # `set -o pipefail` that aborts the script before the guard below can run.
  # Reading to EOF and printing in END keeps the pipeline rc 0.
  GO_SHA="$(printf '%s\n' "$GO_DL_JSON" | awk -v f="\"filename\": \"${GO_TARBALL}\"" '
    index($0, f) { found = 1 }
    found && !got && /"sha256":/ {
      if (match($0, /[0-9a-f]{64}/)) { sha = substr($0, RSTART, RLENGTH); got = 1 }
    }
    END { print sha }')"
  [[ "$GO_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "could not resolve SHA256 for ${GO_TARBALL}" >&2; exit 1; }
  curl -fsSL "https://go.dev/dl/${GO_TARBALL}" -o /tmp/go.tgz
  echo "${GO_SHA}  /tmp/go.tgz" | sha256sum -c - || { echo "Go tarball checksum mismatch — aborting" >&2; rm -f /tmp/go.tgz; exit 1; }
  rm -rf /usr/local/go
  tar -C /usr/local -xzf /tmp/go.tgz
  rm -f /tmp/go.tgz
  # PATH for login shells + the systemd build (deploy's non-login shells).
  echo 'export PATH=$PATH:/usr/local/go/bin' > /etc/profile.d/go.sh
fi
/usr/local/go/bin/go version

# ---------------------------------------------------------------------------
log "4/9  Rust toolchain (rustup, as ${DEPLOY_USER})"
if ! sudo -u "$DEPLOY_USER" bash -lc 'command -v cargo' >/dev/null 2>&1; then
  sudo -u "$DEPLOY_USER" bash -lc \
    'curl --proto "=https" --tlsv1.2 -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal'
fi
sudo -u "$DEPLOY_USER" bash -lc 'source "$HOME/.cargo/env"; rustc --version'

# ---------------------------------------------------------------------------
log "5/9  PostgreSQL role + database (${DB_USER}/${DB_NAME})"
systemctl enable --now postgresql
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD 'CHANGE_ME_TO_A_SECURE_PASSWORD';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
warn "Set a real DB password: sudo -u postgres psql -c \"ALTER ROLE ${DB_USER} PASSWORD '...';\""
warn "Then put the SAME password in ${ETC_DIR}/api.env (DB_PASSWORD)."

# ---------------------------------------------------------------------------
log "6/9  Redis (enable, localhost-only by default)"
systemctl enable --now redis-server

# ---------------------------------------------------------------------------
log "7/9  Clone/refresh the repo at ${REPO_DIR}"
if [[ ! -d "$REPO_DIR/.git" ]]; then
  sudo -u "$DEPLOY_USER" git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
else
  echo "repo already cloned — leaving working tree for deploy.sh to update"
fi

# ---------------------------------------------------------------------------
log "8/9  Runtime env files in ${ETC_DIR} (root:${DEPLOY_USER} 0640)"
mkdir -p "$ETC_DIR" "$REPO_DIR/logs"
chown "$DEPLOY_USER:$DEPLOY_USER" "$REPO_DIR/logs"
install_env() {  # $1 template  $2 dest
  if [[ -f "$2" ]]; then echo "$2 exists — keeping your values"; return; fi
  cp "$1" "$2"; chown "root:${DEPLOY_USER}" "$2"; chmod 0640 "$2"
  warn "Created $2 from template — edit secrets before first deploy."
}
install_env "$REPO_DIR/deployment/env/api.env.example"    "$ETC_DIR/api.env"
install_env "$REPO_DIR/deployment/env/server.env.example" "$ETC_DIR/server.env"

# ---------------------------------------------------------------------------
log "9/9  systemd units + narrow passwordless systemctl for ${DEPLOY_USER}"
# Three services: the Go API + two game instances (Arena 8081, Sanctuary 8082).
cp "$REPO_DIR/deployment/systemd/omega-api.service"       /etc/systemd/system/
cp "$REPO_DIR/deployment/systemd/omega-arena.service"     /etc/systemd/system/
cp "$REPO_DIR/deployment/systemd/omega-sanctuary.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable omega-api.service omega-arena.service omega-sanctuary.service

# Let deploy.sh (running as deploy) start/stop/restart/status ONLY these three
# units without a password. Fully-qualified unit names, no wildcards — a wildcard
# like 'omega-api*' would also match e.g. 'omega-api.service.d' or unrelated units
# the operator later creates with that prefix.
cat > /etc/sudoers.d/omega-deploy <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start omega-api.service omega-arena.service omega-sanctuary.service, \
/usr/bin/systemctl stop omega-api.service omega-arena.service omega-sanctuary.service, \
/usr/bin/systemctl restart omega-api.service omega-arena.service omega-sanctuary.service, \
/usr/bin/systemctl status omega-api.service omega-arena.service omega-sanctuary.service
EOF
chmod 0440 /etc/sudoers.d/omega-deploy
visudo -cf /etc/sudoers.d/omega-deploy >/dev/null

cat <<EOF

$(printf '\033[1;32m==> Provisioning complete.\033[0m')

Next steps:
  1. Set the DB password (role + ${ETC_DIR}/api.env must match):
       sudo -u postgres psql -c "ALTER ROLE ${DB_USER} PASSWORD 'YOUR_PW';"
       sudo nano ${ETC_DIR}/api.env       # DB_PASSWORD + JWT_SECRET_KEY
  2. From your laptop, deploy the code + start services:
       ./scripts/deploy.sh
EOF
