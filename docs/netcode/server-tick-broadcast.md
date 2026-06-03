# Server tick loop & snapshot broadcast

**Status:** Partial (verified 2026-06-03 against code). The hot path is built and runs, but
the per-player Snapshot build is **O(players × entities)** (quadratic in players) with no shared
broad-phase, and the priority scheduler's per-tick diagnostics are computed but **never surfaced
to `ServerMetrics`**.

This is the server-side counterpart to [`interpolation.md`](interpolation.md) and
[`client-prediction.md`](client-prediction.md): how the authoritative simulation advances one
**Tick** at a time, and how it turns world state into per-client **Snapshots**.

## The two cadences are decoupled

| Cadence | Rate | Period | Where | Drives |
| --- | --- | --- | --- | --- |
| **Tick** (simulation) | 30 Hz | 33.3 ms | `server_main.gd:178-182` | inputs, movement, AI, collisions, Game events |
| **Snapshot** (`STATE_UPDATE`) | **20 Hz live** | 50 ms | `server_main.gd:211-218,249` | replicated entity state to clients |

The Tick rate is `config.tick_rate` = 30 (`server_config.gd:9`, `server_config.json:3`). The
Snapshot rate is decoupled via a separate accumulator: `ServerConfig`'s *default* `snapshot_rate_hz`
is `0`, which falls back to the Tick rate (`server_config.gd:88-93`) — but the shipped config file
sets `snapshot_rate_hz = 20` (`server_config.json:10`), and **the JSON wins at runtime**. So the
**live Snapshot rate is 20 Hz (50 ms)**, not 30 Hz.

> **Discrepancy to flag:** the in-code default (fallback to 30 Hz) and the deployed config (20 Hz)
> disagree. Anything reading the default would assume 30 Hz; the running server sends at 20 Hz.
> Several stale client constants assume 20 Hz across the board (see
> [`interpolation.md`](interpolation.md)) — but the *simulation* is 30 Hz, so those are wrong in
> the other direction.

## The tick loop runs in `_process`, not `_physics_process`

The server drives its own fixed Tick from a manual accumulator inside `Node._process`
(`server_main.gd:170-182`), **not** Godot's `_physics_process`:

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

`_process_server_tick()` (`server_main.gd:203-263`) does exactly this, every Tick:

| Step | Call | Line |
| --- | --- | --- |
| advance Snapshot accumulator, set `snapshot_due` | inline | `:211-218` |
| open per-tick batch window | `nm.begin_batch()` | `:226-228` |
| 1. process client inputs (incl. shoot edges) | `_process_client_inputs()` | `:231` |
| 2. update game state (projectiles, spawner, timers) | `_update_game_state()` | `:234` |
| 3. monster AI | `_update_monster_ai()` | `:237` |
| 4. snapshot monster positions (for PvE lag-comp rewind) | `record_position_snapshot()` | `:241` |
| 5. collisions / damage / kills | `collision_handler.process_collisions()` | `:244` |
| 6. **broadcast Snapshot — only if `snapshot_due`** | `broadcast_state_updates()` | `:249-253` |
| 7. cleanup dead monsters | `cleanup_dead_monsters()` | `:256` |
| flush per-peer batches | `nm.flush_batches()` | `:258-259` |
| record tick time | `record_tick_time()` | `:262-263` |

**Game events** (damage, kill, shot-fired, respawn, `PLAYER_INFO`) are broadcast inline during
steps 1–5 on *every* Tick — only the continuous `STATE_UPDATE` Snapshot is rate-limited. So a hit
or kill still reaches clients at full 30 Hz cadence even though positions stream at 20 Hz.

## Per-tick BATCH flush adds up to one tick of queuing

When `packet_batching_enabled` (default true, `server_config.gd:25,79`), the loop opens a batch
window at the top of the Tick and flushes at the bottom (`server_main.gd:226-228,258-259`). Every
`send_to_client` / `broadcast_to_clients` during the Tick is queued per-peer and coalesced into a
single WebSocket BATCH frame at end-of-Tick. This slashes per-frame framing overhead when inputs,
collisions, and a Snapshot all fire together — but it means a message produced early in a Tick
waits until that Tick ends before it leaves the box: **up to ~33 ms of server-side queuing** on
top of transport latency. See [`transport-websocket.md`](transport-websocket.md) for how the
batched frame is then polled and sent over TCP.

## Per-player Snapshot build is O(players × entities) — the quadratic

`broadcast_state_updates()` (`server_broadcast_service.gd:58-168`) collects every authoritative
entity once into `all_entities` (`:72-83`), then **loops over every authenticated player**
(`:97`) and, *for each one*, re-runs the full AoI filter + delta + scheduler pass:

- AoI filter walks **all entities** per player (`_filter_entities_by_aoi`, `:176-208`) — a linear
  scan, no shared spatial broad-phase. With P players that is **P × N** distance checks per
  Snapshot tick.
- The map is 2000×2000 and the AoI radius is 1000 enter / 1100 exit (`server_config.gd:15,19`), so
  a radius-1000 circle covers ~78% of the arena — when players cluster, AoI culls almost nothing,
  and the inner loop stays near full N. See [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md).

This is **O(P × N)** and, because N grows with P, effectively **O(P²) in players** every Snapshot
tick. At the 500–1000-player target this is the dominant server cost and the headline reason this
doc is tagged Partial. The collision system already has a 64-unit spatial grid in
`projectile_manager`, but it is **not** reused for AoI broad-phase (Planned — spatial grid for
broadcast is Phase 3 of the perf plan).

## Delta compression

Each per-player packet is either a **baseline** (full state) or a **delta**, decided per peer by
its `DeltaStateCache` (`delta_state_cache.gd`).

- **Delta mask** is an 8-bit field (`packet_types.gd:66-70`): `POSITION` (bit 0), `ANIMATION`,
  `FLAGS`, plus `REMOVED` (bit 6) and `FULL_STATE` (bit 7). `calculate_delta_mask`
  (`delta_state_cache.gd:71-104`) diffs current state against the per-peer cache and sets only
  changed bits; an entity whose mask is 0 is skipped entirely (`server_broadcast_service.gd:475-476`).
- Position equality uses a 0.05-unit threshold (`delta_state_cache.gd:109-111`), matching the
  0.1-unit wire quantization. See [`wire-protocol.md`](wire-protocol.md) for byte layout.
- **Forced baseline every 100 Ticks** (`DELTA_FULL_STATE_INTERVAL`, `packet_types.gd:78`;
  `needs_full_state_for_interval`, `delta_state_cache.gd:115-116`). At 20 Hz live that is one full
  resync per peer every ~5 s. (The constant's comment says "~5 seconds at 20Hz" — correct for the
  live rate, stale if you assume the 30 Hz default.)
- **No baseline ack.** The server pushes baselines on a fixed interval and trusts they arrive; the
  client never acknowledges a baseline, so a dropped baseline is only repaired by the next
  100-Tick cycle (or a client `REQUEST_FULL_STATE`, `server_broadcast_service.gd:228-258`).
- Only entries that actually go out update the cache (`update_cache_partial`,
  `server_broadcast_service.gd:533-540`); deferred entities keep their stale cache entry so they
  re-prioritize next tick.
- AoI exits and stale-cache entries are emitted as explicit `REMOVED` deltas so a client never
  strands an entity (`:128-133,504-524`).

## Per-peer 1200-byte budget + priority scheduler

Each delta packet is sized by a per-peer `SnapshotScheduler` (`snapshot_scheduler.gd`) against
`max_snapshot_bytes` = **1200** (`server_config.gd:33,42`). The scheduler scores every candidate:

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
> `server_broadcast_service.gd:382-413`) emits *every* visible entity with no scheduler and no
> 1200-byte cap, and the wire `entity_count` field is a `u8` → a hard 255-entity ceiling with
> silent truncation. See [`wire-protocol.md`](wire-protocol.md).

### Scheduler diagnostics: computed but not surfaced (the Partial gap)

`broadcast_state_updates` aggregates per-tick scheduler stats — entities deferred, max queue age,
% of peers at budget — into `last_tick_diagnostics` (`server_broadcast_service.gd:49-54,92-95,
152-168`). But **nothing reads them.** `ServerMetrics.update_metrics` (`server_metrics.gd:48-93`)
has no fields for scheduler stats, and `ServerMain._process` (`server_main.gd:185-194`) calls it
with only player/entity/tick counts + `network_stats` — it never touches
`broadcast_service.last_tick_diagnostics`. So the `SERVER_METRICS` broadcast cannot show whether
the budget is starving entities. Wiring these into `ServerMetrics` is the remaining Phase 2 task.

## Eviction, batching, and the connect/disconnect bookkeeping

- A new peer gets a fresh `DeltaStateCache` and (lazily) a `SnapshotScheduler` on connect
  (`server_main.gd:582`, `server_broadcast_service.gd:221-224,360-364`); both are dropped on
  disconnect (`:368-371`).
- On shutdown the half-built batch is discarded so each `DISCONNECT` ships immediately
  (`server_main.gd:800-803`).

## The eight questions

- **Client:** nothing — this doc is the authoritative server's hot path. Clients only *consume* the
  Snapshots ([`interpolation.md`](interpolation.md)).
- **Server:** the entire 30 Hz Tick loop, 20 Hz Snapshot build, delta compression, AoI filter,
  priority scheduler, and per-tick BATCH flush.
- **Predicted:** nothing here — prediction is client-side; the server is authoritative.
- **Replicated:** all entity state, as per-peer delta/baseline `STATE_UPDATE` Snapshots; Game
  events replicate inline every Tick.
- **Persisted:** nothing — all sim state is in-memory; only the Go API persists account/leaderboard.
- **Validated:** inputs and movement during step 1 (`_process_client_inputs`); broadcast itself
  validates nothing beyond `entity_id >= 0`.
- **Can fail:** O(P²) build dominates CPU when players cluster (AoI culls little on a 2000×2000 map);
  dropped baseline unrepaired for ~5 s (no ack); `u8` entity_count truncates baselines >255 entities
  silently; scheduler starvation is invisible (diagnostics unwired).
- **Tested:** load-tested via the Python bot swarm (`load_testing/`, `baseline`/`target`/`stress`);
  `ServerMetrics` reports avg/max tick time; no automated test asserts Snapshot correctness or
  scheduler fairness today.

## See also

- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — the AoI filter and LOD bands this loop runs per player
- [`wire-protocol.md`](wire-protocol.md) — delta-mask byte layout, `u8` entity_count cap, quantization
- [`transport-websocket.md`](transport-websocket.md) — how the end-of-tick BATCH frame is polled and sent
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md) — the client side of these Snapshots
- [`performance-budgets.md`](performance-budgets.md) — tick-time and bandwidth targets vs. measured
