#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="ws://localhost:8081"
BOT_COUNT="10"
STAGGER_MS="200"
TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
PID_FILE="$TMP_BASE/omgea-bots.pid"
LOG_FILE="$TMP_BASE/omgea-bots.log"
FOREGROUND="0"

usage() {
  cat <<EOF
Usage: $0 [--server ws://host:port] [--bots count] [--stagger ms] [--log file] [--pid-file file] [--foreground]

Starts long-running external WebSocket gameplay bots that authenticate and play like clients.

Options:
  --server      WebSocket server URL (default: ws://localhost:8081)
  --bots        Number of bots, capped at 10 by default workflow (default: 10)
  --stagger     Milliseconds between bot connects (default: 200)
  --log         Bot output log file (default: $LOG_FILE)
  --pid-file    PID file for stop_bots.sh (default: $PID_FILE)
  --foreground  Run in the foreground instead of starting a background process
  -h, --help    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server|-s)
      SERVER_URL="$2"
      shift 2
      ;;
    --bots|-b)
      BOT_COUNT="$2"
      shift 2
      ;;
    --stagger)
      STAGGER_MS="$2"
      shift 2
      ;;
    --log|-l)
      LOG_FILE="$2"
      shift 2
      ;;
    --pid-file)
      PID_FILE="$2"
      shift 2
      ;;
    --foreground)
      FOREGROUND="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "$BOT_COUNT" =~ ^[0-9]+$ ]]; then
  echo "--bots must be a positive integer" >&2
  exit 1
fi

if (( BOT_COUNT < 1 || BOT_COUNT > 10 )); then
  echo "--bots must be between 1 and 10" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  SELECTED_PYTHON="$PYTHON_BIN"
elif [[ -x "$ROOT_DIR/load_testing/venv/bin/python" ]]; then
  SELECTED_PYTHON="$ROOT_DIR/load_testing/venv/bin/python"
else
  SELECTED_PYTHON="python3"
fi

require_python_dependency() {
  local module_name="$1"

  if ! "$SELECTED_PYTHON" -c "import ${module_name}" >/dev/null 2>&1; then
    cat >&2 <<EOF
Missing Python dependency: ${module_name}

Install the bot runtime dependencies before starting bots:
  cd load_testing
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt

Or install directly with:
  $SELECTED_PYTHON -m pip install -r "$ROOT_DIR/load_testing/requirements.txt"
EOF
    exit 1
  fi
}

require_python_dependency "websockets"

CMD=(
  "$SELECTED_PYTHON" "$ROOT_DIR/load_testing/bot_swarm.py"
  --server "$SERVER_URL"
  --bots "$BOT_COUNT"
  --duration 0
  --stagger "$STAGGER_MS"
  --behavior strategy
  --no-report
)

echo "Starting $BOT_COUNT gameplay bots against $SERVER_URL"

if [[ "$FOREGROUND" == "1" ]]; then
  echo "Running in foreground with $SELECTED_PYTHON. Press Ctrl+C to stop."
  "${CMD[@]}"
else
  if [[ -f "$PID_FILE" ]]; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
      echo "Bots already running with PID $EXISTING_PID"
      echo "Use scripts/stop_bots.sh --pid-file \"$PID_FILE\" to stop them."
      exit 1
    fi
  fi

  mkdir -p "$(dirname "$LOG_FILE")"
  mkdir -p "$(dirname "$PID_FILE")"
  nohup "${CMD[@]}" > "$LOG_FILE" 2>&1 &
  BOT_PID="$!"
  echo "$BOT_PID" > "$PID_FILE"
  sleep 0.5
  if ! kill -0 "$BOT_PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Bot process exited during startup. Log: $LOG_FILE" >&2
    tail -20 "$LOG_FILE" >&2 || true
    exit 1
  fi
  echo "Bots started with PID $BOT_PID using $SELECTED_PYTHON"
  echo "Log: $LOG_FILE"
  echo "Stop with: scripts/stop_bots.sh --pid-file \"$PID_FILE\""
fi
