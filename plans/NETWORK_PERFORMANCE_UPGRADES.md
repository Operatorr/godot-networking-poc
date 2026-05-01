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
| **2** | §1.2 (priority queue), §1.3 (rate budget), §8.2 (scheduler diagnostics), §8.3 (bot regression suite) | TODO | Replaces modulo LOD; needs §1.1 in (done) and §8 hooks (started). |
| **3** | §3.1 (uniform grid)                 | TODO       | CPU headroom for higher peer counts; enables PvP rewind work.      |
| **4** | §2 (wire format), §7.1 (writer pool), §7.3 (de-box state) | TODO | Bandwidth + allocator tightening; needs bot regression suite from Phase 2. |
| **5** | §4 (PvP rewind), §5.1 (straddle interp), §5.2 (effect throttle audit) | TODO | Player-feel work — dependent on §1 timestamps + §3 grid.           |
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
