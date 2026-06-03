# AGENTS.md — Omega Realm networking POC

A top-down 2D bullet-hell multiplayer shooter built to **stress-test low-level netcode for MMO
scale** (target: 500–1000 concurrent players on one Godot 4.6 headless server). Gameplay is
intentionally minimal — one shooting ability, HP only, one monster type — so the **network** is
the thing under test, not game complexity.

> **Active focus:** diagnosing and fixing perceived input lag / "sluggish on localhost" and
> building netcode that survives 100 ms+ ping and scales. **Start at
> [`docs/netcode/latency-budget.md`](docs/netcode/latency-budget.md).**

This file is a **map, not a manual.** Deep knowledge lives in `docs/` — the system of record.
Don't re-derive what's already written there; read it, then go deep where needed.

## Repository layout

- `client/` — single Godot 4.6 project; exports **both** the client and the headless server
  (mode detected at runtime). This is where ~all gameplay and netcode lives.
  - `autoload/` — singletons: `network_manager` (dual WS client/server), `game_manager`,
    `scene_manager`, `auth_manager`, `audio_manager`, `entity_name_cache`.
  - `scripts/server/` — authoritative sim: tick loop, players, monsters, projectiles, broadcast.
  - `scripts/client/` — prediction, interpolation, HUD, menus.
  - `scripts/shared/` — protocol, packets, game constants, entity scenes.
- `api/` — Go backend: JWT auth, characters, leaderboard, regions. PostgreSQL + Redis.
- `deployment/` — Docker Compose + per-service Dockerfiles.
- `load_testing/` — Python bot swarm (`baseline` / `target` / `stress` scenarios).
- `scripts/` — build/deploy/run automation.
- `docs/` — **system of record** (map below).

## Documentation map

- [`docs/CONTEXT.md`](docs/CONTEXT.md) — glossary. **Use these exact terms** (Tick ≠ Frame ≠ Snapshot).
- [`docs/index.md`](docs/index.md) — full doc catalogue with verification status.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — top-level system architecture + POC success criteria.
- **[`docs/netcode/`](docs/netcode/) — the core of this project:**
  - `latency-budget.md` — **start here.** Every millisecond of perceived delay, accounted, with `file:line`.
  - `smoothness-render.md` — the "30 fps at 100 fps" root cause and fix.
  - `overview.md` — authority model, the loops, the packet map.
  - `client-prediction.md` · `interpolation.md` · `server-tick-broadcast.md`
  - `transport-websocket.md` · `interest-mgmt-aoi.md` · `wire-protocol.md`
  - `performance-budgets.md` — targets vs measured numbers.
- [`docs/systems/`](docs/systems/) — gameplay systems, **status-tagged**: players/movement,
  combat/hits, monsters/AI, audio, UI/HUD, state machines.
- [`docs/exec-plans/active/netcode-perf-fixes.md`](docs/exec-plans/active/netcode-perf-fixes.md) — the prioritized fix roadmap.
- [`docs/adr/`](docs/adr/) — load-bearing decisions (why WebSocket/TCP, why fixed-tick authority).

## How every system is documented

Each netcode/system doc answers the **same eight questions**, so coverage is mechanically
checkable and nothing important is skipped:

> What runs on the **client**? on the **server**? What is **predicted**? **replicated**?
> **persisted**? **validated**? What can **fail**? How is it **tested**?

## Working rules

- **Context7** for Godot 4.6 and Go docs before writing code. Language: **GDScript**.
- **godot-mcp** to drive the engine when needed.
- Prefer `class_name` references. If a script must be preloaded because Godot can't resolve a
  global class during headless startup, name the const exactly like the class:
  `const Projectile := preload(".../projectile.gd")`. No parallel `FooScript` aliases.
- Detect run target at runtime: `OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"`.
- Governing rule for all gameplay: **the client requests, the server decides.**
- **Do not** add Claude as a git co-author.

## Build / run / test

```bash
# Build
./scripts/build_client.sh        # client export (win/mac/linux)
./scripts/build_server.sh        # headless server export
./scripts/build_api.sh           # Go API

# Run a local stack
./scripts/deploy.sh up            # docker compose: api + server + db + redis
./scripts/run_server.sh           # headless game server only

# Load test (against a running server)
cd load_testing && python bot_swarm.py --scenario target --server ws://<host>:8081
```

## Invariants (hold today; enforce in review)

- Entity id ranges: **players 1–999, projectiles 10000–29999, monsters 30000–39999**.
- Arena bounds: `(-1000,-1000)..(1000,1000)`; boundary walls at ±1005.
- Wire header: `[u8 type][u16 length]`; positions quantized to 0.1 unit.
- All gameplay state is server-authoritative and in-memory; the Go API owns only
  account/character/leaderboard persistence.

## Known invariant violations under active fix

These are *targets the code does not yet meet* — see the roadmap, do not assume they hold:

- The Local player should be moved by the `PredictionController` **only**; today `Player.gd`
  also moves it (double-ownership). → `docs/systems/players-movement.md`
- Render smoothness should not depend on FPS; today motion steps at 30 Hz. → `docs/netcode/smoothness-render.md`
