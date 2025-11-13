# Godot Headless Server Dockerfile
# Note: This requires Godot export templates to be set up
# and the server to be exported first using: godot --export-release "Linux Headless Server"

FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    libx11-6 \
    libgl1 \
    libxcursor1 \
    libxinerama1 \
    libxrandr2 \
    libxi6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy exported server binary
# This should be built before docker build using export presets
COPY ../exports/server/linux/omega-server.x86_64 ./omega-server

# Make executable
RUN chmod +x omega-server

# Expose game server port
EXPOSE 8081

# Run headless server
CMD ["./omega-server", "--headless"]
