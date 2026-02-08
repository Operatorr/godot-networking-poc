#!/bin/bash
# Deploy Omega Realm to a Docker-capable host
# Usage: ./scripts/deploy.sh [--build] [--down] [--logs]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOYMENT_DIR="$PROJECT_ROOT/deployment"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Determine env file
ENV_FILE="$DEPLOYMENT_DIR/.env.production"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$DEPLOYMENT_DIR/.env.example"
    echo -e "${YELLOW}[WARN]${NC} No .env.production found, using .env.example defaults"
fi

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  up       Build and start all containers (default)"
    echo "  down     Stop and remove all containers"
    echo "  build    Rebuild container images"
    echo "  logs     Follow container logs"
    echo "  status   Show container status"
    echo "  restart  Restart all containers"
    echo "  health   Check health of all services"
    echo ""
    echo "Examples:"
    echo "  $0              # Build and start everything"
    echo "  $0 up           # Same as above"
    echo "  $0 down         # Stop all services"
    echo "  $0 logs         # Follow all logs"
    echo "  $0 health       # Check service health"
}

compose_cmd() {
    docker compose -f "$DEPLOYMENT_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

cmd_up() {
    echo -e "${BLUE}[INFO]${NC} Starting Omega Realm services..."
    compose_cmd up -d --build
    echo ""
    echo -e "${GREEN}[OK]${NC} Services started. Checking health..."
    sleep 5
    cmd_status
}

cmd_down() {
    echo -e "${BLUE}[INFO]${NC} Stopping Omega Realm services..."
    compose_cmd down
    echo -e "${GREEN}[OK]${NC} Services stopped."
}

cmd_build() {
    echo -e "${BLUE}[INFO]${NC} Building container images..."
    compose_cmd build
    echo -e "${GREEN}[OK]${NC} Build complete."
}

cmd_logs() {
    compose_cmd logs -f
}

cmd_status() {
    echo ""
    echo "=========================================="
    echo "  Omega Realm - Container Status"
    echo "=========================================="
    compose_cmd ps
}

cmd_restart() {
    echo -e "${BLUE}[INFO]${NC} Restarting services..."
    compose_cmd restart
    echo -e "${GREEN}[OK]${NC} Services restarted."
}

cmd_health() {
    echo ""
    echo "=========================================="
    echo "  Omega Realm - Health Check"
    echo "=========================================="
    echo ""

    # Check API
    API_PORT=$(grep -E "^API_PORT=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || echo "8080")
    API_PORT="${API_PORT:-8080}"
    echo -n "  API Server (port $API_PORT):  "
    if curl -sf "http://localhost:$API_PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}HEALTHY${NC}"
    else
        echo -e "${RED}UNREACHABLE${NC}"
    fi

    # Check containers
    echo ""
    echo "  Container Health:"
    compose_cmd ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || compose_cmd ps
    echo ""
}

# Parse command
COMMAND="${1:-up}"

case "$COMMAND" in
    up)      cmd_up ;;
    down)    cmd_down ;;
    build)   cmd_build ;;
    logs)    cmd_logs ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    health)  cmd_health ;;
    --help|-h) usage ;;
    *)
        echo -e "${RED}[ERROR]${NC} Unknown command: $COMMAND"
        usage
        exit 1
        ;;
esac
