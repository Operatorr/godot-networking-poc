# Interest management (AoI) & LOD

**Status:** Partial (verified 2026-06-03 against code) — AoI, hysteresis, 3-tier LOD, and a
byte-budget scheduler are built and wired, but the AoI radius culls almost nothing on the current
map and the per-client scan is O(players × entities) with no shared spatial broad-phase.

> This is a **scale** concern, not a perceived-latency one. AoI exists so a Snapshot to one player
> doesn't carry every entity on the Arena. Today it filters by a generous radius and sorts what's
> left by priority under a byte budget — correct in shape, but tuned so loosely that under the
> 500–1000-player target it does little useful culling and costs O(N²) to compute.

## What AoI is here

For each authenticated player, the server filters the global entity list down to the **Remote
entities** near that player's **Local player**, then sends only those in that player's Snapshot.
Entities outside the radius are culled from that Snapshot and explicitly despawned on the client.

Three mechanisms stack, all per-client, every Snapshot tick:

1. **AoI radius filter with hysteresis** — enter/exit radii so entities near the boundary don't flicker.
2. **3-tier LOD** — near / mid / far classification feeding a distance penalty.
3. **Byte-budget scheduler** — priority-sorts the survivors and defers the lowest-priority ones
   past a per-Snapshot byte cap (see [`server-tick-broadcast.md`](server-tick-broadcast.md)).

The whole pipeline lives in `server_broadcast_service.gd::broadcast_state_updates`
(`server_broadcast_service.gd:58`), called once per Snapshot tick (20 Hz live, see below).

## Configuration (live values)

Config is loaded by `ServerConfig` and wired into the broadcast service at startup
(`server_main.gd:143-147`). Defaults live in `server_config.gd:15-22`; the runtime JSON at
`data/config/server_config.json` overrides a subset.

| Knob | Default (`server_config.gd`) | JSON override | Effect |
|---|---|---|---|
| `aoi_radius` | 1000.0 (`:15`) | 1000.0 | Enter radius — new entity appears within this distance |
| `aoi_exit_radius` | 1100.0 (`:19`) | — (default) | Exit radius — visible entity drops only past this |
| `lod_near_radius` | 400.0 (`:22`) | — (default) | ≤400u → LOD_NEAR (penalty 0) |
| `lod_mid_radius` | 700.0 (`:23`) | — (default) | ≤700u → LOD_MID (penalty 4); else LOD_FAR (penalty 8) |
| `max_snapshot_bytes` | 1200 (`:33`) | — (default) | Per-peer per-Snapshot byte budget; 0 disables deferral |
| `snapshot_rate_hz` | 0 → falls back to tick_rate=30 (`:88-93`) | **20** | **Live Snapshot rate is 20 Hz** (the JSON wins) |

> **Discrepancy to flag:** the code default for `snapshot_rate_hz` is 0 (→ 30 Hz tick rate), but
> `data/config/server_config.json:9` sets it to **20**, and the JSON wins at runtime. So AoI runs
> at **20 Hz (50 ms)**, not the 30 Hz Tick rate. Same drift noted in
> [`server-tick-broadcast.md`](server-tick-broadcast.md). Radii are squared once at startup
> (`server_main.gd:145-146`) so the hot path never calls `sqrt`.

## Radius filter + hysteresis

`_filter_entities_by_aoi` (`server_broadcast_service.gd:176-208`) walks the global entity list for
each player. Per entity:

- The Local player itself is **never culled** (`:192-196`) — self always rides along.
- A `distance_squared_to` is compared against `exit_radius_sq` if the entity was already visible to
  this client last tick, else `enter_radius_sq` (`:200-201`). That asymmetry is the hysteresis: an
  entity must close to within 1000u to appear, then stays until it exceeds 1100u.
- Per-client visibility is remembered in `client_visible_entities[peer_id]`
  (`:106`, `:133`); entities that were visible last tick but aren't now become explicit despawn
  deltas (`DELTA_MASK_REMOVED`, `:128-132`) so the client doesn't strand a ghost.

The filter returns `{entities, lods}` with a parallel `PackedByteArray` of LOD tiers — deliberately
**not** a `Dictionary.duplicate()` per entity, to avoid per-entity allocation at scale
(`:175`, `:184-185`, `:208`).

## 3-tier LOD

`_classify_lod` (`server_broadcast_service.gd:212-217`) buckets each visible entity by squared
distance: `≤ lod_near_radius_sq` → NEAR, `≤ lod_mid_radius_sq` → MID, else FAR
(tiers `LOD_NEAR/MID/FAR = 0/1/2`, `:11-13`). The tier is **not** a separate send-rate throttle; it
feeds the scheduler as a **distance penalty** subtracted from priority
(`DISTANCE_PENALTY_BY_LOD = [0, 4, 8]`, `snapshot_scheduler.gd:26`,`:137-140`). Far entities thus
sort lower and are the first deferred when the byte budget bites — they update at a *fraction* of the
Snapshot rate rather than on a fixed divisor.

## Byte-budget scheduler (deferral)

When a Snapshot is a delta (not a forced baseline), the surviving entities go through the per-peer
`SnapshotScheduler` (`server_broadcast_service.gd:141`,`:420-554`; `snapshot_scheduler.gd`). It
priority-sorts candidates and keeps appending until the per-peer `max_snapshot_bytes` (1200) is hit,
then **defers** the rest to a later tick.

Priority (`snapshot_scheduler.gd:117-126`):

```
priority = importance(type)            # player 10, projectile 8, monster 4
         + ticks_since_last_sent       # anti-starvation: deferred entities climb
         - distance_penalty(lod_tier)  # NEAR 0 / MID 4 / FAR 8
         + change_bonus(delta_mask)    # full/removed +6; pos/anim/flags +2 each
```

- **Anti-starvation:** `ticks_since_last_sent` is added to priority (`snapshot_scheduler.gd:124`),
  so an entity deferred enough ticks eventually outranks fresh near entities and gets sent.
- **Pinned entries bypass the budget:** AoI exits and stale-cache despawns are pinned
  (`server_broadcast_service.gd:438-457`,`:504-524`; `snapshot_scheduler.gd:99`) so a client never
  loses an entity it was tracking until the next baseline.
- **Baselines skip the scheduler entirely.** A forced full-state Snapshot (every 100 ticks) is built
  by `_create_full_state_packet` with **no byte budget** (`server_broadcast_service.gd:138-139`,
  `:382-413`) — see "What can fail" below.
- Scheduler diagnostics (`deferred`, `max_queue_age`, `hit_budget`) are aggregated into
  `last_tick_diagnostics` (`:162-168`) for ServerMetrics, but are **not yet surfaced** on the
  SERVER_METRICS broadcast (Phase 2 gap).

## Why this is Partial — known gaps

| Gap | Evidence | Consequence |
|---|---|---|
| **Radius culls ~nothing on this map.** Arena is 2000×2000 (`game_constants.gd:63-66`); a radius-1000 circle covers ~78% of it. | `server_config.gd:15`; `game_constants.gd:63-66` | When players cluster (the common case in a bullet-hell), almost every entity is inside everyone's AoI — the filter pays O(N²) cost to cull near-zero entities. |
| **O(players × entities) scan, no shared broad-phase.** Each player re-walks the *entire* global entity list every Snapshot. | `server_broadcast_service.gd:97-118`,`:189-208` | O(players²) overall (entities scale with players). This is the dominant broadcast cost at 500–1000 players. |
| **The 64-unit projectile grid is not reused for AoI.** A spatial hash exists but only for projectile collision. | `projectile_manager.gd:20`,`:127-149` | AoI can't answer "entities near X" in O(nearby); it brute-forces. The broad-phase that would fix the row above already exists, unused here. |
| **Far entities starve under budget pressure.** FAR penalty (−8) plus a tight 1200-byte budget defers far entities indefinitely while clustered near entities saturate the budget. | `snapshot_scheduler.gd:26`,`:98-104`; `server_broadcast_service.gd:42` | Acceptable by design (anti-starvation eventually re-sends), but with a near-useless radius the budget — not AoI — becomes the real interest-management mechanism, which was not the intent. |
| **Baselines have no byte budget.** Forced full-state every 100 ticks emits *all* visible entities ignoring `max_snapshot_bytes`. | `server_broadcast_service.gd:138-139`,`:382-413` | A baseline tick for a clustered player can blow far past 1200 bytes and past the u8 `entity_count` cap (255), risking silent truncation. See [`server-tick-broadcast.md`](server-tick-broadcast.md). |

## Planned

- **Shared spatial broad-phase for AoI** — reuse/generalize the projectile grid
  (`projectile_manager.gd:127-149`) so the per-player filter is O(nearby) instead of O(all). Removes
  the O(N²) scan that dominates broadcast cost.
- **Tune the AoI radius** down (and/or scale the Arena up) so the radius actually culls when players
  cluster — today radius 1000 on a 2000×2000 map makes AoI nearly a no-op.
- **Surface scheduler diagnostics** (`last_tick_diagnostics`, `server_broadcast_service.gd:49-54`)
  on the SERVER_METRICS broadcast so deferral / queue-age are observable under load (Phase 2).
- **Per-client rate budget** (Phase 2) — cap bytes/sec per peer, not just bytes/Snapshot.

## The eight questions

- **Client:** receives the AoI-filtered Snapshot and despawns entities that left its AoI; does no AoI itself.
- **Server:** computes AoI, hysteresis, LOD, and budget per player every Snapshot tick (`server_broadcast_service.gd:58`).
- **Predicted:** nothing — AoI is server-side Snapshot filtering, orthogonal to prediction.
- **Replicated:** only entities inside a player's AoI are replicated to that player; exits are despawned.
- **Persisted:** nothing — AoI/visibility state is in-memory per peer (`client_visible_entities`, `snapshot_schedulers`), cleared on disconnect (`:368-371`).
- **Validated:** the Local player is never culled (`:192-196`); pinned despawns can't be budget-dropped (`snapshot_scheduler.gd:99`).
- **Can fail:** clustered players → radius culls ~nothing + O(N²) scan; baseline ticks ignore the byte budget and the u8 entity cap → silent truncation.
- **Tested:** exercised indirectly by the Python bot swarm (`load_testing/`, `baseline`/`target`/`stress`); no dedicated AoI/scheduler unit test today.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the Snapshot tick, batching, baseline cadence, and the byte/entity caps AoI feeds into
- [`performance-budgets.md`](performance-budgets.md) — the 500–1000-player targets this O(N²) scan must meet
