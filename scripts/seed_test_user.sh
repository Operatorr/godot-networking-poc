#!/bin/bash
# Seed/update the local test login user from .env.test.
# Usage: ./scripts/seed_test_user.sh [--reset-character] [-username name] [-password pass]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
GO_PATH="${GO_PATH:-go}"

cd "$PROJECT_ROOT/api"
exec "$GO_PATH" run ./cmd/seed_test_user "$@"
