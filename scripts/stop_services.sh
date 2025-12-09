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

    if [ ! -f "$pid_file" ]; then
        echo -e "${YELLOW}[WARN]${NC} $name PID file not found - service may not be running"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} $name process (PID: $pid) not running"
        rm -f "$pid_file"
        return 0
    fi

    echo -e "${BLUE}[INFO]${NC} Stopping $name (PID: $pid)..."

    # Try graceful shutdown first (SIGTERM)
    kill -TERM "$pid" 2>/dev/null

    # Wait up to 5 seconds for graceful shutdown
    local count=0
    while kill -0 "$pid" 2>/dev/null && [ $count -lt 5 ]; do
        sleep 1
        count=$((count + 1))
    done

    # Force kill if still running
    if kill -0 "$pid" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} $name didn't stop gracefully, forcing..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "${GREEN}[OK]${NC} $name stopped"
        rm -f "$pid_file"
    else
        echo -e "${RED}[ERROR]${NC} Failed to stop $name"
        return 1
    fi
}

# Main execution
echo "=========================================="
echo "  Omega Realm - Service Shutdown"
echo "=========================================="
echo ""

if [ "$STOP_API" = true ]; then
    stop_service "$API_PID_FILE" "API Server"
fi

if [ "$STOP_GAME" = true ]; then
    stop_service "$GAME_PID_FILE" "Game Server"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Service shutdown complete!${NC}"
echo "=========================================="
