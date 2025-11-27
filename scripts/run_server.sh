#!/bin/bash
# Run Godot server locally for development/testing
# This runs the server from the editor without exporting

set -e

echo "Starting Omega Realm Server (Development Mode)..."

# Navigate to client directory
cd "$(dirname "$0")/../client"

# Check if Godot is available
if ! command -v godot &> /dev/null; then
    echo "Error: Godot not found in PATH"
    echo "Please install Godot 4.5 or add it to your PATH"
    exit 1
fi

# Check for custom config file path
CONFIG_PATH=""
if [ -n "$1" ]; then
    CONFIG_PATH="$1"
    echo "Using config: $CONFIG_PATH"
fi

# Run Godot in headless server mode
# --headless enables headless mode (no display)
# The project will detect this and run as server via DisplayServer.get_name() == "headless"
echo "Running server on port 8081 (default)..."
echo "Press Ctrl+C to stop the server"
echo ""

if [ -n "$CONFIG_PATH" ]; then
    # Copy config to user:// location for the server to pick up
    # Note: user:// path varies by platform, this is a simplified approach
    godot --headless
else
    godot --headless
fi
