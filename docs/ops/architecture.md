# Omega Realm — System Architecture & POC Success Criteria

**Status:** Active (post-Rust-port; rewritten from the Nov 2024 pre-Rust draft).
**Technology stack:** Godot 4.6 client · Rust `omega-server` (ENet/UDP) · Go API (PostgreSQL + Redis) · web/CMS.

---

> **This is the top-level architecture map.** It describes *what the system is made of and how the
> pieces talk*. For the deep dives, follow the links:
>
> - **The game server** — [`../server/design.md`](../server/design.md) (architecture & rationale)
>   and [`../server/contract.md`](../server/contract.md) (the wire/API contract, as built). These
>   two are the system of record for the server; this file defers to them.
> - **Netcode analyses** — [`../netcode/`](../netcode/) (latency budget, prediction, interpolation,
>   AoI, broadcast). Concepts apply; WebSocket-era file:line cites describe the retired GDScript
>   server.
> - **Numbers** — performance targets vs. measured reality:
>   [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md).
> - **Glossary** — [`../CONTEXT.md`](../CONTEXT.md). Use the exact terms (Tick ≠ Frame ≠ Snapshot).
> - **Repo layout** — [`../gdd/folder-structure.md`](../gdd/folder-structure.md) (canonical tree).
>
> **When this file and the code disagree, the code wins.** The authoritative server is the Rust
> `omega-server` binary over **ENet/UDP**; the legacy Godot headless / WebSocket server is **retired
> and being deleted** (the client refuses server mode).

---

## Table of Contents

1. [POC Goals & Success Criteria](#poc-goals--success-criteria)
2. [System Architecture Overview](#system-architecture-overview)
3. [The Game Server (Rust `omega-server`)](#the-game-server-rust-omega-server)
4. [Transport & Wire Protocol](#transport--wire-protocol)
5. [Shared Simulation (`sim_core`)](#shared-simulation-sim_core)
6. [Authority Model: the client requests, the server decides](#authority-model-the-client-requests-the-server-decides)
7. [Persistence & the Go API](#persistence--the-go-api)
8. [Progression & Classes](#progression--classes)
9. [Bandwidth & CPU Optimization Strategies](#bandwidth--cpu-optimization-strategies)
10. [Deployment](#deployment)
11. [Benchmarking Methodology](#benchmarking-methodology)
12. [Vision: Sharding & Multi-Region (Phase 3 — not built)](#vision-sharding--multi-region-phase-3--not-built)

---

## POC Goals & Success Criteria

### Purpose Statement

This project is a **Proof-of-Concept** built to stress-test low-level netcode for MMO scale. The
gameplay is intentionally minimal (one shooting ability + Class abilities, HP/MP only, one monster
type) so the **network** is the thing under test, not game complexity.

**Primary Goal:** prove that a single authoritative server (one `omega-server` process = one
instance) can hold **500–1000 concurrent players** while staying playable.

**End Vision:** carry the learnings into a production MMO with maximum player density per server,
minimizing infrastructure cost while keeping gameplay responsive.

### Success Criteria

These are the **POC targets**. The binding constraint is **bandwidth, not CPU** — the
single-threaded 30 Hz tick is ample for the target, so per-player bytes are the number that gates
player count. Targets vs. measured reality (and the load-test methodology behind them) are
reconciled in [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md).

| Metric | Target | Measurement |
|---|---|---|
| **Concurrent players** | 500–1000 per instance | ENet bot swarm (`rust/load_test/`) |
| **Server tick rate** | **30 Hz** held under full load | tick-time metric on `/metrics` |
| **Per-player bandwidth (down)** | < 2 KB/s average (≤ ~5 KB/s combat spikes) | per-peer snapshot byte counters |
| **Latency (p95)** | < 150 ms same-region | ENet-native RTT |
| **CPU per player** | < 0.5 % per player | server profiling |
| **Memory per player** | < 5 MB per player | heap monitoring |
| **Correction-snap rate** | low / stable | the live divergence signal on `/metrics` |

> The old draft listed a contradictory mix (a "≥20 Hz" gate in one table, "30 FPS" elsewhere; 2 KB/s
> in one place, 3–5 KB/s in another). The server ticks at a fixed **30 Hz** (`sim_core` is stepped at
> `dt = 1/30`); the single bandwidth target is **< 2 KB/s average per player** with combat headroom.
> This table is the reconciled set.

### Stress-Test Scenarios

1. **Baseline (idle):** all players connected, stationary — connection overhead.
2. **Movement storm:** everyone moving — position-update throughput.
3. **Combat load:** full arena combat with projectiles — event broadcasting + AoI.
4. **Peak chaos:** max monsters + everyone in combat — worst case.

### Why Simplified Gameplay

Minimal game design keeps networking the bottleneck (not game logic), reduces variables when
diagnosing perf, enables rapid protocol iteration, and keeps results portable to richer MMO features
later.

---

## System Architecture Overview

Four components, one monorepo (canonical tree:
[`../gdd/folder-structure.md`](../gdd/folder-structure.md)):

```
                 login / account / character / ticket / leaderboard (HTTPS REST)
   ┌────────────────┐ ─────────────────────────────────────────────▶ ┌────────────────┐
   │  Godot Client  │                                                  │    Go API      │ ◀─▶ PostgreSQL
   │   (4.6)        │                                                  │  (:8080 tcp)   │ ◀─▶ Redis
   │                │ ◀──────── session ticket (Ed25519, short-lived) ─│                │
   │ render /       │                                                  └────────────────┘
   │ predict /      │                                                       ▲
   │ interpolate    │                  region heartbeat / hydrate /         │
   └────────────────┘                  persist character (HTTPS REST)       │
          │                                                                 │
          │  realtime game traffic (ENet / UDP, 3 channels)                 │
          ▼                                                                 │
   ┌────────────────────────────────────────────────────────────────┐      │
   │  Rust omega-server  (one process = one instance)                │ ─────┘
   │  single-threaded synchronous 30 Hz tick over rusty_enet =0.4.0  │
   │  Arena (:8081 udp, metrics :9100) · Sanctuary (:8082 udp, :9101)│
   │  links protocol + sim_core directly; all game state in-memory   │
   └────────────────────────────────────────────────────────────────┘
```

- **Godot client** — rendering, client-side prediction (Local player only), interpolation, input,
  UI. Talks to the Go API over **HTTPS** and to the game server over **ENet/UDP**. It loads
  `sim_core` + `protocol` as a **GDExtension** (`client_ext`) so prediction runs the *same compiled
  code* the server runs.
- **Rust `omega-server`** — the **only** authoritative server: inputs, movement, combat, monster AI,
  visibility/AoI, replication, snapshots, lag compensation, validation, the tick loop. All gameplay
  state is **in-memory and server-authoritative**.
- **Go API** (`api/`) — accounts, login (JWT), character metadata, the leaderboard, region
  coordination, and session-ticket minting. Owns **all durable state** (PostgreSQL + Redis).
- **Web / CMS** — admin + leaderboard surfaces over the same Go API HTTP surface
  ([`../api/web-api.md`](../api/web-api.md)).

Communication protocols, at a glance:

| Edge | Protocol |
|---|---|
| Client ↔ game server | **ENet over UDP** (3 channels; *not* WebSocket, *not* Godot High-Level Multiplayer) |
| Client ↔ Go API | HTTPS REST (JSON) |
| Game server → Go API | HTTPS REST (region heartbeat, character hydrate/persist) |
| Go API ↔ database | native PostgreSQL protocol + Redis |

---

## The Game Server (Rust `omega-server`)

One `omega-server` process **is a single instance** — one tick loop, one ENet host, one world. It
is single-threaded and synchronous at a fixed **30 Hz**. Entities live in plain typed collections
keyed by id range; **no ECS, no parallelism** — Rust single-threaded is ample for the target, and
parallelism stays a *measured* optimization, not a starting assumption (the binding constraint is
bandwidth).

**Entity id ranges (invariant):**

| Kind | Protocol kind tag | Id range |
|---|---|---|
| Player | 0 | 1–999 |
| Projectile | 1 | 10000–29999 |
| Monster | 2 | 30000–39999 |
| World-effect entity (healthorbs, ability effects) | 3 | 40000–49999 |

**Per tick** (`rust/server/src/world.rs` drives it): drain `host.service()` → decode and route
(`rust/protocol/`) → apply inputs → step players through `sim_core::step_player` → monster AI
(`rust/server/src/monster.rs`) → record monster position history (lag-comp ring, ≥ 6 ticks) →
projectile + collision pass (`rust/server/src/projectile.rs`, `combat.rs`) → deaths / respawns /
leaderboard → build per-peer snapshots (AoI grid + hysteresis, per-peer delta cache, byte budget —
`rust/server/src/broadcast.rs`) → send confirms + events (`outbox.rs`) → `host.flush()` → sleep the
remainder in short slices that keep ENet acks timely. Infrequent side I/O (Go API heartbeat,
character persistence — `api_client.rs`, `progression_client.rs`) runs on a **separate thread** over
`std::sync::mpsc`, never blocking the tick.

The live deployment runs **two** instances as separate systemd units: **Arena** (`:8081`, monsters +
PvP) and **Sanctuary** (`:8082`, the safe hub). One crash never touches the other. Observability:
structured `tracing` logs + a Prometheus `/metrics` endpoint per instance (tick time, players,
bandwidth, snapshot bytes, **correction-snap rate**).

> The Godot **headless server is retired** — `client/scripts/server/*.gd` no longer runs (the
> NetworkManager refuses server mode) and is being deleted. Treat it as parity ground-truth only;
> do **not** cite it as live code.

---

## Transport & Wire Protocol

UDP via the **ENet protocol** ([ADR 0003](../adr/0003-enet-udp-transport.md)). The Godot client uses
its **native low-level ENet API** (`ENetConnection` + `ENetPacketPeer`); the server uses the
pure-Rust **`rusty_enet`** (pinned `=0.4.0`), wire-compatible with Godot's ENet. This is deliberately
*not* Godot High-Level Multiplayer / `MultiplayerSynchronizer` / `ENetMultiplayerPeer` and *not*
WebSocket — per-message reliability is the whole point of leaving TCP.

**Three channels**, each matched to its traffic:

| Channel | ENet mode | Carries | Why |
|---|---|---|---|
| 0 | unreliable **sequenced** | snapshots, action confirms | newest wins; a dropped snapshot is superseded, never retransmitted or head-of-line-blocking |
| 1 | **reliable** ordered | auth result, game events, baselines, metrics; client one-shots | discrete messages that must arrive exactly once, in order |
| 2 | unreliable sequenced | player input | the client replays unacked inputs anyway, so loss self-heals |

ENet's **native keepalive / RTT / timeout replaces the old application heartbeat**; the clock-sync
payload interpolation needs (`server_ms`) rides **every snapshot** instead.

**Wire format** (full spec: [`../server/contract.md`](../server/contract.md), built per
[ADR 0004](../adr/0004-schema-driven-wire-protocol.md)): a hand-rolled bit-packed `protocol` crate
(`rust/protocol/`), shared by client and server (no codegen). Every packet is `[u8 type][payload]` —
**no length field** (ENet preserves datagram boundaries) — all multi-byte integers little-endian.
`PROTOCOL_VERSION = 4`; a mismatch is refused at the handshake.

**Quantization** (numerics policy, [`../server/contract.md`](../server/contract.md#numerics-policy-sim_core--protocol)):

- positions / velocities ×10, **truncate toward zero**, clamp to `i16`;
- angles ×100, same rule;
- resources (stamina / mana, colors) ×255, **round half away from zero**, clamp to `u8`.

Keep every ch0 datagram **< 1200 B** (unreliable > MTU silently upgrades to reliable-fragmented); the
per-peer byte budget (256 B floor / 1200 B cap) enforces this for deltas. Baselines are
budget-exempt and ride **ch1 reliable** explicitly (must-arrive, acked, fragmentation is fine there).

---

## Shared Simulation (`sim_core`)

Movement (state machine + mover), arena geometry, collision, dash/charge, knockback, stamina, the
hit predicates, and progression math are written **once** in `rust/sim_core/` — which depends on
nothing network- or Godot-related, so it stays unit-testable. The server links it directly; the Godot
client loads the **same compiled crate as a GDExtension** (`client_ext`, exposing `ProtocolCodec`,
`PredictionSim`, `SimHit`) and calls it for **prediction**.

Because both sides run *literally the same code*, movement prediction **cannot diverge from authority
on the math** — the only corrections left are real ones (server-only events the client hadn't seen,
e.g. an unacked knockback), surfaced as the correction-snap signal on `/metrics`. The cost is a
native module shipped per platform (win/mac/linux), folded into the export pipeline.
`sim_core` semantics mirror Godot exactly (f32 `Vec2`, f64 scalars, truncate-toward-zero
quantization) — see contract §numerics before touching the math.

---

## Authority Model: the client requests, the server decides

The governing rule everywhere is **"the client requests, the server decides."** All gameplay state
is server-authoritative and in-memory.

**Hit authority is a two-netcode model**
([`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md)):

| Interaction | Authority | Notes |
|---|---|---|
| **monster → player** | **client-authoritative + server-validated** | RotMG dodge-feel: the client reports its own hits (`LocalHitReport`); the server plausibility-gates them. |
| **PvP** and **player → monster** | **server-authoritative + lag-compensated** | 8-tick position history; the server re-decides on rewound positions. |

The hit predicates live in `sim_core` (shared exactly by both sides). Under permadeath, a
never-report exploit would become risk-free farming, so a **lenient server backstop is ON**: if a
monster bullet's authoritative path *blatantly* overlaps a player and no `LocalHitReport` arrives in
the grace window, the server applies the hit. **The backstop must stay lenient / blatant-overlap-only
— true 24 u overlap, grace ≥ 15 ticks**; a tight backstop re-decides hits on authoritative positions
and reintroduces the phantom-hit feel the split exists to prevent.

> The GDD's blanket "PvE is client-authoritative" line is **wrong / over-simplified**: only the
> *monster → player* direction is client-authoritative-pending-validation; *player → monster* is
> server-authoritative and lag-compensated. The doc that says otherwise should be corrected to match
> this table.

**Auth** is a **locally-verified session ticket**: the client fetches a short-lived **Ed25519** ticket
from the Go API over HTTPS, then presents it in `ConnectAuth` over ENet. The server verifies the
signature **locally** (holds only the public key, `OMEGA_TICKET_PUBKEY`) — no per-join API round-trip,
so an API hiccup can't block a spawn surge. **Dev / POC default is `--allow-unsigned-tickets`** (an
empty ticket is accepted, a placeholder `character_id` assigned); a non-empty but malformed ticket is
always refused (no silent unsigned downgrade). Minting is implemented at `POST /api/character/ticket`
(`api/internal/auth/ticket.go`); the *client* fetch flow is the remaining piece, so player-facing
deploys still run unsigned until it lands.

---

## Persistence & the Go API

Durable state lives **behind the Go API** (PostgreSQL); the sim hydrates only the living character's
combat-relevant subset on join and treats **death — not logout — as the first-class save**
([ADR 0005](../adr/0005-permadeath-persistence-model.md)). Three state lifetimes (canonical in
[`../CONTEXT.md`](../CONTEXT.md)):

| Lifetime | Examples | Lives in | Survives death? |
|---|---|---|---|
| **Account-scoped durable** | bank, Glory, unlocked classes | Go API / Postgres | Yes |
| **Character-scoped durable** | level, raised stats, carried inventory | Go API / Postgres (hydrated on join) | No — destroyed on death |
| **Session-ephemeral** | HP / MP, position, cooldowns | in-memory in the sim | n/a — reset on entry |

The exploit permadeath must defeat is **disconnect-to-dodge-death**: when HP reaches 0 in the
authoritative tick, the server **synchronously and transactionally** deletes the character + its
inventory, credits account Glory, and leaves the bank untouched — *before any client action can
intervene*. Writes are idempotent absolute-state; the Go API enforces a **single active session per
account** and owns **atomic** bank↔character transfers (letting two languages race those
transactions is the surest way to manufacture dupes).

---

## Progression & Classes

Progression is **server/API-authoritative**
([ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md),
[`../systems/PROGRESSION.md`](../systems/PROGRESSION.md)). The server owns each player's `level`,
`experience`, and `total_lifetime_XP`: it hydrates them on join, applies the level curve and
per-level stats (HP / move speed / damage scale; **max level 50**) in the authoritative tick, and
pushes a display-only `PROGRESS` event to the client. When a character ends (Hardcore death or
voluntary Sacrifice), the server converts lifetime XP to account **Glory** as
`floor(total_lifetime_XP / 100)` in one atomic Go API transaction, on the same disconnect-immune path
death uses.

**Classes** (the `class` byte on the wire): `0 Zealot, 1 VoidHunter, 2 Engineer, 3 PlagueSeer,
4 Warrior, 5 Rogue, 6 Mage`. Only **Warrior / Rogue / Mage** are in pre-alpha scope (the others are
deferred). All Class abilities resolve damage/spawns **server-side**; only **Warrior Charge** and
**Rogue Shadowstep**'s blink are *predicted movement* (shared `sim_core`). The RMB ability costs
**Mana**. See [`../systems/abilities.md`](../systems/abilities.md).

---

## Bandwidth & CPU Optimization Strategies

The primary lever: **reduce bytes per player to host the most players on the least hardware.**
Bandwidth is the binding constraint, so this is where the design spends its effort.

**Bandwidth (implemented):**

1. **Binary bit-packing** — the `protocol` crate packs entity records bit-tight (typed ids,
   2-bit kind + offset; 3-bit anim; 16-bit flags); no JSON, no length fields.
2. **Quantization** — positions/velocities to `i16` at 0.1-unit precision; angles ×100; resources to
   `u8`. (See [transport](#transport--wire-protocol).)
3. **Interest management (AoI)** — only entities inside a player's Area of Interest are sent, via an
   AoI grid with hysteresis (`rust/server/src/broadcast.rs`,
   [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md)).
4. **Delta compression** — per-peer delta caches send only changed fields against an **acked
   baseline** (5-bit per-entity change mask); periodic baselines (100-tick interval, 30-tick resend).
5. **Per-peer byte budget** — a greedy priority scheduler clamps each peer's snapshot to 256..1200 B,
   keeping ch0 datagrams under MTU; baselines are budget-exempt and ride ch1 reliable.

**CPU:** secondary, by design. The single-threaded 30 Hz tick clears the target with headroom;
distance-based AI/processing culling and monster position-history rings keep per-entity cost flat.
Parallelism stays a *measured* optimization. Detailed budgets and measured numbers:
[`../netcode/performance-budgets.md`](../netcode/performance-budgets.md).

---

## Deployment

**Native systemd on a single droplet — no Docker** ([ADR 0007](../adr/0007-native-systemd-deployment.md)).
Three units, deployed by **git-pull-and-rebuild**:

| Unit | Port | Metrics |
|---|---|---|
| `omega-api` | `:8080` tcp | — |
| `omega-arena` | `:8081` udp | `:9100` (localhost only) |
| `omega-sanctuary` | `:8082` udp | `:9101` (localhost only) |

Postgres and Redis run locally on the same droplet. Prometheus exporters bind localhost and are
**not** opened in the firewall (scrape over an SSH tunnel / private network). The full runbook —
provision, deploy, sync, operate, rollback — is in
[`../../deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md):

```bash
./scripts/deploy.sh provision   # one-time: Go/Rust/Postgres/Redis + systemd units + swap
./scripts/deploy.sh             # git pull master → rebuild → restart api + arena + sanctuary
./scripts/deploy.sh sync        # build-free: pull master + restart + health-check
./scripts/deploy.sh status|health|logs|restart
```

**Local stack** (Postgres/Redis already running, e.g. DBngin):

```bash
./scripts/dev_local.sh          # Go API + Arena (udp/8081) + Sanctuary (udp/8082)
# then run the client from the Godot editor (F5) or: godot --path client
```

Build scripts: `build_client.sh`, `build_client_ext.sh` (Rust GDExtension → `client/bin/`),
`build_server.sh`, `build_api.sh`.

---

## Benchmarking Methodology

**Load generation.** The `omega-load-test` bot swarm (`rust/load_test/`, see its README) — ENet bots
that link `protocol` + `sim_core` directly (replacing the retired Python harness). Run against a
local Arena or a live one:

```bash
./scripts/run_load_test.sh --scenario baseline                              # local Arena
OMEGA_SERVER=<droplet-ip>:8081 ./scripts/run_load_test.sh --scenario baseline   # live Arena
```

Scale in steps (100 → 250 → 500 → 750 → 1000 bots) and watch:

- **Server-side** (`/metrics`): tick time, players, packets/bytes per second, snapshot bytes,
  **correction-snap rate**, memory.
- **Network:** RTT distribution (ENet-native), packet loss, per-player bandwidth (up/down).
- **Client-side (bots):** time to receive snapshots, input-to-confirm latency, desync detection.

Reconciled targets per scenario live in
[`../netcode/performance-budgets.md`](../netcode/performance-budgets.md); end-to-end smoke is
`scenes/test/net_smoke.tscn` (exits 0 on PASS).

---

## Vision: Sharding & Multi-Region (Phase 3 — not built)

> **Everything below is forward-looking and NOT implemented.** Today the system is **one droplet, two
> instances** (Arena + Sanctuary), single region. The pieces here are the *intended* scale-out path;
> none of it ships in the POC. Cross-reference [`infrastructure.md`](infrastructure.md) (Phase 3).

The scale-out story rests on the fact that **one `omega-server` process is already a self-contained
instance** with no shared state — horizontal scale is "run more processes," and the Go API is the
only cross-instance coordination point.

**Zone-based sharding (vision).** Shared hub instances (Sanctuary-like) plus per-zone shards, each
zone fronting a pool of instances; the Go API assigns a joining player to an instance with room (or
spins a new one). Players in different shards still **share leaderboards, trade, and matchmake**
through the API, but **cannot see each other in-game** (no cross-instance entity replication — game
servers never talk to each other directly; coordination is always API-mediated).

**Multi-region (vision).** Singapore primary, then Frankfurt + US-West; geo-routed via the API/DNS;
Postgres primary-with-replicas and a global Redis layer for leaderboards. Player state stays
**ephemeral and region-local**; only durable character/account data and leaderboards replicate.

**Orchestration (vision).** Multi-region scale-out may reintroduce containers under an orchestrator
(Kubernetes / Nomad) on its own merits — that does **not** change the single-box, no-Docker POC model
([ADR 0007](../adr/0007-native-systemd-deployment.md)) that ships today.

---

## See also

- [`../server/design.md`](../server/design.md) · [`../server/contract.md`](../server/contract.md) —
  the server (system of record).
- [`infrastructure.md`](infrastructure.md) — hosting tiers, cost phases, the Phase-3 vision in detail.
- [`../api/web-api.md`](../api/web-api.md) — the Go API HTTP surface.
- [`../netcode/`](../netcode/) · [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md)
  — netcode analyses + reconciled numbers.
- [`../gdd/folder-structure.md`](../gdd/folder-structure.md) — canonical repo tree (replaces the old
  in-file folder dump).
- [`../gdd/index.md`](../gdd/index.md) — the game design doc (replaces the deleted `specification.md`).
- ADRs: [0002](../adr/0002-authoritative-server-fixed-tick.md) ·
  [0003](../adr/0003-enet-udp-transport.md) · [0004](../adr/0004-schema-driven-wire-protocol.md) ·
  [0005](../adr/0005-permadeath-persistence-model.md) ·
  [0006](../adr/0006-softcore-hardcore-glory-economy.md) ·
  [0007](../adr/0007-native-systemd-deployment.md).
