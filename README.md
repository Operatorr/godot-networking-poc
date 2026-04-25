# Omega Realm - Multiplayer Networking POC

A proof-of-concept multiplayer game built with **Godot 4.6** and **Go**, designed to stress-test networking architecture for MMO-scale games.

**Goal:** Validate that a single Godot headless server can handle **500-1000 concurrent players** while maintaining playable performance.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Service Management](#service-management)
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
│  (Godot 4.6)    │   (Auth, Characters,         │  (Port 8080)    │
│                 │    Leaderboards)             │                 │
└────────┬────────┘                              └────────┬────────┘
         │                                                │
         │ WebSocket (Port 8081)                         │ PostgreSQL
         │ (Game state, movement, combat)                │ + Redis
         │                                               │
         ▼                                               ▼
┌─────────────────┐                              ┌─────────────────┐
│  Game Server    │ ←────── HTTP (Stats) ──────→ │   Database      │
│  (Godot 4.6     │                              │   PostgreSQL    │
│   Headless)     │                              │   Redis Cache   │
└─────────────────┘                              └─────────────────┘
```

### Component Responsibilities

| Component | Port | Responsibility |
|-----------|------|----------------|
| **Go API Server** | 8080 | Authentication, user accounts, character data, leaderboards, persistence |
| **Godot Game Server** | 8081 | Real-time game state, physics, combat, monster AI, authoritative gameplay |
| **PostgreSQL** | 5432 | Persistent data storage (accounts, characters, game data) |
| **Redis** | 6379 | Session caching, leaderboards, real-time data |

---

## Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Game Engine | Godot | 4.6 |
| Scripting | GDScript | - |
| API Backend | Go | 1.21+ |
| Database | PostgreSQL | 15+ |
| Cache | Redis | 7+ |
| Containerization | Docker | - |

---

## Prerequisites

- **Godot 4.6** - [Download](https://godotengine.org/download)
- **Go 1.21+** - [Download](https://go.dev/dl/)
- **PostgreSQL 15+** - Running locally or via Docker
- **Redis** (optional) - For caching features
- **Docker & Docker Compose** (optional) - For containerized deployment

---

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd godot-networking-poc
```

### 2. Database Setup

Create the database and user:

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE USER omega WITH PASSWORD 'omega_password';
CREATE DATABASE omega_db OWNER omega;
GRANT ALL PRIVILEGES ON DATABASE omega_db TO omega;
\q
```

### 3. Configure API Server

```bash
cd api
cp .env.example .env
# Edit .env with your database credentials
```

### 4. Start Services

```bash
# From project root
./scripts/start_services.sh
```

Or manually:

```bash
# Terminal 1: Start Go API
cd api
go run cmd/server/main.go

# Terminal 2: Start Godot Game Server
cd client
godot --headless

# Terminal 3: Run Godot Client
cd client
godot project.godot
```

### 5. Access the Game

- Open Godot and run the project, or
- Use the exported client binary

---

## Service Management

Helper scripts are provided to manage the Go API and Godot game servers:

### Start Services

```bash
./scripts/start_services.sh           # Start both servers
./scripts/start_services.sh --api-only    # Start only Go API
./scripts/start_services.sh --game-only   # Start only Godot server
```

### Stop Services

```bash
./scripts/stop_services.sh            # Stop both servers
./scripts/stop_services.sh --api-only     # Stop only Go API
./scripts/stop_services.sh --game-only    # Stop only Godot server
```

### Check Status

```bash
./scripts/status_services.sh
```

### View Logs

```bash
tail -f logs/api_server.log    # Go API logs
tail -f logs/game_server.log   # Godot server logs
```

> **Note:** PostgreSQL must be started manually. The scripts do not manage the database.

---

## Project Structure

```
godot-networking-poc/
├── client/                          # Godot 4.6 Project (Client + Server)
│   ├── project.godot               # Project configuration
│   ├── autoload/                   # Singleton scripts
│   │   ├── game_manager.gd         # Game state management
│   │   ├── network_manager.gd      # WebSocket client/server
│   │   ├── auth_manager.gd         # JWT authentication
│   │   ├── audio_manager.gd        # Sound effects and music
│   │   └── scene_manager.gd        # Scene transitions
│   ├── scenes/
│   │   ├── client/                 # Client-only scenes (menus, UI)
│   │   ├── server/                 # Server-only scenes
│   │   ├── shared/                 # Shared entities (player, projectiles)
│   │   └── test/                   # Test scenes
│   ├── scripts/
│   │   ├── client/                 # Client-only logic
│   │   ├── server/                 # Server-only logic (validation, AI)
│   │   └── shared/                 # Shared game logic, protocol
│   └── assets/                     # Graphics, audio (stripped in server)
│
├── api/                            # Go Backend API
│   ├── cmd/server/main.go         # Entry point
│   ├── internal/
│   │   ├── auth/                   # JWT authentication
│   │   ├── database/               # PostgreSQL connection
│   │   ├── handlers/               # HTTP route handlers
│   │   └── models/                 # Data models
│   ├── go.mod                      # Go module
│   └── .env.example                # Environment template
│
├── deployment/                     # Docker configs
│   ├── docker-compose.yml          # Service orchestration
│   ├── api.Dockerfile              # Go API container
│   ├── server.Dockerfile           # Godot headless container
│   └── .env.example                # Environment template
│
├── scripts/                        # Utility scripts
│   ├── start_services.sh           # Start servers
│   ├── stop_services.sh            # Stop servers
│   ├── status_services.sh          # Check server status
│   ├── build_client.sh             # Export game client
│   ├── build_server.sh             # Export headless server
│   └── build_api.sh                # Build Go API
│
├── docs/                           # Documentation
│   └── ARCHITECTURE.md             # Detailed architecture guide
│
├── specs/                          # Feature specifications
│   └── 002-player-character/       # Player system spec and tasks
│
└── .env.test.example               # Test credentials template
```

---

## Development Workflow

### Running in Development Mode

**Client Mode (GUI):**
```bash
cd client
godot project.godot
```

**Server Mode (Headless):**
```bash
cd client
godot --headless
```

The project automatically detects which mode to run based on:
- `OS.has_feature("dedicated_server")` - Export preset flag
- `DisplayServer.get_name() == "headless"` - Runtime detection

### Adding New Features

1. **Shared Logic** (both client & server need it):
   - Add to `client/scripts/shared/`
   - Example: Player movement, combat calculations

2. **Client-Only** (UI, input, graphics):
   - Add to `client/scripts/client/`
   - Example: Menus, HUD, visual effects

3. **Server-Only** (validation, AI, authority):
   - Add to `client/scripts/server/`
   - Example: Anti-cheat, monster behavior

### Building for Production

```bash
# Build all components
./scripts/build_client.sh    # Export client for Win/Mac/Linux
./scripts/build_server.sh    # Export headless server
./scripts/build_api.sh       # Build Go API binary

# Or use Docker
cd deployment
docker-compose up --build
```

---

## Testing

### Test Configuration

Create a test configuration file:

```bash
cp .env.test.example .env.test
```

Edit `.env.test` with your test credentials:

```ini
TEST_USERNAME=testuser
TEST_PASSWORD=testpassword123
TEST_CHARACTER_NAME=
TEST_REALM=Asia
API_SERVER_URL=http://localhost:8080
GAME_SERVER_HOST=localhost
GAME_SERVER_PORT=8081
```

### Test Scenes

| Scene | Purpose |
|-------|---------|
| `client/scenes/test/player_test.tscn` | Simple player testing (no login required) |
| `client/scenes/test/login_character_test.tscn` | Headless integration test: login and verify character data is loaded |
| `client/scenes/test/auto_join_arena.tscn` | End-to-end test: login, connect, join networked arena |

### Running Tests

**Simple Player Test:**
```bash
cd client
godot --path . scenes/test/player_test.tscn
```

**Full Integration Test:**
1. Start all services (API, Database, optionally Game Server)
2. Configure `.env.test` with valid credentials
3. Run the auto-login test scene

**Login Character Test:**
```bash
cd client
godot --headless --path . scenes/test/login_character_test.tscn
```

---

## Game Controls

| Input | Action |
|-------|--------|
| **W** | Move up |
| **A** | Move left |
| **S** | Move down |
| **D** | Move right |
| **W+D** | Move diagonally (normalized speed) |
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

### Godot Server Configuration

The headless server loads settings from `client/data/config/server_config.json`:

```json
{
  "port": 8081,
  "tick_rate": 30,
  "max_players": 100,
  "region": "asia",
  "debug_logging": true,
  "heartbeat_timeout_seconds": 5.0,
  "api_server_url": "http://localhost:8080"
}
```

| Setting | Description | Default |
|---------|-------------|---------|
| `port` | WebSocket port for game connections | `8081` |
| `tick_rate` | Server physics tick rate (Hz) | `30` |
| `max_players` | Maximum concurrent players | `100` |
| `region` | Server region identifier | `asia` |
| `debug_logging` | Enable verbose logging | `true` |
| `heartbeat_timeout_seconds` | Client timeout threshold | `5.0` |
| `api_server_url` | URL of the Go API server | `http://localhost:8080` |

**Override at runtime:** Place a `server_config.json` in the user data directory (`user://server_config.json`) to override the embedded config. Useful for Docker volume mounts.

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

1. Check if port 8081 is in use:
   ```bash
   lsof -i :8081
   ```

2. Kill existing process:
   ```bash
   ./scripts/stop_services.sh --game-only
   ```

### Login Redirects to Login Screen

This is expected behavior when:
- No valid JWT token is stored
- Token has expired
- User is not authenticated

Use the auto-login test scene with valid credentials in `.env.test`.

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

- [Architecture Guide](docs/ARCHITECTURE.md) - Detailed system architecture
- [Feature Specs](specs/) - Feature specifications and tasks

---

## License

This project is currently licensed under the **MIT License**.

This is the license for the development period to allow for community review and contributions. The final commercial product will be released under a proprietary license.

For more details, see the [LICENSE.md](LICENSE.md) file.

---

**Last Updated:** December 2025
