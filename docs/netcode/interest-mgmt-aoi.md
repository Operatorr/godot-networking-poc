# Interest management (AoI) & LOD

**Status:** Implemented (verified 2026-06-04 against code) — AoI radius (tuned down to 700/800),
hysteresis, 3-tier LOD, a byte-budget scheduler, **and a shared per-tick spatial-grid broad-phase**
(#9) are all built and wired. The two former Partial gaps — a near-useless cull radius (#10) and an
O(players × entities) scan (#9) — are resolved; the remaining caveat is that none of it has yet been
*measured* at the 500–1000-player target.

> This is a **scale** concern, not a perceived-latency one. AoI exists so a Snapshot to one player
> doesn't carry every entity on the Arena. It now narrows each viewer's candidate set with a shared
> spatial grid, filters by a meaningfully-tight radius (700 enter / 800 exit), and sorts the
> survivors by priority under a byte budget.

## What AoI is here

For each authenticated player, the server filters the global entity list down to the **Remote
entities** near that player's **Local player**, then sends only those in that player's Snapshot.
Entities outside the radius are culled from that Snapshot and explicitly despawned on the client.

Four mechanisms stack, all per-client, every Snapshot tick:

0. **Shared spatial-grid broad-phase (#9)** — one `SpatialGrid` is built per Tick from final entity
   positions and queried per peer to get an O(nearby) candidate band, instead of walking every entity.
1. **AoI radius filter with hysteresis** — enter/exit radii so entities near the boundary don't flicker.
2. **3-tier LOD** — near / mid / far classification feeding a distance penalty.
3. **Byte-budget scheduler** — priority-sorts the survivors and defers the lowest-priority ones
   past a per-Snapshot byte cap (see [`server-tick-broadcast.md`](server-tick-broadcast.md)).

The whole pipeline lives in `server_broadcast_service.gd::broadcast_state_updates`
(`server_broadcast_service.gd:112`), called once per Snapshot tick.

## Configuration (live values)

Config is loaded by `ServerConfig` and wired into the broadcast service at startup
(`server_main.gd:153-154`). Defaults live in `server_config.gd:19-27`; the runtime JSON at
`data/config/server_config.json` sets the same values explicitly.

| Knob | Default (`server_config.gd`) | JSON | Effect |
|---|---|---|---|
| `aoi_radius` | **700.0** (`:19`) | **700.0** | Enter radius — new entity appears within this distance |
| `aoi_exit_radius` | **800.0** (`:23`) | **800.0** | Exit radius — visible entity drops only past this |
| `lod_near_radius` | 400.0 (`:26`) | — (default) | ≤400u → LOD_NEAR (penalty 0) |
| `lod_mid_radius` | 700.0 (`:27`) | — (default) | ≤700u → LOD_MID (penalty 4); else LOD_FAR (penalty 8) |
| `max_snapshot_bytes` | 1200 (`:37`) | — (default) | Per-peer per-Snapshot byte budget; 0 disables deferral |
| `snapshot_rate_hz` | 0 → falls back to tick_rate=30 (`:102-107`) | **30** | Live Snapshot rate is **30 Hz** (#3 raised it from 20) |

> **Gameplay-safety note:** the 700 enter radius is deliberately kept **≥ `MONSTER_DETECTION_RANGE`
> (650, `game_constants.gd:347`)** — a monster that can aggro a player is always inside that player's
> AoI, so AoI culling can never hide an entity that is actively engaging the viewer. Radii are squared
> once when assigned (`server_main.gd:153-154`) so the hot path never calls `sqrt`.

## Shared spatial-grid broad-phase (#9)

Before any per-peer filtering, `build_aoi_grid` (`server_broadcast_service.gd:79-107`) runs **once
per Tick**: it collects every authoritative entity (`to_entity_data` / `collect_state_updates`) into
one list and inserts each into a fresh `SpatialGrid` (`spatial_grid.gd`, `class_name SpatialGrid`)
with cell size = `aoi_exit_radius / 4` (the roadmap's `aoi_radius/4` hint, sized off the larger exit
radius). `ServerMain` primes this at the top of the Snapshot tick (`server_main.gd:269`); the
broadcast loop falls back to building it inline if unprimed (`:128-129`).

Each peer then queries the grid for its candidate band —
`_tick_grid.query_radius(state.position, aoi_exit_radius)` (`server_broadcast_service.gd:161`) —
instead of walking the global entity list. The query uses the **larger exit radius** so
hysteresis-retained entities up to `aoi_exit_radius` are never missed; the exact distance +
hysteresis test still runs in `_filter_entities_by_aoi` on that narrowed set. This replaces the old
O(players × entities) scan with O(players × nearby) — the dominant broadcast cost at scale. The same
grid is built once and shared by all peers; projectile and monster *collision* grids are separate and
unchanged.

## Radius filter + hysteresis

`_filter_entities_by_aoi` (`server_broadcast_service.gd:235-280`) iterates only the **grid candidate
band** for each player (no longer the global list). Per candidate:

- The Local player itself is **never culled** (`:272`) — self always rides along.
- A `distance_squared_to` is compared against `exit_radius_sq` if the entity was already visible to
  this client last tick, else `enter_radius_sq` (`:261`). That asymmetry is the hysteresis: an
  entity must close to within **700u** to appear, then stays until it exceeds **800u**.
- Per-client visibility is remembered in `client_visible_entities[peer_id]`
  (`:38`, `:153`, `:185`); entities that were visible last tick but aren't now become explicit despawn
  deltas (`DELTA_MASK_REMOVED`, `:180-184`) so the client doesn't strand a ghost.

The filter returns `{entities, lods}` with a parallel `PackedByteArray` of LOD tiers — deliberately
**not** a `Dictionary.duplicate()` per entity, to avoid per-entity allocation at scale.

## 3-tier LOD

`_classify_lod` (`server_broadcast_service.gd:282`) buckets each visible entity by squared
distance: `≤ lod_near_radius_sq` → NEAR, `≤ lod_mid_radius_sq` → MID, else FAR
(tiers `LOD_NEAR/MID/FAR = 0/1/2`). The tier is **not** a separate send-rate throttle; it
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
- Scheduler diagnostics (`entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct`,
  `peers_evaluated`, plus `snapshot_count_overflow`) are aggregated into `last_tick_diagnostics`
  (`:62-67`, `:221-226`) and **now surfaced** on the SERVER_METRICS broadcast and HUD (#15 — see
  [`performance-budgets.md`](performance-budgets.md)).

## Remaining caveats (no longer Partial-blocking)

The two structural gaps that made this doc Partial — a near-useless cull radius and an
O(players × entities) scan — are **resolved** (#10 radius 700/800; #9 shared spatial grid). What
remains is tuning-under-measurement, not missing mechanism:

| Caveat | Evidence | Consequence |
|---|---|---|
| **Not yet measured at target load.** The 700/800 radii and the shared grid are correct in shape but unproven at 500–1000 players. | `server_config.gd:19,23`; `spatial_grid.gd` | The scheduler diagnostics (#15) are now wired precisely so this can be observed under load before further tuning. |
| **Far entities can still starve under budget pressure.** FAR penalty (−8) plus a tight 1200-byte budget defers far entities while clustered near entities saturate the budget. | `snapshot_scheduler.gd:26`; `server_broadcast_service.gd:42` | Acceptable by design (anti-starvation eventually re-sends); now that the radius actually bounds the candidate set, the budget is a backstop rather than the primary cull. |
| **Baselines still have no byte budget.** Forced full-state every 100 ticks emits *all* visible entities ignoring `max_snapshot_bytes`. | `server_broadcast_service.gd:480` (`_create_full_state_packet`) | A baseline tick for a clustered player can still exceed 1200 bytes. The u8 `entity_count` truncation risk is **gone** (count is now u16, #11) — overflow can now only happen at the far-larger `MAX_PACKET_SIZE` byte ceiling, which `snapshot_count_overflow` warns on. See [`server-tick-broadcast.md`](server-tick-broadcast.md). |

## Done (was Planned)

- ✅ **Shared spatial broad-phase for AoI (#9)** — `spatial_grid.gd` (`SpatialGrid`) built once per Tick
  (`build_aoi_grid`) and queried per peer (`query_radius`); the per-player filter is now O(nearby).
- ✅ **Tune the AoI radius down (#10)** — enter 1000→700, exit 1100→800 (kept ≥ `MONSTER_DETECTION_RANGE`
  650); `regression_assertions.py` defaults updated in lockstep.
- ✅ **Surface scheduler diagnostics (#15)** — `last_tick_diagnostics` now flows to ServerMetrics, the
  SERVER_METRICS packet, and the HUD.
- ✅ **Per-client rate budget (#13)** — `CONNECT_AUTH` advertises a bytes/sec budget; the server derives a
  per-peer `max_snapshot_bytes` from it. See [`server-tick-broadcast.md`](server-tick-broadcast.md).

## Still planned

- **Measure at target load** — validate the 700/800 radii + grid against 500–1000 players using the
  now-surfaced scheduler diagnostics; add an AoI-clustering load scenario (none in the harness today).

## The eight questions

- **Client:** receives the AoI-filtered Snapshot and despawns entities that left its AoI; does no AoI itself.
- **Server:** builds the shared grid once and computes AoI, hysteresis, LOD, and budget per player every Snapshot tick (`server_broadcast_service.gd:79`, `:112`).
- **Predicted:** nothing — AoI is server-side Snapshot filtering, orthogonal to prediction.
- **Replicated:** only entities inside a player's AoI are replicated to that player; exits are despawned.
- **Persisted:** nothing — AoI/visibility state is in-memory per peer (`client_visible_entities`, `snapshot_schedulers`), cleared on disconnect (`:466`).
- **Validated:** the Local player is never culled (`:272`); pinned despawns can't be budget-dropped (`snapshot_scheduler.gd:99`); the 700 enter radius stays ≥ `MONSTER_DETECTION_RANGE` so an aggro'd monster is never AoI-hidden.
- **Can fail:** unproven at 500–1000 players (now observable via the surfaced scheduler diagnostics); baseline ticks still ignore the byte budget, though the u8 entity-count truncation is gone (count is u16, #11).
- **Tested:** exercised by the Python bot swarm (`load_testing/`, `baseline`/`target`/`stress`) with `regression_assertions.py` asserting the 700/800 cull; no dedicated AoI/scheduler unit test today.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the Snapshot tick, batching, baseline cadence, and the byte/entity caps AoI feeds into
- [`performance-budgets.md`](performance-budgets.md) — the 500–1000-player targets the now-O(nearby) AoI scan must meet
