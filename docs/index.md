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
| **TBD / Unbuilt** | Design-directional spec; no code yet (the doc says so). |
| **Retired** | Superseded; kept as a thin redirect stub or for history. |

## The game server (current core — start here)

| Doc | Status | What it answers |
|---|---|---|
| [`server/README.md`](server/README.md) | Implemented | Index + the crate map — what each `rust/` crate is. |
| [`server/design.md`](server/design.md) | Implemented | Architecture & rationale: topology, transport, shared sim, tick, auth, persistence, hits, progression, deploy. |
| [`server/contract.md`](server/contract.md) | Implemented | Crate APIs, ENet channel plan, the bit-packed wire format, numerics policy — as built. **The wire-format system of record.** |

## Game design (the GDD — design intent; thin/minimal where the POC is)

| Doc | Status | What it answers |
|---|---|---|
| [`gdd/index.md`](gdd/index.md) | Reference | The canonical Game Design Document (v4.0, post-Rust-port): the bullet-hell roguelite design, modes, classes, progression, world. |
| [`gdd/folder-structure.md`](gdd/folder-structure.md) | Planned | Target canonical repo map (post-Rust, data-driven); supersedes the old monolithic GDD's folder section. Marks which paths don't yet exist. |
| [`gdd/game-modes.md`](gdd/game-modes.md) | Partial | The modes (Arena/Sanctuary/etc.) wrapping the shared core loop — who can hurt whom, what resets, what's at stake. Says where unbuilt. |
| [`gdd/classes/index.md`](gdd/classes/index.md) | Implemented (scope-limited) | The seven Classes: base stats, per-level scaling, each Class's RMB ability (mirrors `client/data/classes/`). Pre-alpha limits live to Warrior/Rogue/Mage. |
| [`gdd/classes/warrior.md`](gdd/classes/warrior.md) | Implemented | Warrior — stats + RMB ability. |
| [`gdd/classes/rogue.md`](gdd/classes/rogue.md) | Implemented | Rogue — stats + RMB ability. |
| [`gdd/classes/mage.md`](gdd/classes/mage.md) | Implemented | Mage — stats + RMB ability. |
| [`gdd/classes/zealot.md`](gdd/classes/zealot.md) | Implemented (disabled pre-alpha) | Zealot — stats + RMB ability. |
| [`gdd/classes/engineer.md`](gdd/classes/engineer.md) | Implemented (disabled pre-alpha) | Engineer — stats + RMB ability. |
| [`gdd/classes/void_hunter.md`](gdd/classes/void_hunter.md) | Implemented (disabled pre-alpha) | Void Hunter — stats + RMB ability. |
| [`gdd/classes/plague_seer.md`](gdd/classes/plague_seer.md) | Implemented (disabled pre-alpha) | Plague Seer — stats + RMB ability. |
| [`gdd/MONSTERS.md`](gdd/MONSTERS.md) | Planned | The 95-monster biome roster (19 biomes × 4 regulars + 1 boss): schema-friendly entries (id, faction, archetype, tier, level, ai_profile, signature_ability). |
| [`gdd/BIOMES.md`](gdd/BIOMES.md) | Planned | The world's three realms and their biomes by tier. |
| [`gdd/loot.md`](gdd/loot.md) | TBD / Unbuilt | Intended loot-table design. **No loot/item/inventory system exists** — only health orbs on monster kill. Spec to build against. |
| [`gdd/progression/EXP_player_table.md`](gdd/progression/EXP_player_table.md) | Reference | Player XP-to-next-level table + the level curve equation (max level 50). |
| [`gdd/progression/EXP_monster_table.md`](gdd/progression/EXP_monster_table.md) | Reference | Monster EXP-reward table + equation (`round(100 × 1.15^(lvl-1))`). |
| [`gdd/progression/EXP_contribution.md`](gdd/progression/EXP_contribution.md) | Reference | How EXP is split — encounter participation, not pure damage/proximity. |

## The web API & player website (Go backend + Astro front)

| Doc | Status | What it answers |
|---|---|---|
| [`api/web-api.md`](api/web-api.md) | Implemented | The HTTP/JSON API reference for web/CMS consumers (Astro on Vercel): base URLs + TLS, JWT auth & refresh, register/login/character/regions/leaderboard endpoints, data models, server-only endpoints, SSR + httpOnly-cookie integration. |
| [`CMS.md`](CMS.md) | Partial | The player website/dashboard (AS BUILT — Astro `web/` over the Go API) **vs** the content-CMS (enemy/item/spell editors, balance dashboard — ASPIRATIONAL, not built). |

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
| [`netcode/interest-mgmt-aoi.md`](netcode/interest-mgmt-aoi.md) | Implemented | AoI 700/800 + shared spatial grid, LOD, byte-budget deferral, surfaced diagnostics. |
| [`netcode/performance-budgets.md`](netcode/performance-budgets.md) | Reference | Targets vs measured, with the gap and the doc-drift. |
| [`netcode/wire-protocol.md`](netcode/wire-protocol.md) | Retired (redirect) | Thin stub → [`server/contract.md`](server/contract.md). The old GDScript byte format is gone; link contract.md directly. |
| [`netcode/transport-websocket.md`](netcode/transport-websocket.md) | Retired (redirect) | Thin stub → [`server/contract.md`](server/contract.md) (live transport is ENet/UDP, [ADR 0003](adr/0003-enet-udp-transport.md)); HOL analysis in [ADR 0001](adr/0001-websocket-tcp-transport.md). |

## Gameplay systems (status-tagged; thin by design — this is a minimal POC)

| Doc | Status | Topic |
|---|---|---|
| [`systems/players-movement.md`](systems/players-movement.md) | Partial | Player entity, movement, validation (+ double-movement bug home). |
| [`systems/players-movement-state-machine.md`](systems/players-movement-state-machine.md) | Implemented | 7-state server-authoritative movement SM: dash, sprint, knockback, stun, stamina, mana. |
| [`systems/combat-hits.md`](systems/combat-hits.md) | Implemented | Shooting, projectiles, lag-compensated swept PvP + PvE hits, cosmetic shoot feedback. |
| [`systems/abilities.md`](systems/abilities.md) | Implemented | The RMB Class-ability system: input flag + cursor, server dispatch, Mana/cooldown, world-effect entities, `ABILITY_EFFECT` (protocol v4). |
| [`systems/monsters-ai.md`](systems/monsters-ai.md) | Implemented | The Toxic Slime and its server-side AI state machine. |
| [`systems/monster-architecture.md`](systems/monster-architecture.md) | Implemented · roadmap Planned | Monster factory, data-driven definitions, schema, and the add-a-monster pipeline. |
| [`systems/PROGRESSION.md`](systems/PROGRESSION.md) | Implemented | Experience & levels: server/API-authoritative; per-level stat scaling; XP→Glory; max level 50. |
| [`systems/audio.md`](systems/audio.md) | Implemented | AudioManager + procedurally-generated sound (no audio assets). |
| [`systems/ui-hud.md`](systems/ui-hud.md) | Implemented | HUD components, menus, effects, scene flow. |
| [`systems/state-machines.md`](systems/state-machines.md) | Implemented | Player-life, movement, scene, connection, and AI state machines. |
| [`systems/offline-modes.md`](systems/offline-modes.md) | Implemented | Practice & Offline Sandbox — client-authoritative test scenes (no server) on a shared `OfflineArena`. |
| [`systems/arena-visuals.md`](systems/arena-visuals.md) | Implemented | Generated class/monster/projectile spritesheets (PixelLab), `SheetLibrary` loader, arena props, class identity on the wire (protocol v3), random bot classes. |
| [`systems/bot-ai.md`](systems/bot-ai.md) | Retired | Python bot-swarm tactical AI (removed); live harness is `rust/load_test/` (simplified strategy port). |
| [`client/error-codes.md`](client/error-codes.md) | Implemented | Catalogue of user-facing client error codes (e.g. `(Error 47)` = API TLS handshake failure). |

## Art & design direction

| Doc | Status | Topic |
|---|---|---|
| [`design/BASE_DESIGN_GUIDE.md`](design/BASE_DESIGN_GUIDE.md) | Reference | The grimdark-fantasy / cosmic-horror tone & world bible. |
| [`design/STYLEGUIDE.md`](design/STYLEGUIDE.md) | Reference | The global pixel-art style guide / sprite prompt library. |
| [`design/MEADOWS_STYLEGUIDE.md`](design/MEADOWS_STYLEGUIDE.md) | Reference | Meadows biome art direction: bright, peaceful early-game palette/props/VFX. |
| [`design/SANCTUARY_STYLEGUIDE.md`](design/SANCTUARY_STYLEGUIDE.md) | Reference | Town/Sanctuary biome art direction: palette, tiles, props, VFX, HUD. |
| [`design/sanctuary-layout.md`](design/sanctuary-layout.md) | Implemented | The Sanctuary city hub: vast walled city with enterable buildings, oblique (Hammerwatch-style) placeholder rendering, city plan + coordinates, NPC roster, reusable Portal, asset-replacement guide. |

## Decisions (ADRs)

| Doc | Status | Topic |
|---|---|---|
| [`adr/0001-websocket-tcp-transport.md`](adr/0001-websocket-tcp-transport.md) | Accepted (superseded by 0003) | Why WebSocket-over-TCP (and the HOL trade-off). Substrate retired; HOL analysis preserved. |
| [`adr/0002-authoritative-server-fixed-tick.md`](adr/0002-authoritative-server-fixed-tick.md) | Accepted | Why a single authoritative server at a fixed 30 Hz tick. |
| [`adr/0003-enet-udp-transport.md`](adr/0003-enet-udp-transport.md) | Implemented | ENet-over-UDP datagram transport (supersedes 0001's substrate) — shipped with the Rust port. |
| [`adr/0004-schema-driven-wire-protocol.md`](adr/0004-schema-driven-wire-protocol.md) | Implemented | Redesigned wire protocol as a shared Rust crate (no codegen); **amends 0003**'s "wire format unchanged". |
| [`adr/0005-permadeath-persistence-model.md`](adr/0005-permadeath-persistence-model.md) | Accepted | Permadeath persistence — death is the server-authoritative transactional save; item integrity via the Go API. |
| [`adr/0006-softcore-hardcore-glory-economy.md`](adr/0006-softcore-hardcore-glory-economy.md) | Accepted | Softcore/Hardcore modes, XP→Glory exchange, and server-authoritative progression — **extends 0005**. |
| [`adr/0007-native-systemd-deployment.md`](adr/0007-native-systemd-deployment.md) | Implemented | Native systemd deploy (drop Docker); git-pull rebuild; Arena+Sanctuary+API as units. |

## Operations & top-level architecture

| Doc | Status | Topic |
|---|---|---|
| [`ops/architecture.md`](ops/architecture.md) | Active | Top-level system architecture (what the pieces are, how they talk) & POC success criteria. Rewritten post-Rust-port. |
| [`ops/infrastructure.md`](ops/infrastructure.md) | Reference | Single-droplet as-built reality (Phase 1) + scaling Vision (Phases 2–3, not built). Native systemd deploy: [ADR 0007](adr/0007-native-systemd-deployment.md) + [`deployment/DEPLOYMENT.md`](../deployment/DEPLOYMENT.md). |
| [`ops/multi-region.md`](ops/multi-region.md) | Implemented mechanism · operator guide | Running game servers in multiple regions (e.g. Frankfurt + Singapore): one global API/DB control plane, per-region UDP game servers + Sanctuary, region select → heartbeat-advertised connect address. |
| [`ops/distribution.md`](ops/distribution.md) | Active · operator guide | Client testing/build/ship: run-from-editor vs export, local/prod API toggle, `build_client.sh` outputs, the M3 signed-ticket player-facing deploy runbook, and the no-automated-distribution gap. |

## Project conventions & reference material

| Doc | Status | Topic |
|---|---|---|
| [`CONTEXT.md`](CONTEXT.md) | Reference | Glossary — the project's canonical language (Tick ≠ Frame ≠ Snapshot). |
| [`changelog.json`](changelog.json) | Reference | Machine-readable per-commit changelog (added/fixed), consumed by the web dashboard. |
| [`references/harness-engineering-codex-agent-first-world.md`](references/harness-engineering-codex-agent-first-world.md) | Reference | The agent-first harness guide this doc structure follows. |

## Deleted / moved (history note)

These no longer exist in `docs/`; pointers for stale links:

| Was | Now |
|---|---|
| `docs/GDD.md` | → [`gdd/index.md`](gdd/index.md) |
| `docs/specification.md` | **Deleted** → see [`gdd/index.md`](gdd/index.md) (the GDD is the design spec). |
| `docs/DESYNC_PLAN.md` | **Deleted** (historical; fixes shipped) → see git history. |
| `docs/ARCHITECTURE.md` | → [`ops/architecture.md`](ops/architecture.md) |
| `docs/INFRASTRUCTURE.md` | → [`ops/infrastructure.md`](ops/infrastructure.md) |
| `docs/api/cms-api.md` | → [`api/web-api.md`](api/web-api.md) |
| `docs/systems/MONSTERS.md` | → [`gdd/MONSTERS.md`](gdd/MONSTERS.md) |
| `docs/classes/*.md` | → [`gdd/classes/`](gdd/classes/index.md) |
| `docs/gdd/EXP_*.md` | → [`gdd/progression/`](gdd/progression/EXP_player_table.md) |

## Conventions

- Every netcode/system doc ends with **The eight questions** (client / server / predicted /
  replicated / persisted / validated / can-fail / tested) so coverage is checkable.
- Numbers are cited to `file:line`. When code and a doc disagree, **the code wins** — fix the
  doc (or open a roadmap item if the code is wrong).
- This index and the cross-links are validated by a link-check; keep them resolving.
- The **wire format** has one system of record: [`server/contract.md`](server/contract.md). Link
  it directly; the `netcode/wire-protocol.md` and `netcode/transport-websocket.md` stubs only
  redirect there.
