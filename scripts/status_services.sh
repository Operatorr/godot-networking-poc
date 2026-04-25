#!/bin/bash
# Check status of all game services
# Usage: ./status_services.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# PID files
PID_DIR="$PROJECT_ROOT/.pids"
API_PID_FILE="$PID_DIR/api_server.pid"
GAME_PID_FILE="$PID_DIR/game_server.pid"

# Load test environment if exists
if [ -f "$PROJECT_ROOT/.env.test" ]; then
    source "$PROJECT_ROOT/.env.test"
fi

# Load API .env if exists because the Go server reads PORT.
if [ -f "$PROJECT_ROOT/api/.env" ]; then
    set -a
    source "$PROJECT_ROOT/api/.env"
    set +a
fi

# Set defaults
API_PORT="${PORT:-${API_PORT:-8080}}"
GAME_PORT="${GAME_PORT:-8081}"

process_exists() {
    local pid="$1"

    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    if command -v lsof >/dev/null 2>&1 && lsof -p "$pid" >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

# Log files
LOG_DIR="$PROJECT_ROOT/logs"
API_LOG="$LOG_DIR/api_server.log"
GAME_LOG="$LOG_DIR/game_server.log"

# Check service status
check_service() {
    local pid_file="$1"
    local name="$2"
    local port="$3"

    printf "%-20s" "$name:"

    local port_pids=""
    if [ -n "$port" ] && command -v lsof >/dev/null 2>&1; then
        port_pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    fi

    if [ ! -f "$pid_file" ]; then
        if [ -n "$port_pids" ]; then
            echo -e "${GREEN}RUNNING${NC} (PID: $(echo "$port_pids" | tr '\n' ' '), Port: $port, no PID file)"
            return 0
        fi
        echo -e "${RED}NOT RUNNING${NC} (no PID file)"
        return 1
    fi

    local pid=$(cat "$pid_file")

    if ! process_exists "$pid"; then
        if [ -n "$port_pids" ]; then
            echo -e "${GREEN}RUNNING${NC} (PID: $(echo "$port_pids" | tr '\n' ' '), Port: $port, stale PID file: $pid)"
            return 0
        fi
        echo -e "${RED}NOT RUNNING${NC} (stale PID file)"
        return 1
    fi

    # Check if port is listening
    if [ -n "$port" ]; then
        if [ -n "$port_pids" ]; then
            echo -e "${GREEN}RUNNING${NC} (PID: $pid, Port: $port)"
        else
            echo -e "${YELLOW}RUNNING${NC} (PID: $pid, Port not listening)"
        fi
    else
        echo -e "${GREEN}RUNNING${NC} (PID: $pid)"
    fi

    return 0
}

# Check database connection
check_database() {
    printf "%-20s" "PostgreSQL:"

    # Try to check if postgres is running
    if command -v pg_isready &> /dev/null; then
        if pg_isready -q 2>/dev/null; then
            echo -e "${GREEN}RUNNING${NC}"
            return 0
        fi
    fi

    # Fallback: check if port 5432 is open
    if lsof -i :5432 -sTCP:LISTEN >/dev/null 2>&1; then
        echo -e "${GREEN}RUNNING${NC} (port 5432 open)"
        return 0
    fi

    echo -e "${RED}NOT RUNNING${NC} (or not accessible)"
    return 1
}

# Main execution
echo "=========================================="
echo "  Omega Realm - Service Status"
echo "=========================================="
echo ""

check_database
check_service "$API_PID_FILE" "API Server" "$API_PORT"
check_service "$GAME_PID_FILE" "Game Server" "$GAME_PORT"

echo ""
echo "=========================================="
echo "Log Files:"
echo "  API:  $API_LOG"
echo "  Game: $GAME_LOG"
echo "=========================================="
