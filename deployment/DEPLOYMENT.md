# Omega Realm - Deployment Guide

Step-by-step guide for deploying the Omega Realm game server and API to a DigitalOcean droplet.

## Prerequisites

- Docker and Docker Compose on the target server
- SSH access to the DigitalOcean droplet

## Architecture

```
Internet
  │
  ├── :8080/tcp → API Server (Go) → PostgreSQL + Redis
  └── :8081/udp → Game Server (Rust omega-server, ENet/UDP; Prometheus on :9100)
```

## 1. Provision DigitalOcean Droplet

### Recommended Specs
- **Size**: 4 GB RAM / 2 vCPUs (minimum for 100 players)
- **Region**: Singapore (SGP1) for alpha testing
- **Image**: Ubuntu 22.04 LTS
- **Additional**: Enable monitoring

### Initial Setup

```bash
# SSH into droplet
ssh root@<droplet-ip>

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose plugin
apt-get install docker-compose-plugin

# Verify
docker --version
docker compose version

# Create deploy user (optional, recommended)
adduser deploy
usermod -aG docker deploy
```

## 2. Configure Firewall

```bash
# Allow SSH
ufw allow 22/tcp

# Allow API
ufw allow 8080/tcp

# Allow Game Server (ENet over UDP)
ufw allow 8081/udp

# Enable firewall
ufw enable
ufw status
```

## 3. Game Server Binary

Nothing to pre-build: `server.Dockerfile` compiles the Rust `omega-server` from `rust/`
inside the image (multi-stage build) and bakes in `server_config.docker.json`. The compose
stack builds it automatically in the next step.

## 4. Deploy

### Clone and Configure

```bash
# On the droplet
git clone <repo-url> /opt/omega-realm
cd /opt/omega-realm/deployment

# Create production env file
cp .env.production.example .env.production
nano .env.production  # Set secure passwords and JWT secret
```

### Build and Start

```bash
# Using the deploy script
../scripts/deploy.sh up

# Or manually
docker compose --env-file .env.production up -d --build
```

### Verify

```bash
# Check all containers are running
docker compose ps

# Check API health
curl http://localhost:8080/health

# Check logs
docker compose logs -f game-server
docker compose logs -f api
```

## 5. Test Auto-Restart

```bash
# Kill the game server container
docker kill omega-game-server

# Wait a few seconds, verify it restarts
sleep 10
docker compose ps  # Should show "Up" status
```

## 6. Run Load Tests

From your development machine (or another server) — scenarios and flags in
`rust/load_test/README.md`:

```bash
# Baseline (50 bots)
./scripts/run_load_test.sh --scenario baseline --server <droplet-ip>:8081

# Target load (100 bots)
./scripts/run_load_test.sh --scenario target --server <droplet-ip>:8081

# Stress test (200 bots — needs max_players >= 200 in the server config)
./scripts/run_load_test.sh --scenario stress --server <droplet-ip>:8081
```

> Bots authenticate ticket-less, so the server must allow unsigned tickets (the dev
> default). A production server running `--require-tickets` will reject them.

## Monitoring

### Container Stats

```bash
# Real-time resource usage
docker stats

# Recent logs
docker compose logs --tail=100 game-server
docker compose logs --tail=100 api
```

### Quick Health Check

```bash
../scripts/deploy.sh health
```

## Rollback Procedure

If a deployment fails:

```bash
# Stop current containers
docker compose down

# Revert to previous code
git checkout <previous-commit>

# Rebuild and restart
docker compose --env-file .env.production up -d --build

# Verify
docker compose ps
curl http://localhost:8080/health
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_USER` | `omega` | PostgreSQL username |
| `DB_PASSWORD` | `omega_password` | PostgreSQL password |
| `DB_NAME` | `omega_db` | Database name |
| `API_PORT` | `8080` | API server port |
| `GAME_SERVER_PORT` | `8081` | Game server ENet/UDP port |
| `JWT_SECRET` | (dev default) | JWT signing secret |
| `LOG_LEVEL` | `info` | Log verbosity (debug/info/warn/error) |

## Troubleshooting

### Game server won't start
- Check logs: `docker compose logs game-server`
- Ensure UDP port 8081 is not in use: `ss -ulnp | grep 8081`

### API can't connect to database
- Check PostgreSQL health: `docker compose exec postgres pg_isready`
- Verify env variables match between API and PostgreSQL services

### Bots can't connect
- Verify firewall allows UDP port 8081: `ufw status` (must show `8081/udp`)
- Check the Prometheus endpoint responds: `curl http://<ip>:9100/metrics`
- Check game server logs for connection errors

### High latency
- Check server CPU: `docker stats`
- Review tick rate in game server logs
- Consider upgrading droplet size
