# Technical Design Specification

**Version:** 1.0  
**Date:** November 2025 **Project Type:** Top-down 2D multiplayer bullet-hell shooter

---

## Project Overview

### Game Features

-   **Genre:** Top-down 2D sprite based bullet-hell multiplayer competitive shooter
-   **Style:** Left click to shoot
-   **Networking:** Low Level API for maximum performance to support highest possible simultaneous player count
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

-   **Engine:** Godot 4.5
-   **Language:** GDScript
-   **Rendering:** 2D sprite-based
-   **Networking:** WebSocket (Low Level API)

### Server

-   **Game Server:** Godot 4.5 Headless
-   **API Server:** Go
-   **Database:** PostgreSQL
-   **Cache:** Redis
-   **Deployment:** Docker containers on DigitalOcean

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

-   **Engine:** Godot 4.5
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
├── Dockerfile                     # Container definition
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
└── deployments/
    ├── docker-compose.yml        # Local development
    └── kubernetes/               # K8s manifests (future)
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
