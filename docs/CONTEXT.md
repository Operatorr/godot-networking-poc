# Omega Realm — Context Glossary

The shared language of this project. When code, docs, or conversation use a term that maps to
an entry below, use the canonical word — not the listed alternatives. This file is a glossary
only: no implementation details, no numbers, no design decisions. Those live in `docs/netcode/`
and `docs/systems/`.

## Product & world

**Omega Realm**:
The product this repository is building toward — a production MMO. This repo is the networking
proof-of-concept that de-risks it.
_Avoid_: "the game" (ambiguous between POC and MMO).

**POC**:
This repository — a deliberately-minimal bullet-hell shooter whose purpose is to prove the
netcode can scale, not to be a finished game.

**Arena**:
The single shared combat map where all play happens. There is exactly one.
_Avoid_: level, world, zone, map.

## World structure & navigation

**Plane**:
One of the three top-level world groupings — Mainland, Underworld, and Creator's Realm. Each Plane
contains multiple Biomes spanning a progression tier range.
_Avoid_: dimension, realm (reserve for the product name "Omega Realm"), world (that's a playable Instance).

**Biome**:
The environmental theme of a World — determines monster roster, visual style, and tier. Each Biome
belongs to exactly one Plane. Canonical Biome IDs are in `docs/systems/MONSTERS.md`.
_Avoid_: zone, region, area.

**World**:
A playable Instance of a specific Biome. Players enter via a Portal from the Sanctuary. Worlds may
spawn Rifts. Multiple World Instances of the same Biome can run concurrently within a Shard.
_Avoid_: level, map, arena (that's the single POC combat map), realm.

**Shard**:
A server node that hosts a bounded set of World and Dungeon Instances with a shared player cap. The
Sanctuary lobby selects a Shard for the player before they enter a World.
_Avoid_: server, node, cluster, instance (a Shard contains Instances, it is not one).

**Portal**:
An in-world object a player walks through to transition between Instances — entering Worlds, Dungeons,
the Arena, or returning to the Sanctuary. Passing through a Portal is a persistence checkpoint.
_Avoid_: gateway, door, teleporter.

**Rift**:
A dungeon Portal that spawns dynamically inside a World. Taking a Rift transports the player into a
themed Dungeon Instance matched to the host Biome.
_Avoid_: portal (Rift is a specific kind of Portal), dungeon entrance.

**Dungeon**:
A themed Instance accessed via a Rift. Shorter and more intense than a World; themed to the Biome in
which its Rift spawned.
_Avoid_: raid, level, instance (too generic).

## Time & cadence (these three are distinct — most confusion lives here)

**Tick**:
One step of the server's authoritative simulation. The whole game advances one Tick at a time.
_Avoid_: update, step, frame.

**Frame**:
One client render/draw. Frames happen far more often than Ticks; a client may draw many Frames
between two Ticks.
_Avoid_: tick (when you mean a render frame).

**Snapshot**:
One network broadcast of world state from server to a client (a `STATE_UPDATE` packet). The
Snapshot cadence is independent of the Tick cadence.
_Avoid_: update, state sync, packet (when you specifically mean a Snapshot).

**Render delay**:
The amount of server time into the past at which a client draws *remote* entities, so it always
has a newer Snapshot to interpolate toward. A deliberate latency traded for smoothness.
_Avoid_: interpolation lag, buffer delay, smoothing delay.

## Entities & ownership

**Local player**:
The player-controlled character on this client. Predicted locally; the client owns its motion
between server corrections.
_Avoid_: my player, own player, hero.

**Remote entity**:
Any other player, monster, or projectile — everything not the Local player. Rendered by
interpolation from Snapshots, never predicted.
_Avoid_: other player (too narrow — also covers monsters/projectiles).

**Ghost**:
A Local player that is mistakenly rendered as a Remote entity because the client never learned
its own entity id. A specific failure mode, not a feature.
_Avoid_: phantom, double, clone.

**Authority sync**:
The moment a client learns its own entity id (via `PLAYER_INFO`) and switches its character from
"awaiting identity" to predicted-and-owned.
_Avoid_: handshake (that's the auth/login step), spawn.

## Networking concepts (as this project uses them)

**Authoritative server**:
The single source of truth for all gameplay. Clients send intent; the server decides outcomes.
The governing rule is "the client requests, the server decides."
_Avoid_: host, master.

**Prediction**:
The client simulating the Local player's own input immediately, before the server confirms, so
movement feels instant.
_Avoid_: client-side movement, extrapolation (that's a different thing).

**Reconciliation**:
Correcting the predicted Local player to the server's authoritative position, replaying any
inputs the server hasn't acknowledged yet.
_Avoid_: rollback, resync, correction (too vague).

**Interpolation**:
Drawing a Remote entity by blending between two buffered Snapshots. Distinct from Prediction
(which is for the Local player only).

**Baseline**:
A full-state Snapshot a client is brought up to, against which subsequent delta Snapshots are
diffed.
_Avoid_: keyframe, full sync.

**AoI** (Area of Interest):
The region around a player within which Remote entities are sent to that player. Entities
outside it are culled from that player's Snapshots.
_Avoid_: view radius, visibility range, interest radius (use AoI).

**Game event**:
A discrete, one-shot authoritative occurrence broadcast to clients (damage, kill, shot fired,
respawn) — a `GAME_EVENT` packet. Distinct from a Snapshot, which is continuous state.
_Avoid_: message, notification.

**Lag compensation**:
The server rewinding entity positions to the Tick the shooter actually saw, so a well-aimed shot
hits despite latency.
_Avoid_: hit rewind, favor-the-shooter (that's the policy, not the mechanism).

## Progression & persistence (Vision — but the Rust port builds the service boundary now)

These describe the future Realm-of-the-Mad-God-like MMO the POC de-risks. POC gameplay is HP-only, but
the Rust server port designs its Go-API persistence boundary around these terms, so they are canonical.
See the [Rust port migration spec](rust-port/migration-spec.md) D10 and
[ADR 0005](adr/0005-permadeath-persistence-model.md).

**Account-scoped state**:
Durable state that belongs to the *account* and survives character death — the bank, glory, unlocked
classes, currency. Lives behind the Go API; never enters the combat sim.
_Avoid_: account data, profile (too vague), save file.

**Character-scoped state**:
Durable state that belongs to one *character* and persists across logout/login while it lives — level,
the potion-raised stats, carried inventory. Hydrated into the sim on join; **destroyed on death**.
_Avoid_: player state (ambiguous with the live entity), character save.

**Session-ephemeral state**:
State that exists only for one play session and is never persisted — current HP/MP, position, active
cooldowns. Born in the sim, reset on every entry.
_Avoid_: runtime state, temporary state.

**Permadeath**:
The rule that a character's death is permanent: the character and its carried inventory
(Character-scoped state) are destroyed, while the Account-scoped state survives.
_Avoid_: death (which is also the in-Tick HP→0 event; permadeath is the persistence consequence).

**Bank**:
The account-owned, cross-character item store. Account-scoped; mutated only at a bank chest in the
Sanctuary, through the Go API, never inside the combat sim.
_Avoid_: vault, stash, chest, storage.

**Glory**:
The account-scoped progression score credited when a character dies. Survives permadeath.
_Avoid_: score (reserve for the in-session leaderboard), XP (that's Character-scoped).

**Sanctuary**:
The safe hub Instance where players manage Account-scoped state — no combat. Contains the Bank,
Vendors, and Class Trainers. Portals in the Sanctuary lead to Worlds and the Arena; Portals in Worlds
and Dungeons return to the Sanctuary.
_Avoid_: lobby, town, hub, nexus (use Sanctuary).

**Vendor**:
An NPC in the Sanctuary who buys and sells equipment in exchange for currency.
_Avoid_: merchant, trader, shopkeeper.

**Class Trainer**:
An NPC in the Sanctuary who teaches a character new spells for its class.
_Avoid_: trainer, teacher, instructor.

**Instance**:
One running copy of a World, Dungeon, Arena, or Sanctuary. Stateless-on-entry; transitions between
Instances through a Portal double as persistence checkpoints.
_Avoid_: room, session, level.
