# Rust game server (omega-server) — one process = one Instance (migration-spec D13).
# Build context is the REPO ROOT (see docker-compose.yml): the image builds the rust/
# workspace and carries a compose-specific config (api url points at the api service).

FROM rust:1-slim AS builder

WORKDIR /build
COPY rust/ .
RUN cargo build --release -p omega-server

FROM debian:bookworm-slim

# curl for the health check; ca-certificates for the API heartbeat client.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /build/target/release/omega-server ./omega-server
COPY deployment/server_config.docker.json ./server_config.json

# Game traffic is ENet over UDP; 9100 is the Prometheus exporter.
EXPOSE 8081/udp
EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:9100/metrics > /dev/null || exit 1

CMD ["./omega-server", "--config", "server_config.json"]
