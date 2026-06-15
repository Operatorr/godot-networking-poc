# Folder Structure — canonical repo map (post-Rust, data-driven)

**Status:** TARGET structure for the restructure. This is the canonical layout the codebase is
moving toward; some paths below do not yet exist on disk and are marked accordingly.

This document **supersedes** the "Project Folder Structure" section of the old monolithic GDD
(`docs/GDD.md` @ `3f92407`), which described a single `res://` Godot tree containing **both** the
client *and* a GDScript server (with `scripts/network/network_server.gd`, `services/`,
`repositories/`, `tournament/`, etc.). That tree is obsolete:

- The **server is now Rust** (`omega-server`), not GDScript — see [`AGENTS.md`](../../AGENTS.md) and
  [`docs/server/design.md`](../server/design.md). The GDScript `scripts/server/` tree survives only
  as parity ground-truth and no longer runs (NetworkManager refuses server mode).
- Persistence (accounts/characters/leaderboard) lives in the **Go `api/`**, not in Godot
  `repositories/`/`services/`.
- The repo is a **multi-root monorepo** (`rust/`, `client/`, `api/`, `web/`, `deployment/`,
  `docs/`), not one `res://` project.

The old GDD's *intent* — a **data-driven content system** (base scenes + JSON definitions +
factories) — is preserved and is the organising principle of `client/` below.

---

## Top-level trees

```
omega-realm/
├── rust/          # Cargo workspace — the authoritative server + shared sim (the core)
├── client/        # Godot 4.6 project — client-only export
├── api/           # Go backend — auth, characters, leaderboard, progression, regions
├── web/           # Astro SSR site + dashboard (+ future content editor)
├── deployment/    # Native systemd deploy (no Docker — ADR 0007)
└── docs/          # System of record
```

Why split this way: the **network** is the thing under test, so the Rust server, the shared
simulation, and the bot swarm are first-class siblings — not buried inside the game project. The
client is a pure consumer of the wire protocol; persistence is a separate Go service; the website
is a separate Astro app. Each tree builds and tests independently
(see [`AGENTS.md`](../../AGENTS.md) → Build / run / test).

---

## The data-driven principle (how `client/` is organised)

Game content is **not** one scene file per enemy/item/spell. Instead, three layers cooperate:

1. **Base scenes** (`client/scenes/entities/…`) — one reusable `.tscn` per *category*
   (`base_enemy`, `base_projectile`, `base_item`, …). These hold the nodes/visual rig only.
2. **JSON definitions** (`client/data/…`) — the *parameters* for each concrete thing
   (this enemy's HP/speed/damage/sprite, this spell's `{damage, speed, radius, lifetime, pierce}`).
   Loaded at startup by `scripts/data/database_loader.gd`, cached in `definition_cache.gd`,
   validated against `client/data/schemas/`.
3. **Factories** (`client/scripts/factories/…`) — instantiate a base scene, then stamp a
   definition onto it (`enemy_factory.gd` reads an enemy definition → spawns `base_enemy.tscn`
   configured for that enemy).

What this buys / its limits (carried over from the GDD):

- **Free without a recompile** (pure data): reskins, stat tweaks, drop tables, spawn weights, a new
  projectile spell expressible as existing parameters.
- **Requires a Rust recompile + deploy** (new simulation *verb*): a boss that splits on death, a
  spell that teleports/reflects — anything `rust/sim_core` doesn't already understand. The client's
  data-driven layer is presentation/config; **authoritative behavior lives in Rust**, and the
  governing rule still holds: *the client requests, the server decides.*

Definitions that affect simulation must agree on both sides: the server has its own authoritative
copy of the balance-relevant numbers; client JSON must not diverge from what Rust enforces.

---

## `rust/` — Cargo workspace (the core)

```
rust/
├── Cargo.toml / Cargo.lock        # workspace
├── protocol/        # bit-packed wire format (shared, no codegen — ADR 0004)
├── sim_core/        # shared movement / collision / hit / progression sim
│                    #   (server AND client prediction link this → zero divergence)
├── server/          # the omega-server binary
│   └── src/
│       ├── sim/     # TARGET grouping: world, world_entity, player, monster,
│       │            #   projectile, combat, ability, progression, rng
│       └── net/     # TARGET grouping: broadcast, outbox, auth, config,
│                    #   api_client, progression_client, metrics, main
│                    # (today these are flat .rs files in src/ — the sim/ & net/
│                    #  split is the restructure target)
├── client_ext/      # GDExtension: ProtocolCodec, PredictionSim, SimHit → GDScript
└── load_test/       # omega-load-test bot swarm (links protocol + sim_core directly)
```

See [`docs/server/design.md`](../server/design.md) and
[`docs/server/contract.md`](../server/contract.md) for the as-built server.

---

## `client/` — Godot 4.6 (client-only export)

```
client/
├── project.godot · export_presets.cfg · icon.svg
│
├── autoload/                      # Singletons (autoloaded)
│   ├── game_manager.gd            # game state coordination
│   ├── network_manager.gd         # ENet client (refuses server mode)
│   ├── auth_service.gd            # auth/session (currently auth_manager.gd)
│   ├── scene_manager.gd
│   ├── audio_manager.gd · audio_manager.tscn
│   ├── entity_name_cache.gd
│   ├── event_bus.gd               # TARGET: global signal bus
│   └── transport/                 # the transport seam
│       ├── transport.gd           # interface
│       ├── enet_transport.gd      # ENet/UDP (production)
│       └── websocket_transport.gd # legacy seam
│
├── scripts/                       # GDScript
│   ├── core/                      # game_state, game_mode_{base,pve,pvp,race}
│   ├── data/                      # the data-driven loader layer
│   │   ├── database_loader.gd     # loads all JSON definitions at startup
│   │   ├── definition_cache.gd    # caches loaded definitions
│   │   ├── definitions/           # one *_definition.gd per category
│   │   └── validators/            # JSON-schema validation
│   ├── factories/                 # base-scene + definition → instance
│   │   └── entity / enemy / item / spell / projectile_factory.gd
│   ├── entities/                  # entity scripts (mirror scenes/entities/)
│   │   ├── base_entity.gd · living_entity.gd
│   │   ├── player/                # controller, movement, classes/
│   │   ├── enemies/               # base, ai_* behaviors
│   │   ├── projectiles/
│   │   ├── world_effects/
│   │   ├── npc.gd · portal.gd
│   ├── systems/                   # combat/ spawning/ progression/ inventory/
│   │   │                          #   loot/ visuals/ audio/
│   ├── network/                   # transport/, packet_types, prediction,
│   │   │                          #   interpolation, entity_state_buffer,
│   │   │                          #   client_entity_manager
│   ├── ui/                        # hud/ menus/ dialogs/ helpers
│   ├── levels/                    # arena_base, sanctuary, offline_arena,
│   │   │                          #   practice_level
│   └── utils/                     # client_config, user_preferences, region_info
│
├── scenes/                        # .tscn files (mirror scripts/ where it makes sense)
│   ├── entities/                  # BASE scenes: base_enemy, base_projectile,
│   │   │                          #   base_item, player, …  (data-driven)
│   ├── levels/                    # pvp/ hub/ offline/ biomes/ pve/
│   ├── ui/                        # menus/ hud/ dialogs/
│   └── test/                      # net_smoke.tscn etc.
│
├── data/                          # JSON content definitions (the "data" in data-driven)
│   ├── classes/                   # player class definitions
│   ├── enemies/                   # enemy/boss/ai/spawn definitions
│   ├── balance/                   # damage formulas, scaling, caps
│   ├── loot/                      # drop tables, rarity weights
│   ├── items/  spells/  projectiles/
│   ├── world/biomes/              # biome definitions
│   └── schemas/                   # JSON schemas for validation
│
├── assets/
│   ├── sprites/                   # players/ monsters/ projectiles/ effects/
│   │   │                          #   items/ environment/ npcs/
│   ├── ui/
│   └── shaders/
│
├── bin/                           # built GDExtension (omega_client_ext.gdextension)
└── tests/
```

> **Status — restructure complete.** The client now uses the
> `core/ data/ factories/ entities/ systems/ network/ ui/ levels/ utils/` script layout and the
> `entities/ levels/ ui/ test/` scene layout above; `data/` carries `classes/ config/ monsters/
> balance/ loot/ items/ spells/ projectiles/ world/ schemas/ definitions/`. A few **intentional
> deviations** from the idealized tree:
> - **HUD scenes:** the in-game HUD is `scenes/ui/hud/game_hud.tscn` composing one editable scene per
>   widget (`health_bar`, `mana_bar`, `stamina_bar`, `ability_bar`, `experience_bar`, `minimap`,
>   `kill_feed`, `leaderboard`, `server_status`, `death_screen`, `pause_menu`, `settings_menu`,
>   `connection_lost_overlay`); levels instantiate it instead of building the HUD in GDScript. The
>   minimap renders the level terrain once into `scenes/ui/hud/world_map_view.tscn`. `scenes/ui/inventory/`
>   holds unwired scaffolds (`inventory_panel`, `equipment_panel`, `item_slot`, `item_tooltip`).
>   `damage_numbers.tscn` from the GDD list is still the `effects/damage_number.gd` path (a documented
>   next step), and `base_world.tscn` for the biomes is not built yet.
> - `autoload/auth_manager.gd` keeps its name (the `AuthManager` autoload singleton is referenced
>   everywhere; renaming the singleton was deemed not worth the churn). `event_bus.gd` is added as
>   the `EventBus` autoload.
> - Monster/enemy content data lives under `data/monsters/` (not `data/enemies/`).
> - `scripts/server/` (the retired GDScript server) was **deleted** — see
>   [`../server/legacy-parity.md`](../server/legacy-parity.md), not the top of this doc.
> - Class scope: all seven classes are defined, but only Warrior/Rogue/Mage are playable
>   (`PacketTypes.PLAYABLE_CLASSES`); the other four are deferred, not removed.

---

## `api/` — Go backend

```
api/
├── cmd/                # entrypoints: server, gen_ticket_key, seed_test_user
├── internal/
│   ├── auth/           # JWT auth, session tickets
│   ├── handlers/       # HTTP handlers (auth, character, leaderboard, region, ticket, …)
│   ├── models/
│   ├── database/       # PostgreSQL access
│   ├── redis/
│   ├── progression/
│   ├── middleware/
│   ├── content/        # TARGET: content/definition serving (CMS backend)
│   └── admin/          # TARGET: admin handlers
├── migrations/
├── config/  pkg/  bin/
└── go.mod / go.sum
```

Owns **only** account / character / leaderboard / progression persistence. All gameplay state is
server-authoritative and in-memory in `omega-server`.

---

## `web/` — Astro SSR site + dashboard

```
web/
├── astro.config.mjs · package.json · tsconfig.json
├── src/                # pages, components, dashboard (+ future content-editor pages)
├── public/
└── docs/               # web-specific docs (e.g. GO_API_CONTRACT.md)
```

---

## `deployment/` — native systemd deploy (ADR 0007, no Docker)

```
deployment/
├── systemd/                         # unit files
├── server_config.arena.json         # per-instance config (Arena udp/8081)
├── server_config.sanctuary.json     #   (Sanctuary udp/8082)
├── env/                             # env templates
├── provision_server.sh              # one-time bootstrap
├── server_update.sh                 # git-pull rebuild deploy
├── server_sync.sh                   # restart without rebuild
├── harden_vps.sh                    # firewall / fail2ban / SSH
├── Caddyfile · setup_tls.sh         # HTTPS/TLS
└── DEPLOYMENT.md
```

---

## `docs/` — system of record

```
docs/
├── index.md            # full doc catalogue + verification status
├── CONTEXT.md          # glossary (Tick ≠ Frame ≠ Snapshot)
├── ARCHITECTURE.md
├── gdd/                # DESIGN source of truth
│   ├── index.md        # the GDD
│   ├── folder-structure.md   # ← THIS FILE (canonical repo map)
│   ├── world/biomes/   # BIOMES.md, world/biome design
│   ├── classes/        # player class designs
│   ├── MONSTERS.md
│   ├── progression/
│   ├── game-modes
│   └── loot
├── server/             # the Rust server (design.md, contract.md)
├── netcode/            # latency budget, prediction, interpolation, AoI, broadcast
├── systems/            # gameplay systems (status-tagged)
├── design/             # art / style guides
├── adr/                # architecture decision records
├── api/                # Go API reference
├── ops/                # operations
└── references/
```

---

## Conventions

- **Absolute `res://` paths** in the Godot project; absolute filesystem paths in tooling/docs.
- Prefer `class_name` references. If a script must be preloaded because Godot can't resolve a global
  class during headless startup, name the const exactly like the class:
  `const Projectile := preload(".../projectile.gd")` — no parallel `FooScript` aliases.
- Sim semantics in `rust/sim_core` mirror Godot exactly (see
  [`docs/server/contract.md`](../server/contract.md) §numerics) — keep the client's
  prediction/factory math aligned with the authoritative Rust sim.
- Scenes and their scripts mirror each other: `scenes/entities/enemies/base_enemy.tscn` ↔
  `scripts/entities/enemies/base_enemy.gd`.
