#!/usr/bin/env bash
set -euo pipefail

TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
PID_FILE="$TMP_BASE/omgea-bots.pid"
TIMEOUT_SECONDS="10"

usage() {
  cat <<EOF
Usage: $0 [--pid-file file] [--timeout seconds]

Stops gameplay bots started by scripts/start_bots.sh.

Options:
  --pid-file  PID file to read (default: $PID_FILE)
  --timeout   Seconds to wait before force killing (default: 10)
  -h, --help  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pid-file)
      PID_FILE="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="$2"
      shift 2
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

if [[ ! -f "$PID_FILE" ]]; then
  echo "No bot PID file found at $PID_FILE"
  exit 0
fi

BOT_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$BOT_PID" ]]; then
  echo "Bot PID file is empty: $PID_FILE"
  rm -f "$PID_FILE"
  exit 0
fi

if ! kill -0 "$BOT_PID" 2>/dev/null; then
  echo "Bot process $BOT_PID is not running"
  echo "It likely exited before this stop request completed. Check the bot log from start_bots.sh for the failure reason."
  rm -f "$PID_FILE"
  exit 0
fi

echo "Stopping bot process $BOT_PID"
kill "$BOT_PID"

for _i in $(seq 1 "$TIMEOUT_SECONDS"); do
  if ! kill -0 "$BOT_PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Bots stopped"
    exit 0
  fi
  sleep 1
done

echo "Bot process $BOT_PID did not exit after ${TIMEOUT_SECONDS}s; force killing"
kill -9 "$BOT_PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Bots stopped"
