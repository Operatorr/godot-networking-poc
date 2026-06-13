# Technical Design Specification

**Version:** 1.0  
**Date:** November 2025 **Project Type:** Top-down 2D multiplayer bullet-hell shooter

---

## Project Overview

### POC Purpose

This project is a **Proof-of-Concept (POC)** designed to stress-test low-level networking for MMO-scale multiplayer games. The primary goal is to validate that a single game server can handle **500-1000 concurrent players** while maintaining playable performance.

**Why This Matters:**
- Building toward a full MMO requires proving the networking layer can scale
- Simplified gameplay intentionally isolates networking performance from game complexity
- Results will inform architecture decisions for the production MMO

**What We're Testing:**
- Maximum concurrent connections per server
- Bandwidth efficiency under load
- Server tick rate stability with hundreds of players
- Latency characteristics during combat scenarios

### Game Features

-   **Genre:** Top-down 2D sprite based bullet-hell multiplayer competitive shooter
-   **Style:** Left click to shoot
-   **Networking:** WebSocket with low-level binary protocol optimized for MMO scale (target: 500-1000 concurrent players per server). Emphasis on efficient packet design, delta compression, and minimal bandwidth per player.
-   **Core Modes:**
    -   PvP: Competitive arena battles
    -   PvPvE: Monster Spawns in arena during battle
-   **Player:** Only one shooting ability, sprite projectile
    -   No player classes
    -   No player abilities
    -   No experience points
    -   No leveling
    -   Just HP stat
-   **Monster:** Only one moster type, and only one shooting ability, sprite projectile

## Technology Stack

### Client

-   **Engine:** Godot 4.6
-   **Language:** GDScript
-   **Rendering:** 2D sprite-based
-   **Networking:** WebSocket (Low Level API)

### Server

-   **Game Server:** Godot 4.6 Headless
-   **API Server:** Go
-   **Database:** PostgreSQL
-   **Cache:** Redis
-   **Deployment:** Native systemd services on DigitalOcean (no Docker — [ADR 0007](adr/0007-native-systemd-deployment.md))

---

## Movement Mechanics & Controls

### Control Scheme

The game uses a **twin-stick shooter** style control scheme:

-   **WASD keys** (+ arrow keys as alternative) for 8-directional movement
-   **Mouse** for aiming direction
-   **Left mouse button** for firing primary attack
-   **T Key** exiting to main Menu

### Core Movement System

#### Basic Movement

-   **Movement Type:** Free 8-directional movement (not grid-based)

### Movement State Machine

The PlayerMovement component uses a state machine with these states:

1. **IDLE:** Not moving, no input
2. **WALKING:** Standard WASD movement

### Animation Coordination

Movement states sync with sprite animations:

-   **Idle Animation:** Playing when `velocity == Vector2.ZERO`
-   **Walk Animation:** Playing during normal movement, blend based on direction
-   **Hit Animation:** Hit visuals

**Animation System:**

-   One sprite for idle
-   One sprite frame for moving, cycle between moving and idle frame
-   One sprite for hit

### Technical Considerations

#### Level Size Guidelines

For 2D sprite-based game using TileMap:

-   **Hub City:** ~60x60 to 100x100 tiles (compact, navigable)
-   **Arena:** ~40x40 to 100x100 tiles (focused combat arenas)

#### Level Connection Architecture

**Main Menu → Arena Entry:**

-   Player clicks play from main menu to enter Arena, no Queue System
-   Loading screen
-   Arena scene loads
-   Monster spawner begins
-   On death: Respawn in Arena

**Arena → Exit:**

-   On teleport out: Exits to main menu

---

## Technology Stack

### Client

-   **Engine:** Godot 4.6
-   **Language:** GDScript
-   **Rendering:** 2D sprite-based

---

## Data-Driven Content System

### Philosophy

Instead of creating individual scene files for every enemy, and projectile (which would result in thousands of scenes), this architecture uses:

-   **Base Scenes:** Shared template scenes (e.g., `base_enemy.tscn`)
-   **Factories:** Factory classes that instantiate base scenes and apply definitions
-   **Hot Updates:** Content can be updated without rebuilding/patching the game

### Example: Enemy System

#### Data-Driven Approach

```
scenes/enemies/
└── base_enemy.tscn      (50 KB)

data/enemies/
└── enemy_database.json  (100 KB for 100+ enemies)
```

---

## Server Project Structure

### Backend API (Go)

```
/api/
├── main.go                         # API entry point
├── go.mod                         # Go modules
├── go.sum
│                                   # (built natively to api/bin/server — no Dockerfile; ADR 0007)
│
├── cmd/
│   └── server/
│       └── main.go               # Server initialization
│
├── internal/
│   ├── auth/
│   │   ├── jwt.go               # JWT handling
│   │   └── middleware.go        # Auth middleware
│   │
│   ├── handlers/
│   │   ├── auth_handler.go      # Login/register
│   │   ├── character_handler.go # Character management
│   │   ├── leaderboard_handler.go
│   │   └── region_handler.go    # Region selection
│   │
│   ├── models/
│   │   ├── user.go              # User model
│   │   ├── character.go         # Character model
│   │   └── leaderboard.go       # Leaderboard model
│   │
│   ├── database/
│   │   ├── postgres.go          # PostgreSQL connection
│   │   ├── redis.go             # Redis connection
│   │   └── migrations/          # Database migrations
│   │
│   └── websocket/
│       └── hub.go               # WebSocket hub for events
│
├── pkg/
│   ├── config/
│   │   └── config.go            # Configuration loader
│   └── utils/
│       └── validators.go        # Input validation
│
└── (deploy)                      # native systemd — see deployment/ + ADR 0007
    ├── systemd/*.service         # omega-api / omega-arena / omega-sanctuary units
    └── provision_server.sh       # one-time bootstrap; server_update.sh = git-pull deploy
```

---

## Database Structure

### PostgreSQL Tables

```
omega_realm/
├── users
│   ├── id (UUID, PRIMARY KEY)
│   ├── username (VARCHAR, UNIQUE)
│   ├── email (VARCHAR, UNIQUE)
│   ├── password_hash (VARCHAR)
│   ├── region (VARCHAR)
│   ├── created_at (TIMESTAMP)
│   └── last_login (TIMESTAMP)
│
├── characters
│   ├── id (UUID, PRIMARY KEY)
│   ├── user_id (UUID, FOREIGN KEY)
│   ├── name (VARCHAR, UNIQUE)
│   ├── created_at (TIMESTAMP)
│   └── last_played (TIMESTAMP)
│
├── leaderboards
│   ├── id (UUID, PRIMARY KEY)
│   ├── character_id (UUID, FOREIGN KEY)
│   ├── pvp_kills (INTEGER)
│   ├── monster_kills (INTEGER)
│   ├── deaths (INTEGER)
│   ├── session_id (UUID)
│   └── updated_at (TIMESTAMP)
│
└── sessions
    ├── id (UUID, PRIMARY KEY)
    ├── character_id (UUID, FOREIGN KEY)
    ├── server_region (VARCHAR)
    ├── started_at (TIMESTAMP)
    └── ended_at (TIMESTAMP)
```

---

_Document Version: 1.0_  
_Last Updated: November 2024_  
_Status: Ready for Implementation_
