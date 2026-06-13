#!/usr/bin/env bash
# Run ONE Rust game-server instance locally for development/testing.
# Dev mode accepts unsigned session tickets (config default allow_unsigned_tickets=true);
# production runs --require-tickets with OMEGA_TICKET_PUBKEY set.
#
# The instance's identity is chosen with --mode/--port (forwarded to omega-server):
#   ./scripts/run_server.sh                                  # Arena (default), udp/8081
#   ./scripts/run_server.sh --mode arena     --port 8081     # Arena: monsters + PvP, ±1000
#   ./scripts/run_server.sh --mode sanctuary --port 8082     # Sanctuary: safe town, ±1856 walk-through
#
# Usage: ./scripts/run_server.sh [--mode arena|sanctuary] [--port N] [--config <file>] [--require-tickets] [...]
# Defaults to udp/8081 (Arena) and :9100 (Prometheus). To run BOTH instances at once, use
# ./scripts/dev_local.sh (which also starts the Go API).
set -euo pipefail
cd "$(dirname "$0")/../rust"

exec cargo run --release -p omega-server -- "$@"
