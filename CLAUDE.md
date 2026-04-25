# Claude Instructions for Multiplayer Game

## Working on Tasks

1. **use Context7** to get Godot 4.6 Documentation when writing scripts. Language: GDScript
2. **use Context7** to get Golang documentation if needed
3. **use godot-mcp** for interacting with Godot engine if neccesary
4. **do not** commit with Claude as Co-Author

## GDScript Style

- Prefer `class_name` references directly.
- If a script must be preloaded because Godot cannot resolve a newer global class during headless startup, name the preload constant exactly like the exported class, e.g. `const Projectile := preload(".../projectile.gd")`. Do not introduce parallel `FooScript` aliases.

## Project Documentation

```
specification.md
```

## Network Architecture Documentation

```
docs/ARCHITECTURE.md
```

## Monorepo project structure

```
  omega-networking/                   # Root (Git repo)
  ├── client/                         # Godot 4.6 Project
  │   ├── project.godot
  │   ├── export_presets.cfg         # Client AND Server exports
  │   ├── scenes/
  │   │   ├── client/               # Client-only scenes
  │   │   │   ├── menus/
  │   │   │   │   └── main_menu.tscn
  │   │   │   └── components/
  │   │   │       └── game_ui.tscn
  │   │   ├── server/               # Server-only scenes
  │   │   │   └── server_main.tscn
  │   │   └── shared/               # Shared entities
  │   │       ├── arena.tscn
  │   │       └── base_player.tscn
  │   ├── scripts/
  │   │   ├── client/               # Client-only logic
  │   │   │   ├── input_controller.gd
  │   │   │   └── prediction.gd
  │   │   ├── server/               # Server-only logic
  │   │   │   ├── server_manager.gd
  │   │   │   └── validation.gd
  │   │   └── shared/               # Shared game logic
  │   │       ├── network_protocol.gd
  │   │       ├── entity_data.gd
  │   │       └── game_constants.gd
  │   ├── autoload/
  │   │   ├── network_manager.gd    # Handles both client/server modes
  │   │   └── game_manager.gd
  │   └── assets/
  │       ├── sprites/              # Stripped in server export
  │       └── audio/                # Stripped in server export
  │
  ├── api/                           # Go Backend (separate)
  │   ├── go.mod
  │   ├── main.go
  │   └── ...
  │
  ├── deployment/
  │   ├── docker-compose.yml        # Parameterized with env vars, health checks
  │   ├── client.Dockerfile
  │   ├── server.Dockerfile         # Uses headless export, health check
  │   ├── api.Dockerfile
  │   ├── .env.example
  │   ├── .env.production.example   # Production env template
  │   └── DEPLOYMENT.md             # DigitalOcean deployment guide
  │
  ├── load_testing/                  # Python load testing infrastructure
  │   ├── bot_client.py             # Single bot: binary WS protocol client
  │   ├── bot_swarm.py              # Orchestrator: spawn 50-200+ bots
  │   ├── requirements.txt
  │   └── README.md
  │
  └── scripts/
      ├── build_client.sh
      ├── build_server.sh
      ├── build_api.sh
      ├── deploy.sh                 # Docker deploy CLI (up/down/health/logs)
      ├── start_services.sh
      ├── stop_services.sh
      ├── status_services.sh
      └── run_server.sh
```

## Active Technologies
- GDScript (Godot 4.6) (001-main-menu-ui)
- GDScript (Godot 4.6) + Godot Engine 4.6 (built-in physics, CharacterBody2D, AnimatedSprite2D)
- In-memory player state; persistence handled by separate systems

## Recent Changes
- 001-main-menu-ui: Added GDScript (Godot 4.6)

## Load Testing

Run from any machine against the game server:
```bash
cd load_testing && pip install -r requirements.txt
python bot_swarm.py --scenario baseline --server ws://<server-ip>:8081
python bot_swarm.py --scenario target --server ws://<server-ip>:8081
python bot_swarm.py --scenario stress --server ws://<server-ip>:8081
```

## Deployment

```bash
# Local Docker stack
./scripts/deploy.sh up

# Production (see deployment/DEPLOYMENT.md for full guide)
cd deployment
cp .env.production.example .env.production
# Edit .env.production with secure values
docker compose --env-file .env.production up -d --build
```
