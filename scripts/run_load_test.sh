#!/usr/bin/env bash
# Run the bot-swarm load test against a running omega-server (./scripts/run_server.sh).
# Bots authenticate ticket-less, so the server must allow unsigned tickets (the dev default).
#
# Usage: ./scripts/run_load_test.sh --scenario baseline
#        ./scripts/run_load_test.sh --bots 75 --duration 120 --server 10.0.0.1:8081
# See rust/load_test/README.md (or --help) for scenarios and flags.
set -euo pipefail
cd "$(dirname "$0")/../rust"

exec cargo run --release -p omega-load-test -- "$@"
