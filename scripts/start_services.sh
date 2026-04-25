#!/bin/bash
# Start all game services (Go API server and Godot game server)
# Usage: ./start_services.sh [--api-only | --game-only]
# Note: PostgreSQL database should be started manually

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

# Log files
LOG_DIR="$PROJECT_ROOT/logs"
API_LOG="$LOG_DIR/api_server.log"
GAME_LOG="$LOG_DIR/game_server.log"

# Load test environment if exists
if [ -f "$PROJECT_ROOT/.env.test" ]; then
    source "$PROJECT_ROOT/.env.test"
    echo -e "${BLUE}[INFO]${NC} Loaded .env.test configuration"
fi

# Set defaults
GODOT_PATH="${GODOT_PATH:-godot}"
GO_PATH="${GO_PATH:-go}"
API_PORT="${API_PORT:-8080}"
GAME_PORT="${GAME_PORT:-8081}"

# Create directories
mkdir -p "$PID_DIR" "$LOG_DIR"

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
START_API=true
START_GAME=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --api-only)
            START_GAME=false
            shift
            ;;
        --game-only)
            START_API=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--api-only | --game-only]"
            echo ""
            echo "Options:"
            echo "  --api-only   Only start the Go API server"
            echo "  --game-only  Only start the Godot game server"
            echo "  --help       Show this help message"
            echo ""
            echo "Note: PostgreSQL database must be started manually."
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR]${NC} Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if service is already running
check_running() {
    local pid_file="$1"
    local name="$2"
    local port="$3"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if process_exists "$pid"; then
            echo -e "${YELLOW}[WARN]${NC} $name is already running (PID: $pid)"
            return 0
        else
            rm -f "$pid_file"
        fi
    fi

    if [ -n "$port" ] && command -v lsof >/dev/null 2>&1; then
        local port_pids
        port_pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "$port_pids" ]; then
            local pid
            pid=$(echo "$port_pids" | head -n 1)
            echo "$pid" > "$pid_file"
            echo -e "${YELLOW}[WARN]${NC} $name is already listening on port $port (PID: $pid)"
            return 0
        fi
    fi

    return 1
}

# Start Go API Server
start_api_server() {
    echo -e "${BLUE}[INFO]${NC} Starting Go API Server..."

    # Load API .env before port checks because the Go server reads PORT.
    if [ -f "$PROJECT_ROOT/api/.env" ]; then
        set -a
        source "$PROJECT_ROOT/api/.env"
        set +a
    fi
    export PORT="${PORT:-$API_PORT}"

    if check_running "$API_PID_FILE" "API Server" "$PORT"; then
        return 0
    fi

    cd "$PROJECT_ROOT/api"

    # Check if Go is available
    if ! command -v "$GO_PATH" &> /dev/null; then
        echo -e "${RED}[ERROR]${NC} Go not found at: $GO_PATH"
        echo "Please install Go or set GO_PATH in .env.test"
        return 1
    fi

    # Build and run
    echo -e "${BLUE}[INFO]${NC} Building API server..."
    "$GO_PATH" build -o bin/server ./cmd/server

    echo -e "${BLUE}[INFO]${NC} Starting API server on port $PORT..."
    nohup ./bin/server > "$API_LOG" 2>&1 &
    local pid=$!
    echo $pid > "$API_PID_FILE"

    # Wait for server to start
    sleep 2

    if process_exists "$pid" && lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q "^$pid$"; then
        echo -e "${GREEN}[OK]${NC} API Server started (PID: $pid)"
        echo -e "${BLUE}[INFO]${NC} API Server log: $API_LOG"
    else
        echo -e "${RED}[ERROR]${NC} API Server failed to start"
        cat "$API_LOG"
        rm -f "$API_PID_FILE"
        return 1
    fi
}

# Start Godot Game Server
start_game_server() {
    echo -e "${BLUE}[INFO]${NC} Starting Godot Game Server..."

    if check_running "$GAME_PID_FILE" "Game Server" "$GAME_PORT"; then
        return 0
    fi

    cd "$PROJECT_ROOT/client"

    # Check if Godot is available
    if ! command -v "$GODOT_PATH" &> /dev/null; then
        # Try common macOS path
        if [ -f "/Applications/Godot.app/Contents/MacOS/Godot" ]; then
            GODOT_PATH="/Applications/Godot.app/Contents/MacOS/Godot"
        else
            echo -e "${RED}[ERROR]${NC} Godot not found at: $GODOT_PATH"
            echo "Please install Godot or set GODOT_PATH in .env.test"
            return 1
        fi
    fi

    echo -e "${BLUE}[INFO]${NC} Starting Godot server in headless mode..."
    nohup "$GODOT_PATH" --headless > "$GAME_LOG" 2>&1 &
    local pid=$!
    echo $pid > "$GAME_PID_FILE"

    # Wait for server to start
    sleep 3

    if kill -0 "$pid" 2>/dev/null; then
        echo -e "${GREEN}[OK]${NC} Game Server started (PID: $pid)"
        echo -e "${BLUE}[INFO]${NC} Game Server log: $GAME_LOG"
    else
        echo -e "${RED}[ERROR]${NC} Game Server failed to start"
        cat "$GAME_LOG"
        return 1
    fi
}

# Main execution
echo "=========================================="
echo "  Omega Realm - Service Startup"
echo "=========================================="
echo ""

if [ "$START_API" = true ]; then
    start_api_server || exit 1
fi

if [ "$START_GAME" = true ]; then
    start_game_server || exit 1
fi

echo ""
echo "=========================================="
echo -e "${GREEN}All requested services started!${NC}"
echo ""
echo "To stop services: ./scripts/stop_services.sh"
echo "To view logs:"
[ "$START_API" = true ] && echo "  API:  tail -f $API_LOG"
[ "$START_GAME" = true ] && echo "  Game: tail -f $GAME_LOG"
echo "=========================================="
