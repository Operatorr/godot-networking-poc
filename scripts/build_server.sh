#!/usr/bin/env bash
# Build the Rust game server (omega-server). The old Godot headless-server export is retired
# (migration-spec D1) — the client project now exports the CLIENT only.
set -euo pipefail
cd "$(dirname "$0")/../rust"

echo "Building omega-server (release)..."
cargo build --release -p omega-server

echo "Server build complete: rust/target/release/omega-server"
echo ""
echo "Run it locally:"
echo "  ./scripts/run_server.sh    # dev mode (unsigned tickets accepted)"
echo "Args: --config <file> | --require-tickets | --allow-unsigned-tickets"
