#!/usr/bin/env bash
# Run the bot-swarm load test against a running omega-server.
#
# Auth: against a LOCAL dev server bots join ticket-less (the server allows unsigned tickets —
# dev_local.sh passes --allow-unsigned-tickets). Against the fail-closed LIVE server they must
# present a SIGNED ticket: --live makes each bot fetch one from the Go API's load-test endpoint
# (POST /api/loadtest/ticket) using OMEGA_LOAD_TEST_SECRET — which must match the live API's
# LOAD_TEST_TICKET_SECRET. The minted tickets carry synthetic character_ids (>= 1_000_000) that
# the server keeps out of all DB I/O, so the swarm authenticates without touching real data and
# the live server stays locked down (no unsigned-ticket window). See rust/load_test/README.md.
#
# Target selection (highest precedence first):
#   --server <host:port>     explicit (e.g. --server 1.2.3.4:8081)
#   --live                   the live ARENA — same address the client's LIVE switch uses
#   OMEGA_SERVER=<host:port>  env default, so you don't retype the live IP
#   (none set)               falls back to the load-test default 127.0.0.1:8081 (local ARENA)
#
# The swarm targets the ARENA instance (udp/8081): the load test exercises monsters + PvP +
# AoI, which the Sanctuary (--mode sanctuary, udp/8082) deliberately has none of. Do NOT point
# --server at the Sanctuary — it is the safe hub, not under load test.
#
# Examples:
#   ./scripts/run_load_test.sh --scenario baseline                 # local server (unsigned)
#   OMEGA_LOAD_TEST_SECRET=… ./scripts/run_load_test.sh --scenario baseline --live   # LIVE (signed)
#   OMEGA_SERVER=<droplet-ip>:8081 ./scripts/run_load_test.sh --scenario baseline   # LIVE addr only
#   ./scripts/run_load_test.sh --bots 3 --scenario strategy --server <droplet-ip>:8081
#
# See rust/load_test/README.md (or --help) for scenarios and flags.
set -euo pipefail
cd "$(dirname "$0")/../rust"

# The live ARENA: the region host the client advertises (deployment/server_config.arena.json
# `advertise_url`) on ARENA_DEFAULT_PORT 8081 — exactly what the client's LIVE switch connects to.
# resolve_server() in main.rs does DNS, so the hostname is fine. Override with OMEGA_LIVE_SERVER.
LIVE_SERVER="${OMEGA_LIVE_SERVER:-gsapi.marrowtech.app:8081}"
# The live API origin that mints load-test tickets (HTTPS via Caddy). Override with OMEGA_TICKET_API.
LIVE_API="${OMEGA_TICKET_API:-https://gsapi.marrowtech.app}"

# Walk the args: consume our own --live (the binary doesn't know it), pass everything else through,
# and note whether the caller already pinned --server/-s (that always wins).
ARGS=()
want_live=false
has_server=false
for a in "$@"; do
  case "$a" in
    --live) want_live=true ;;
    --server|-s) has_server=true; ARGS+=("$a") ;;
    *) ARGS+=("$a") ;;
  esac
done

# Resolve the target unless --server was explicit: --live beats OMEGA_SERVER beats the binary default.
if ! $has_server; then
  if $want_live; then
    ARGS+=(--server "$LIVE_SERVER")
  elif [[ -n "${OMEGA_SERVER:-}" ]]; then
    ARGS+=(--server "$OMEGA_SERVER")
  fi
elif $want_live; then
  echo "run_load_test.sh: both --server and --live given; --server wins." >&2
fi

# --live also turns on signed-ticket auth: point the binary at the live API and require the
# shared secret up front (clearer than letting every bot fail with BAD_TICKET). The binary reads
# OMEGA_TICKET_API / OMEGA_LOAD_TEST_SECRET itself, so we just export the API origin and check
# the secret here. A caller using an explicit --server for live can do the same by exporting both.
if $want_live; then
  if [[ -z "${OMEGA_LOAD_TEST_SECRET:-}" ]]; then
    echo "run_load_test.sh: --live needs OMEGA_LOAD_TEST_SECRET set (it must match the live API's" >&2
    echo "  LOAD_TEST_TICKET_SECRET). Example: OMEGA_LOAD_TEST_SECRET=… $0 $* " >&2
    exit 2
  fi
  export OMEGA_TICKET_API="$LIVE_API"
fi

exec cargo run --release -p omega-load-test -- ${ARGS+"${ARGS[@]}"}
