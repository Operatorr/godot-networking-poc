# Omega Realm - Architecture & Design Principles

**Date:** November 2024
**Version:** 1.0
**Target Technology Stack:** Go API, PostgreSQL, Redis, Godot Headless Servers

---

## Table of Contents

1. [Monorepo Structure](#monorepo-structure)
2. [WebSocket Architecture & Requirements](#websocket-architecture--requirements)
3. [System Architecture Overview](#system-architecture-overview)
4. [Godot Server Limitations & Principles](#godot-server-limitations--principles)
5. [Bandwidth Optimization Strategies](#bandwidth-optimization-strategies)
6. [CPU Optimization Strategies](#cpu-optimization-strategies)
7. [Sharding Strategy](#sharding-strategy)
8. [Architecture Recommendation for Omega Realm](#architecture-recommendation-for-omega-realm)
9. [Development Workflow](#development-workflow)

---

## Monorepo Structure

Omega Realm uses a **single Godot project with dual client/server export presets**, combined with a Go API backend in a monorepo structure.

### Repository Layout

```
omega-networking/
├── client/                          # Single Godot 4.5 Project (Client + Server)
│   ├── project.godot               # Project configuration
│   ├── export_presets.cfg          # Client AND Server export configurations
│   ├── autoload/                   # Singletons (detect server mode at runtime)
│   │   ├── game_manager.gd         # Detects dedicated_server feature tag
│   │   ├── network_manager.gd      # Dual WebSocket client/server
│   │   ├── auth_manager.gd         # Client-only (disabled on server)
│   │   ├── audio_manager.gd        # Client-only (disabled on server)
│   │   └── scene_manager.gd        # Routes to client vs server scenes
│   ├── scenes/
│   │   ├── client/                 # Client-only scenes (menus, UI)
│   │   ├── server/                 # Server-only scenes (server_main.tscn)
│   │   └── shared/                 # Shared entities (arena, player, monsters)
│   ├── scripts/
│   │   ├── client/                 # Client-only logic
│   │   ├── server/                 # Server-only logic
│   │   └── shared/                 # Shared game logic, protocol definitions
│   └── assets/                     # Auto-stripped in server export
│
├── api/                            # Go Backend API
│   ├── cmd/server/main.go         # Entry point
│   ├── internal/
│   │   ├── auth/                   # JWT authentication
│   │   ├── database/               # PostgreSQL connection
│   │   ├── handlers/               # HTTP route handlers
│   │   └── models/                 # Data models
│   ├── go.mod                      # Go module definition
│   └── Dockerfile → ../deployment/api.Dockerfile
│
├── deployment/                     # Docker & deployment configs
│   ├── docker-compose.yml          # Orchestrates all services
│   ├── api.Dockerfile              # Go API container
│   ├── server.Dockerfile           # Godot headless server container
│   └── .env.example                # Environment variable template
│
├── scripts/                        # Build automation
│   ├── build_client.sh             # Export client for Win/Mac/Linux
│   ├── build_server.sh             # Export headless server
│   └── build_api.sh                # Build Go API
│
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md             # This file
│   └── specification.md            # Game design specification
│
└── exports/                        # Build outputs (git-ignored)
    ├── client/
    │   ├── windows/
    │   ├── linux/
    │   └── macos/
    └── server/linux/
```

### Single Godot Project Approach

**Why One Project?**
- Godot 4.5 supports `OS.has_feature("dedicated_server")` feature tag detection
- Client and server share identical game logic, physics, and entity definitions
- Export presets with "Strip Visuals" automatically remove client assets from server builds
- No code duplication for protocol, entities, or game rules

**How It Works:**
```gdscript
# autoload/game_manager.gd
func _ready() -> void:
    is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

    if is_server:
        _initialize_server()  # Load server scene, start WebSocket server
    else:
        _initialize_client()  # Load main menu, prepare for connection
```

**Export Presets:**
```ini
[preset.0] name="Windows Desktop (Client)"
dedicated_server=false  # Full assets, UI, audio

[preset.3] name="Linux Headless Server"
dedicated_server=true   # Adds "dedicated_server" feature tag
# Texture/audio stripped automatically
```

### Component Communication

```
┌─────────────────┐         HTTP REST API        ┌─────────────────┐
│  Game Client    │ ←──────────────────────────→ │   Go API        │
│  (Godot 4.5)    │   (Auth, Characters,         │  (Port 8080)    │
│                 │    Leaderboards)              │                 │
└────────┬────────┘                               └────────┬────────┘
         │                                                 │
         │ WebSocket (Port 8081)                          │ PostgreSQL
         │ (Game state, movement,                         │ + Redis
         │  combat)                                       │
         │                                                │
         ▼                                                ▼
┌─────────────────┐                               ┌─────────────────┐
│  Game Server    │ ←────── HTTP (Stats) ───────→ │   Database      │
│  (Godot 4.5     │                                │   PostgreSQL    │
│   Headless)     │                                │   Redis Cache   │
└─────────────────┘                               └─────────────────┘
```

---

## WebSocket Architecture & Requirements

### Why WebSockets Are Essential

Omega Realm's multiplayer experience requires **persistent, bidirectional, low-latency communication** between game clients and servers. WebSockets are non-negotiable because:

#### Game Design Requirements

| Feature                       | Requirement                             | Why WebSocket                                                   |
| ----------------------------- | --------------------------------------- | --------------------------------------------------------------- |
| **Real-time player movement** | <100ms latency in shared zones          | HTTP request/response too slow; WebSocket provides instant push |
| **Combat synchronization**    | Damage, hits, effects visible instantly | Bidirectional communication needed                              |
| **PvP arenas**                | Competitive gameplay                    | Millisecond-accurate state sync required                        |

#### HTTP Polling Comparison (Why NOT to use it)

```
WebSocket (✅ IDEAL):
├─ Persistent TCP connection
├─ Server pushes updates instantly
├─ Total latency: 10-50ms (network + processing)
├─ Bandwidth: Only data sent/received, no polling overhead
├─ 100 players = ~100KB/s data only, efficient
└─ Feels snappy and responsive
```

### WebSocket Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         GAME CLIENT (Godot)                      │
│  ┌─────────────────┐                                             │
│  │ Input Handler   │                                             │
│  └────────┬────────┘                                             │
│           │                                                      │
│  ┌────────▼────────────────────┐                                │
│  │  WebSocket Connection Pool   │                                │
│  │  ├─ Movement updates (1/s)   │                                │
│  │  ├─ Combat actions (instant) │                                │
│  │  └─ Input confirmations      │                                │
│  └────────┬────────────────────┘                                │
│           │ TCP/WebSocket                                        │
│           │ (Persistent connection)                              │
└───────────┼─────────────────────────────────────────────────────┘
            │
┌───────────▼─────────────────────────────────────────────────────┐
│                    GAME SERVER (Godot Headless)                  │
│  ┌─────────────────────────────────┐                            │
│  │ WebSocket Multiplexer           │                            │
│  │ ├─ Receives player input        │                            │
│  │ ├─ Validates actions            │                            │
│  │ └─ Broadcasts state to others   │                            │
│  └──────────┬──────────────────────┘                            │
│             │                                                    │
│  ┌──────────▼────────────────────┐                              │
│  │ Game Logic                     │                              │
│  │ ├─ Physics simulation          │                              │
│  │ ├─ Combat calculations         │                              │
│  │ ├─ AI behavior                 │                              │
│  │ ├─ Entity updates              │                              │
│  │ └─ Damage tracking             │                              │
│  └──────────┬─────────────────────┘                              │
│             │                                                    │
│  ┌──────────▼─────────────────────┐                             │
│  │ State Broadcaster               │                             │
│  │ ├─ Delta compression            │                             │
│  │ ├─ Interest management (culling)│                             │
│  │ └─ Broadcast to clients         │                             │
│  └──────────┬──────────────────────┘                            │
└─────────────┼──────────────────────────────────────────────────┘
              │
    ┌─────────▼──────────┐
    │ TCP/WebSocket      │
    │ (state broadcasts) │
    └─────────┬──────────┘
              │
┌─────────────▼───────────────────────────────────────────────────┐
│                  BACKEND API (Go)                               │
│  ┌────────────────────────┐                                     │
│  │ HTTP/REST Endpoints    │                                     │
│  │ ├─ Authentication      │                                     │
│  │ ├─ Persistence         │                                     │
│  │ ├─ Character data      │                                     │
│  └────────────┬───────────┘                                     │
└───────────────┼─────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────┐
│         DATABASE TIER (PostgreSQL + Redis)                       │
│  ├─ User accounts & sessions                                     │
│  ├─ Leaderboards (Redis cache)                                   │
│  └─ Game definitions (cached)                                    │
└──────────────────────────────────────────────────────────────────┘
```

### WebSocket Protocol Details

**Connection per Game Client:**

```gdscript
# Godot client initiates WebSocket to Game Server
var ws = WebSocketClient.new()
ws.connect_to_url("wss://game-server.example.com:8443")
# Persistent connection for entire play session
# Reconnect with exponential backoff if connection lost
```

**Message Types over WebSocket:**

| Message Type      | Direction       | Frequency | Size     | Purpose                            |
| ----------------- | --------------- | --------- | -------- | ---------------------------------- |
| **PlayerInput**   | Client → Server | 10/s      | 50B      | Movement, actions, spells          |
| **StateUpdate**   | Server → Client | 10/s      | 100-500B | Player/enemy positions, animations |
| **GameEvent**     | Server → Client | Instant   | 50-200B  | Damage, kills, status effects      |
| **Heartbeat**     | Bidirectional   | 1/s       | 4B       | Keep-alive, detect disconnects     |
| **ActionConfirm** | Server → Client | Instant   | 20B      | Confirm attack                     |

**Bandwidth per Player (detailed calculation):**

```
Per-second data flow (single player in zone):
├─ Outbound (to server):
│  ├─ PlayerInput: 50B × 10/s = 500B/s
│  ├─ Heartbeat: 4B × 1/s = 4B/s
│  └─ Total UP: ~504B/s
│
├─ Inbound (from server):
│  ├─ StateUpdate: 200B × 10/s = 2000B/s (worst case, many players visible)
│  ├─ GameEvent: ~100B × 5 events/s = 500B/s
│  ├─ Heartbeat: 4B × 1/s = 4B/s
│  └─ Total DOWN: ~2504B/s (highly variable based on zone population)
│
└─ Total sustained: ~3KB/s per player
   (30KB/10sec = 3KB/s minimum, spikes to 5-10KB/s during combat)
```

---

## System Architecture Overview

### High-Level Data Flow

```
┌──────────────────────┐
│   Game Client(s)     │
│     (Godot)          │
└──────┬───────────────┘
       │ WebSocket (game state)
       │ TCP/UDP (ENet)
       ▼
┌──────────────────────────────────┐
│  Game Server (Godot Headless)    │
│  ├─ Authority on game state      │
│  ├─ Validates all actions        │
│  ├─ Simulates physics            │
│  ├─ Runs AI                      │
│  └─ Broadcasts state             │
└──────┬───────────────────────────┘
       │ HTTP/WebSocket (game events)
       │ Character state updates
       ▼
┌──────────────────────────────────┐
│  Backend API (Go)                │
│  ├─ Stateless                    │
│  ├─ Handles auth/persistence     │
│  ├─ Manages tournaments          │
│  ├─ Updates leaderboards         │
│  └─ Serves content definitions   │
└──────┬───────────────────────────┘
       │ SQL queries
       │ Redis cache ops
       ▼
┌──────────────────────────────────┐
│  Data Layer                      │
│  ├─ PostgreSQL (persistent)      │
│  └─ Redis (session/leaderboards) │
└──────────────────────────────────┘
```

### Communication Protocols

- **Client ↔ Game Server:** WebSocket (persistent TCP)
- **Game Server ↔ API Server:** HTTP REST + WebSocket for events
- **API Server ↔ Database:** Native PostgreSQL protocol
- **Caching Layer:** Redis (in-memory)

---

## Godot Server Limitations & Principles

### Per-Player Costs

Every connected player incurs costs across CPU, memory, and network:

| Resource           | Cost       | Notes                                     |
| ------------------ | ---------- | ----------------------------------------- |
| **RAM**            | 2-5 MB     | Player object, state data, input buffer   |
| **CPU**            | 0.5-2%     | Input processing, validation, network I/O |
| **Bandwidth Down** | 1-10 KB/s  | State updates, depends on zone complexity |
| **Bandwidth Up**   | 0.5-1 KB/s | Player input, actions                     |

### Per-Enemy Costs

Each AI enemy (PvE):

| Resource      | Cost     | Notes                                              |
| ------------- | -------- | -------------------------------------------------- |
| **RAM**       | 5-15 KB  | State, pathfinding data, behavior tree             |
| **CPU**       | 1-5%     | Pathfinding (20% of cost), physics (40%), AI (40%) |
| **Bandwidth** | 0-2 KB/s | Only broadcast if visible to players               |

### Performance Degradation Curve

As you approach capacity, performance degrades non-linearly:

```
Performance (%)
100%  ┌────────────────
      │
 90%  │    ▲ Linear region
      │   ╱  ╲
 75%  │  ╱    ╲  ← Comfortable zone (80% capacity)
      │ ╱      ╲
 50%  │╱        ╲
      │          ╲ ← Degradation zone (90%+)
 25%  │           ╲___
      │               ╲____
  0%  └──────────────────────
      0%    50%    100%   120%
           Server Capacity

Principles:
- 0-70% capacity: Linear performance
- 70-85% capacity: Slight frame time increase (~10%)
- 85-95% capacity: Noticeable lag (15-30% frame time increase)
- 95%+ capacity: Severe lag, unplayable
- >100% capacity: Server becomes unstable, crashes

RULE: Keep servers at 70-80% capacity for safety margin
```

### Anti-Patterns to AVOID

❌ **Broadcasting all state to all players**

```gdscript
# BAD: Every player gets every entity's state
func broadcast_state():
    for player in all_players:
        for entity in all_entities:
            player.send_state_update(entity)
# Cost: O(n²) complexity, 100 players × 200 enemies = 20k updates/frame
```

✅ **Interest Management / Culling**

```gdscript
# GOOD: Only send relevant entities
func broadcast_state():
    for player in all_players:
        var visible_entities = get_visible_entities(player.position, RENDER_DISTANCE)
        for entity in visible_entities:
            player.send_state_update(entity)
# Cost: O(n) per player, filtered by visibility
```

❌ **Syncing every frame (60+ Hz)**

```gdscript
# BAD: Network overhead too high
func _physics_process(delta):
    for player in all_players:
        sync_player_state(player)  # Every frame!
# Cost: 6000+ updates/sec for 100 players (unrealistic)
```

✅ **Intelligent update frequency**

```gdscript
# GOOD: Update based on change
func _physics_process(delta):
    for player in all_players:
        if player.state_changed():  # Only if moved significantly
            sync_player_state(player)
# Cost: ~10-20 updates/sec per player (varies by activity)
```

---

## Bandwidth Optimization Strategies

The primary goal: **Reduce bandwidth per player to host maximum players on minimum hardware.**

### 1. Delta Compression

Send only **changes**, not entire state:

```json
FULL STATE (❌ 500 bytes):
{
  "player_id": 1,
  "position": [123.5, 456.2],
  "rotation": 45.0,
  "animation": "walk",
  "health": 85,
  "mana": 120,
  "stamina": 95,
  "buffs": ["haste", "regen"],
  "equipment": {...},
  "level": 5
}

DELTA COMPRESSION (✅ 50 bytes):
{
  "id": 1,
  "p": [123.5, 456.2],     // position changed
  "a": "walk"              // animation changed
}
// Skip unchanged fields: rotation, health, mana, equipment, etc.
```

### 2. Interest Management / Culling

Don't send information about entities outside a player's **Area of Interest (AoI)**:

**Expected savings:** 70-90% bandwidth reduction

### 3. Packet Structure Optimization

Use compact binary format instead of JSON:

**Expected savings:** 80-90% bandwidth reduction

### 4. Update Frequency Scaling

Send updates less frequently for distant/less-important entities:

**Expected savings:** 60-70% bandwidth reduction

### Total Bandwidth Reduction Example

Combining all 5 strategies:

```
Base bandwidth per player: 10 KB/s
├─ After delta compression (-85%): 1.5 KB/s
├─ After interest culling (-75%): 0.4 KB/s
├─ After packet optimization (-85%): 0.06 KB/s
├─ After update frequency scaling (-65%): 0.02 KB/s

FINAL: 0.002 KB/s per player = 200 players on 1 KB/s bandwidth
```

This allows **100-200 concurrent players** on a single Godot server with reasonable bandwidth usage.

---

## CPU Optimization Strategies

### 1. Physics Pooling & Reuse

Reuse physics objects instead of creating/destroying:

**Expected savings:** 70-90% CPU reduction for frequently spawned entities

### 2. AI Culling by Distance

Only run AI for nearby enemies:

**Expected savings:** 80-90% CPU reduction for distant enemies

### 3. Pathfinding Optimization

Use A\* with caching, not every frame:

**Expected savings:** 80-90% CPU reduction for pathfinding

### 4. Entity Streaming / LOD

Different detail levels based on distance:

**Expected savings:** 70-90% CPU reduction for large entity counts

### 5. Batch Processing

Process updates in batches instead of per-frame:

**Expected savings:** 50-70% CPU reduction for frequent operations

### Total CPU Reduction Example

```
Base CPU usage: 100%
├─ Physics pooling (-80%): 20%
├─ AI culling (-85%): 3%
├─ Pathfinding (-85%): 0.5%
├─ Entity LOD (-75%): 1%
└─ Batch processing (-65%): 0.35%

FINAL: ~25% baseline CPU usage per 100 players
This allows 4× more players on the same hardware
```

---

## Sharding Strategy

### Zone-Based Sharding Architecture

```
SHARD TOPOLOGY:

┌──────────────────────┐
│   HUB CITIES        │
│ (Shared instances)  │
│ 500 players max     │
└──────────────────────┘
           │
    ┌──────┴──────┬──────────┬──────────┐
    │             │          │          │
    ▼             ▼          ▼          ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ Forest │  │ Desert │  │ Mountain│ │Volcanic│
│ Shard  │  │ Shard  │  │ Shard   │ │ Shard  │
│ 100p/  │  │ 100p/  │  │ 100p/   │ │100p/   │
│ inst   │  │ inst   │  │ inst    │ │ inst   │
└────┬───┘  └────┬───┘  └────┬────┘  └────┬───┘
     │           │           │            │
  [Inst 1]    [Inst 1]    [Inst 1]     [Inst 1]
  [Inst 2]    [Inst 2]    [Inst 2]     [Inst 2]
  [Inst 3]    [Inst 3]    [Inst 3]     [Inst 3]
     ...         ...         ...          ...

DUNGEON LAYER (Private Instances):
     ▲             ▲           ▲            ▲
     │             │           │            │
  Rift D1       Rift D1      Rift D1      Rift D1
  (1-5p)        (1-5p)       (1-5p)       (1-5p)
  Rift D2       Rift D2      Rift D2      Rift D2
  (1-5p)        (1-5p)       (1-5p)       (1-5p)
```

### Player Assignment Algorithm

```gdscript
class_name ShardingManager extends Node

var shards: Dictionary = {
    "hub_city_1": ShardsCluster.new(max_players=500),
    "hub_city_2": ShardsCluster.new(max_players=500),
    "hub_city_3": ShardsCluster.new(max_players=500),
    "forest": ShardsCluster.new(max_players=100, instances_count=5),
    "desert": ShardsCluster.new(max_players=100, instances_count=5),
    "mountain": ShardsCluster.new(max_players=100, instances_count=5),
    "volcanic": ShardsCluster.new(max_players=100, instances_count=5),
}

func assign_player_to_shard(player: Player, target_zone: String) -> bool:
    var shard = shards[target_zone]

    # Try to find instance with space
    for instance in shard.instances:
        if instance.player_count < instance.max_players:
            instance.add_player(player)
            return true

    # Create new instance if configured to do so
    if shard.instances.size() < shard.max_instances:
        var new_instance = create_zone_instance(target_zone)
        new_instance.add_player(player)
        shard.instances.append(new_instance)
        return true

    # No space available
    return false

# Example flow:
# Player A joins "forest" zone
#  → Check Forest Shard Instance 1: 85 players (max 100)
#  → Has space! Add Player A
#  → Player A joins Forest Instance 1
#
# Player B joins "forest" zone
#  → Check Forest Shard Instance 1: now 86 players
#  → Has space! Add Player B
#  → Players A and B in same instance
#
# Player C joins "forest" zone with friends
#  → Forest Shard Instance 1: 100 players (FULL)
#  → Try Instance 2: 50 players
#  → Has space! Add Player C
#  → Player C joins Forest Instance 2 (different from A/B)
```

### Cross-Shard Communication

Players in different shards need to:

- ✅ Share leaderboards (API handles this)
- ✅ Trade items (API transaction service)
- ✅ Join tournaments together (matchmaking service)
- ❌ See each other in-game (not possible across shards)

```
┌──────────────────────────────────────┐
│ Backend API (Cross-Shard Hub)        │
├──────────────────────────────────────┤
│ Leaderboard Service                  │
│ (aggregates from all shards)         │
│                                      │
│ Tournament Matchmaking               │
│ (can queue players from different    │
│  shards, match them in new instance) │
│                                      │
│ Trading Post                         │
│ (players from all shards can trade)  │
└──────────────────────────────────────┘
         ▲    ▲     ▲    ▲
         │    │     │    │
    ┌────┴─┬──┴──┬──┴──┬─┴────┐
    │      │     │     │      │
  Forest Desert Mountain Volcanic Hubs
  Shards Shards  Shards  Shards Shards
```

### Expansion Strategy

**Phase 1 (Alpha/Beta):** Single shard for all zones

---

## Architecture Recommendation for Omega Realm

### Technology Stack

**Frontend:**

- Godot 4.5 Desktop Client
- WebSocket for real-time communication
- Delta compression for efficient state sync

**Game Server:**

- Godot 4.5 Headless Server
- Authoritative architecture (server validates all actions)
- ENet protocol (for legacy compatibility, though WebSocket preferred)
- Sharded by zone (expandable)

**API Server:**

- Go (language: fast, concurrent, memory-efficient)
- REST API for static operations
- WebSocket for real-time game events
- Stateless (for horizontal scaling)

**Database:**

- PostgreSQL (primary persistence)
- Redis (caching, leaderboards, sessions)

**Deployment:**

- Docker containers
- Kubernetes or Docker Swarm for orchestration (at scale)
- CDN for static content (CloudFlare)

### Why This Stack

| Component   | Choice         | Reason                                                             |
| ----------- | -------------- | ------------------------------------------------------------------ |
| Client      | Godot          | Already using for game; built-in networking                        |
| Game Server | Godot Headless | Shares codebase with client; optimal for gameplay                  |
| API Server  | **Go**         | 100k+ req/s throughput, minimal memory, concurrency via goroutines |
| Database    | PostgreSQL     | Proven for MMOs, ACID transactions, spatial queries (for zones)    |
| Cache       | Redis          | Lightning-fast leaderboards, session storage                       |
| Protocol    | WebSocket      | Real-time, bidirectional, low-latency                              |

### Scaling Assumptions

- **Alpha:** 50-100 concurrent players, 1-2 servers, $20-50/month
- **Beta:** 100-500 concurrent players, 3-6 servers, $80-150/month
- **Launch:** 500-2,000 concurrent players, 10-20 servers, $300-800/month
- **10k+ Target:** 10,000+ concurrent players, 50-100+ servers globally, $2,000-5,000/month

### Success Metrics to Monitor

1. **Server FPS:** Maintain >30 FPS with <50ms frame time
2. **Player Latency:** <100ms 95th percentile in same-region play
3. **Network Bandwidth:** <5 KB/s per player average
4. **CPU per Player:** <1% per player
5. **Zone Instance Fullness:** Target 70-80%, cap at 95%

This architecture is designed for **rapid iteration** (fast content updates via API) while maintaining **authoritative security** (server validates all gameplay) and **scalability** (sharding supports growth without major rewrites).

---

## Development Workflow

### Local Development Setup

**Prerequisites:**
- Godot 4.5
- Go 1.21+
- Docker & Docker Compose
- PostgreSQL (or use Docker)
- Redis (or use Docker)

**Quick Start:**
```bash
# 1. Start infrastructure services
cd deployment
docker-compose up postgres redis

# 2. Build and run API
cd ../api
go mod download
go run cmd/server/main.go

# 3. Run Godot client (opens editor)
cd ../client
godot project.godot

# 4. Run Godot server (headless mode)
godot --headless project.godot
```

### Building for Production

**Build All Components:**
```bash
# Client exports (Windows, Mac, Linux)
./scripts/build_client.sh

# Server export (Linux headless)
./scripts/build_server.sh

# API binary
./scripts/build_api.sh
```

**Docker Deployment:**
```bash
cd deployment
docker-compose up --build
```

### Testing Changes

**Test Client Locally:**
1. Open `client/project.godot` in Godot editor
2. Press F5 to run
3. Client detects it's NOT headless, loads main menu

**Test Server Locally:**
```bash
cd client
godot --headless project.godot
# Server detects headless mode, loads server_main.tscn
# Starts WebSocket server on port 8081
```

**Test Full Stack:**
```bash
# Terminal 1: Start infrastructure
cd deployment && docker-compose up postgres redis

# Terminal 2: Start API
cd api && go run cmd/server/main.go

# Terminal 3: Start game server
cd client && godot --headless project.godot

# Terminal 4: Run client
cd client && godot project.godot
```

### Code Organization Principles

**Client-Only Code** (`client/scenes/client/`, `client/scripts/client/`):
- UI/UX, menus, HUD
- Input handling
- Client-side prediction
- Audio/visual effects
- Scene transitions

**Server-Only Code** (`client/scenes/server/`, `client/scripts/server/`):
- Server WebSocket management
- Authoritative game logic
- Player state validation
- Monster AI
- Damage calculation
- Anti-cheat

**Shared Code** (`client/scenes/shared/`, `client/scripts/shared/`):
- Entity definitions (Player, Monster, Projectile)
- Network protocol (MessageType enums, packet structures)
- Game constants (movement speed, damage values)
- Physics parameters

**When to Put Code in Shared:**
- If both client AND server need it
- Physics simulation
- Entity data structures
- Network message definitions

**When to Keep Separate:**
- Client: Anything related to rendering, input, or UI
- Server: Anything related to validation, anti-cheat, or authority

### Git Workflow

```bash
# Feature development
git checkout -b feature/player-movement
# Make changes to client/scripts/shared/player/
git add client/scripts/shared/player/
git commit -m "Implement player movement logic"

# Protocol changes require updates to both sides
git add client/scripts/shared/networking/protocol.gd
git add client/autoload/network_manager.gd
git commit -m "Add new PLAYER_DASH message type"

# API changes
git add api/internal/handlers/
git commit -m "Add character stats endpoint"

# Deploy changes
git push origin feature/player-movement
```

### Common Development Tasks

**Add New Network Message Type:**
1. Add enum to `client/scripts/shared/networking/protocol.gd`
2. Update `network_manager.gd` client send function
3. Update `network_manager.gd` server receive handler
4. Test both client and server

**Add New Entity:**
1. Create scene in `client/scenes/shared/entities/`
2. Add script in `client/scripts/shared/entities/`
3. Both client and server can instantiate

**Add UI Element:**
1. Create scene in `client/scenes/client/components/`
2. Add script in `client/scripts/client/ui/`
3. Server never loads this (automatic)

### Deployment Checklist

Before deploying to production:

- [ ] Run all build scripts successfully
- [ ] Test client exports on target platforms
- [ ] Test server with `--headless` flag
- [ ] Verify API connects to database
- [ ] Check docker-compose services start
- [ ] Review `.env` configuration
- [ ] Test full stack locally
- [ ] Backup database before deployment

---

**Last Updated:** November 2025
**Maintainer:** Development Team
