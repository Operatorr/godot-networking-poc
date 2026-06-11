#!/usr/bin/env bash
# Run the Rust game server locally for development/testing.
# Dev mode accepts unsigned session tickets (config default allow_unsigned_tickets=true);
# production runs --require-tickets with OMEGA_TICKET_PUBKEY set.
#
# Usage: ./scripts/run_server.sh [--config <file>] [--require-tickets] [...]
# Listens on udp/8081 (game) and :9100 (Prometheus) by default.
set -euo pipefail
cd "$(dirname "$0")/../rust"

exec cargo run --release -p omega-server -- "$@"
