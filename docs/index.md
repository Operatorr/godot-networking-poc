# Documentation index

The system of record for the Omega Realm networking POC. Start at [`../AGENTS.md`](../AGENTS.md)
for the map; this page is the **catalogue** with verification status. Terms are defined in
[`CONTEXT.md`](CONTEXT.md) — use them.

**Status tags** (also shown in each doc's header):

| Tag | Meaning |
|---|---|
| **Implemented** | Built and matches the doc. |
| **Partial** | Built, but with documented gaps/bugs (the doc says which). |
| **Planned** | Designed/agreed, not built. |
| **Vision** | Aspirational (the future MMO); not part of the POC. |
| **Reference** | Numbers/decisions/background, not a system. |
| **Active** | A live exec-plan being worked. |

## The Rust server port (current core — start here)

| Doc | Status | What it answers |
|---|---|---|
| [`rust-port/README.md`](rust-port/README.md) | Implemented | **Port status** — what was built, how it was verified, deliberate deviations. |
| [`rust-port/migration-spec.md`](rust-port/migration-spec.md) | Implemented | The full decision log D1–D14 (transport, protocol, sim parity, persistence, deploy, cutover). |
| [`rust-port/contract.md`](rust-port/contract.md) | Implemented | Crate APIs, ENet channel plan, the bit-packed wire format, numerics policy — as built. |
| [`rust-port/extraction/`](rust-port/extraction/) | Reference | Behavioral port-notes extracted from the GDScript (`file:line` cited) — the parity ground truth. |

## The performance investigation (pre-port; concepts stand, GDScript cites are historical)

| Doc | Status | What it answers |
|---|---|---|
| [`netcode/latency-budget.md`](netcode/latency-budget.md) | Verified | Why it feels sluggish on localhost — every ms accounted, `file:line`. |
| [`netcode/smoothness-render.md`](netcode/smoothness-render.md) | Verified · fix Planned | The "30 fps at 100 fps" stutter — root cause + the decisive fix. |
| [`netcode/perf-notes/tick-rate-30-vs-60.md`](netcode/perf-notes/tick-rate-30-vs-60.md) | Reference · results PENDING | The gated 30-vs-60 Hz tick trial — protocol + empty results table (#8). |
| [`exec-plans/active/netcode-perf-fixes.md`](exec-plans/active/netcode-perf-fixes.md) | Active | The prioritized fix roadmap (P0→P3); #7–#15 done 2026-06-04. |

## Netcode (the core of the project)

| Doc | Status | Topic |
|---|---|---|
| [`netcode/overview.md`](netcode/overview.md) | Implemented | Authority model, the three loops, the packet map. |
| [`netcode/hit-authority-model.md`](netcode/hit-authority-model.md) | Partial | **Two netcodes:** client-authoritative PvE/monster hits (RotMG) vs server-authoritative PvP — the per-owner authority split and its anti-cheat intent. |
| [`netcode/client-prediction.md`](netcode/client-prediction.md) | Partial | Local-player prediction & reconciliation (+ double-movement bug). |
| [`netcode/interpolation.md`](netcode/interpolation.md) | Partial | Remote-entity interpolation & the **adaptive** (jitter-driven, 1–3 tick) Render delay. |
| [`netcode/server-tick-broadcast.md`](netcode/server-tick-broadcast.md) | Implemented | 30 Hz tick + 30 Hz snapshot, shared-grid AoI, delta, bandwidth-budget scheduler, baseline acks. |
| [`netcode/transport-websocket.md`](netcode/transport-websocket.md) | Superseded | WebSocket-over-TCP + transport seam; head-of-line blocking. Retired with the Rust port — live transport is ENet/UDP (ADR 0003, `rust-port/contract.md`). |
| [`netcode/interest-mgmt-aoi.md`](netcode/interest-mgmt-aoi.md) | Implemented | AoI 700/800 + shared spatial grid, LOD, byte-budget deferral, surfaced diagnostics. |
| [`netcode/wire-protocol.md`](netcode/wire-protocol.md) | Implemented | Binary packet formats, quantization, u16 entity_count, `BASELINE_ACK`, auth budget. |
| [`netcode/performance-budgets.md`](netcode/performance-budgets.md) | Reference | Targets vs measured, with the gap and the doc-drift. |

## Gameplay systems (status-tagged; thin by design — this is a minimal POC)

| Doc | Status | Topic |
|---|---|---|
| [`systems/players-movement.md`](systems/players-movement.md) | Partial | Player entity, movement, validation (+ double-movement bug home). |
| [`systems/players-movement-state-machine.md`](systems/players-movement-state-machine.md) | Implemented | 7-state server-authoritative movement SM: dash, sprint, knockback, stun, stamina, mana. |
| [`systems/combat-hits.md`](systems/combat-hits.md) | Implemented | Shooting, projectiles, lag-compensated swept PvP + PvE hits, cosmetic shoot feedback. |
| [`systems/abilities.md`](systems/abilities.md) | Implemented | The RMB Class-ability system: input flag + cursor, server dispatch, Mana/cooldown, world-effect entities, `ABILITY_EFFECT` (protocol v4). |
| [`classes/index.md`](classes/index.md) | Implemented | The seven Classes: base stats, per-level scaling, and each Class's RMB ability (mirrors `client/data/classes/`). |
| [`systems/monsters-ai.md`](systems/monsters-ai.md) | Implemented | The Toxic Slime and its server-side AI state machine. |
| [`systems/PROGRESSION.md`](systems/PROGRESSION.md) | Implemented | Experience & levels: server/API-authoritative; per-level stat scaling; XP→Glory; max level 50. |
| [`systems/bot-ai.md`](systems/bot-ai.md) | Retired | Python bot-swarm tactical AI (removed); live harness is `rust/load_test/` (simplified strategy port). |
| [`systems/monster-architecture.md`](systems/monster-architecture.md) | Implemented · roadmap Planned | Monster factory, data-driven definitions, schema, and the add-a-monster pipeline. |
| [`systems/audio.md`](systems/audio.md) | Implemented | AudioManager + procedurally-generated sound (no audio assets). |
| [`systems/ui-hud.md`](systems/ui-hud.md) | Implemented | HUD components, menus, effects, scene flow. |
| [`systems/state-machines.md`](systems/state-machines.md) | Implemented | Player-life, movement, scene, connection, and AI state machines. |
| [`systems/offline-modes.md`](systems/offline-modes.md) | Implemented | Practice & Offline Sandbox — client-authoritative test scenes (no server) on a shared `OfflineArena`. |
| [`systems/arena-visuals.md`](systems/arena-visuals.md) | Implemented | Generated class/monster/projectile spritesheets (PixelLab), `SheetLibrary` loader, arena props, class identity on the wire (protocol v3), random bot classes. |
| [`design/sanctuary-layout.md`](design/sanctuary-layout.md) | Implemented | The Sanctuary city hub: vast walled city with enterable buildings, oblique (Hammerwatch-style) placeholder rendering, city plan + coordinates, NPC roster, reusable Portal, asset-replacement guide. |
| [`design/SANCTUARY_STYLEGUIDE.md`](design/SANCTUARY_STYLEGUIDE.md) | Reference | Town/Sanctuary biome art direction: palette, tiles, props, VFX, HUD. |

## Decisions & background

| Doc | Status | Topic |
|---|---|---|
| [`adr/0001-websocket-tcp-transport.md`](adr/0001-websocket-tcp-transport.md) | Accepted | Why WebSocket-over-TCP (and the HOL trade-off). |
| [`adr/0002-authoritative-server-fixed-tick.md`](adr/0002-authoritative-server-fixed-tick.md) | Accepted | Why a single authoritative server at a fixed 30 Hz tick. |
| [`adr/0003-enet-udp-transport.md`](adr/0003-enet-udp-transport.md) | Implemented | ENet-over-UDP datagram transport (supersedes 0001's substrate) — shipped with the Rust port. |
| [`adr/0004-schema-driven-wire-protocol.md`](adr/0004-schema-driven-wire-protocol.md) | Implemented | Redesigned wire protocol as a shared Rust crate (no codegen); **amends 0003**'s "wire format unchanged". |
| [`adr/0005-permadeath-persistence-model.md`](adr/0005-permadeath-persistence-model.md) | Accepted | Permadeath persistence — death is the server-authoritative transactional save; item integrity via the Go API. |
| [`adr/0006-softcore-hardcore-glory-economy.md`](adr/0006-softcore-hardcore-glory-economy.md) | Accepted | Softcore/Hardcore modes, XP→Glory exchange, and server-authoritative progression — **extends 0005** (D15). |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Reference | Top-level system architecture & POC success criteria. |
| [`specification.md`](specification.md) | Reference | Game design spec / GDD (the minimal bullet-hell design). |
| [`INFRASTRUCTURE.md`](INFRASTRUCTURE.md) | Reference | Deployment / infra (Docker, DigitalOcean). |
| [`CONTEXT.md`](CONTEXT.md) | Reference | Glossary — the project's canonical language. |

## Legacy / superseded (kept for history — do not treat as current)

| Doc | Note |
|---|---|
| [`DESYNC_PLAN.md`](DESYNC_PLAN.md) | Legacy desync root-causes; fixes A/B/C shipped (see roadmap "Already done"). |
| [`../plans/NETWORK_PERFORMANCE_UPGRADES.md`](../plans/NETWORK_PERFORMANCE_UPGRADES.md) | Detailed 6-phase plan; the roadmap supersedes it as the *entry point*. |
| [`../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md) | Parallel engineering-budget plan; same. |
| [`../plans/RECOMMENDATIONS.md`](../plans/RECOMMENDATIONS.md) | Earlier recommendations. |
| [`harness-engineering-codex-agent-first-world.md`](harness-engineering-codex-agent-first-world.md) | The harness guide this doc structure follows. |

## Conventions

- Every netcode/system doc ends with **The eight questions** (client / server / predicted /
  replicated / persisted / validated / can-fail / tested) so coverage is checkable.
- Numbers are cited to `file:line`. When code and a doc disagree, **the code wins** — fix the
  doc (or open a roadmap item if the code is wrong).
- This index and the cross-links are validated by a link-check; keep them resolving.
