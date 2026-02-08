# Godot Headless Server Dockerfile
# Requires the server to be exported first:
#   godot --export-release "Linux Headless Server" exports/server/linux/omega-server.x86_64

FROM ubuntu:22.04

# Install minimal runtime dependencies + curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libx11-6 \
    libgl1 \
    libxcursor1 \
    libxinerama1 \
    libxrandr2 \
    libxi6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy exported server binary
COPY exports/server/linux/omega-server.x86_64 ./omega-server

# Copy server config (can be overridden via volume mount)
COPY data/config/server_config.json ./server_config.json

# Make executable
RUN chmod +x omega-server

# Game server port (matches ServerConfig default)
EXPOSE 8081

# Health check: verify process is running
# The game server uses raw TCP/WebSocket, so we check the process
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pgrep -f omega-server || exit 1

# Run headless server
CMD ["./omega-server", "--headless"]
