#!/bin/bash
# Stop all game services (Go API server and Godot game server)
# Usage: ./stop_services.sh [--api-only | --game-only]

set -e

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

# Parse arguments
STOP_API=true
STOP_GAME=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --api-only)
            STOP_GAME=false
            shift
            ;;
        --game-only)
            STOP_API=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--api-only | --game-only]"
            echo ""
            echo "Options:"
            echo "  --api-only   Only stop the Go API server"
            echo "  --game-only  Only stop the Godot game server"
            echo "  --help       Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR]${NC} Unknown option: $1"
            exit 1
            ;;
    esac
done

# Stop a service by PID file
stop_service() {
    local pid_file="$1"
    local name="$2"
    local port="$3"
    local pids=""

    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if process_exists "$pid"; then
            pids="$pid"
        else
            echo -e "${YELLOW}[WARN]${NC} $name process (PID: $pid) not running"
            rm -f "$pid_file"
        fi
    else
        echo -e "${YELLOW}[WARN]${NC} $name PID file not found - checking port $port"
    fi

    if [ -n "$port" ] && command -v lsof >/dev/null 2>&1; then
        local port_pids
        port_pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "$port_pids" ]; then
            pids=$(printf "%s\n%s\n" "$pids" "$port_pids" | sed '/^$/d' | sort -u)
        fi
    fi

    if [ -z "$pids" ]; then
        echo -e "${YELLOW}[WARN]${NC} $name is not running"
        return 0
    fi

    local failed=false
    local pid
    for pid in $pids; do
        echo -e "${BLUE}[INFO]${NC} Stopping $name (PID: $pid)..."

        # Try graceful shutdown first (SIGTERM)
        kill -TERM "$pid" 2>/dev/null || true

        # Wait up to 5 seconds for graceful shutdown
        local count=0
        while process_exists "$pid" && [ $count -lt 5 ]; do
            sleep 1
            count=$((count + 1))
        done

        # Force kill if still running
        if process_exists "$pid"; then
            echo -e "${YELLOW}[WARN]${NC} $name didn't stop gracefully, forcing..."
            kill -9 "$pid" 2>/dev/null || true
            sleep 1
        fi

        if ! process_exists "$pid"; then
            echo -e "${GREEN}[OK]${NC} $name stopped"
        else
            echo -e "${RED}[ERROR]${NC} Failed to stop $name (PID: $pid)"
            failed=true
        fi
    done

    if [ "$failed" = false ]; then
        rm -f "$pid_file"
    else
        return 1
    fi
}

# Main execution
echo "=========================================="
echo "  Omega Realm - Service Shutdown"
echo "=========================================="
echo ""

if [ "$STOP_API" = true ]; then
    stop_service "$API_PID_FILE" "API Server" "$API_PORT"
fi

if [ "$STOP_GAME" = true ]; then
    stop_service "$GAME_PID_FILE" "Game Server" "$GAME_PORT"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Service shutdown complete!${NC}"
echo "=========================================="
