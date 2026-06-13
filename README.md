# Omega Realm - Multiplayer Networking POC

A proof-of-concept multiplayer game built with **Godot 4.6** (client), **Rust** (authoritative
game server), and **Go** (backend API), designed to stress-test networking architecture for
MMO-scale games.

**Goal:** Validate that a single authoritative server can handle **500-1000 concurrent
players** while maintaining playable performance.

> Deep documentation lives in [`docs/`](docs/index.md) — start with
> [`docs/rust-port/migration-spec.md`](docs/rust-port/migration-spec.md) and
> [`docs/rust-port/contract.md`](docs/rust-port/contract.md) for the current core.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Local Dev Stack](#local-dev-stack)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Game Controls](#game-controls)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────┐         HTTP REST API        ┌─────────────────┐
│  Game Client    │ ←──────────────────────────→ │   Go API        │
│  (Godot 4.6 +   │   (Auth, Characters,         │  (Port 8080)    │
│  Rust GDExt)    │    Leaderboards)             │                 │
└────────┬────────┘                              └────────┬────────┘
         │                                                │
         │ ENet/UDP (Port 8081)                           │ PostgreSQL
         │ (Inputs, snapshots, combat)                    │ + Redis
         │                                                │
         ▼                                                ▼
┌─────────────────┐                              ┌─────────────────┐
│  Game Server    │ ←── HTTP (region beat) ────→ │   Database      │
│  (Rust          │                              │   PostgreSQL    │
│   omega-server) │                              │   Redis Cache   │
└─────────────────┘                              └─────────────────┘
```

### Component Responsibilities

| Component | Port | Responsibility |
|-----------|------|----------------|
| **Go API Server** | 8080 (TCP) | Authentication, user accounts, character data, leaderboards, persistence |
| **Rust Game Server** | 8081 (UDP) | Real-time game state, movement, combat, monster AI, authoritative gameplay; Prometheus metrics on 9100 |
| **PostgreSQL** | 5432 | Persistent data storage (accounts, characters, leaderboard) |
| **Redis** | 6379 | Session caching, leaderboards, region status |

All gameplay state is server-authoritative and in-memory; only the Go API touches the
databases. The client and server share the bit-packed wire protocol (`rust/protocol`) and the
movement/collision simulation (`rust/sim_core`), which the client consumes through a
GDExtension (`rust/client_ext`) — prediction and authority run the same code by construction.

---

## Quick Commands

| Action | Command |
|--------|---------|
| Start local stack (API + game server) | `./scripts/dev_local.sh` |
| Start game server only | `./scripts/run_server.sh` |
| Stop local stack | `Ctrl+C` in the `dev_local.sh` terminal |
| Launch bots (gameplay) | `./scripts/run_load_test.sh --bots 2 --scenario strategy` |
| Launch bots (load scenario) | `./scripts/run_load_test.sh --scenario baseline` |
| Stop bots | `Ctrl+C` in the load test terminal |

---

## Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Game Engine (client) | Godot | 4.6 |
| Client scripting | GDScript | - |
| Game server / protocol / sim | Rust | stable |
| Transport | ENet over UDP (`rusty_enet`) | =0.4.0 |
| API Backend | Go | 1.24+ |
| Database | PostgreSQL | 15+ |
| Cache | Redis | 7+ |
| Deployment | Native systemd (no Docker — [ADR 0007](docs/adr/0007-native-systemd-deployment.md)) | - |

---

## Prerequisites

- **Godot 4.6** - [Download](https://godotengine.org/download)
- **Rust** (stable toolchain) - [Install](https://rustup.rs)
- **Go 1.24+** - [Download](https://go.dev/dl/)
- **PostgreSQL 15+** - Running locally (e.g. DBngin) or a native install
- **Redis** - Required (sessions, leaderboard cache, region status; API exits if unreachable)

---

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd omgea-networking
```

### 2. Provision the Databases

The API requires **two** running services — bring them up however you like (DBngin, a
native install, or managed):

- **PostgreSQL** (accounts, characters, leaderboard persistence) — **required**.
- **Redis** (sessions, leaderboard cache, region status) — **required**. The API exits on
  startup if it cannot connect to Redis (`api/cmd/server/main.go`).

You only need to have the servers reachable; the schema is migrated automatically on first
API start. There is no manual `CREATE USER` / `CREATE DATABASE` step — point the API at an
existing empty database instead.

### 3. Configure the API Server

Copy the API environment template and fill in your **PostgreSQL** and **Redis** connection
details:

```bash
cd api
cp .env.example .env
```

Edit `api/.env` and set, at minimum:

```ini
# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_USER=omega
DB_PASSWORD=omega_password
DB_NAME=omega_db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

### 4. Seed the Test User

First create the test credentials file and set the username/password the seeder will create:

```bash
# From project root
cp .env.test.example .env.test
```

Edit `.env.test` and set the login the seeder should provision:

```ini
TEST_USERNAME=testuser
TEST_PASSWORD=testpassword123
```

Then run the seeder, which reads the credentials from `.env.test` and the database
connection from `api/.env`, and creates/updates that login in PostgreSQL:

```bash
./scripts/seed_test_user.sh
```

> To re-test character creation for an existing user, re-run with `--reset-character`.

### 5. Start the Local Dev Stack

```bash
# From project root — starts the Go API (background) and the Rust game server (foreground)
./scripts/dev_local.sh
```

Press **Ctrl+C** to stop both. PostgreSQL and Redis are **not** managed by this script —
start them yourself first (step 2).

### 6. Access the Game

- Open Godot and run the project (`client/`), or
- Use the exported client binary

### 7. Launch Bots (optional)

With the server running, start the ENet bot swarm in a separate terminal:

```bash
# 2 gameplay-like bots (closest to a real client)
./scripts/run_load_test.sh --bots 2 --scenario strategy

# Override server address (default: 127.0.0.1:8081)
./scripts/run_load_test.sh --bots 2 --scenario strategy --server 10.0.0.1:8081
```

Bots authenticate ticket-less (dev mode) and run the same `sim_core` movement integration
as the real client. For named load scenarios (`baseline`, `stress`, `combat`, etc.) and
full flags, see `rust/load_test/README.md`.

---

## Local Dev Stack

`./scripts/dev_local.sh` is the day-to-day way to run the backend locally. It:

- checks that `go` and `cargo` are installed and that PostgreSQL and Redis (as configured in
  `api/.env`) are reachable, and fails fast with a clear message if not;
- builds and starts the **Go API** in the background (log: `logs/api_server.log`, PID:
  `.pids/api_server.pid`) and waits for `http://localhost:8080/health`;
- builds and runs the **Rust game server** in the foreground (udp/8081 game, :9100 metrics)
  in dev mode (unsigned session tickets accepted);
- stops the API again when the game server exits or you hit Ctrl+C.

```bash
./scripts/dev_local.sh                          # API on :8080, game on udp/8081
API_PORT=9090 ./scripts/dev_local.sh            # override API port
./scripts/dev_local.sh -- --require-tickets     # pass args through to omega-server
tail -f logs/api_server.log                     # follow API logs
```

Other run options:

```bash
./scripts/run_server.sh --mode arena --port 8081   # one Rust game instance only (no API)
./scripts/deploy.sh                                 # deploy to the live server (native, git-driven)
```

> **Deploy:** `./scripts/deploy.sh` SSHes into the droplet, pulls `master`, rebuilds, and
> restarts the native systemd services (API + Arena + Sanctuary). One-time setup:
> `./scripts/deploy.sh provision`. See [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)
> and [ADR 0007](docs/adr/0007-native-systemd-deployment.md).

---

## Project Structure

```
omgea-networking/
├── rust/                            # Cargo workspace — the authoritative server lives here
│   ├── protocol/                   # Bit-packed wire format (shared, ADR 0004)
│   ├── sim_core/                   # Movement/collision/hit sim (server + client prediction)
│   ├── server/                     # omega-server binary (30 Hz tick, ENet/UDP, metrics)
│   ├── client_ext/                 # GDExtension: ProtocolCodec, PredictionSim, SimHit
│   └── load_test/                  # omega-load-test ENet bot swarm
│
├── client/                          # Godot 4.6 project (exports the CLIENT only)
│   ├── autoload/                   # Singletons (network_manager, transport/, game_manager…)
│   ├── scenes/                     # client/, shared/, test/ scenes
│   ├── scripts/
│   │   ├── client/                 # Prediction, interpolation, HUD, menus
│   │   ├── shared/                 # Packet enums, constants, entities, arenas
│   │   └── server/                 # RETIRED GDScript server — kept as parity ground truth
│   └── bin/                        # Built GDExtension libraries
│
├── api/                            # Go backend API
│   ├── cmd/server/main.go         # Entry point
│   ├── internal/                   # auth/, database/, handlers/, models/
│   └── .env.example                # Environment template
│
├── deployment/                     # Native systemd deploy (no Docker — ADR 0007)
│   ├── systemd/                    # omega-api / omega-arena / omega-sanctuary units
│   ├── server_config.{arena,sanctuary}.json  # per-instance configs (ports/modes/metrics)
│   ├── env/                        # api.env / server.env templates → /etc/omega-realm/
│   ├── provision_server.sh         # one-time bootstrap; server_update.sh = git-pull deploy
│   ├── update_os.sh                # apt full-upgrade + Ubuntu release upgrade
│   └── harden_vps.sh               # firewall / fail2ban / SSH lockdown
│
├── scripts/                        # Utility scripts
│   ├── dev_local.sh                # Local dev stack: Go API + Arena + Sanctuary (native)
│   ├── run_server.sh               # One Rust game instance (--mode/--port)
│   ├── run_load_test.sh            # ENet bot swarm load test (OMEGA_SERVER for live target)
│   ├── run_tests.sh                # Headless GDScript regression tests
│   ├── build_client.sh             # Export game client
│   ├── build_client_ext.sh         # Build Rust GDExtension -> client/bin/
│   ├── build_server.sh             # Build Rust omega-server (release)
│   ├── build_api.sh                # Build Go API
│   ├── seed_test_user.sh           # Seed the local test login
│   └── deploy.sh                   # Native deploy from your laptop (ssh + git pull + rebuild)
│
├── docs/                           # System of record — see docs/index.md
└── .env.test.example               # Test credentials template
```

---

## Development Workflow

### Running in Development Mode

**Client (GUI):**
```bash
cd client
godot project.godot
```

**Game server:**
```bash
./scripts/run_server.sh        # or ./scripts/dev_local.sh for server + API
```

The GDScript server mode is retired — `NetworkManager` refuses to start as a server; the
Rust `omega-server` binary is the only authority.

### Adding New Features

1. **Simulation / protocol** (authority and prediction):
   - Add to `rust/sim_core` / `rust/protocol`, expose to GDScript via `rust/client_ext`
   - Rebuild the extension: `./scripts/build_client_ext.sh`

2. **Client-Only** (UI, input, graphics):
   - Add to `client/scripts/client/`
   - Example: Menus, HUD, visual effects

3. **Server-Only** (validation, AI, authority):
   - Add to `rust/server`
   - Example: Anti-cheat, monster behavior

Governing rule for all gameplay: **the client requests, the server decides.**

### Building for Production

```bash
# Build all components
./scripts/build_client.sh        # Export client for Win/Mac/Linux
./scripts/build_client_ext.sh    # Rust GDExtension -> client/bin/
./scripts/build_server.sh        # Rust omega-server (release)
./scripts/build_api.sh           # Build Go API binary
```

---

## Deploying to a Server (native, no Docker)

The live server runs everything as **native systemd services** — Go API + two Rust game
instances (Arena `8081`, Sanctuary `8082`) + PostgreSQL + Redis. Git is the deploy
channel: `./scripts/deploy.sh` SSHes in, the server pulls `master` and rebuilds. Full
runbook: [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md) ·
rationale: [ADR 0007](docs/adr/0007-native-systemd-deployment.md).

> **Deploy reads `origin/master`.** `server_update.sh` does `git reset --hard origin/master`,
> so commit + push your changes to GitHub **before** deploying — the server only ever runs
> what's on `master`.

### Configure your server target (one-time, not committed)

`scripts/deploy.sh` reads the server IP / SSH user from **`deployment/deploy.env`**, which is
**git-ignored** — your IP never lands in the repo:

```bash
cp deployment/deploy.env.example deployment/deploy.env
# edit deployment/deploy.env → set OMEGA_HOST=<your-droplet-ip>
```

| Key | Required | Default |
|-----|:---:|---------|
| `OMEGA_HOST` | ✅ | — (script errors if unset) |
| `OMEGA_USER` | | `deploy` |
| `OMEGA_BRANCH` | | `master` |
| `OMEGA_REPO_DIR` | | `/home/<user>/omega-realm` |

A shell export wins over the file for one-off targets, e.g.
`OMEGA_HOST=1.2.3.4 ./scripts/deploy.sh status`.

### Which script to run when

Everything below is **one script — `scripts/deploy.sh`** — run from your laptop; it SSHes
in and drives the matching on-server script. The headline one is `all`:

```bash
./scripts/deploy.sh all     # OS updates → pull master + rebuild → restart → health, in one shot
```

| Goal | Command (run from your **laptop**) | Runs on server |
|------|-----------------------------------|----------------|
| **★ Everything: OS update + deploy + verify** | `./scripts/deploy.sh all` | `update_os.sh` → `server_update.sh` |
| **0. Harden a fresh box** (firewall, fail2ban, SSH) | `ssh deploy@<ip> 'sudo bash ~/harden_vps.sh'` | `deployment/harden_vps.sh` |
| **1. One-time bootstrap** (Go/Rust/Postgres/Redis, swap, systemd units, sudoers) | `./scripts/deploy.sh provision` | `deployment/provision_server.sh` |
| **2. Set secrets** (DB password + JWT) | `ssh deploy@<ip>` → edit `/etc/omega-realm/api.env` | — |
| **3. Deploy / redeploy latest `master`** | `./scripts/deploy.sh` | `deployment/server_update.sh` |
| **OS security + package updates** | `./scripts/deploy.sh os-update` | `deployment/update_os.sh` |
| **OS update + reboot if needed** | `./scripts/deploy.sh os-update --reboot` | `deployment/update_os.sh` |
| **Ubuntu version upgrade** (risky; snapshot first) | `./scripts/deploy.sh os-update --release-upgrade` | `deployment/update_os.sh` |
| Status of all services | `./scripts/deploy.sh status` | — |
| Follow logs (api + arena + sanctuary) | `./scripts/deploy.sh logs` | — |
| Health (API `/health` + metrics) | `./scripts/deploy.sh health` | — |
| Restart without rebuilding | `./scripts/deploy.sh restart` | — |
| Interactive shell on the box | `./scripts/deploy.sh ssh` | — |

> `all` deliberately does **not** reboot mid-run (that would kill the deploy). If
> `update_os.sh` reports a reboot is required, run `./scripts/deploy.sh os-update --reboot`
> afterwards — systemd restarts every service on boot.

### First-time deploy, end to end

```bash
# (after committing + pushing this repo's deployment tooling to master)
cp deployment/deploy.env.example deployment/deploy.env  # set OMEGA_HOST=<your ip> (git-ignored)
ssh deploy@<ip> 'sudo bash ~/harden_vps.sh'   # 0. firewall/fail2ban/SSH lockdown
./scripts/deploy.sh provision                  # 1. install toolchains, DB, units, swap
ssh deploy@<ip>                                # 2. set real secrets:
  sudo -u postgres psql -c "ALTER ROLE omega PASSWORD 'YOUR_PW';"
  sudo nano /etc/omega-realm/api.env           #    DB_PASSWORD + JWT_SECRET_KEY
  exit
./scripts/deploy.sh                            # 3. pull master, build, start everything
./scripts/deploy.sh health                     # 4. verify
```

### Keeping the OS patched

`harden_vps.sh` enables **`unattended-upgrades`**, so security patches install
automatically every day — no action needed. For routine maintenance just run
**`./scripts/deploy.sh all`** (e.g. monthly): it does the **full** package/kernel upgrade,
redeploys the latest `master`, and verifies health in one go. If it reports a reboot is
required, follow up with `./scripts/deploy.sh os-update --reboot` (systemd brings all
services back up on boot). Ubuntu **version** jumps are opt-in via
`os-update --release-upgrade` — take a droplet snapshot first.

---

## Testing

### Rust workspace (must stay green)

```bash
cd rust && cargo test --workspace && cargo clippy --workspace --all-targets && cargo fmt --check
```

### GDScript regression tests

```bash
./scripts/run_tests.sh
```

### End-to-end smoke

Needs a running game server on `127.0.0.1:8081` (e.g. `./scripts/run_server.sh`):

```bash
cd client && godot --path . res://scenes/test/net_smoke.tscn   # exits 0 on PASS
```

### Load test

Needs a running game server; scenarios and flags in `rust/load_test/README.md`:

```bash
./scripts/run_load_test.sh --scenario baseline
```

### Test Configuration

Create a test configuration file:

```bash
cp .env.test.example .env.test
```

Edit `.env.test` with your test credentials, then seed/update that local login user in
PostgreSQL:

```bash
./scripts/seed_test_user.sh
./scripts/seed_test_user.sh --reset-character   # to re-test character creation
```

### Test Scenes

| Scene | Purpose |
|-------|---------|
| `client/scenes/test/player_test.tscn` | Simple player testing (no login required) |
| `client/scenes/test/login_character_test.tscn` | Headless integration test: login and verify character data is loaded |
| `client/scenes/test/net_smoke.tscn` | End-to-end ENet smoke test against a running server |
| `client/scenes/test/arena_client_smoke.tscn` | Arena client smoke scene |
| `client/scenes/test/sandbox.tscn` | Offline sandbox |

---

## Game Controls

| Input | Action |
|-------|--------|
| **W** | Move up |
| **A** | Move left |
| **S** | Move down |
| **D** | Move right |
| **W+D** | Move diagonally (normalized speed) |
| **Shift** | Dash |
| **Mouse** | Aim (character rotates toward cursor) |
| **Left Click** | Shoot projectile |
| **F3** | Toggle debug overlay |
| **Space** | Apply 25 damage (test scenes only) |
| **Escape** | Reset player (test scenes only) |

### Debug Overlay (F3)

Shows real-time information:
- HP (current/max)
- Position (X, Y)
- State (IDLE/WALKING, NONE/ATTACKING/HIT/DEAD)
- Velocity
- Rotation

---

## Configuration

### Environment Files

One file per concern — don't mix them:

| File | Purpose | Template |
|------|---------|----------|
| `api/.env` | Local API runtime config: port, PostgreSQL, Redis, JWT. Read by the Go API and by `./scripts/dev_local.sh` / `./scripts/seed_test_user.sh`. | `api/.env.example` |
| `.env.test` | Test login **only**: the seeded user's credentials plus the endpoints the smoke/login test scenes connect to. No DB/Redis config here. | `.env.test.example` |
| `/etc/omega-realm/api.env` | **Production** API config on the server (secrets + DB/Redis), loaded by the `omega-api` systemd unit. Not in the repo. | `deployment/env/api.env.example` |
| `/etc/omega-realm/server.env` | **Production** game-server env on the server (ticket policy), shared by both game units. | `deployment/env/server.env.example` |

### API Server (.env)

```bash
cd api
cp .env.example .env
# Edit .env with your database credentials
```

```ini
# Server
PORT=8080

# Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=omega
DB_PASSWORD=omega_password
DB_NAME=omega_db

# JWT
JWT_SECRET_KEY=your-secret-key-change-this
JWT_ACCESS_TOKEN_EXPIRY=15m
JWT_REFRESH_TOKEN_EXPIRY=7d

# Regions
AVAILABLE_REGIONS=Asia,Europe,US-West
DEFAULT_REGION=Asia
```

### Godot Client Configuration

The client loads settings from `client/data/config/client_config.json`:

```json
{
  "api_base_url": "http://localhost:8080",
  "api_timeout_seconds": 10.0,
  "debug_logging": true
}
```

| Setting | Description | Default |
|---------|-------------|---------|
| `api_base_url` | URL of the Go API server (for auth and region list) | `http://localhost:8080` |
| `api_timeout_seconds` | HTTP request timeout | `10.0` |
| `debug_logging` | Enable verbose logging | `true` |

**Override at runtime:** Place a `client_config.json` in the user data directory (`user://client_config.json`) to override the embedded config without modifying the exported build.

### Game Server Configuration

`omega-server` loads `server_config.json` from its working directory, falling back to
`client/data/config/server_config.json`, or takes an explicit `--config <file>`. Production
passes `--config deployment/server_config.arena.json` (or `…sanctuary.json`) via the systemd
units. Env overrides apply on top (CLI flag > env > config > default) — see
`rust/server/src/config.rs` for the full key list. The most relevant keys:

| Setting | Description | Default |
|---------|-------------|---------|
| `port` | UDP game port (ENet) | `8081` |
| `tick_rate` | Server simulation tick rate (Hz) | `30` |
| `max_players` | Maximum concurrent players | `100` |
| `region` | Server region identifier | `local` |
| `api_server_url` | URL of the Go API server (region heartbeat) | `http://localhost:8080` |
| `metrics_port` | Prometheus exporter port (0 disables) | `9100` |
| `allow_unsigned_tickets` | Dev mode: accept unsigned session tickets | `true` |
| `aoi_radius` / `aoi_exit_radius` | Area-of-interest enter/exit radii | `1000` / `1100` |
| `max_snapshot_bytes` | Unreliable snapshot budget per packet | `1200` |

Production runs `--require-tickets` with `OMEGA_TICKET_PUBKEY` set (Ed25519).

### Godot Project Settings

Key input actions defined in `project.godot`:
- `move_up`, `move_down`, `move_left`, `move_right` - WASD movement
- `shoot` - Left mouse button
- `toggle_debug` - F3 key

Collision layers:
- Layer 1: Players
- Layer 2: Monsters
- Layer 3: Projectiles
- Layer 4: Environment

---

## Troubleshooting

### "PacketWriter not found" Error

Clear the Godot cache:
```bash
rm -rf client/.godot
```
Then reopen the project in Godot.

### Database Connection Failed

1. Ensure PostgreSQL is running:
   ```bash
   pg_isready
   ```

2. Verify credentials in `api/.env`

3. Check database exists:
   ```bash
   psql -U omega -d omega_db -c "SELECT 1"
   ```

### Game Server Won't Start

1. Check if the UDP game port or the metrics port is already in use:
   ```bash
   lsof -nP -iUDP:8081
   lsof -nP -iTCP:9100 -sTCP:LISTEN
   ```

2. Kill the existing `omega-server` process shown by `lsof`, then restart.

### Verify the Stack Is Up

```bash
curl http://localhost:8080/health      # Go API
curl http://localhost:9100/metrics     # Rust server Prometheus metrics
lsof -nP -iUDP:8081                    # Rust server game socket
```

### Login Redirects to Login Screen

This is expected behavior when:
- No valid JWT token is stored
- Token has expired
- User is not authenticated

Use valid credentials from `.env.test` (seeded via `./scripts/seed_test_user.sh`).

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Concurrent Players | 500-1000 per server |
| Server Tick Rate | ≥20 Hz under load |
| Per-Player Bandwidth | <2 KB/s average |
| Latency (p95) | <150ms same-region |
| CPU per Player | <0.5% |
| Memory per Player | <5 MB |

---

## Documentation

- [Documentation index](docs/index.md) - Full catalogue with verification status
- [Architecture Guide](docs/ARCHITECTURE.md) - Detailed system architecture
- [Rust port](docs/rust-port/) - Migration spec (D1-D14), wire/API contract, extraction notes
- [ADRs](docs/adr/) - Load-bearing decisions

---

## License

This project is currently licensed under the **MIT License**.

This is the license for the development period to allow for community review and contributions. The final commercial product will be released under a proprietary license.

For more details, see the [LICENSE.md](LICENSE.md) file.

---

## GUI Pallette

- #111418 background
- #1E2430 panel dark
- #2E3748 panel mid
- #5B657A border/inactive
- #E7D9B4 primary text
- #FFF6D6 highlighted text
- #E3A23B primary accent / selected button
- #C96B2C pressed state / warning
- #4DA6A8 secondary accent / submenu / info
- #A84D6E danger / quit / destructive option

**Last Updated:** June 2026
