#!/usr/bin/env bash
# Run the bot-swarm load test against a running omega-server.
# Bots authenticate ticket-less, so the target server must allow unsigned tickets
# (the dev default, and the native deploy default — see deployment/env/server.env).
#
# Target selection (pick one):
#   --server <host:port>     explicit, highest precedence (e.g. --server 1.2.3.4:8081)
#   OMEGA_SERVER=<host:port>  env default, so you don't retype the live IP
#   (neither set)            falls back to the load-test default 127.0.0.1:8081 (the ARENA)
#
# The swarm targets the ARENA instance (udp/8081): the load test exercises monsters + PvP +
# AoI, which the Sanctuary (--mode sanctuary, udp/8082) deliberately has none of. Do NOT point
# --server at the Sanctuary — it is the safe hub, not under load test.
#
# Examples:
#   ./scripts/run_load_test.sh --scenario baseline                 # local server
#   OMEGA_SERVER=157.230.244.25:8081 ./scripts/run_load_test.sh --scenario baseline   # LIVE
#   ./scripts/run_load_test.sh --bots 2 --behavior strategy --server 157.230.244.25:8081
#
# See rust/load_test/README.md (or --help) for scenarios and flags.
set -euo pipefail
cd "$(dirname "$0")/../rust"

# Inject OMEGA_SERVER as --server unless the caller already passed --server/-s.
ARGS=("$@")
if [[ -n "${OMEGA_SERVER:-}" ]]; then
  has_server=false
  for a in "$@"; do [[ "$a" == "--server" || "$a" == "-s" ]] && has_server=true && break; done
  $has_server || ARGS+=(--server "$OMEGA_SERVER")
fi

exec cargo run --release -p omega-load-test -- ${ARGS+"${ARGS[@]}"}
