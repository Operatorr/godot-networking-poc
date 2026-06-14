# Interest management (AoI) & LOD

**Status:** Implemented (verified 2026-06-14 against `rust/server/src/net/broadcast.rs`) — AoI radius
(1000 enter / 1100 exit, sized to cover the client's view on wide/ultrawide displays), hysteresis,
3-tier LOD, a per-peer byte-budget scheduler, **and a shared per-tick spatial-grid broad-phase** are
all built and wired in the Rust **`omega-server`**. The two former structural gaps — a near-useless
cull radius and an O(players × entities) scan — are resolved; the remaining caveat is that none of it
has yet been *measured* at the 500–1000-player target.

> The Rust `omega-server` (single-threaded synchronous 30 Hz tick over `rusty_enet`) is the **only**
> authoritative server. The legacy GDScript headless server is retired; its
> `server_broadcast_service.gd` / `snapshot_scheduler.gd` / `spatial_grid.gd` / `delta_state_cache.gd`
> were ported verbatim into `rust/server/src/net/broadcast.rs`, which is the single source of truth for
> everything below. Cite the Rust module, not the GDScript.

> This is a **scale** concern, not a perceived-latency one. AoI exists so a Snapshot to one player
> doesn't carry every entity on the Arena. It narrows each viewer's candidate set with a shared
> spatial grid, filters by a radius sized to the client's view (1000 enter / 1100 exit), and sorts
> the survivors by priority under a per-peer byte budget.

## What AoI is here

For each authenticated player, the server filters the global entity list down to the entities near
that player's own entity, then sends only those in that player's Snapshot. Entities outside the
radius are culled from that Snapshot and explicitly despawned on the client (a `REMOVED` delta
record).

Four mechanisms stack, all per-peer, every Snapshot tick:

0. **Shared spatial-grid broad-phase** — one `SpatialGrid` (`broadcast.rs`) is built per Snapshot
   tick from final entity positions and queried per peer to get an O(nearby) candidate band, instead
   of walking every entity.
1. **AoI radius filter with hysteresis** — enter/exit radii so entities near the boundary don't
   flicker.
2. **3-tier LOD** — near / mid / far classification feeding a distance penalty.
3. **Per-peer byte-budget scheduler** — priority-sorts the survivors and defers the lowest-priority
   ones past a per-peer byte cap (see [`server-tick-broadcast.md`](server-tick-broadcast.md)).

The whole pipeline lives in `BroadcastService::broadcast_state_updates`
(`rust/server/src/net/broadcast.rs`), called once per Snapshot tick from the tick loop
(`rust/server/src/sim/world.rs`, step 6, gated on `snapshot_due`). Entities are gathered fresh that tick
via `World::collect_entities` (`world.rs`) into a flat `&[EntityData]` (`{ id, position, animation,
flags }`).

## Configuration (live values)

Config defaults live in `ServerConfig::default` (`rust/server/src/config.rs`); the same keys are
overridable from `server_config.json` / env / CLI (`config.rs` key parser). They are wired into the
broadcast service once at construction in `World::new` via `BroadcastService::new(aoi_radius,
aoi_exit_radius, lod_near_radius, lod_mid_radius, max_snapshot_bytes)` (`world.rs`).

| Knob | Default (`config.rs`) | Effect |
|---|---|---|
| `aoi_radius` | **1000.0** | Enter radius — new entity appears within this distance |
| `aoi_exit_radius` | **1100.0** | Exit radius — visible entity drops only past this |
| `lod_near_radius` | 400.0 | ≤400u → `LOD_NEAR` (penalty 0) |
| `lod_mid_radius` | 1000.0 | ≤1000u → `LOD_MID` (penalty 4); else `LOD_FAR` (penalty 8) |
| `max_snapshot_bytes` | 1200 | Global per-peer byte cap; clamped to `MIN_SNAPSHOT_FLOOR`(256)..1200; 0 is rejected at validation and forced to 1200 |
| `snapshot_rate_hz` | 0 → falls back to `tick_rate`=30 | Live Snapshot rate is **30 Hz** |

The LOD radii are squared once at `BroadcastService::new` (`lod_near_radius_sq`, `lod_mid_radius_sq`)
so the hot path never calls `sqrt`. The AoI enter/exit radii are squared per Snapshot tick at the top
of `broadcast_state_updates` (`enter_sq` / `exit_sq`); the per-entity test uses `distance_squared_to`.

> **Gameplay-safety note:** the 1000 enter radius is deliberately kept **≥
> `MONSTER_DETECTION_RANGE` (650, `rust/sim_core/src/constants.rs`)** — a monster that can aggro a
> player is always inside that player's AoI, so AoI culling can never hide an entity that is actively
> engaging the viewer.

> **View-coverage note:** the circular AoI must contain the client's *rectangular* view, or entities
> pop in/out at the screen edges. On a 21:9 (3440×1440) display with the `expand` stretch and the
> client's camera zoom, the visible world's horizontal half-extent (~860u, ~955u sprint-zoomed)
> exceeded earlier (700/800) radii and caused left/right edge pop-in. The 1000/1100 radii cover that
> view (only sprint-zoom *corners* at ~1035u may still rarely pop).

## Shared spatial-grid broad-phase

Before any per-peer filtering, `broadcast_state_updates` builds **one** `SpatialGrid` per Snapshot
tick: it inserts every authoritative entity (by index into the `all_entities` slice) at its final
position. Cell size = `effective_exit / 4.0`, where `effective_exit = max(aoi_exit_radius,
aoi_radius)` (sized off the larger exit radius; falls back to 256.0 if AoI is disabled).

`SpatialGrid` (`broadcast.rs`):

- `cell_of` uses a **true floor** (`(pos / cell_size).floor() as i32`) so negative coordinates bucket
  correctly — the Arena spans `(-1000,-1000)..(1000,1000)`.
- `query_radius(center, radius)` returns a **superset**: every index in the `(2r+1)²` cell square
  around the center cell (`r_cells = ceil(radius / cell_size)`). The caller distance-filters the
  result; the grid never does the exact circle test.

Each peer queries the grid for its candidate band with the **larger exit radius**
(`grid.query_radius(self_position, effective_exit)`), so hysteresis-retained entities up to
`aoi_exit_radius` are never missed; the exact distance + hysteresis test then runs on that narrowed
set. This replaces the old O(players × entities) scan with O(players × nearby) — the dominant
broadcast cost at scale. The grid is built once and shared by all peers; projectile/monster
*collision* grids (in the sim/collision pass) are separate.

When AoI is disabled (`aoi_radius <= 0.0`), the grid is skipped and every peer sees all entities
(`visible = (0..all_entities.len())` at `LOD_NEAR`).

## Radius filter + hysteresis

For each peer, `broadcast_state_updates` iterates only the **grid candidate band** (no global walk).
Per candidate:

- The peer's **own entity is never culled** — it's pushed at `LOD_NEAR` and short-circuits the test.
  A cell-edge rounding safety net re-adds self by linear scan if the grid query somehow missed it.
- `distance_squared_to` is compared against `exit_sq` if the entity was visible to this peer last
  tick, else `enter_sq`. That asymmetry is the hysteresis: an entity must close to within **1000u**
  to appear, then stays until it exceeds **1100u**. The test is **strict `>`** (`dist_sq >
  threshold_sq` culls), so an entity exactly on the radius stays visible.
- Per-peer visibility is remembered in `BroadcastService::visible_entities[peer]`. Entities visible
  last tick but not this tick become explicit AoI-exit removals (fed to the delta builder as pinned
  `REMOVED` records) so the client never strands a ghost. `prev_visible` is materialized into a
  `HashSet<u16>` each tick for O(1) membership (was a `Vec::contains` O(n²) in GDScript).

The filter yields `Vec<(usize, u8)>` — `(entity index, LOD tier)` — deliberately not a per-entity
allocation/clone, to avoid churn at scale.

## 3-tier LOD

`BroadcastService::classify_lod(dist_sq)` (`broadcast.rs`) buckets each visible entity by squared
distance: `≤ lod_near_radius_sq` → `LOD_NEAR`, `≤ lod_mid_radius_sq` → `LOD_MID`, else `LOD_FAR`
(`LOD_NEAR/MID/FAR = 0/1/2`; a zero radius disables that tier's gate). The tier is **not** a separate
send-rate throttle; it feeds the scheduler as a **distance penalty** subtracted from priority
(`DISTANCE_PENALTY_BY_LOD = [0, 4, 8]`). Far entities thus sort lower and are the first deferred when
the byte budget bites — they update at a *fraction* of the Snapshot rate rather than on a fixed
divisor.

## Per-peer delta cache

Each peer owns a `DeltaStateCache` (`broadcast.rs`, `BroadcastService::delta_caches[peer]`) — the
port of `delta_state_cache.gd`. It tracks the last `{position, animation, flags, last_tick_sent,
is_new}` the peer was told about each entity, plus baseline bookkeeping (`baseline_tick`,
`acked_baseline_tick`, `pending_baseline_tick`).

- `calculate_delta_mask` returns `FULL` for a never-seen or `is_new` entity, or when the baseline
  interval has elapsed (`tick - baseline_tick >= DELTA_FULL_STATE_INTERVAL`, 100 ticks); otherwise a
  bitwise OR of `POSITION` / `ANIMATION` / `FLAGS` for the fields that changed. Position equality uses
  `POSITION_EPSILON = 0.05` (half the 0.1-unit wire quantization step, strict `<` per axis) so
  sub-quantum jitter costs zero bits.
- `update_cache_partial` is **mask-aware**: only fields whose bit was actually sent are committed;
  withheld fields stay dirty. This is what makes scheduler deferral **lossless** — a deferred entity
  re-presents the same delta next tick.
- `cleanup_stale_entities(active)` drops cache rows for entities that left the peer's AoI tracking
  entirely and returns their ids as pinned despawns.

## Byte-budget scheduler (deferral)

When a Snapshot is a delta (not a forced baseline), `create_delta_packet` (`broadcast.rs`) stages
three candidate groups, then runs the greedy `schedule(candidates, peer_max_bytes)`:

1. **AoI-exit removals** — `REMOVED` records for entities that just left the radius. **Pinned.**
2. **Visible entities with a non-zero delta mask** — unchanged (mask 0) entities are skipped entirely
   (zero bytes). The record is `EntityRecord::full(...)` for a `FULL` mask, else a partial record
   carrying only the set fields.
3. **Stale-cache despawns** — `REMOVED` for entities that left AoI tracking entirely (and weren't
   already in group 1). **Pinned.**

Priority per candidate:

```
priority = importance(entity_id)        # player 10, projectile 8, monster 4, world-effect 4, other 1
         + ticks_since_last_sent        # anti-starvation: deferred entities climb
         - DISTANCE_PENALTY_BY_LOD[lod] # NEAR 0 / MID 4 / FAR 8
         + change_bonus(mask)           # FULL or REMOVED +6; else +2 per POSITION/ANIMATION/FLAGS bit
```

`importance` is derived from the entity-id band via `protocol::entity_type_for_id` (players 1–999,
projectiles 10000–29999, monsters 30000–39999, world effects 40000–49999). World effects
(Healthorbs/mines/dot-zones/bibles) replicate about as eagerly as monsters (priority 4).

`schedule` sorts by **(priority desc, entity_id asc)**, then admits greedily by the **real bit-level
wire size** of each record (`EntityRecord::wire_bits`) — not the GDScript's fixed 10/3-byte table —
until `max_bytes * 8` bits are reached:

- **Pinned entries bypass the budget** but still *consume* bits, so an AoI-exit or stale-cache
  despawn is never budget-dropped — a client never loses an entity it was tracking until the next
  baseline.
- **No early break:** a smaller, lower-priority record may still fit after a larger one was deferred,
  so the loop continues past the first overflow.
- **Anti-starvation:** `ticks_since_last_sent` is added to priority, so an entity deferred enough
  ticks eventually outranks fresh near entities and gets sent. (New entities get
  `ticks_since = tick`, a large initial priority bump.)
- `max_bytes == 0` disables the budget. In practice the per-peer budget is never 0 — see below.
- Only the records the scheduler actually **selects** are committed to the delta cache
  (`update_cache_partial`); deferred records stay dirty.

Scheduler stats (`deferred`, `max_queue_age_ticks`, `hit_budget`) are aggregated per tick into
`BroadcastService::diagnostics` (`TickDiagnostics`: `entities_deferred_per_tick`,
`max_queue_age_ticks`, `peers_at_budget_pct`, `peers_evaluated`, plus cumulative
`snapshot_count_overflow`). These are surfaced on the `ServerMetrics` (type 68) broadcast and the HUD
(see [`performance-budgets.md`](performance-budgets.md)). When only pre-auth peers are connected, the
per-tick fields are zeroed so `ServerMetrics` doesn't re-broadcast stale numbers.

### Per-peer byte budget (bandwidth-derived)

The cap is not a single global number. At auth, `World::handle_connect_auth` (`world.rs`) derives a
per-peer budget from the client's advertised `bandwidth_budget_bps` (from `ConnectAuth`, falling back
to `default_client_bandwidth_bps`, clamped to `[min_client_bandwidth_bps,
max_client_bandwidth_bps]`): `per_peer_bytes = clamp(effective_bps / snapshot_rate_hz, 256,
max_snapshot_bytes)`. It's stored via `BroadcastService::set_peer_byte_budget`; `create_delta_packet`
reads it per peer (`peer_snapshot_bytes`), falling back to `max_snapshot_bytes` when absent (never 0,
since 0 would disable the budget).

## Baselines (skip AoI's byte budget)

A forced full-state Snapshot is built by `create_full_state_packet` (`broadcast.rs`) with **no byte
budget** — it emits all of the peer's currently-visible entities (the same AoI-filtered set), sets
`is_baseline`, resets `baseline_tick`, and rides **ch1 reliable** (must-arrive, acked, fragmentation
is fine) per [`../server/contract.md`](../server/contract.md). The client acks with
`BaselineAck{server_tick}`; the server only emits deltas against an **acked** baseline, so no delta
referencing tick T can be in flight before the client holds baseline T.

A baseline is due when `needs_full_state_for_interval` (every `DELTA_FULL_STATE_INTERVAL` = 100 ticks)
or `needs_baseline_resend` (un-acked for `BASELINE_ACK_TIMEOUT_TICKS` = 30 ticks) fires. **Gotcha:**
if AoI-exit removals are pending the same tick the baseline is due, the delta is sent instead (so the
removal isn't lost) and the baseline slips to the next tick — see the `baseline_deferred_when_removals_pending`
test. `handle_full_state_request` answers a client `RequestFullState` (type 4) with an **unfiltered**
full-state (all entities, no AoI) plus a `PLAYER_INFO` replay for every authenticated player
(Authority-sync recovery).

## Remaining caveats

The structural gaps are resolved (radius 1000/1100; shared spatial grid). What remains is
tuning-under-measurement, not missing mechanism:

| Caveat | Evidence | Consequence |
|---|---|---|
| **Not yet measured at target load.** The 1000/1100 radii and the shared grid are correct in shape but unproven at 500–1000 players. | `config.rs` defaults; `broadcast.rs` `SpatialGrid` | The scheduler diagnostics are wired precisely so this can be observed under load before further tuning. |
| **Far entities can still starve under budget pressure.** FAR penalty (−8) plus a tight budget defers far entities while clustered near entities saturate it. | `DISTANCE_PENALTY_BY_LOD` in `broadcast.rs` | Acceptable by design (anti-starvation eventually re-sends); now that the radius bounds the candidate set, the budget is a backstop rather than the primary cull. |
| **Baselines have no byte budget.** A baseline for a clustered player can exceed the 1200 B MTU — which is exactly why baselines ride **ch1 reliable** (fragmentation allowed). | `create_full_state_packet` (`broadcast.rs`) | Entity count is a `u16` on the wire, so the old u8-count truncation is gone; the `STATE_MAX_FULL_ENTITIES` (7280) cap is a diagnostic backstop that bumps `snapshot_count_overflow`. |

## Still planned

- **Measure at target load** — validate the 1000/1100 radii + grid against 500–1000 players using the
  surfaced scheduler diagnostics; add an AoI-clustering load scenario to `rust/load_test/`.

## The eight questions

- **Client:** receives the AoI-filtered Snapshot and despawns entities that left its AoI (`REMOVED`
  delta records); does no AoI itself.
- **Server:** the Rust `omega-server` builds the shared grid once and computes AoI, hysteresis, LOD,
  and budget per peer every Snapshot tick (`BroadcastService::broadcast_state_updates`,
  `rust/server/src/net/broadcast.rs`).
- **Predicted:** nothing — AoI is server-side Snapshot filtering, orthogonal to the shared-sim
  prediction (`sim_core` via the `client_ext` GDExtension).
- **Replicated:** only entities inside a peer's AoI are replicated to that peer; exits are despawned.
- **Persisted:** nothing — AoI/visibility/delta-cache state is in-memory per peer
  (`visible_entities`, `delta_caches`, `peer_snapshot_bytes`), cleared on disconnect
  (`BroadcastService::remove_peer`). Durable state is the Go API's job.
- **Validated:** the peer's own entity is never culled; pinned removals/despawns can't be
  budget-dropped; the 1000 enter radius stays ≥ `MONSTER_DETECTION_RANGE` so an aggro'd monster is
  never AoI-hidden.
- **Can fail:** unproven at 500–1000 players (now observable via the surfaced diagnostics); baseline
  ticks ignore the byte budget (mitigated by ch1 reliable + u16 count + `snapshot_count_overflow`
  warn).
- **Tested:** `rust/server/src/net/broadcast.rs` `#[cfg(test)]` unit tests cover delta-mask transitions,
  the baseline interval/ack/resend flow, scheduler pinned-bypass and no-early-break, the
  baseline→delta→removal sequence, on-ring hysteresis, and baseline-deferral-while-removals-pending.
  End-to-end load behavior is exercised by the `rust/load_test/` bot swarm; no dedicated
  AoI-clustering load scenario exists yet.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the Snapshot tick, batching, baseline
  cadence, and the byte/entity caps AoI feeds into
- [`../server/contract.md`](../server/contract.md) — the wire format (typed entity ids, Snapshot
  delta/baseline records, channels) AoI emits into
- [`performance-budgets.md`](performance-budgets.md) — the 500–1000-player targets the now-O(nearby)
  AoI scan must meet
