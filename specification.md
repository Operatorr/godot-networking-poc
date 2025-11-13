# Omega Realm - Project Structure Specification

**Version:** 1.0  
**Date:** November 2024  
**Project Type:** Top-down 2D multiplayer bullet-hell shooter

---

## Technology Stack

### Client

- **Engine:** Godot 4.5
- **Language:** GDScript
- **Rendering:** 2D sprite-based
- **Networking:** WebSocket (Low Level API)

### Server

- **Game Server:** Godot 4.5 Headless
- **API Server:** Go
- **Database:** PostgreSQL
- **Cache:** Redis
- **Deployment:** Docker containers on DigitalOcean

---

## Godot Project Folder Structure

```
res://
├── project.godot                      # Project configuration
├── export_presets.cfg                 # Export settings
│
├── autoload/                          # Singleton systems (autoloaded)
│   ├── game_manager.gd               # Core game state management
│   ├── network_manager.gd            # Network connection handling
│   ├── auth_manager.gd               # Authentication management
│   ├── audio_manager.gd              # Global audio system
│   └── scene_manager.gd              # Scene transition handling
│
├── scenes/                            # All scene files (.tscn)
│   ├── main.tscn                     # Entry point scene
│   ├── menus/                        # UI scenes
│   │   ├── main_menu.tscn           # Main menu with play/exit/region
│   │   ├── character_creation.tscn  # Character name input
│   │   └── loading_screen.tscn      # Loading transitions
│   │
│   ├── game/                         # Gameplay scenes
│   │   ├── arena.tscn              # Main arena level
│   │   └── game_ui.tscn            # In-game HUD/leaderboard
│   │
│   ├── entities/                     # Game entities
│   │   ├── player/
│   │   │   └── base_player.tscn    # Player character template
│   │   ├── monsters/
│   │   │   └── base_monster.tscn   # Monster template
│   │   └── projectiles/
│   │       └── base_projectile.tscn # Projectile template
│   │
│   └── components/                   # Reusable components
│       ├── health_component.tscn    # HP system
│       ├── movement_component.tscn  # Movement handler
│       └── spawner_component.tscn   # Entity spawner
│
├── scripts/                          # GDScript files (.gd)
│   ├── player/
│   │   ├── player_controller.gd    # Player input/movement
│   │   ├── player_combat.gd        # Shooting mechanics
│   │   └── player_animation.gd     # Animation state machine
│   │
│   ├── monsters/
│   │   ├── monster_ai.gd           # AI behavior
│   │   └── monster_combat.gd       # Monster shooting
│   │
│   ├── networking/
│   │   ├── client_network.gd       # Client-side networking
│   │   ├── network_protocol.gd     # Message serialization
│   │   ├── state_buffer.gd         # State interpolation
│   │   └── prediction.gd           # Client prediction
│   │
│   ├── systems/
│   │   ├── projectile_system.gd    # Projectile management
│   │   ├── spawn_system.gd         # Monster spawning
│   │   └── leaderboard_system.gd   # Kill tracking
│   │
│   └── ui/
│       ├── main_menu_controller.gd # Menu logic
│       └── hud_controller.gd       # HUD updates
│
├── assets/                          # Game assets
│   ├── sprites/
│   │   ├── player/
│   │   │   ├── idle.png
│   │   │   ├── walk.png
│   │   │   ├── attack.png
│   │   │   └── hit.png
│   │   ├── monsters/
│   │   │   └── monster_sheet.png
│   │   ├── projectiles/
│   │   │   └── bullet.png
│   │   └── environment/
│   │       └── arena_tileset.png
│   │
│   ├── audio/
│   │   ├── music/
│   │   │   └── menu_bgm.ogg
│   │   ├── sfx/
│   │   │   ├── player_shoot.ogg
│   │   │   ├── player_hit.ogg
│   │   │   ├── player_death.ogg
│   │   │   ├── monster_shoot.ogg
│   │   │   ├── monster_hit.ogg
│   │   │   ├── monster_death.ogg
│   │   │   ├── button_hover.ogg
│   │   │   └── button_click.ogg
│   │   └── ambience/
│   │       └── arena_ambience.ogg
│   │
│   └── ui/
│       ├── fonts/
│       │   └── main_font.tres
│       └── themes/
│           └── default_theme.tres
│
├── data/                            # Data-driven content
│   ├── config/
│   │   ├── game_settings.json     # Game configuration
│   │   └── network_config.json    # Network settings
│   └── definitions/
│       ├── player_stats.json      # Player HP and stats
│       └── monster_stats.json     # Monster definitions
│
└── resources/                       # Godot resource files
    ├── shaders/                    # Visual effects
    └── materials/                  # Sprite materials
```

---

## Server Project Structure

### Game Server (Godot Headless)

```
omega-server/
├── project.godot
├── export_presets.cfg
│
├── server/
│   ├── server_main.gd             # Server entry point
│   ├── game_state_manager.gd      # Authoritative game state
│   ├── client_manager.gd          # Connected clients handling
│   ├── physics_controller.gd      # Server physics
│   └── validation.gd              # Action validation
│
├── networking/
│   ├── websocket_server.gd        # WebSocket listener
│   ├── packet_handler.gd          # Message processing
│   └── broadcast_manager.gd       # State broadcasting
│
├── systems/
│   ├── monster_spawner.gd         # Server-side spawning
│   ├── combat_system.gd           # Damage calculation
│   └── respawn_system.gd          # Player respawning
│
└── shared/                         # Shared with client
    └── network_protocol.gd        # Protocol definitions
```

### Backend API (Go)

```
omega-api/
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

### Redis Keys Structure

```
redis/
├── sessions/
│   └── session:{user_id}         # Active session data
│
├── leaderboards/
│   ├── global:pvp_kills          # Sorted set
│   ├── region:{region}:pvp_kills # Regional leaderboards
│   └── arena:{arena_id}:active   # Current arena players
│
└── cache/
    ├── user:{user_id}            # User data cache
    └── character:{char_id}       # Character cache
```

---

## Deployment Structure

```
deployment/
├── docker/
│   ├── game-server/
│   │   ├── Dockerfile
│   │   └── entrypoint.sh
│   │
│   ├── api-server/
│   │   ├── Dockerfile
│   │   └── entrypoint.sh
│   │
│   └── docker-compose.yml       # Local testing
│
├── scripts/
│   ├── deploy.sh                # Deployment script
│   ├── backup.sh                # Database backup
│   └── monitor.sh               # Health checks
│
└── config/
    ├── production/
    │   ├── game-server.env
    │   ├── api-server.env
    │   └── database.env
    │
    └── development/
        ├── game-server.env
        ├── api-server.env
        └── database.env
```

---

## Development Workflow Structure

```
omega-realm-workspace/
├── client/                      # Godot client project
├── server/                      # Godot headless server
├── api/                        # Go backend API
├── database/                   # Database schemas/migrations
├── deployment/                 # Deployment configurations
├── docs/                       # Documentation
│   ├── architecture.md
│   ├── infrastructure.md
│   └── specification.md
├── tests/                      # Test suites
│   ├── load-tests/
│   ├── unit-tests/
│   └── integration-tests/
└── tools/                      # Development tools
    ├── stress-tester/         # Bot client for testing
    └── monitoring/            # Performance monitoring
```

---

_Document Version: 1.0_  
_Last Updated: November 2024_  
_Status: Ready for Implementation_
