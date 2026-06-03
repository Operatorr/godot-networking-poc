# Network Performance Upgrades

Spec for the next wave of networking work for Omega Realm. Builds on the
in-flight changes (TASK-064/065/066: AoI, LOD frequency scaling, packet
batching) and aligns the protocol against the Valve in-game protocol design
notes (Bernier 2001) and the in-tree `RECOMMENDATIONS.md` checklist for
client-side prediction (CSP) and entity interpolation.

The intent is not to pick one big rewrite. It is to land a sequence of small,
measurable wins that each move the game closer to a CS-style "every player
runs on their own clock with no apparent latency" experience while keeping the
authoritative server cheap to scale horizontally.

Each track lists: motivation → concrete deliverables → acceptance signal.
Telemetry (bytes/sec per peer, server tick time, per-channel byte share) is
the contract — every track must publish a before/after number under the
existing `bot_swarm.py` baseline/target/stress scenarios.

---

## 0. Where we are today

**Already implemented**

- Authoritative server tick at 30 Hz with shared physics constants
  (`game_constants.gd`).
- Binary, length-prefixed wire protocol with quantized positions/angles
  (s16 @ 0.1 unit), delta compression, and forced full-state baselines every
  100 ticks (`packet_types.gd`, `state_update_packet.gd`).
- Client-side prediction with input sequence numbers, command buffer, and
  reconciliation against `ACTION_CONFIRM` (`prediction.gd`).
- Entity interpolation with a per-entity position-history buffer, capped
  extrapolation (≤2 ticks), and teleport detection
  (`interpolation_controller.gd`).
- Server-side rewind for PvE projectile hit tests
  (`monster_manager.record_position_snapshot` plus
  `MAX_PVE_PROJECTILE_COMPENSATION_TICKS`).
- AoI culling with hysteresis, distance-based LOD update frequency, and per-
  tick packet batching across all server-emitted messages
  (`server_broadcast_service.gd`, `network_manager.gd`).

**Known gaps relative to the Valve spec**

| Valve mechanism                              | Status        | Note                                                         |
| -------------------------------------------- | ------------- | ------------------------------------------------------------ |
| `cl_updaterate` / variable snapshot rate     | **Done (server-side)** | `ServerConfig.snapshot_rate_hz` decouples broadcast cadence from physics tick (§1.1). Client preference advertising is still TODO. |
| `rate` (per-client bandwidth budget)         | Missing       | No per-peer byte/sec ceiling; large bursts go unthrottled.   |
| Snapshot priority queue                      | Partial (LOD) | LOD throttling is modulo-based; not priority-based.          |
| PvP lag compensation                         | Missing       | Only PvE projectiles rewind; PvP hits use current tick.      |
| Effect throttling under re-prediction        | Unverified    | Need an audit pass on shoot/hit FX in `prediction.gd`.       |
| Position history with sub-tick straddling    | Partial       | We interpolate between the two newest snapshots, not target-time-straddled pairs in a longer history. |
| Spatial partitioning for AoI / collisions    | Missing       | AoI is O(N·M); projectile collision is per-entity scan.      |
| Unreliable transport (UDP / WebTransport)    | Missing       | All traffic on TCP-backed WebSocket — head-of-line blocking. |
| Server clock sync                            | **Done**      | `HEARTBEAT` carries `server_ms`; client maintains EMA-filtered offset (§5.4). |
| Per-channel byte breakdown                   | **Done**      | `NetworkManager.bytes_sent_by_type` exposed via `ServerMetrics` (§8.1). |
| AoI per-entity Dict allocation               | **Done**      | LOD tag now travels in a parallel `PackedByteArray`, no `Dictionary.duplicate()` (§7.2). |
| Client/server teleport threshold parity      | **Done**      | Interpolation controller imports `GameConstants.TELEPORT_THRESHOLD` (§5.3). |
| Bot-driven regression assertions             | **Partial**   | Phase 2 step 1: `regression_assertions.py` ships AoI / LOD-cadence / batch-decode / per-peer-budget assertions; the per-peer-budget one is wired but skipped until §1.3 advertises a budget (§8.3). |

The rest of this document is the prioritized plan to close those gaps.

---

## 1. Snapshot Pipeline (highest leverage)

### 1.1 Decouple snapshot rate from tick rate

Today every physics tick produces a `STATE_UPDATE` per peer. Source/Half-Life
sends 20 snapshots/s by default off a higher physics tick. With the current
30 Hz tick this is bandwidth we don't need on a fast LAN and bandwidth we
**can't afford** for a remote player on a marginal connection.

- Add `snapshot_rate_hz` (default 20) and `snapshot_min_rate_hz` (default 10)
  to `ServerConfig`.
- Server records every tick into per-entity history (we already do this for
  monsters; extend to players/projectiles).
- Snapshot loop runs on its own accumulator (`snapshot_timer`) — emit a state
  packet only when the accumulator elapses.
- Per-client effective snapshot rate is `min(client.requested_rate,
  snapshot_rate_hz)`. Clients advertise their preference in the
  `CONNECT_AUTH` payload (new `requested_snapshot_hz` u8 field).

**Acceptance:** at 20 Hz snapshot rate, peer egress drops by ~33% vs the
current 30 Hz, and server CPU drops measurably (`server_metrics.avg_tick_time`
≤ baseline).

### 1.2 Priority-based entity selection ("budgeted snapshots")

Replace LOD modulo gating with a priority queue per client. Priority for an
entity (per peer, per tick) is roughly:

```
priority = importance(entity_type)
         + ticks_since_last_sent_to_peer
         - distance_penalty(dist_sq)
         + change_bonus(delta_mask)
```

Send entities in priority order until a per-snapshot byte budget is hit
(`max_snapshot_bytes`, default e.g. 1200 bytes — fits a typical MTU after
headers). Entities that didn't make the cut keep accruing
`ticks_since_last_sent` and bubble up next tick.

This generalizes both LOD frequency scaling and the Valve "rate"-driven
delivery: a low-bandwidth peer just gets a smaller `max_snapshot_bytes` and
the queue handles the rest. It also fixes a subtle bug in modulo LOD —
nothing currently guarantees a FAR entity ever fits inside a packet under
heavy entity counts.

**Acceptance:** under the `stress` scenario, no peer's outbound traffic
exceeds `max_snapshot_bytes * snapshot_rate_hz` over any 1 s window.

### 1.3 Per-client bandwidth budget (`rate`)

Mirror Valve's `rate` cvar. Each client publishes a max-bytes-per-second
budget in `CONNECT_AUTH`. The snapshot scheduler uses the budget to size
`max_snapshot_bytes` and to gate non-essential events (e.g. defer
`LEADERBOARD_UPDATE` when the peer is saturated). Hard-cap at 256 KB/s to
prevent abuse.

**Acceptance:** `peer_bytes_sent` deltas stay below each peer's advertised
budget over any rolling 1 s window in the stress scenario.

---

## 2. Wire Format Tightening

These are pure bandwidth wins; no behavior change client-side beyond decoding.

### 2.1 Variable-length entity IDs

Players never exceed 100 (`max_players`). Most player IDs fit in a u8; only
projectile/monster IDs need u16. Add an entity-ID encoding hint in the entity
LOD/type byte:

- Reserve a bit in the per-entity header indicating "id is u8 vs u16".
- Saves 1 byte per entity per delta. With ~50 visible entities × 20
  Hz = ~1 KB/s/peer.

### 2.2 Delta-encoded positions

Today every position is an absolute `s16` quantized at 0.1 units. For deltas,
the change since the cached value is usually < ±20 units; that fits in two
`s8`s. Add a delta-position bit:

- `DELTA_MASK_POSITION_SMALL`: read two `s8`s, apply as offset from cached.
- `DELTA_MASK_POSITION` keeps current behavior for big jumps / spawns.
- Wins: ~2 bytes per moving entity per tick. At stress (~150 moving entities,
  20 Hz, 50 peers) this is ~3 MB/s of egress saved fleetwide.

### 2.3 Drop redundant entity_type on subsequent deltas

Entity type cannot change across an entity's lifetime. Today we re-send it on
every full-state slot inside a delta packet. Strip it everywhere except the
initial "first time visible to this peer" path.

**Acceptance for the section:** stress baseline `total_bytes_sent` drops by
≥25% with no behavioral regressions in the bot validation suite.

---

## 3. Spatial Partitioning

### 3.1 Uniform-grid broad phase

`_filter_entities_by_aoi` is O(N·M); projectile collision in
`projectile_manager.check_collisions_with_*` is similar. Both can share one
uniform grid keyed by `floor(pos / cell_size)` with `cell_size ≈ aoi_radius
/ 4`.

- Build the grid once per tick after physics integration.
- AoI: query cells inside `(player_pos, aoi_radius)`.
- Projectile broad phase: query cells along the swept segment.
- Monster spawn validity: query the grid instead of scanning all monsters.

This also unblocks future features (vision cones, audio falloff, LoS) by
giving them a cheap broad-phase primitive.

**Acceptance:** at 100 players × 100 monsters, server `avg_tick_time` halves
relative to the current array-scan baseline.

### 3.2 Optional: line-of-sight AoI

Layer LoS on top of the grid: an entity in AoI but behind an obstacle
(`GameConstants.ARENA_OBSTACLES`) is demoted one LOD tier (or fully culled
for very-distant occluders). Requires a fast ray vs. obstacle test against
the static obstacle set; the existing `line_intersects_obstacle` helper is
reusable. Revisit only after 3.1 ships.

---

## 4. Lag Compensation Coverage

Per the Valve spec, lag compensation is the difference between "have to lead
my target" and "click to hit." Today we lag-compensate PvE only.

### 4.1 PvP projectile rewind

Extend the existing position-history mechanism to players. On a PvP-source
projectile spawn:

- Compute `rewind_ticks = clamp(client_render_tick gap, 0, MAX_PVP_LIMIT)`
  with a **stricter** cap than PvE (default 4 ticks ≈ 133 ms) per the Valve
  warning about "shooting around corners."
- During collision tests, compare the projectile against rewound positions of
  potential victims.
- Mark hits with the lag-compensated tick in `ACTION_CONFIRM` for client
  attribution.

### 4.2 Hitscan path (future-proofing)

When hitscan weapons land, the same rewind pipeline applies — but with an
extra trust check: reject the hit if `rewind_ticks > MAX_PVP_LIMIT` or the
shooter's reported `client_render_tick` is wildly inconsistent with their
RTT. Log to `server_metrics` as `cheat_signals` for later review.

**Acceptance:** PvP hits feel responsive at 100 ms RTT in the QA bench, and
rewind never modifies projectile victims older than `MAX_PVP_LIMIT * tick_ms`.

---

## 5. CSP & Interpolation Audit

Per `RECOMMENDATIONS.md`. These are correctness items, not throughput.

### 5.1 Position-history interpolation that straddles target time

`interpolation_controller.gd` already keeps a per-entity buffer, but
`_calculate_interpolated_position` interpolates between "current tick" and
"next tick" snapshots rather than searching the buffer for the pair that
**straddles `client_time - interp_delay`**. Under variable snapshot spacing
(see §1.1) the difference matters: spaced packets need straddle search to
stay smooth.

- Implement `EntityStateBuffer.get_pair_for_target_time(t)` returning the two
  snapshots whose timestamps bracket `t`.
- Drive `t` from server timestamps embedded in `STATE_UPDATE`
  (`server_tick * tick_interval`).

### 5.2 Effect-throttling under re-prediction

When the client re-runs unacknowledged inputs after a correction
(`prediction.gd::_replay_inputs`), shoot SFX / muzzle flashes / footsteps
must only fire on the **first** simulation of each input. Add a `predicted`
boolean to the shared shoot path; the first-pass call sets `played=true` on
the input snapshot, replay calls inspect that flag and skip.

### 5.3 Teleport threshold parity

The interpolation controller has `TELEPORT_DISTANCE_THRESHOLD`; we should
share the constant with server validation
(`GameConstants.TELEPORT_THRESHOLD`) so a teleport on the server is also
treated as a teleport on the client (no smooth-interp through the map).

### 5.4 Clock sync packet

Per the Valve spec footnote 6: clients should adopt a server clock so
`client_time` and the `server_tick` line up. We already pass `server_tick`
into client packets, but we never resync the wall clock. Add an explicit
`SERVER_TIME_SYNC` field piggybacked on every Nth heartbeat (`{u32 server_ms,
u32 echoed_client_ms}`); client maintains a low-pass-filtered offset.

**Acceptance:** the bot suite reports < 5 ms RMS clock drift at 1 Hz sync.

---

## 6. Transport-Layer Options

### 6.1 WebSocket → WebTransport (datagrams)

WebSocket sits on TCP, so a single dropped packet stalls every snapshot
behind it. WebTransport (HTTP/3 datagrams) is the drop-in modern equivalent
and Godot 4.6 ships preliminary support. Migration plan:

1. Keep WebSocket for handshake + reliable channel (auth, leaderboard, chat).
2. Move `STATE_UPDATE` and `PLAYER_INPUT` to a parallel datagram channel.
3. Fall back to WebSocket if the datagram channel fails to negotiate.

This unlocks meaningful latency reduction for international peers and is the
biggest single user-perceptible improvement once §1 and §2 are in.

### 6.2 Per-channel reliability

Even on TCP, we can split logical channels: bulk state on one socket, events
on another. Less impactful than 6.1 but a useful intermediate if the
datagram migration slips.

---

## 7. Server CPU & Memory

### 7.1 Reuse `PacketWriter` buffers

`_encode_packet` allocates a fresh `PacketWriter` (and its
`PackedByteArray`) for every send. Under stress this is the largest
allocator on the server (verified via Godot profiler in past sweeps). Add a
small pool keyed by approximate buffer size; reset and reuse.

### 7.2 Avoid per-entity `Dictionary.duplicate()`

The new AoI filter clones each visible entity dict to attach `_lod`. At
scale this costs ~hundreds of thousands of dict copies/s. Replace with a
parallel `Array[int]` of LOD tiers keyed positionally to `visible_entities`.

### 7.3 Stop boxing entity state through `Dictionary`

The hot path goes
`PlayerState → Dictionary → DeltaCache compares → Dictionary entries →
PacketWriter`. A typed struct (small RefCounted with ints/Vector2 fields)
avoids hashed lookups. Worth measuring before committing — the readability
hit is real.

---

## 8. Observability

You can't tune what you can't see. Land before/with the work above.

### 8.1 Per-channel byte breakdown

Extend `ServerMetrics` to track bytes by `MessageType`:
`{state_update, game_event, action_confirm, batch_overhead, ...}`. Surface
in `SERVER_METRICS` so the in-game HUD can show the dominant channel. Goal:
identify regressions instantly when a refactor blows up bandwidth.

### 8.2 Snapshot scheduler diagnostics

When §1.2 lands, expose: per-tick "items deferred" count, max queue age, and
peers that hit byte budget. These are the indicators that tell us whether
the queue is healthy or starving entities.

### 8.3 Bot-driven regression suite

Augment `bot_swarm.py` with assertions:

- AoI cull: a bot at the far edge of the map should observe ~zero entities
  beyond `aoi_radius + aoi_exit_radius_margin`.
- LOD: the bot's stream of position updates for a NEAR peer arrives every
  tick; FAR every ~`lod_far_interval` ticks.
- Batch unwrap: every received WebSocket frame either has type
  `STATE_UPDATE` etc. or is a BATCH whose inner packets all decode.

Run on CI under each scenario; fail the build on regressions.

---

## 9. Roadmap

The order matters: each phase unblocks the next.

| Phase | Tracks                              | Status     | Why this order                                                     |
| ----- | ----------------------------------- | ---------- | ------------------------------------------------------------------ |
| **1** | §8.1 (per-channel bytes), §7.2 (no AoI dict alloc), §5.3 (teleport parity), §5.4 (clock sync), §1.1 (decoupled snapshot rate) | **Shipped** | Need numbers before tuning; ship the highest-leverage decoupling so subsequent work has knobs. |
| **2** | §1.2 (priority queue), §1.3 (rate budget), §8.2 (scheduler diagnostics), §8.3 (bot regression suite) | **In progress** | Step 1 shipped. Step 2 is halfway through: scheduler module + config knobs are implemented, broadcast-service wiring is in progress, ServerMetrics diagnostics and unit tests remain. Step 3 still pending. |
| **3** | §3.1 (uniform grid)                 | TODO       | Single focused PR. Promotes `projectile_manager`'s ad-hoc grid scaffolding to a shared `spatial_grid.gd` used by AoI, projectile broad-phase, monster spawn validity, and the static obstacle test. CPU headroom for higher peer counts; enables PvP rewind work. |
| **4** | §2 (wire format), §7.1 (writer pool), §7.3 (de-box state) | TODO | Single PR with `WIRE_VERSION` bump. **All three §2 sub-changes** (varint IDs, delta-encoded positions, drop redundant entity_type) ship together — bot suite from Phase 2 is the symmetry net. **§7.3 ships** (typed `EntityWireSnapshot` replaces the `to_entity_data()` Dict). |
| **5** | §4 (PvP rewind), §5.1 (straddle interp), §5.2 (effect throttle guard) | TODO | Player-feel work — dependent on §1 timestamps + §3 grid. Exploration confirmed §5.2 is **already correct** (prediction.gd::_replay_input does no FX firing); ship it as a comment + debug-only assertion that locks the invariant in. |
| **6** | §6 (transport), §3.2 (LoS AoI)      | TODO       | Largest engineering surface; do last when wins are quantified.     |

**Definition of done for the document:** every phase ships behind a config
flag, with the bot-swarm regression suite green and a documented
before/after telemetry snapshot in `docs/PERFORMANCE_NOTES.md`.

### Phase 1 implementation notes

Phase 1 landed in the same change-set that introduced this document. Concrete
artifacts:

- `ServerConfig.snapshot_rate_hz` (default `0` = match tick rate). Verified by
  setting to 20 with 30 Hz tick rate; broadcast loop fires on a 2-of-3 tick
  cadence. Acceptance signal pending under bot-swarm baseline runs.
- `NetworkManager.bytes_sent_by_type` accumulates per-`MessageType` bytes;
  `ServerMetrics.bytes_sent_by_type` snapshots the cumulative counter into
  the periodic `SERVER_METRICS` broadcast. Consumers diff samples to derive
  bytes/sec per channel.
- `_filter_entities_by_aoi` returns `{entities, lods}` — `lods` is a
  `PackedByteArray` parallel to `entities`, eliminating ~N dict-copies/tick.
- `HEARTBEAT` payload widened to `[u32 timestamp][u32 server_ms]`.
  `NetworkManager.get_server_time_ms()` returns 0 until at least one sample
  is filtered in (EMA, α=0.2). Available for future use by interpolation
  straddle search (§5.1) and lag-compensated PvP (§4).
- `InterpolationController.TELEPORT_THRESHOLD` now references
  `GameConstants.TELEPORT_THRESHOLD` directly so a future server-side change
  cannot drift from client behavior.

### Phase 2 implementation notes

Phase 2 is being shipped as a **single PR** ordered into three internal steps so
each commit is independently reviewable while the bot regression suite (step 1)
guards the behavioral changes that follow (steps 2–3).

Current resume status:

- **Done:** implement `client/scripts/server/snapshot_scheduler.gd`.
- **Done:** add scheduler config knobs (`ServerConfig.max_snapshot_bytes`,
  default `1200`, wired into `ServerBroadcastService` from `ServerMain`).
- **In progress:** wire scheduler into `server_broadcast_service.gd`.
- **Open:** plumb scheduler diagnostics through `ServerMetrics` and the
  `SERVER_METRICS` payload.
- **Open:** add unit tests for `SnapshotScheduler` and the broadcast-service
  scheduling edge cases.

#### Step 1 — Bot regression suite (§8.3) — **Shipped**

Concrete artifacts:

- `load_testing/bot_client.py` — `BotMetrics` extended with four assertion-tracking
  fields:
  - `decode_failures: int` — incremented in `_handle_batch_payload` on
    truncate / overflow / empty-payload paths so any malformed BATCH envelope
    surfaces loudly instead of being silently dropped at debug log level.
  - `entity_observations: dict[int, list[tuple[int, float]]]` — per-entity
    `(server_tick, distance_to_self)` log written by the new
    `_record_observations_for_assertions` hook in `_handle_single_message`
    after each `STATE_UPDATE` parse. Capped at 4096 samples/entity so long
    stress runs stay within ~10 MB worst case per bot.
  - `max_observed_entity_distance: float` — running max for the AoI cull
    assertion, only updated after the bot knows its own entity_id.
  - `bytes_received_samples: list[tuple[float, int]]` — reserved for the
    rolling-window per-peer-budget assertion that activates with §1.3.
- `load_testing/regression_assertions.py` (new) — four assertions plus driver:
  - `assert_aoi_cull` — `max_observed_entity_distance ≤ aoi_exit_radius + 50u`
    tolerance; passes if ≥95% of eligible bots stay within budget.
  - `assert_lod_cadence` — bins per-entity tick gaps by NEAR / MID / FAR using
    the average distance over the gap, asserts band median is within ±50% of
    the configured interval (with +1 floor for NEAR's expected gap of 1).
  - `assert_batch_decode_clean` — zero-tolerance gate on `decode_failures` —
    any failure points to a server bug or protocol drift.
  - `assert_per_peer_budget` — skipped until `AssertionConfig.rate_budget_bytes_per_sec`
    is non-zero; will check rolling 1 s windows once §1.3 lands.
  - `AssertionConfig` mirrors `server_config.gd` defaults so the suite stays
    accurate across environments; callers override when the server is
    non-default.
- `load_testing/bot_swarm.py` — new `--assertions {strict,warn,off}` flag
  (default `warn`) and `--rate-budget` flag. `run_all` runs after
  `aggregate_metrics` regardless of `--no-report`; results render below the
  success-criteria block and are serialized into the JSON report. **Strict
  mode exits with code `2`** (distinct from `1` for success-criteria failure)
  so CI can tell the two apart.

End-to-end against a live server is **deferred to step 3** when the
CONNECT_AUTH wire change forces a server boot anyway. Synthetic pass / fail /
skip paths verified via in-process bot fabrication; existing `test_bot_client.py`
suite (19 tests) still green.

#### Step 2 — Priority queue + scheduler diagnostics (§1.2 + §8.2) — **In progress**

Replaces the old modulo LOD gating
(`server_broadcast_service.gd::_should_send_position_for_lod`) with a per-peer
priority queue. That helper has been removed in the current diff, and LOD
tiers now feed the scheduler as a distance penalty instead of fixed update
intervals.

Implemented in the current diff:

- `client/scripts/server/snapshot_scheduler.gd` (new `RefCounted`) owns
  candidate priority calculation, pinned candidate handling, byte-budget
  selection, and result diagnostics (`deferred_count`,
  `max_queue_age_ticks`, `bytes_used`, `hit_budget`, `candidate_count`).
- `ServerConfig.max_snapshot_bytes` added with default `1200`; `0` disables
  budget deferral while preserving scheduler ordering.
- `ServerMain._initialize_server` assigns `config.max_snapshot_bytes` to
  `broadcast_service.max_snapshot_bytes`.
- `ServerBroadcastService` preloads `SnapshotScheduler`, creates one scheduler
  per peer alongside `DeltaStateCache`, and erases scheduler state on peer
  disconnect / cache clear.
- `_create_delta_packet` now stages candidate entries, pins removals / stale
  despawns so clients do not retain orphaned entities, schedules everything
  else against `max_snapshot_bytes`, and only updates the delta cache for
  entries that were actually selected. Deferred entities should therefore
  stay dirty and bubble up on later snapshots.
- `ServerBroadcastService.last_tick_diagnostics` is populated with
  `entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct`,
  and `peers_evaluated`, but these values are not yet exposed through
  `ServerMetrics`.

Priority details currently implemented:

  ```
  priority = importance(entity_type)              # PLAYER=10, PROJECTILE=8, MONSTER=4
           + (current_tick - cache.last_tick_sent[entity_id])
           - distance_penalty(lod_tier)           # NEAR=0, MID=4, FAR=8
           + change_bonus(delta_mask)             # position/anim/flags +2 each; full/remove +6
  ```

Remaining Step 2 work before closing it:

- Finish / verify the broadcast-service integration. Pay special attention to
  full-state baseline behavior, pinned removals exceeding the byte budget, and
  cache correctness for deferred partial deltas.
- Plumb `broadcast_service.last_tick_diagnostics` into
  `ServerMetrics.update_metrics`, store it in `ServerMetrics.metrics`, and
  include it in the `SERVER_METRICS` packet.
- Add focused unit coverage for `SnapshotScheduler.compute_priority`,
  `schedule(max_bytes)`, pinned candidates, zero-budget behavior, deterministic
  priority tie-breaking, and deferred-candidate cache behavior in
  `_create_delta_packet`.
- Run the existing bot-client tests plus the Phase 2 assertion suite after the
  diagnostics surface is complete. The new `assert_lod_cadence` remains the
  safety net for starvation across LOD bands.

#### Step 3 — Per-client bandwidth budget (§1.3) — TODO

Wire change. Bumps `WIRE_VERSION` to 2.

- `client/scripts/shared/networking/packets/auth_packet.gd` gains two fields
  after `player_color`:
  - `requested_snapshot_hz: u8` (0 = use server default; clamped to
    `[snapshot_min_rate_hz, snapshot_rate_hz]` server-side)
  - `rate_budget_bytes_per_sec: u32` (0 = unlimited; hard-cap server-side at
    256 KB/s)
- `packet_types.gd` introduces `WIRE_VERSION = 2`; mismatched `CONNECT_AUTH`
  rejected server-side with explicit error code so old clients don't connect
  silently.
- Server stores per-peer prefs alongside `delta_caches` in
  `server_broadcast_service.gd`; per-peer
  `max_snapshot_bytes = min(default, rate_budget / effective_snapshot_rate)`.
- Client surface: `client/scripts/client/user_preferences.gd` adds a
  Bandwidth pref (Auto / Low / Medium / High → byte budgets), default Auto.
- Bot suite gains a `--rate-budget` invocation in CI to exercise
  `assert_per_peer_budget` end-to-end.

---

## Phases 3–5 — direction, strategy, and decisions

The following decisions were locked in after the Phase 2 step-1 implementation
work, so future contributors don't relitigate them:

### Phase 3 — uniform spatial grid (§3.1)

Single focused PR, no wire change, no behavioral change. Promotes the existing
ad-hoc grid scaffolding (`projectile_manager.gd:20/127/141` —
`GRID_CELL_SIZE=64`, `_build_entity_grid`, `_query_nearby`) into a shared
`client/scripts/server/spatial_grid.gd` (RefCounted) and adopts it across:

- `server_broadcast_service._filter_entities_by_aoi` (replaces O(N·M) scan)
- `projectile_manager.check_collisions_with_players` and
  `check_collisions_with_monsters` (drop the local grid build)
- `monster_spawner.gd` spawn-validity scan
- `game_constants.circle_intersects_obstacle` /
  `line_intersects_obstacle` (one-time grid built at boot for static obstacles)

`cell_size = aoi_radius / 4` per the spec. The lag-compensated projectile path
keeps per-tick grids built on rewound positions but uses the same module.

**Acceptance:** at 100 players × 100 monsters, server `avg_tick_time` halves
vs Phase 2 baseline. Bot suite still green.

### Phase 4 — wire format + writer pool + de-box state

Single PR. **Bumps `WIRE_VERSION` to 3.** Old clients rejected with explicit
error. Bot suite (Phase 2) is the symmetry net. All sub-changes ship together
to avoid multiple wire bumps:

- **§2.1 Variable-length entity IDs** — reserve bit 5 (`DELTA_MASK_ID_WIDE`)
  in the per-entity delta_mask byte: 0 = u8 id, 1 = u16 id. Same scheme via a
  type-byte header bit in full-state entries. Encoder picks narrowest fit.
  Touch points: `state_update_packet.gd:198/211` (encode), `253/267` (decode).
- **§2.2 Delta-encoded positions** — reserve bit 6
  (`DELTA_MASK_POSITION_SMALL`). When set: read two `s8` offsets; apply to
  cached position. Encoder uses small-delta when both quantized offsets fit
  in `[-127, 127]`. `DeltaStateCache.position` (`delta_state_cache.gd:14`)
  already retains the value to subtract.
- **§2.3 Drop redundant entity_type** — already correct in the delta path
  (`state_update_packet.gd:216` only writes `entity_type` when
  `DELTA_MASK_FULL_STATE` is set). The redundancy is in the full-state path:
  add `ENTITY_FLAG_HAS_TYPE` header bit so encoder can omit type for
  entities the client already knows.
- **§7.1 PacketWriter pool** — new
  `client/scripts/shared/networking/packet_writer_pool.gd` (FIFO, size cap 32)
  living on `NetworkManager`. Replaces `PacketWriter.new()` at
  `state_update_packet.gd:169`, `network_manager.gd:594`, and any other call
  sites grep finds. Pool calls existing `writer.reset()`
  (`packet_writer.gd:187`).
- **§7.3 De-box entity state** — new
  `client/scripts/shared/networking/entity_wire_snapshot.gd` (typed
  RefCounted: `entity_id`, `entity_type`, `position`, `animation_state`,
  `flags`). Replaces the `to_entity_data() -> Dictionary` methods on
  `PlayerState:82`, `MonsterState:122`, `ProjectileState:154` with
  `to_wire_snapshot(out) -> void` writing into a pre-allocated snapshot.
  `DeltaStateCache.calculate_delta_mask` (`delta_state_cache.gd:71`) takes
  the typed snapshot directly — no more `Dictionary.get()` lookups in the
  delta hot path. Snapshot objects pooled per peer per tick.

**Acceptance:** stress baseline `total_bytes_sent` drops ≥25% vs Phase 3
baseline; bot regression suite green; `avg_tick_time` flat or improved;
`PacketWriter` no longer in top-3 server-side allocators.

### Phase 5 — PvP rewind + straddle interpolation + effect-throttle guard

Single PR. Player-feel work, dependent on Phase 1 (clock sync) and Phase 3
(spatial grid).

- **§5.1 Straddle interpolation** — `EntityStateBuffer` already captures
  `timestamp_ms` per snapshot (`entity_state_buffer.gd:23/43`) but it's
  unused. Add `get_pair_for_target_time(target_ms)` returning
  `[before_snap, after_snap, factor]`.
  `InterpolationController._calculate_interpolated_position` (line 459)
  computes `target_ms = NetworkManager.get_server_time_ms() - RENDER_DELAY_MS`
  and calls the new method. While `get_server_time_ms()` returns 0
  (pre-handshake), fall back to the existing tick-based path so we don't
  break interpolation before the first heartbeat samples in.
- **§4 PvP projectile rewind** — `player_manager.gd` mirrors
  `monster_manager.gd`'s position-history pattern:
  - `_position_history: Dictionary` keyed by `server_tick`, retained for
    `MAX_PVP_PROJECTILE_COMPENSATION_TICKS` ticks (new constant, **default 4**
    — stricter than PvE's 6 per the Valve "shooting around corners" warning).
  - `record_position_snapshot(server_tick)` called from
    `server_main._process_server_tick` after physics.
  - `get_alive_player_snapshot(server_tick)` with the same exact-or-fallback
    pattern as `monster_manager.get_alive_monster_snapshot`.
  - `projectile_manager.check_collisions_with_players` (line 246) for PvP
    projectiles uses rewound positions queried through the shared spatial
    grid (Phase 3).
  - `ACTION_CONFIRM` payload extended with the lag-compensated tick (extra
    `u32`) for client-side hit attribution.
  - New `ServerMetrics.cheat_signals` counter for rewind-cap violations.
- **§5.2 Effect-throttle guard** — exploration confirmed
  `prediction.gd::_replay_input` already does no FX firing (effects are
  entirely server-event-driven from `arena_base.gd`). Decision:
  **lock the invariant in** rather than skip:
  - One-line block comment above `_replay_input` documenting the invariant.
  - Debug-only assertion via a thread-local `_in_replay: bool` flag, with
    `audio_manager.gd` and particle/effect entry points asserting
    `not Prediction._in_replay` in debug builds. Compiles out in release.

**Acceptance:** straddle interp produces visibly smoother motion at
`snapshot_rate_hz=15`; PvP hits at 100 ms simulated RTT register on rewound
positions (verifiable by sending a synthetic projectile from a bot and
asserting the hit tick on `ACTION_CONFIRM` matches the rewound tick); bot's
`_in_replay` assertion never fires across a 2-minute stress run; bot suite
reports no regression in any prior-phase assertion.

### Cross-phase verification protocol

For every phase before merging:

1. `./scripts/deploy.sh up` — local stack boots cleanly.
2. `python load_testing/smoke_test.py` — single-bot integration green.
3. `python load_testing/bot_swarm.py --scenario baseline --assertions strict` — green.
4. `python load_testing/bot_swarm.py --scenario target --assertions strict` — green.
5. `python load_testing/bot_swarm.py --scenario stress --assertions strict` — green; capture before/after numbers.
6. Manual play-test (human + bot fleet) — no visible regressions.
7. Append a telemetry snapshot (bytes/sec by channel, `avg_tick_time`, queue diagnostics where applicable) to `docs/PERFORMANCE_NOTES.md`.

---

## Appendix A — Mapping to source material

- *RECOMMENDATIONS.md*: §5.1 (history straddle), §5.2 (effect throttling),
  §5.3 (teleport parity) directly cover the "Implementation Checklist for
  Remote Players" and "Effect Throttling" items.
- *Valve / Bernier 2001*: §1.1 implements `cl_updaterate`-style decoupled
  snapshot rate; §1.3 implements the `rate` cvar; §4 implements
  lag-compensation as described in "Lag Compensation"; §5.4 implements the
  clock sync described in footnote 6; §6 addresses footnote 7 (variable
  packet spacing under bandwidth pressure).
