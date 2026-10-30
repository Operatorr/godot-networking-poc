#!/usr/bin/env bash
# quick_stress.sh — ONE command, ~90 s, full telemetry: the fast hill-climb loop.
#
#   ./scripts/quick_stress.sh                      # 100 strategy bots, 60 s, local Arena
#   ./scripts/quick_stress.sh --bots 150 --label n2 # 150 bots, tag the run "n2"
#   ./scripts/quick_stress.sh --bots 50 --duration 30 --behavior combat
#
# What it does, start to finish, with no human in the loop:
#   1. builds omega-server + omega-load-test (release; incremental, so seconds when unchanged)
#   2. starts a LOCAL Arena server (deployment/server_config.loadtest.json: max_players 999,
#      no API, unsigned tickets) with OMEGA_MEASURE_DIR telemetry on (per-tick + 1 Hz samples)
#   3. starts a 1 Hz host sampler (server/bots CPU + RSS, system CPU, UDP error counters)
#   4. runs the bot swarm (`--scenario quick` defaults: 100 bots, 60 s, strategy behavior,
#      one join per 100 ms, sharded over --threads OS threads so the GENERATOR is never the
#      bottleneck on a multi-core box)
#   5. stops everything, then renders loadtest-runs/<run>/REPORT.md + summary.json and prints
#      the compact summary to stdout, and appends one row to the hill-climb ledger
#      (docs/netcode/perf-notes/hill-climb/ledger.md) unless --no-ledger.
#
# Everything lands in loadtest-runs/<timestamp>-<label>/ (gitignored); loadtest-runs/latest
# points at the newest run. Read REPORT.md first; raw evidence is next to it.
#
# Options:
#   --bots N          bot count (default 100)         --duration S   seconds (default 60)
#   --behavior B      default|idle|movement|combat|clustered|strategy (default strategy)
#   --threads T       swarm threads (default: min(4, nproc-1), >=1)
#   --stagger MS      ms between joins (default 100)  --seed S       bot RNG seed (default 1)
#   --label L         run label (default "quick")     --port P       server UDP port (default 8081)
#   --config FILE     server config (default deployment/server_config.loadtest.json)
#   --no-build        skip cargo build                --no-ledger    don't append the ledger row
#   --server-env K=V  extra env for the server (repeatable; e.g. OMEGA_AOI_AUDIT=1)
#   --                everything after is passed to omega-load-test verbatim
#
# Exit code: the load test's (0 criteria met · 1 criteria failed · 2 strict assertions failed),
# or 3 if the harness itself failed (server didn't start, port busy, ...). The report is always
# rendered when the swarm ran, even if the run "broke" — that is the point.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BOTS=100; DURATION=60; BEHAVIOR=strategy; THREADS=""; STAGGER=100; SEED=1; LABEL=quick
PORT=8081; CONFIG="deployment/server_config.loadtest.json"; BUILD=1; LEDGER=1
SERVER_ENV=(); EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bots) BOTS="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --behavior) BEHAVIOR="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --stagger) STAGGER="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --no-build) BUILD=0; shift ;;
    --no-ledger) LEDGER=0; shift ;;
    --server-env) SERVER_ENV+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) echo "quick_stress.sh: unknown option '$1' (see --help)" >&2; exit 3 ;;
  esac
done
LABEL="$(echo "$LABEL" | tr -c 'A-Za-z0-9_.\n-' '-')"
NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
if [[ -z "$THREADS" ]]; then
  THREADS=$(( NPROC - 1 )); (( THREADS > 4 )) && THREADS=4; (( THREADS < 1 )) && THREADS=1
fi

RUN_ROOT="$ROOT/loadtest-runs"
RUN="$RUN_ROOT/$(date -u +%Y%m%d-%H%M%S)-$LABEL"
mkdir -p "$RUN/server" "$RUN/bots"
ln -sfn "$RUN" "$RUN_ROOT/latest"
PIDS="$RUN/pids.txt"; : > "$PIDS"
SERVER_PID=""; SAMPLER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -INT "$SERVER_PID" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$SERVER_PID" 2>/dev/null || break; sleep 0.3; done
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
  [[ -n "$SAMPLER_PID" ]] && kill "$SAMPLER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

T0=$(date +%s)
echo "quick_stress: run dir $RUN"
echo "quick_stress: $BOTS $BEHAVIOR bots × ${DURATION}s, join every ${STAGGER} ms, $THREADS swarm thread(s), seed $SEED"

# 1. build
if (( BUILD )); then
  echo "quick_stress: building (release)…"
  if ! (cd rust && cargo build --release -p omega-server -p omega-load-test 2>&1 | grep -E "^(error|warning: unused)" -A 6; test "${PIPESTATUS[0]}" -eq 0); then
    echo "quick_stress: build FAILED" >&2; exit 3
  fi
fi
SERVER_BIN="rust/target/release/omega-server"; SWARM_BIN="rust/target/release/omega-load-test"
[[ -x "$SERVER_BIN" && -x "$SWARM_BIN" ]] || { echo "quick_stress: binaries missing (run without --no-build)" >&2; exit 3; }

# preflight: the port must be free (a leftover server would silently absorb the swarm)
if command -v ss >/dev/null 2>&1 && ss -lun 2>/dev/null | grep -q ":$PORT "; then
  echo "quick_stress: udp/$PORT is already in use (a previous server still running?)" >&2; exit 3
elif command -v lsof >/dev/null 2>&1 && lsof -nP -iUDP:"$PORT" >/dev/null 2>&1; then
  echo "quick_stress: udp/$PORT is already in use (a previous server still running?)" >&2; exit 3
fi
# one UDP socket per bot (+ headroom)
ulimit -n $(( BOTS + 512 > 4096 ? BOTS + 512 : 4096 )) 2>/dev/null || true

# 2. server
T_SERVER=$(date +%s.%N)
env OMEGA_MEASURE_DIR="$RUN/server" RUST_LOG="${RUST_LOG:-info}" OMEGA_METRICS_PORT=0 ${SERVER_ENV+"${SERVER_ENV[@]}"} \
  "$SERVER_BIN" --config "$CONFIG" --port "$PORT" --allow-unsigned-tickets > "$RUN/server.log" 2>&1 &
SERVER_PID=$!
echo "server=$SERVER_PID" >> "$PIDS"
for _ in $(seq 1 50); do
  grep -q "listening on udp" "$RUN/server.log" 2>/dev/null && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "quick_stress: server exited at boot — see $RUN/server.log" >&2; tail -20 "$RUN/server.log" >&2; exit 3; }
  sleep 0.2
done
grep -q "listening on udp" "$RUN/server.log" || { echo "quick_stress: server never started listening" >&2; exit 3; }

# 3. host sampler
python3 scripts/quick_stress/sample_host.py --out "$RUN/host.ndjson" --pids "$PIDS" --udp-port "$PORT" &
SAMPLER_PID=$!

# 4. swarm
T_SWARM=$(date +%s.%N)
echo "quick_stress: swarm running (ramp ≈ $(( BOTS * STAGGER / 1000 )) s + ${DURATION} s)…"
"$SWARM_BIN" --scenario quick --bots "$BOTS" --duration "$DURATION" --behavior "$BEHAVIOR" \
  --threads "$THREADS" --stagger "$STAGGER" --seed "$SEED" --server "127.0.0.1:$PORT" \
  -o "$RUN/bots/report.json" ${EXTRA+"${EXTRA[@]}"} > "$RUN/bots.log" 2>&1 &
SWARM_PID=$!
echo "bots=$SWARM_PID" >> "$PIDS"
wait "$SWARM_PID"; SWARM_EXIT=$?
T_SWARM_END=$(date +%s.%N)

# 5. stop + report
cleanup; SERVER_PID=""; SAMPLER_PID=""
trap - EXIT
T1=$(date +%s)
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY="$(git status --porcelain 2>/dev/null | grep -q . && echo true || echo false)"
cat > "$RUN/run.json" <<JSON
{
  "label": "$LABEL", "bots": $BOTS, "duration_s": $DURATION, "behavior": "$BEHAVIOR",
  "threads": $THREADS, "stagger_ms": $STAGGER, "seed": $SEED, "port": $PORT, "config": "$CONFIG",
  "git_sha": "$GIT_SHA", "git_dirty": $GIT_DIRTY, "host_cpus": $NPROC,
  "platform": "$(uname -sm)", "swarm_exit": $SWARM_EXIT,
  "t_server_start": $T_SERVER, "t_swarm_start": $T_SWARM, "t_swarm_end": $T_SWARM_END,
  "wall_s": $(( T1 - T0 )), "extra_args": "${EXTRA[*]:-}"
}
JSON
LEDGER_ARGS=()
(( LEDGER )) && LEDGER_ARGS=(--ledger "docs/netcode/perf-notes/hill-climb/ledger.md")
python3 scripts/quick_stress/report.py "$RUN" ${LEDGER_ARGS+"${LEDGER_ARGS[@]}"} || echo "quick_stress: report FAILED (raw evidence is in $RUN)" >&2
echo
echo "quick_stress: done in $(( T1 - T0 )) s → $RUN/REPORT.md  (swarm exit $SWARM_EXIT)"
exit "$SWARM_EXIT"
