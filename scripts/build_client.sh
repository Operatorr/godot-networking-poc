#!/bin/bash
# Build script for Godot client

set -e

echo "Building Omega Realm Client..."

# Navigate to client directory
cd "$(dirname "$0")/../client"

# Check if Godot is available
if ! command -v godot &> /dev/null; then
    echo "Error: Godot not found in PATH"
    echo "Please install Godot 4.5 or add it to your PATH"
    exit 1
fi

# Export for Windows
echo "Exporting Windows client..."
godot --headless --export-release "Windows Desktop (Client)" "../exports/client/windows/omega-client.exe"

# Export for Linux
echo "Exporting Linux client..."
godot --headless --export-release "Linux Desktop (Client)" "../exports/client/linux/omega-client.x86_64"

# Export for macOS
echo "Exporting macOS client..."
godot --headless --export-release "macOS (Client)" "../exports/client/macos/omega-client.app"

echo "Client build complete!"
echo "Exports located in: ../exports/client/"
