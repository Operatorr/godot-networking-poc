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
