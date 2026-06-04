# Server tick loop & snapshot broadcast

**Status:** Implemented (verified 2026-06-04 against code). The former Partial gaps are closed: the
per-player Snapshot build now narrows candidates through a **shared per-tick spatial grid** (#9), the
scheduler's per-tick diagnostics are **surfaced to `ServerMetrics`** and the HUD (#15), each peer has
a **bandwidth-derived byte budget** (#13), and Baselines are **acked** (#14, inert on TCP). What
remains is measurement at the 500–1000-player target, not missing mechanism.

This is the server-side counterpart to [`interpolation.md`](interpolation.md) and
[`client-prediction.md`](client-prediction.md): how the authoritative simulation advances one
**Tick** at a time, and how it turns world state into per-client **Snapshots**.

## The two cadences are decoupled

| Cadence | Rate | Period | Where | Drives |
| --- | --- | --- | --- | --- |
| **Tick** (simulation) | 30 Hz | 33.3 ms | `server_main.gd:178-188` | inputs, movement, AI, collisions, Game events |
| **Snapshot** (`STATE_UPDATE`) | **30 Hz live** | 33.3 ms | `server_main.gd:170`, broadcast gate per tick | replicated entity state to clients |

The Tick rate is `config.tick_rate` = 30 (`server_config.gd:13`, `server_config.json` `tick_rate:30`;
the default now derives from `GameConstants.SERVER_TICK_RATE`, with a `GAME_SERVER_TICK_RATE` env
override). The Snapshot rate is decoupled via a separate accumulator: `ServerConfig`'s *default*
`snapshot_rate_hz` is `0`, which falls back to the Tick rate (`server_config.gd:102-107`) — and the
shipped config file now sets `snapshot_rate_hz = 30` (raised from 20 by #3), so the **live Snapshot
rate is 30 Hz**, matching the Tick. (Several client constants that once assumed 20 Hz are noted in
[`interpolation.md`](interpolation.md); the 30-vs-60 trial is in
[`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md).)

## The tick loop runs in `_process`, not `_physics_process`

The server drives its own fixed Tick from a manual accumulator inside `Node._process`
(`server_main.gd:178-188`), **not** Godot's `_physics_process`:

```gdscript
func _process(delta: float) -> void:
    ...
    tick_timer += delta
    var tick_interval := 1.0 / config.tick_rate
    while tick_timer >= tick_interval:
        tick_timer -= tick_interval
        _process_server_tick()
```

Consequences, all deliberate:

- **Catch-up `while`-loop** (`:180`): if a frame ran long, multiple Ticks fire in one `_process`
  pass to keep wall-clock cadence. No frame is skipped; Ticks can bunch.
- **No `Engine.max_fps` cap.** Headless `_process` is called as fast as the OS schedules it, so on
  a quiet server `_process` fires far more often than 30 Hz and the `while` body simply does
  nothing until `tick_timer` crosses the interval. Burns CPU spinning; a `max_fps` or wait would
  reduce idle load (Planned — not set today).
- Decoupling from `_physics_process` means physics-tick settings (30 Hz) don't gate the loop; the
  loop owns its own clock.

### One Tick, in order

`_process_server_tick()` (`server_main.gd:213-283`) does exactly this, every Tick:

| Step | Call | Line |
| --- | --- | --- |
| advance Snapshot accumulator, set `snapshot_due` | inline | `:217-228` |
| open per-tick batch window | `nm.begin_batch()` | `:236-238` |
| 1. process client inputs (incl. shoot edges) | `_process_client_inputs()` | `:241` |
| 2. update game state (projectiles, spawner, timers) | `_update_game_state()` | `:244` |
| 3. monster AI | `_update_monster_ai()` | `:247` |
| 4. snapshot monster **and player** positions (PvE **and PvP** lag-comp rewind) | `record_position_snapshot()` | `:253-254` |
| 5. collisions / damage / kills | `collision_handler.process_collisions()` | `:257-259` |
| 6. **build shared AoI grid + broadcast Snapshot — only if `snapshot_due`** | `build_aoi_grid()` + `broadcast_state_updates()` | `:262-273` |
| 7. cleanup dead monsters | `cleanup_dead_monsters()` | `:276` |
| flush per-peer batches | `nm.flush_batches()` | `:278-279` |
| record tick time | `record_tick_time()` | `:282-283` |

**Game events** (damage, kill, shot-fired, respawn, `PLAYER_INFO`) are broadcast inline during
steps 1–5 on *every* Tick — only the continuous `STATE_UPDATE` Snapshot is gated by `snapshot_due`.
With the live Snapshot rate now equal to the 30 Hz Tick (#3), positions and events stream at the same
cadence; the gate still exists so a future lower snapshot rate decouples cleanly. Step 4 now snapshots
**player** positions too (`player_manager.record_position_snapshot`) — the history the new PvP
lag-comp rewind (#7) reads (see [`../systems/combat-hits.md`](../systems/combat-hits.md)).

## Per-tick BATCH flush adds up to one tick of queuing

When `packet_batching_enabled` (default true, `server_config.gd:25,79`), the loop opens a batch
window at the top of the Tick and flushes at the bottom (`server_main.gd:226-228,258-259`). Every
`send_to_client` / `broadcast_to_clients` during the Tick is queued per-peer and coalesced into a
single WebSocket BATCH frame at end-of-Tick. This slashes per-frame framing overhead when inputs,
collisions, and a Snapshot all fire together — but it means a message produced early in a Tick
waits until that Tick ends before it leaves the box: **up to ~33 ms of server-side queuing** on
top of transport latency. See [`transport-websocket.md`](transport-websocket.md) for how the
batched frame is then polled and sent over TCP.

## Per-player Snapshot build now uses a shared spatial grid (#9)

`build_aoi_grid()` (`server_broadcast_service.gd:79-107`) runs **once per Snapshot tick**: it
collects every authoritative entity into one list and inserts each into a fresh `SpatialGrid`
(`spatial_grid.gd`, `class_name SpatialGrid`) with cell size `aoi_exit_radius / 4`. `ServerMain`
primes it right before the broadcast (`server_main.gd:269`).

`broadcast_state_updates()` (`server_broadcast_service.gd:112`) then **loops over every authenticated
player** (`:144`) and, for each, queries the shared grid for a candidate band
(`_tick_grid.query_radius(state.position, aoi_exit_radius)`, `:161`) instead of walking all entities,
before running the hysteresis-aware AoI filter + delta + scheduler pass. This turns the former
**O(players × entities)** scan into **O(players × nearby)** — the change that retired this doc's
Partial tag. The radius was also tuned down to 700 enter / 800 exit (#10) so the candidate band is
genuinely small when players cluster. See [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md). (The
projectile/monster *collision* grids in `projectile_manager` are separate and unchanged.)

## Delta compression

Each per-player packet is either a **baseline** (full state) or a **delta**, decided per peer by
its `DeltaStateCache` (`delta_state_cache.gd`).

- **Delta mask** is an 8-bit field (`packet_types.gd:66-70`): `POSITION` (bit 0), `ANIMATION`,
  `FLAGS`, plus `REMOVED` (bit 6) and `FULL_STATE` (bit 7). `calculate_delta_mask`
  (`delta_state_cache.gd:71-104`) diffs current state against the per-peer cache and sets only
  changed bits; an entity whose mask is 0 is skipped entirely (`server_broadcast_service.gd:475-476`).
- Position equality uses a 0.05-unit threshold (`delta_state_cache.gd:109-111`), matching the
  0.1-unit wire quantization. See [`wire-protocol.md`](wire-protocol.md) for byte layout.
- **Forced baseline every 100 Ticks** (`DELTA_FULL_STATE_INTERVAL`, `packet_types.gd:85`;
  `needs_full_state_for_interval`, `delta_state_cache.gd`). At the 30 Hz live Snapshot rate that is one
  full resync per peer every ~3.3 s (the constant's comment now reads "~3.3s at 30Hz").
- **Baseline acks (#14, inert on TCP).** The 100-Tick cadence is now a **floor**, not the only repair:
  the client acks each received full-state Baseline via a `BASELINE_ACK` packet
  (`interpolation_controller.gd:185`), and the server tracks the per-peer acked/pending Baseline
  (`delta_state_cache.gd:44-47,210,218-224`; `server_broadcast_service.gd:446-452`) and **proactively
  resends** on a detected gap rather than waiting out the full interval. On **today's TCP** transport
  this is **inert** — reliable in-order delivery never drops a Baseline — so it is forward-looking for
  the [ADR 0003](../adr/0003-enet-udp-transport.md) ENet/UDP transport. A client can still force a
  resync with `REQUEST_FULL_STATE`.
- Only entries that actually go out update the cache (`update_cache_partial`,
  `server_broadcast_service.gd:533-540`); deferred entities keep their stale cache entry so they
  re-prioritize next tick.
- AoI exits and stale-cache entries are emitted as explicit `REMOVED` deltas so a client never
  strands an entity (`:128-133,504-524`).

## Per-peer byte budget (now bandwidth-derived, #13) + priority scheduler

Each delta packet is sized by a per-peer `SnapshotScheduler` (`snapshot_scheduler.gd`) against that
peer's byte budget. The service-global ceiling is `max_snapshot_bytes` = **1200**
(`server_config.gd:37`), but each peer's effective cap is now **derived from the bandwidth budget it
advertised in `CONNECT_AUTH`** (#13): the client sends a trailing `[u32 bandwidth_budget_bps]`
(`auth_packet.gd:33`), the server clamps it to `[min_client_bandwidth_bps, max_client_bandwidth_bps]`
(defaults 24000 / 200000) and computes
`per_peer_bytes = clamp(budget / snapshot_rate_hz, MIN_SNAPSHOT_FLOOR=256, max_snapshot_bytes)`
(`server_main.gd:700-702`), stored per peer in `server_broadcast_service.gd:300` and read back via
`_budget_for_peer` (`:308`). A peer that advertised nothing falls back to the global 1200. This is the
**per-second** ceiling the old budget lacked: a marginal connection now gets fewer bytes per Snapshot,
not just per packet. The scheduler scores every candidate:

```
priority = importance(type) + ticks_since_last_sent − distance_penalty(lod) + change_bonus(mask)
```

(`snapshot_scheduler.gd:117-155`). Numbers:

| Term | Values | Source |
| --- | --- | --- |
| importance | player 10, projectile 8, monster 4, default 1 | `:20-23,129-134` |
| distance_penalty (LOD) | NEAR 0, MID 4, FAR 8 | `:26,137-140` |
| change_bonus | full/removed 6; else +2 per changed field | `:143-155` |
| `ticks_since_last_sent` | raw add — starved entities climb until they win | `:124` |

`schedule()` (`:87-107`) sorts by priority, then greedily admits candidates while
`bytes + encoded_size <= max_bytes`. **Pinned** candidates (removals, AoI exits, cache cleanup)
bypass the budget entirely (`:99`) so a despawn is never dropped. Anything that doesn't fit is
**deferred** — it isn't sent this Snapshot, accrues `ticks_since_last_sent`, and bubbles up next
time. Net effect: under budget pressure, far/low-priority entities update at a *fraction* of the
Snapshot rate rather than being lost. Encoded sizes are predicted by
`encoded_size_for_mask` (`:161-173`) mirroring the wire encoder, so no speculative encode is
needed.

> **Baselines have no byte budget.** A full-state packet (`_create_full_state_packet`,
> `server_broadcast_service.gd:480`) emits *every* visible entity with no scheduler and no
> 1200-byte cap. The old hard 255-entity ceiling is **gone** — `entity_count` is now a `u16`
> (#11), so a crowded Baseline no longer silently truncates; the only ceiling left is the
> `MAX_PACKET_SIZE` byte budget, and `snapshot_count_overflow` warns if it is ever brushed. See
> [`wire-protocol.md`](wire-protocol.md).

### Scheduler diagnostics: now surfaced (#15)

`broadcast_state_updates` aggregates per-tick scheduler stats into `last_tick_diagnostics`
(`server_broadcast_service.gd:62-67,221-226`): `entities_deferred_per_tick`, `max_queue_age_ticks`,
`peers_at_budget_pct`, `peers_evaluated`, plus the #11 `snapshot_count_overflow` counter. These now
**reach the client.** `ServerMetrics` gained matching `sched_*` fields (`server_metrics.gd:27-31`),
populated from `broadcast_service.last_tick_diagnostics` each metrics tick (`:74-75`); they are
encoded into the fixed-length `SERVER_METRICS` packet (`network_manager.gd:876-880`, decode
`:1010-1014`) and rendered in the HUD `server_status` panel (`server_status.gd:65-69,125-127`). So you
can now see whether the budget is starving entities. See
[`performance-budgets.md`](performance-budgets.md).

## Eviction, batching, and the connect/disconnect bookkeeping

- A new peer gets a fresh `DeltaStateCache` and (lazily) a `SnapshotScheduler` on connect
  (`server_main.gd:582`, `server_broadcast_service.gd:221-224,360-364`); both are dropped on
  disconnect (`:368-371`).
- On shutdown the half-built batch is discarded so each `DISCONNECT` ships immediately
  (`server_main.gd:800-803`).

## The eight questions

- **Client:** nothing — this doc is the authoritative server's hot path. Clients only *consume* the
  Snapshots ([`interpolation.md`](interpolation.md)).
- **Server:** the entire 30 Hz Tick loop, 30 Hz Snapshot build, shared-grid AoI filter, delta
  compression, bandwidth-derived priority scheduler, baseline-ack tracking, and per-tick BATCH flush.
- **Predicted:** nothing here — prediction is client-side; the server is authoritative.
- **Replicated:** all entity state, as per-peer delta/baseline `STATE_UPDATE` Snapshots; Game
  events replicate inline every Tick.
- **Persisted:** nothing — all sim state is in-memory; only the Go API persists account/leaderboard.
- **Validated:** inputs and movement during step 1 (`_process_client_inputs`); broadcast itself
  validates nothing beyond `entity_id >= 0`.
- **Can fail:** unmeasured at the 500–1000-player target (the shared grid + 700/800 radius should
  hold but are unproven — now observable via the surfaced scheduler diagnostics); an unbudgeted
  Baseline for a clustered player can still exceed 1200 bytes (truncation risk is gone — count is now
  u16); the baseline-ack resend path is inert on TCP.
- **Tested:** load-tested via the Python bot swarm (`load_testing/`, `baseline`/`target`/`stress`)
  with `regression_assertions.py` asserting AoI cull at 700/800; `ServerMetrics` reports avg/max tick
  time plus the new `sched_*` diagnostics; no automated test asserts Snapshot correctness or scheduler
  fairness today.

## See also

- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — the AoI filter and LOD bands this loop runs per player
- [`wire-protocol.md`](wire-protocol.md) — delta-mask byte layout, `u8` entity_count cap, quantization
- [`transport-websocket.md`](transport-websocket.md) — how the end-of-tick BATCH frame is polled and sent
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md) — the client side of these Snapshots
- [`performance-budgets.md`](performance-budgets.md) — tick-time and bandwidth targets vs. measured
