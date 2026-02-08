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

    if [ ! -f "$pid_file" ]; then
        echo -e "${RED}NOT RUNNING${NC} (no PID file)"
        return 1
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "${RED}NOT RUNNING${NC} (stale PID file)"
        return 1
    fi

    # Check if port is listening
    if [ -n "$port" ]; then
        if lsof -i ":$port" -sTCP:LISTEN >/dev/null 2>&1; then
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
check_service "$API_PID_FILE" "API Server" "8080"
check_service "$GAME_PID_FILE" "Game Server" "8081"

echo ""
echo "=========================================="
echo "Log Files:"
echo "  API:  $API_LOG"
echo "  Game: $GAME_LOG"
echo "=========================================="
