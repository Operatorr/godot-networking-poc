#!/usr/bin/env bash
# Start the local dev stack: Go API + BOTH game instances (Arena + Sanctuary).
#
# Two omega-server instances run side by side (one binary, two --mode/--port):
#   * Arena     — udp/8081, --mode arena     (monsters + PvP, ±1000 w/ pillars; the default)
#   * Sanctuary — udp/8082, --mode sanctuary (no monsters, PvP off, ±1856 walk-through town)
# Entering the world joins the Sanctuary (8082); the Arena portal dials the Arena (8081).
#
# Assumes PostgreSQL and Redis are ALREADY RUNNING outside this repo (e.g. via
# DBngin or a local install) — this script never starts Docker or databases.
# API config is read from api/.env (the Go server loads .env from its cwd).
#
# Usage: ./scripts/dev_local.sh [-- <extra omega-server args>]
#   ./scripts/dev_local.sh                          # API :8080, arena udp/8081, sanctuary udp/8082
#   API_PORT=9090 ./scripts/dev_local.sh            # override API port
#   ./scripts/dev_local.sh -- --require-tickets     # extra args passed to BOTH instances
#
# Ctrl+C stops all three processes. API log: logs/api_server.log
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

PID_DIR="$PROJECT_ROOT/.pids"
LOG_DIR="$PROJECT_ROOT/logs"
API_PID_FILE="$PID_DIR/api_server.pid"
ARENA_PID_FILE="$PID_DIR/arena_server.pid"
SANCTUARY_PID_FILE="$PID_DIR/sanctuary_server.pid"
API_LOG="$LOG_DIR/api_server.log"
ARENA_LOG="$LOG_DIR/arena_server.log"
SANCTUARY_LOG="$LOG_DIR/sanctuary_server.log"
mkdir -p "$PID_DIR" "$LOG_DIR"

# Args after `--` are forwarded to omega-server.
SERVER_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --)
            shift
            SERVER_ARGS=("$@")
            break
            ;;
        --help|-h)
            sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            fail "Unknown option: $1 (use -- to pass args to omega-server)"
            ;;
    esac
done

# ---- Dependency checks ------------------------------------------------------

command -v go >/dev/null 2>&1    || fail "go not found in PATH (install Go 1.21+)"
command -v cargo >/dev/null 2>&1 || fail "cargo not found in PATH (install Rust)"

# Read DB/Redis endpoints from api/.env so the reachability checks match what
# the API will actually dial.
if [ -f "$PROJECT_ROOT/api/.env" ]; then
    # NOTE: this executes api/.env as shell (any code in it runs with your
    # privileges). Trusted because it's a dev-owned, gitignored local file —
    # never point this at an untrusted .env.
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/api/.env"
    set +a
else
    warn "api/.env not found — API will use built-in defaults (cp api/.env.example api/.env)"
fi
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
API_PORT="${API_PORT:-${PORT:-8080}}"
export PORT="$API_PORT"

# The Go internal endpoints (/api/internal/*) and the region heartbeat now FAIL
# CLOSED: without SERVER_API_TOKEN / REGION_HEARTBEAT_TOKEN they reject (503)
# unless ALLOW_INSECURE_INTERNAL=true. The local stack runs token-less, so opt
# into the insecure dev path explicitly here (never set this in production).
export ALLOW_INSECURE_INTERNAL=true

# Portable TCP reachability probe (only used as a fallback when pg_isready /
# redis-cli aren't installed). Avoids `nc -G` (BSD/macOS-only connect timeout):
# bash's /dev/tcp works on both macOS and Linux. `timeout` caps the connect if
# present; otherwise the kernel's default connect timeout applies.
tcp_open() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 2 bash -c "exec 3<>/dev/tcp/$1/$2" >/dev/null 2>&1
    else
        (exec 3<>/dev/tcp/"$1"/"$2") >/dev/null 2>&1
    fi
}

if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -q -h "$DB_HOST" -p "$DB_PORT" \
        || fail "PostgreSQL not ready at $DB_HOST:$DB_PORT — start it (e.g. DBngin) first"
else
    tcp_open "$DB_HOST" "$DB_PORT" \
        || fail "PostgreSQL not reachable at $DB_HOST:$DB_PORT — start it (e.g. DBngin) first"
fi
ok "PostgreSQL reachable at $DB_HOST:$DB_PORT"

if command -v redis-cli >/dev/null 2>&1; then
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1 \
        || fail "Redis not responding at $REDIS_HOST:$REDIS_PORT — start it first (API exits without it)"
else
    tcp_open "$REDIS_HOST" "$REDIS_PORT" \
        || fail "Redis not reachable at $REDIS_HOST:$REDIS_PORT — start it first (API exits without it)"
fi
ok "Redis reachable at $REDIS_HOST:$REDIS_PORT"

# ---- Cleanup on exit ---------------------------------------------------------

API_PID=""
ARENA_PID=""
SANCTUARY_PID=""
stop_pid() {
    local pid="$1" name="$2"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 0
    info "Stopping $name (PID: $pid)..."
    kill -TERM "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
}
cleanup() {
    trap - INT TERM EXIT
    echo ""
    stop_pid "$SANCTUARY_PID" "sanctuary server"
    stop_pid "$ARENA_PID" "arena server"
    stop_pid "$API_PID" "API server"
    rm -f "$API_PID_FILE" "$ARENA_PID_FILE" "$SANCTUARY_PID_FILE"
    ok "Local dev stack stopped"
}
trap cleanup INT TERM EXIT

# ---- Go API (background) -----------------------------------------------------

if [ -f "$API_PID_FILE" ] && kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
    fail "API server already running (PID: $(cat "$API_PID_FILE")) — stop it or rm $API_PID_FILE"
fi

info "Building Go API..."
(cd "$PROJECT_ROOT/api" && go build -o bin/server ./cmd/server)

info "Starting API server on :$API_PORT (log: $API_LOG)..."
(cd "$PROJECT_ROOT/api" && exec ./bin/server) >"$API_LOG" 2>&1 &
API_PID=$!
echo "$API_PID" > "$API_PID_FILE"

for _ in $(seq 1 15); do
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
        ok "API server healthy at http://localhost:$API_PORT (PID: $API_PID)"
        break
    fi
    kill -0 "$API_PID" 2>/dev/null || { tail -30 "$API_LOG" >&2; fail "API server exited during startup — see $API_LOG"; }
    sleep 1
done
curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1 \
    || { tail -30 "$API_LOG" >&2; fail "API server did not become healthy — see $API_LOG"; }

# ---- Rust game servers (Arena + Sanctuary) --------------------------------------

info "Building omega-server (release)..."
(cd "$PROJECT_ROOT/rust" && cargo build --release -p omega-server)

# Both instances share one binary, distinguished by --mode/--port. cwd rust/ so the config
# fallback ../client/data/config/server_config.json resolves. Extra args after `--` (e.g.
# --require-tickets) are forwarded to BOTH. NOTE: both default to Prometheus :9100; the second
# bind warns and is skipped (non-fatal) — only the Arena's metrics are scrapeable locally.
cd "$PROJECT_ROOT/rust"

# The server's allow_unsigned_tickets default is now false (fail closed). The
# local stack runs token-less, so opt into unsigned tickets here. Passing the
# flag BEFORE SERVER_ARGS means an explicit `-- --require-tickets` still wins
# (omega-server applies ticket args last-wins).
info "Starting ARENA server (udp/8081, monsters + PvP). Log: $ARENA_LOG"
./target/release/omega-server --mode arena --port 8081 --allow-unsigned-tickets ${SERVER_ARGS+"${SERVER_ARGS[@]}"} \
    >"$ARENA_LOG" 2>&1 &
ARENA_PID=$!
echo "$ARENA_PID" > "$ARENA_PID_FILE"

info "Starting SANCTUARY server (udp/8082, safe town). Log: $SANCTUARY_LOG"
./target/release/omega-server --mode sanctuary --port 8082 --allow-unsigned-tickets ${SERVER_ARGS+"${SERVER_ARGS[@]}"} \
    >"$SANCTUARY_LOG" 2>&1 &
SANCTUARY_PID=$!
echo "$SANCTUARY_PID" > "$SANCTUARY_PID_FILE"

ok "Stack up: API :$API_PORT, Arena udp/8081, Sanctuary udp/8082. Ctrl+C stops everything."
# wait -n would exit when EITHER server dies; wait on both so the trap runs on Ctrl+C and the
# script stays up as long as either instance lives.
wait "$ARENA_PID" "$SANCTUARY_PID"
