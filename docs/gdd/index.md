# Game Design Document — Omega Realm

**Version:** 4.0 (post-Rust-port canonical)

**Date:** June 2026

**Project Type:** 3/4 top-down 2D multiplayer bullet-hell shooter roguelite

**Architecture:** Authoritative Rust game server (ENet/UDP) + Go persistence API + Godot 4.6 client

---

This is the canonical game-design document. It owns the **what** (overview, modes, world, classes,
HUD, progression, permadeath). The **how** (wire protocol, server architecture, numerics) lives in
the server docs — this GDD links there rather than restating it.

- Server architecture & rationale: [`../server/design.md`](../server/design.md)
- Wire/API contract as built: [`../server/contract.md`](../server/contract.md)
- Glossary (use these exact terms — Tick ≠ Frame ≠ Snapshot): [`../CONTEXT.md`](../CONTEXT.md)
- Folder structure: [folder-structure.md](folder-structure.md)
- CMS / content tooling: [../CMS.md](../CMS.md)
- Web/API surface (auth, characters, leaderboard, regions): [../api/web-api.md](../api/web-api.md)

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Game World](#game-world)
3. [Classes](#classes)
4. [HUD](#hud)
5. [Action-bar](#action-bar)
6. [Monsters](#monsters)
7. [Bots](#bots)
8. [Difficulty](#difficulty)
9. [Progression](#progression)
10. [Permadeath & Glory](#permadeath--glory)
11. [Technology Stack](#technology-stack)
12. [Network Architecture](#network-architecture)
13. [Data-Driven Content](#data-driven-content)

---

## Project Overview

### Game Features

- **Genre:** Top-down 2D bullet-hell shooter
- **Style:** Fantasy with spells and character classes
- **Multiplayer:** Authoritative-server architecture (the Rust `omega-server` is the only authority)
- **Core Modes:**
  - **PvE (primary):** Bullet-hell combat roguelite.
    - In Hardcore, dying awards **Glory**.
    - Glory is the meta-progression currency: spend it to permanently boost health, unlock new
      weapons, purchase passive buffs, or unlock skill-tree points — making subsequent runs more
      forgiving.

    ```text
    award floor(lifetime XP / divisor)

    GloryXPDivisor = 100

    // GloryFor returns the Glory awarded when a character at (level, experience) dies
    // (hardcore) or is sacrificed (softcore): floor(TotalLifetimeXP / GloryXPDivisor).
    func GloryFor(level, experience int) int64 {
        return TotalLifetimeXP(level, experience) / int64(GloryXPDivisor)
    }
    ```

  - **PvP:** Competitive arena battles.
  - **Tournament:** Scheduled competitive events.
  - **Cutthroat Races:** PoE-style leveling races with PvP enabled. Every player starts a fresh
    reset (à la *Rust*) at level 1 and simultaneously ventures into the world to level up while
    fighting each other (PvPvE).
- **Progression:**
  - Fast leveling to the max level cap (50). See [Progression](#progression) for formulas and the
    detailed tables under [progression/](progression/).
  - Permadeath in Hardcore; Softcore characters must voluntarily **sacrifice** in the Sanctum to
    gain Glory.
  - Permanent stat potions for character power growth.
  - Gear-focused endgame.
- **Key Features:**
  - Multiple character classes.
  - Permadeath mechanics.
  - Persistent character progression (account/character state owned by the Go API).
  - Competitive leaderboards.

---

## Game World

### The Sanctuary

The Sanctuary (also called **The Sanctum** in the CMS) is the town — a shared, multiplayer hub
instance with PvP turned off. It runs as its own server instance (the **Sanctuary** instance, ENet
UDP `8082`). In town, players can:

- Access their banks
- Spend Glory to upgrade their account
- Visit vendors and talk to NPCs
- Buy and sell equipment
- Trade and interact with other players
- Enter portals to the **Arena** (the PvP/combat instance, ENet UDP `8081`) or out into the open
  world

### Open World

From the Sanctuary the player takes one of three portals out to the open-world shards:

- **Mainland** (Tier 1–4)
  - Forest / Meadows (Tier 1)
  - Beach (Tier 1)
  - Dark Forest / Deep Forest / Dense Forest (Tier 2)
  - Reef (Tier 3)
  - Mountains (Tier 3)
  - Ocean (Tier 4)
  - Unholy / Infected (Outside) (Tier 4)
- **Underworld** (Tier 3–7)
  - Rocks (Tier 3)
  - Scorched Ground (Tier 4)
  - Mountain (Tier 4)
  - Lava (Tier 5)
  - Purgatory (Tier 6)
  - Hell (Tier 7)
- **The Creators Realm** (Tier 4–7)
  - Grass (Tier 4)
  - Cloud (Tier 5)
  - Platform (Tier 5)
  - Construct (Tier 6)
  - Void (Tier 7)
  - Higher Construct (Tier 7)

Mainland should be **one shard**: if a large open world is feasible, all biomes live in a single
scene/level; otherwise each biome breaks out into its own shard/scene. **Underworld** is a second
shard and **The Creators Realm** a third. One open-world boss exists per biome.

See [BIOMES.md](BIOMES.md) for the biome reference.

### Dungeons

Each biome has one dungeon with a boss. Dungeons are **procedurally generated** so the layout is
unique every run.

### Loot Table (TBD)

A loot table is needed; each item carries a minimum Tier requirement matching the monster tier it
drops from. Some items also carry a biome requirement (can only drop in that biome). Loot is mostly
equippable by all classes, with some class restrictions. Some items grant spells or abilities that
the player can equip in an action-bar / ability slot.

---

## Classes

In-scope classes (pre-alpha):

- **Warrior**
- **Rogue**
- **Mage**

Deferred classes (designed, not yet in scope):

- **Zealot**
- **VoidHunter**
- **Engineer**
- **PlagueSeer**

The class is part of a character's identity and rides the wire as the protocol `class` byte:
`0=Zealot, 1=VoidHunter, 2=Engineer, 3=PlagueSeer, 4=Warrior, 5=Rogue, 6=Mage` (see
[`../server/contract.md`](../server/contract.md) §ConnectAuth). Each class's RMB ability is detailed
in [classes/](classes/).

---

## HUD

The HUD shows:

- **HP Bar**
- **Mana Bar** (used for spells and class abilities)
- **Energy Bar** (used for sprinting)
- **EXP Bar**

---

## Action-bar

- **SPACE** — Dash
- **RMB** — Class-unique ability (costs Mana)
- **Slot 1**
- **Slot 2**
- **Slot 3**
- **Slot 4**

Ability slots 1–4 are for abilities received from Glory unlocks, items, or the skill-tree.

> **Predicted vs. server-decided abilities:** only **Warrior Charge** and **Rogue Shadowstep**
> (blink) are predicted *movement* — the client extension simulates them locally and the server
> reconciles. All other RMB abilities and all ability *damage* are decided server-side; the client
> request (RMB ability-held flag + cursor) is advisory, per "the client requests, the server
> decides." See [`../systems/abilities.md`](../systems/abilities.md).

---

## Monsters

See [MONSTERS.md](MONSTERS.md).

---

## Bots

Bots are used for load testing. The PvP bot AI is strong and challenging, and **must be preserved**:
extract it into a design pattern whose parts can be reused for Monster AI and tuned for difficulty.

The load-test bot swarm lives in `rust/load_test/` (the `omega-load-test` binary) — ENet bots that
link the `protocol` and `sim_core` crates directly. See its README for scenarios and flags.

---

## Difficulty

Difficulty does not come from Monster Level alone — it also comes from **Monster AI**. A monster can
be high level but have tuned-down AI (easy to beat), while a low-level monster can have highly tuned
AI. Higher-tuned AI makes a monster:

- Move more to avoid your projectiles
- Aim better to hit you
- React faster (lower reaction-time latency)

---

## Progression

Progression is **server/API-authoritative** (since protocol v4). The Rust server hydrates a
character's level/XP on join from the Go API, runs leveling during play, and pushes the
authoritative level/XP/move-speed to the client via the `PROGRESS` game event; the API owns the
durable record. See [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md),
[`../server/contract.md`](../server/contract.md) §GameEvent, and
[ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md).

**Max level: 50.**

### EXP formulas

```text
# Monster EXP
MonsterEXP(level) = round(100 × 1.15^(level - 1))

# EXP required to level
EXPRequired(level):
  Level 1     = 5  × MonsterEXP(1)
  Levels 2–49 = 10 × MonsterEXP(level)
  Level 50    = 0   (max level)
```

Detailed tables and the contribution model live under [progression/](progression/):

- [progression/EXP_player_table.md](progression/EXP_player_table.md) — per-level XP requirements
- [progression/EXP_monster_table.md](progression/EXP_monster_table.md) — monster XP by level
- [progression/EXP_contribution.md](progression/EXP_contribution.md) — encounter-based EXP
  eligibility (radius, recent-contribution window, minimum contribution share)

---

## Permadeath & Glory

- **Hardcore:** permadeath. On death the character is gone and the account is awarded **Glory**.
- **Softcore:** the character does not die on defeat; to gain Glory the player must voluntarily
  **sacrifice** the character in the Sanctum.

In both cases the Glory award is `floor(TotalLifetimeXP / GloryXPDivisor)` with
`GloryXPDivisor = 100` (see [Project Overview](#project-overview)). Glory funds permanent
meta-progression: health, weapon unlocks, passive buffs, skill-tree points. The Glory economy is
defined in [ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md); persistence (Glory balance,
characters, leaderboard) is owned by the Go API ([../api/web-api.md](../api/web-api.md)).

---

## Technology Stack

> Authoritative as built. Code wins over any older description.

### Game server (the core)

- **`omega-server`** — Rust binary in `rust/server/`. **The only authoritative server.** One process
  = one instance. Single-threaded, **synchronous 30 Hz tick** owning the ENet host and the whole
  world. (The legacy GDScript headless server is retired — the client refuses server mode — and is
  being removed; do not treat `client/scripts/server/*.gd` as live code.)
- **Transport:** ENet over UDP via `rusty_enet` (pinned `=0.4.0`). Native ENet keepalive/RTT
  replaced the old app heartbeat; `server_ms` rides every snapshot for clock sync.
- **Shared simulation:** `rust/sim_core/` (movement state machine, mover, arena geometry, hit
  predicates, progression math) — no Godot/net deps. The Godot client runs the **same** compiled
  crate through the `client_ext` GDExtension (`ProtocolCodec` / `PredictionSim` / `SimHit`), so
  client prediction cannot diverge from the server by construction.
- **Wire format:** hand-rolled bit-packed protocol crate `rust/protocol/`, `[u8 type][payload]`, no
  length field (ENet preserves datagram boundaries), little-endian, `PROTOCOL_VERSION = 7`. As-built
  spec: [`../server/contract.md`](../server/contract.md).
- **Auth:** Ed25519 session ticket minted by the Go API, verified locally by the server. Dev default
  is `--allow-unsigned-tickets`.
- **Observability:** Prometheus exporter per instance.

### Client

- **Engine:** Godot 4.6 — **client only** (the project no longer exports a server).
- **Languages:** GDScript (client glue/UI) + Rust (the shared sim via the GDExtension).
- **Rendering:** 2D sprite-based.

### Backend services (persistence)

- **API server:** Go (`api/`) — JWT auth, characters, leaderboard, regions, Glory; mints the
  Ed25519 game-connect ticket. Owns **all** durable state.
- **Database:** PostgreSQL.
- **Cache:** Redis (leaderboards, active sessions, region heartbeat TTL).
- **Authentication:** JWT (web/API) → Ed25519 ticket (game connect).

### DevOps

- **Version control:** Git.
- **Deployment:** **native systemd on one droplet — no Docker** ([ADR 0007](../adr/0007-native-systemd-deployment.md)).
  - `omega-api` — `:8080/tcp`
  - `omega-arena` — `:8081/udp` (metrics `:9100`)
  - `omega-sanctuary` — `:8082/udp` (metrics `:9101`)
  - Deploy is git-pull-and-rebuild via `scripts/deploy.sh`.
- **Monitoring:** Prometheus + Grafana.

---

## Network Architecture

> Authoritative as built. Governing rule everywhere: **the client requests, the server decides.**

### Client-Server model

- The Rust `omega-server` is the **sole authority**. All gameplay state is server-authoritative and
  held in memory; only account/character/leaderboard/Glory state is persisted (by the Go API).
- The client **predicts** local movement using the shared `sim_core` crate and **reconciles**
  against server snapshots. It interpolates remote entities.
- Transport is **ENet/UDP**, not Godot High-Level Multiplayer. There is no
  `MultiplayerSynchronizer`, `ENetMultiplayerPeer`, or WebSocket in the live path.

### Channels (3)

| Channel | Mode | Carries |
|---|---|---|
| **ch0** `CH_SNAPSHOT` | unreliable **sequenced** | delta snapshots, action confirms |
| **ch1** `CH_RELIABLE` | reliable ordered | auth, game events, server metrics, baseline snapshots (S→C); connect-auth, baseline-ack, full-state/respawn requests, local hit report (C→S) |
| **ch2** `CH_INPUT` | unreliable **sequenced** | player input |

Full wire detail (snapshot/delta encoding, typed entity ids, quantization, byte budgets) is in
[`../server/contract.md`](../server/contract.md).

### Two-netcode hit model

The hit authority depends on **who is hitting whom**:

- **Monster → player:** **client-authoritative + server-validated** (RotMG dodge-feel). The client
  reports the hit on its own entity (`LocalHitReport`); the server validates plausibility and applies
  a **lenient blatant-overlap-only backstop** (true 24-unit overlap only, grace ≥ 15 ticks) so
  cheating is caught without punishing honest dodges.
- **PvP and player → monster:** **server-authoritative + lag-compensated** (8-tick monster position
  history / rewind).

This replaces the older blanket "PvE is client-authoritative" claim — it was wrong/nuanced. PvE is
*not* uniformly client-authoritative; only the **monster→player damage** leg is client-driven, and
even that is server-validated with a backstop.

### Server validates

- All combat outcomes (player→monster and PvP damage, healing, deaths)
- Movement (anti-cheat thresholds against predicted positions)
- Item generation and drops
- Experience, level-ups, and Glory (progression is server/API-authoritative)
- Ability usage, cooldowns, and all ability damage
- Permadeath / respawn triggers
- Pickups (e.g. Healthorbs)

### Client handles

- Input gathering (sent on ch2)
- Client-side prediction of local movement (and the two predicted-movement abilities) with server
  reconciliation
- Reporting monster→player hits on its own entity (`LocalHitReport`, server-validated)
- Interpolation of remote entities
- Visual effects, animations, audio, and UI

---

## Data-Driven Content

Game content (enemies, items, spells, projectiles) is defined in data (JSON / the CMS database)
rather than per-entity scene files, so balance and reskins can change without a client rebuild.

**Free without recompiling (pure parameter changes):**

- A reskin of an existing enemy with different HP/speed/damage
- A projectile spell described by `{damage, speed, radius, lifetime, pierce}`
- Balance tuning, drop tables, spawn weights

**Requires a recompile + deploy (genuinely new behavior):**

- A boss that splits into 3 on death
- A spell that teleports you or reflects bullets
- Any new verb the simulation doesn't already understand

> The authoritative simulation is the Rust `sim_core` crate — data-driven values feed it, but new
> *verbs* (new movement/collision/hit behavior) are code changes there, mirrored in the Godot client
> via the GDExtension. Content tooling (the CMS) and the publish flow are documented in
> [../CMS.md](../CMS.md); the HTTP/JSON surface that backs it is in [../api/web-api.md](../api/web-api.md).
