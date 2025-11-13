#!/bin/bash
# Build script for Go API server

set -e

echo "Building Omega Realm API..."

# Navigate to API directory
cd "$(dirname "$0")/../api"

# Check if Go is available
if ! command -v go &> /dev/null; then
    echo "Error: Go not found in PATH"
    echo "Please install Go 1.21+ or add it to your PATH"
    exit 1
fi

# Download dependencies
echo "Downloading dependencies..."
go mod download
go mod tidy

# Run tests
echo "Running tests..."
go test ./... || echo "Warning: Some tests failed"

# Build the API
echo "Building API server..."
go build -o ../bin/omega-api ./cmd/server

echo "API build complete!"
echo "Binary located in: ../bin/omega-api"
echo ""
echo "To run the API locally:"
echo "  ../bin/omega-api"
