# ADR 0002 — Authoritative server, fixed 30 Hz tick

**Status:** Implemented (verified 2026-06-03 against code)

## Decision

One **Authoritative server** (Godot 4.6 headless) per **Arena**, running a **fixed 30 Hz
Tick** simulation. Clients send **input intent only** — never positions, never hit results.
The governing rule is **"the client requests, the server decides"** ([CONTEXT.md](../CONTEXT.md)).

The Tick is driven by a manual accumulator in `Node._process` (not `_physics_process`): the loop
drains `tick_timer` in fixed `1.0 / tick_rate` steps and calls `_process_server_tick()` each step
(`server_main.gd:177-182`). `tick_rate` defaults to 30 (`server_config.gd:9`) and the live config
keeps it at 30 (`client/data/config/server_config.json`). There is no `Engine.max_fps` cap and no
sharding: exactly one Arena exists ([CONTEXT.md](../CONTEXT.md)).

## Context

This is the POC's load-bearing decision; everything else in `docs/netcode/` follows from it.

- **Anti-cheat.** All gameplay state is server-authoritative and in-memory; the server validates
  every action (movement bounds, shoot cooldown, hit resolution). A client that lies about its
  position or kills is ignored — it can only submit intent. The Go API persists accounts only,
  never gameplay ([architecture.md](../ops/architecture.md) success criteria).
- **Determinism.** A single fixed-timestep simulation means one source of truth and reproducible
  Ticks, which is what makes client **Prediction** + **Reconciliation** tractable
  ([client-prediction.md](../netcode/client-prediction.md)) and what the load tests measure
  against.
- **The POC's actual goal.** Prove a single headless server sustains **500–1000 concurrent
  players** in one Arena ([architecture.md](../ops/architecture.md)). Per-server *density* is the
  metric under test, so the architecture deliberately keeps everything on one server rather than
  distributing it — distribution would hide the density ceiling we are trying to find.

## Consequences

| Consequence | Detail | Mitigation |
|---|---|---|
| Every action costs a round-trip | Client sees no result until the server's Snapshot returns; projectiles spawn *only* from server `STATE_UPDATE` (`client_entity_manager.gd:114`). | Client **Prediction** of the Local player hides round-trip on movement; remote motion uses interpolation. Combat is **not** predicted today (no muzzle/impact until the round-trip completes) → [latency-budget.md](../netcode/latency-budget.md). |
| 30 Hz is low for a twitch shooter | One Tick = 33.3 ms; input is sampled and sent at 30 Hz (`prediction.gd:71`). Raising it (→60) doubles client prediction/interp CPU and server tick cost, and lifts per-player bandwidth. | A scale trade-off, intentionally left at 30 to maximise player density. Revisit only if responsiveness, not density, becomes the bottleneck → [performance-budgets.md](../netcode/performance-budgets.md). |
| Single server per Arena | No spatial broad-phase sharing; broadcast is per-player O(players × entities) each Snapshot tick → O(N²) in players. | **Sharding deferred** ([architecture.md](../ops/architecture.md) §Sharding Strategy is Vision, not built). Density is pushed via AoI + delta + the snapshot scheduler instead → [interest-mgmt-aoi.md](../netcode/interest-mgmt-aoi.md). |

**Snapshot rate is decoupled from the Tick rate.** The Tick runs at 30 Hz, but Snapshots fire on
a separate accumulator (`server_main.gd:53-59`, `:157-161`). `snapshot_rate_hz` defaults to 0 →
falls back to the Tick rate, *but* the live config sets it to **20 Hz**
(`client/data/config/server_config.json`), and the JSON wins at runtime. So the shipping server
**Ticks at 30 Hz and Snapshots at 20 Hz (50 ms)** — see Inconsistencies.

## Inconsistencies

- **Snapshot rate doc drift.** Code default (0 → 30 Hz) disagrees with the live config (20 Hz).
  The 20 Hz JSON wins, so the running server snapshots every 50 ms. Several client constants still
  assume 20 Hz Ticks (e.g. `entity_state_buffer.gd:14`, `interpolation_controller.gd:75`) while
  the server Ticks at 30 Hz → micro-stutter until the EMA converges
  ([interpolation.md](../netcode/interpolation.md)).
- **Target drift.** [architecture.md](../ops/architecture.md) lists "≥20 Hz tick" and "2 KB/s"; the
  engineering plan lists 5 KB/s; the code Ticks at 30 Hz. Reconcile in
  [performance-budgets.md](../netcode/performance-budgets.md).

## The eight questions

- **Client:** rendering, input sampling, Local-player Prediction, Remote-entity interpolation.
- **Server:** the entire fixed 30 Hz simulation — movement, combat, AI, validation, broadcast.
- **Predicted:** the Local player only (movement); combat is not predicted.
- **Replicated:** all world state, server → client, via Snapshots and Game events.
- **Persisted:** nothing in the sim — gameplay state is in-memory; only accounts persist (Go API).
- **Validated:** every action — bounds, cooldowns, hits — on the server; clients send intent only.
- **Can fail:** raising the Tick rate trades density for responsiveness; one Arena means an O(N²)
  broadcast ceiling; sharding is not built.
- **Tested:** the `omega-load-test` bot swarm (`rust/load_test/`) drives 50–200+ intent-only
  ENet clients against one server; the server reports 1 Hz `SERVER_METRICS` it aggregates.

## See also

- [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md) — Tick/bandwidth/latency targets vs measured
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — the prioritized fix roadmap that pushes the density ceiling
- [`../netcode/server-tick-broadcast.md`](../netcode/server-tick-broadcast.md) · [`../netcode/client-prediction.md`](../netcode/client-prediction.md) · [`../CONTEXT.md`](../CONTEXT.md)
