#!/bin/bash
# Build script for Godot headless server

set -e

echo "Building Omega Realm Server..."

# Navigate to client directory (server exports from same project)
cd "$(dirname "$0")/../client"

# Check if Godot is available
if ! command -v godot &> /dev/null; then
    echo "Error: Godot not found in PATH"
    echo "Please install Godot 4.5 or add it to your PATH"
    exit 1
fi

# Export headless server
echo "Exporting Linux headless server..."
godot --headless --export-release "Linux Headless Server" "../exports/server/linux/omega-server.x86_64"

echo "Server build complete!"
echo "Export located in: ../exports/server/linux/"
echo ""
echo "To run the server locally:"
echo "  ../exports/server/linux/omega-server.x86_64 --headless"
