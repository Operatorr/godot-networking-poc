# AGENTS.md — Omega Realm networking POC

A top-down 2D bullet-hell multiplayer shooter built to **stress-test low-level netcode for MMO
scale** (target: 500–1000 concurrent players on one server Instance). Gameplay is intentionally
minimal — one shooting ability, HP only, one monster type — so the **network** is the thing
under test, not game complexity.

> **The core** is the Rust **`omega-server`** (ENet/UDP, bit-packed wire protocol, shared
> client/server sim). It is the only authoritative server; the GDScript server is retired.
> **Start at [`docs/server/design.md`](docs/server/design.md)** (architecture & rationale),
> then [`docs/server/contract.md`](docs/server/contract.md) (the wire/API contract as built).

This file is a **map, not a manual.** Deep knowledge lives in `docs/` — the system of record.
Don't re-derive what's already written there; read it, then go deep where needed.

## Repository layout

- `rust/` — Cargo workspace; **the authoritative server lives here**.
  - `protocol/` — the bit-packed wire format (shared, no codegen — ADR 0004).
  - `sim_core/` — movement/collision/hit sim shared by server AND client prediction:
    zero divergence by construction.
  - `server/` — the `omega-server` binary: single-threaded 30 Hz tick over `rusty_enet`
    (pinned `=0.4.0`), Ed25519 session tickets (dev mode: unsigned), Prometheus on `:9100`.
    Modules are grouped: `src/sim/` (world, player, monster, projectile, combat, ability,
    world_entity, rng, leaderboard) and `src/net/` (broadcast, outbox, metrics, auth,
    api_client, progression_client); they re-export flat at the crate root, so code still
    refers to them as `crate::player`, `crate::broadcast`, etc.
  - `client_ext/` — GDExtension exposing `ProtocolCodec`, `PredictionSim`, `SimHit` to GDScript.
  - `load_test/` — the `omega-load-test` bot swarm (replaced the Python `load_testing/`
    harness): ENet bots that link `protocol` + `sim_core` directly. See its README.
- `client/` — Godot 4.6 project; exports the **client only** now. The legacy GDScript server
  has been **removed** (it was retired by the Rust port); its file-by-file parity map to the Rust
  modules lives in [`docs/server/legacy-parity.md`](docs/server/legacy-parity.md), and the source is
  in git history. `NetworkManager` still refuses to run in headless/server mode. The client uses
  a **data-driven layout** (see [`docs/gdd/folder-structure.md`](docs/gdd/folder-structure.md)):
  - `autoload/` — singletons: `game_manager`, `network_manager`, `auth_manager`, `scene_manager`,
    `entity_name_cache`, `audio_manager`, `event_bus`.
  - `scripts/network/` — transport seam, `packet_types`, prediction, interpolation, entity buffer,
    client entity manager.
  - `scripts/entities/` — `player/` (+ `classes/`), `enemies/`, `projectiles/`, `world_effects/`,
    npc, portal. `scripts/data/` — definitions/, validators/, loaders, `game_constants`.
  - `scripts/systems/` — combat/, spawning/, visuals/, audio/, progression/, inventory/, loot/.
  - `scripts/ui/` (hud/, menus/, dialogs/, helpers/), `scripts/core/` (game modes),
    `scripts/factories/`, `scripts/levels/`, `scripts/utils/`.
  - `scenes/` — `entities/`, `levels/` (arena/, hub/, offline/, pve/, biomes/), `ui/`, `test/`.
  - `data/` — JSON content (classes/, monsters/, balance/, loot/, items/, spells/, projectiles/,
    world/, schemas/); `bin/` — built GDExtension (`omega_client_ext.gdextension`).
- `api/` — Go backend: JWT auth, characters, leaderboard, regions. PostgreSQL + Redis.
- `deployment/` — **native** deploy (no Docker — [ADR 0007](docs/adr/0007-native-systemd-deployment.md)):
  systemd units (`systemd/`), per-instance configs (`server_config.{arena,sanctuary}.json`), env
  templates (`env/`), `provision_server.sh` (one-time bootstrap) + `server_update.sh` (git-pull deploy),
  `harden_vps.sh` (firewall/fail2ban/SSH).
- `scripts/` — build/deploy/run automation.
- `docs/` — **system of record** (map below).

## Documentation map

- [`docs/CONTEXT.md`](docs/CONTEXT.md) — glossary. **Use these exact terms** (Tick ≠ Frame ≠ Snapshot).
- [`docs/index.md`](docs/index.md) — full doc catalogue with verification status.
- [`docs/ops/architecture.md`](docs/ops/architecture.md) — top-level system architecture + POC success criteria.
- **[`docs/server/`](docs/server/) — the game server (current core):**
  - `design.md` — architecture & rationale (transport, shared sim, tick, auth, persistence, hits).
  - `contract.md` — workspace/crate APIs, channel plan, wire format, numerics policy, as built.
- [`docs/netcode/`](docs/netcode/) — netcode analyses (latency budget, prediction, interpolation,
  AoI, broadcast), rewritten around the Rust omega-server / `sim_core` / ENet. (The retired
  WebSocket/wire-protocol docs are now redirect stubs pointing at `docs/server/contract.md`.)
- [`docs/systems/`](docs/systems/) — gameplay systems, **status-tagged**: players/movement,
  combat/hits, monsters/AI, audio, UI/HUD, state machines.
- [`docs/adr/`](docs/adr/) — load-bearing decisions: 0002 fixed-tick authority (stands),
  0003 ENet/UDP transport (implemented), 0004 shared Rust protocol crate (implemented),
  0005 permadeath persistence.

## How every system is documented

Each netcode/system doc answers the **same eight questions**, so coverage is mechanically
checkable and nothing important is skipped:

> What runs on the **client**? on the **server**? What is **predicted**? **replicated**?
> **persisted**? **validated**? What can **fail**? How is it **tested**?

## Working rules

- **Context7** for Godot 4.6, Rust-crate, and Go docs before writing code. Languages:
  **Rust** (server, protocol, sim) and **GDScript** (client glue/UI).
- **godot-mcp** to drive the engine when needed.
- Sim semantics in `rust/sim_core` mirror Godot exactly (Vector2 f32 ops, f64 scalars,
  truncate-toward-zero quantization) — see contract.md §numerics before touching math.
- Prefer `class_name` references. If a script must be preloaded because Godot can't resolve a
  global class during headless startup, name the const exactly like the class:
  `const Projectile := preload(".../projectile.gd")`. No parallel `FooScript` aliases.
- Governing rule for all gameplay: **the client requests, the server decides.**
- **Do not** add Claude as a git co-author.

## Build / run / test

```bash
# Build
./scripts/build_client.sh        # Godot client export (win/mac/linux)
./scripts/build_client_ext.sh    # Rust GDExtension -> client/bin/ (run after rust/ changes)
./scripts/build_server.sh        # Rust omega-server (release)
./scripts/build_api.sh           # Go API

# Rust workspace checks (must stay green)
cd rust && cargo test --workspace && cargo clippy --workspace --all-targets && cargo fmt --check

# Run a local stack (native, no Docker — Postgres/Redis already running, e.g. DBngin)
./scripts/dev_local.sh            # Go API + BOTH game instances (Arena udp/8081 + Sanctuary udp/8082)
./scripts/run_server.sh --mode arena --port 8081      # one instance only (dev)

# Deploy to the live server (native systemd; git pull + rebuild) — runs from your laptop
./scripts/deploy.sh provision     # one-time: install Go/Rust/Postgres/Redis + units (ADR 0007)
./scripts/deploy.sh               # pull master, rebuild api + both game servers, restart, health-check
./scripts/deploy.sh sync          # BUILD-FREE: pull master + restart + health-check (runtime-only changes, e.g. server_config.*.json)
./scripts/deploy.sh pull          # JUST sync the server checkout — no rebuild, no restart (server-side deploy scripts, docs)
./scripts/deploy.sh logs|status|health|restart

# End-to-end smoke (needs a running server on 127.0.0.1:8081)
cd client && godot --path . res://scenes/test/net_smoke.tscn   # exits 0 on PASS

# Load test (needs a running server; scenarios + flags in rust/load_test/README.md)
./scripts/run_load_test.sh --scenario baseline                       # local Arena
OMEGA_SERVER=<droplet-ip>:8081 ./scripts/run_load_test.sh --scenario baseline   # live Arena
```

## Invariants (hold today; enforce in review)

- Entity id ranges: **players 1–999, projectiles 10000–29999, monsters 30000–39999**.
- Arena bounds: `(-1000,-1000)..(1000,1000)`; boundary walls at ±1005.
- Wire format: `[u8 type][payload]` over ENet (no length field — datagram boundaries);
  positions quantized to 0.1 unit (truncate toward zero). 3 channels: ch0 snapshots/confirms
  (unreliable sequenced), ch1 reliable (+ baselines), ch2 input. Unreliable payloads < 1200 B.
- All gameplay state is server-authoritative and in-memory; the Go API owns only
  account/character/leaderboard persistence.
- The D11 hit backstop stays **lenient**: true 24 u overlap only, grace ≥ 15 ticks.

## Known invariant violations — fixed on branch `perf/p0-p1-netcode-fixes`

Fixed on that branch (pending play-test + merge); on `master` they still hold as violations:

- The Local player must be moved by the `PredictionController` **only**. *Fixed:* `Player.gd`
  `prediction_owns_movement` skips its own `move_and_slide`. → `docs/systems/players-movement.md`
- Render smoothness must not depend on FPS. *Fixed:* `physics_interpolation=true` + discontinuity
  resets + camera uses the interpolated transform. → `docs/netcode/smoothness-render.md`
