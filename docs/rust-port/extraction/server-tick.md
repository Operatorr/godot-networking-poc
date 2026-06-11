# Server tick loop, snapshot/broadcast pipeline, spatial grid, metrics, config

> Generated extraction notes for the Rust port — derived from GDScript at commit `9e661497a994dcdb2a0d07f73724604af7b01cc5` on branch `feature/rust-port`. Source of truth is the GDScript until cutover.

Subsystem sources (all paths relative to repo root, all under `client/`):

| File | Role |
|---|---|
| `client/scripts/server/server_main.gd` | tick loop, input/shoot pipeline, message dispatch, region heartbeat, shutdown |
| `client/scripts/server/server_broadcast_service.gd` | AoI filter, delta/baseline packet build, per-peer budgets, diagnostics |
| `client/scripts/server/snapshot_scheduler.gd` | per-peer byte-budget priority scheduler |
| `client/scripts/server/spatial_grid.gd` | uniform spatial-hash broad-phase |
| `client/scripts/server/server_metrics.gd` | tick-time + bandwidth metrics, SERVER_METRICS source data |
| `client/scripts/server/server_config.gd` | JSON config loader + env override |
| `client/scripts/server/delta_state_cache.gd` | per-peer delta compression cache + baseline-ack state (read for contract; owned by this pipeline) |

Related per the migration spec: D8 (single-threaded 30 Hz tick, drain inputs → movement → AI → lag-comp history → collisions → snapshots → cleanup), D7 (protocol redesign — wire *bytes* here are reference only, *semantics* carry forward), D11 (hit authority — the `LOCAL_HIT_REPORT` handling documented here is the server side of that model), D13 (the region heartbeat generalizes into instance liveness).

---

## 1. Overview

This subsystem is the **authoritative server main loop**. One Godot headless process runs it; the Rust port runs it as the single synchronous tick thread (D8).

- A **manual accumulator inside the per-frame `_process(delta)` callback** drives a fixed **30 Hz tick** (NOT Godot's physics tick). Each engine frame, `tick_timer += delta`, then a `while tick_timer >= tick_interval` loop fires zero or more ticks. There is no FPS cap on the headless server; `_process` runs as fast as the OS schedules, busy-spinning between ticks.
- Each tick, **in exact order**: snapshot-due accumulator → open packet batch window → drain & apply client inputs (incl. shoot spawning + move confirmations) → update game state (projectiles, monster spawner, invuln/respawn timers, leaderboard timer) → monster AI (+ monster `PROJECTILE_FIRED` events) → record monster & player position history (lag-comp) → collisions → *(if snapshot due)* build shared AoI grid + per-peer broadcast → cleanup dead monsters → flush batches → record tick time.
- The **snapshot cadence is decoupled** from the tick by a second accumulator; with the live config (`snapshot_rate_hz = 30` = tick rate) a snapshot fires **every tick**. Game events (`GAME_EVENT`, `ACTION_CONFIRM`) fire every tick regardless.
- The **broadcast pipeline** per authenticated peer: spatial-grid candidate query → AoI radius filter with enter/exit hysteresis (1000/1100 u) → LOD classification (near/mid/far) → delta-mask computation against a per-peer cache → byte-budget priority scheduler → one `STATE_UPDATE` packet per peer (baseline or delta).
- A **1 Hz metrics pass** (in `_process`, outside the tick) updates `ServerMetrics` and broadcasts a `SERVER_METRICS` packet; a **2 s region-status heartbeat** POSTs liveness JSON to the Go API.

---

## 2. Constants

### 2.1 Tick / loop constants (`server_main.gd`)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `LEADERBOARD_BROADCAST_INTERVAL` | `5.0` | seconds of **tick time** (= 150 ticks @30 Hz; advanced by `tick_interval` per tick, not wall clock) | `server_main.gd:46` |
| `REGION_STATUS_HEARTBEAT_INTERVAL` | `2.0` | seconds of **wall time** (`_process` delta) | `server_main.gd:47` |
| `MIN_SNAPSHOT_FLOOR` | `256` | bytes (floor of the per-peer snapshot byte cap) | `server_main.gd:51` |
| `LOCAL_HIT_REPORT_MAX_PER_SECOND` | `20` | reports per peer per sliding 1000 ms window | `server_main.gd:760` |
| `LOCAL_HIT_VALIDATION_MARGIN` | `64.0` | world units of slack added to the hit radius for plausibility | `server_main.gd:766` |
| metrics update interval | `1.0` | seconds (hardcoded comparison) | `server_main.gd:195` |
| `monster_spawn_rate` (export var) | script default `GameConstants.MONSTER_SPAWN_RATE * 2.0` = `0.4`; **scene override = `0.1` (the live value)** | monsters/second | `server_main.gd:11-13`; `client/scenes/server/server_main.tscn:7` |

### 2.2 Game constants consumed by this subsystem (`client/scripts/shared/game_constants.gd`)

| Constant | Value | Source |
|---|---|---|
| `SERVER_TICK_RATE` | `30.0` (float) | `game_constants.gd:22` |
| `SERVER_TICK_INTERVAL` | `1.0 / 30.0` | `game_constants.gd:25` |
| `REMOTE_ENTITY_RENDER_DELAY_TICKS` | `2` | `game_constants.gd:33` |
| `MAX_PVE_PROJECTILE_COMPENSATION_TICKS` | `6` | `game_constants.gd:40` |
| `MAX_PVP_PROJECTILE_COMPENSATION_TICKS` | `4` | `game_constants.gd:45` |
| `PLAYER_SPEED` | `200.0` u/s | `game_constants.gd:53` |
| `PLAYER_SPRINT_MULTIPLIER` | `1.6` | `game_constants.gd:56` |
| `PLAYER_SPRINT_SPEED` | `200.0 * 1.6` = `320.0` u/s | `game_constants.gd:59` |
| `POSITION_TOLERANCE` | `75.0` u | `game_constants.gd:161` |
| `PROJECTILE_RADIUS` | `8.0` u | `game_constants.gd:335` |
| `PLAYER_HITBOX_RADIUS` | `16.0` u | `game_constants.gd:343` |
| `SHOOT_COOLDOWN` | `0.3` s | `game_constants.gd:364` |
| `MONSTER_SPAWN_RATE` | `0.2` monsters/s | `game_constants.gd:379` |
| `MONSTER_ENTITY_ID_START` | `30000` | `game_constants.gd:386` |

Derived values used inline:
- Projectile spawn offset distance = `PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0` = **26.0 u** (`server_main.gd:392`).
- Local-hit plausibility threshold = `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS + LOCAL_HIT_VALIDATION_MARGIN` = **88.0 u** (`server_main.gd:831`).
- Fire-origin tolerance clamp range = `[PROJECTILE_RADIUS * 2.0, POSITION_TOLERANCE]` = **[16.0, 75.0] u** (`server_main.gd:447-451`).
- Max PvE compensation seconds = `6 / tick_rate` = **0.2 s** at 30 Hz (`server_main.gd:442`).

### 2.3 Scheduler constants (`snapshot_scheduler.gd`)

| Constant | Value | Source |
|---|---|---|
| `PRIORITY_PLAYER` | `10` | `snapshot_scheduler.gd:20` |
| `PRIORITY_PROJECTILE` | `8` | `snapshot_scheduler.gd:21` |
| `PRIORITY_MONSTER` | `4` | `snapshot_scheduler.gd:22` |
| `PRIORITY_DEFAULT` | `1` | `snapshot_scheduler.gd:23` |
| `DISTANCE_PENALTY_BY_LOD` | `[0, 4, 8]` indexed by LOD tier (NEAR=0, MID=1, FAR=2) | `snapshot_scheduler.gd:26` |
| change bonus: FULL_STATE mask | `6` | `snapshot_scheduler.gd:144-145` |
| change bonus: REMOVED mask | `6` | `snapshot_scheduler.gd:146-147` |
| change bonus: per changed field (position/animation/flags) | `+2` each | `snapshot_scheduler.gd:148-155` |
| predicted size: FULL_STATE entry | `10` bytes (id 2 + mask 1 + type 1 + pos 4 + anim 1 + flags 1) | `snapshot_scheduler.gd:162-163` |
| predicted size: REMOVED entry | `3` bytes (id 2 + mask 1) | `snapshot_scheduler.gd:164-165` |
| predicted size: partial delta | `3` + 4 (position) + 1 (animation) + 1 (flags), per set mask bit | `snapshot_scheduler.gd:166-173` |

### 2.4 Broadcast service constants (`server_broadcast_service.gd`)

| Constant | Value | Source |
|---|---|---|
| `LOD_NEAR` / `LOD_MID` / `LOD_FAR` | `0` / `1` / `2` | `server_broadcast_service.gd:11-13` |
| `max_snapshot_bytes` (service field default) | `1200` bytes/snapshot (overwritten from config at init) | `server_broadcast_service.gd:42` |
| grid cell size | `effective_exit_radius / 4.0`; fallback `256.0` when AoI disabled. Live: `1100/4` = **275.0** u | `server_broadcast_service.gd:101-102` |

### 2.5 Delta cache constants (`delta_state_cache.gd`, `packet_types.gd`)

| Constant | Value | Source |
|---|---|---|
| `DELTA_FULL_STATE_INTERVAL` | `100` ticks (forced baseline cadence; ≈3.33 s @30 Hz) | `packet_types.gd:93` |
| `BASELINE_ACK_TIMEOUT_TICKS` | `30` ticks (un-acked baseline → proactive resend) | `delta_state_cache.gd:49` |
| position-equality threshold | `0.05` per axis (`absf(a.x-b.x) < 0.05 and absf(a.y-b.y) < 0.05` → equal); half the 0.1-unit wire quantization step | `delta_state_cache.gd:117-119` |
| `DELTA_MASK_POSITION` | `1 << 0` = 1 | `packet_types.gd:78` |
| `DELTA_MASK_ANIMATION` | `1 << 1` = 2 | `packet_types.gd:79` |
| `DELTA_MASK_FLAGS` | `1 << 2` = 4 | `packet_types.gd:80` |
| `DELTA_MASK_REMOVED` | `1 << 6` = 64 | `packet_types.gd:81` |
| `DELTA_MASK_FULL_STATE` | `1 << 7` = 128 | `packet_types.gd:82` |
| `STATE_FLAG_IS_DELTA` | `1 << 0` = 1 | `packet_types.gd:86` |
| `STATE_FLAG_BASELINE` | `1 << 1` = 2 | `packet_types.gd:87` |
| `EntityType` | `PLAYER = 1`, `MONSTER = 2`, `PROJECTILE = 3` | `packet_types.gd:36-40` |
| `STATE_MAX_FULL_ENTITIES` | `(65535 - 10) / 9` = **7280** (integer division). Header bytes 10 = wire header 3 + tick 4 + flags 1 + count 2; full-state entity = 9 bytes | `state_update_packet.gd:34-46` |
| `MAX_PACKET_SIZE` | `65535` bytes | `packet_types.gd:10` |

### 2.6 Metrics constants (`server_metrics.gd`)

| Constant | Value | Source |
|---|---|---|
| `METRICS_SAMPLE_SIZE` | `30` (ring of last 30 tick times for avg/max) | `server_metrics.gd:35` |

### 2.7 Server config defaults (`server_config.gd:7-50`, `DEFAULTS`)

| Key | Default | Live JSON value (`client/data/config/server_config.json`) | Notes |
|---|---|---|---|
| `port` | `8081` | `8081` | WebSocket listen port |
| `tick_rate` | `int(GameConstants.SERVER_TICK_RATE)` = `30` | `30` | Hz. **Env `GAME_SERVER_TICK_RATE` overrides with highest precedence** (`server_config.gd:160-164`) |
| `max_players` | `100` | `100` | connection cap |
| `region` | `"local"` | `"local"` | sent in region heartbeat |
| `debug_logging` | `true` | `true` | |
| `heartbeat_timeout_seconds` | `5.0` | `5.0` | (consumed by the network layer, not this loop) |
| `api_server_url` | `"http://localhost:8080"` | `"http://localhost:8080"` | empty string disables the region heartbeat |
| `aoi_radius` | `1000.0` | `1000.0` | AoI **enter** radius, u. `0` disables AoI (send all) |
| `aoi_exit_radius` | `1100.0` | `1100.0` | AoI **exit** radius (hysteresis), u |
| `lod_near_radius` | `400.0` | `400.0` | u; squared once at init |
| `lod_mid_radius` | `1000.0` | `1000.0` | u; squared once at init |
| `packet_batching_enabled` | `true` | — (absent → default `true`) | per-tick BATCH coalescing |
| `snapshot_rate_hz` | `0` (→ falls back to `tick_rate`) | `30` | getter clamps to `(0, tick_rate]`: `raw <= 0 → tick_rate`, else `min(raw, tick_rate)` (`server_config.gd:102-107`) |
| `max_snapshot_bytes` | `1200` | — (absent → default `1200`) | global per-peer per-snapshot cap; getter floors at 0 |
| `default_client_bandwidth_bps` | `120000` | `120000` | bytes/sec when client advertises 0 |
| `max_client_bandwidth_bps` | `200000` | `200000` | hard cap on advertised budget |
| `min_client_bandwidth_bps` | `24000` | — (absent → default `24000`) | floor on advertised budget |
| `monster_ai_difficulty` | `0.85` | `0.85` | getter clamps to `[0.0, 1.0]` |

Config file precedence: `user://server_config.json` (Docker volume) → `res://data/config/server_config.json` (embedded) → defaults; **only keys present in `DEFAULTS` are merged** (unknown keys warn and are dropped); env override applies last on every path (`server_config.gd:129-164`).

With the live values, the per-peer snapshot byte cap for a default client is `clamp(trunc(120000 / 30) = 4000, 256, 1200)` = **1200 bytes/snapshot** = 36 KB/s ceiling at 30 Hz.

---

## 3. Data structures

### 3.1 `ServerMain` state (`server_main.gd:16-69, 769`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `config` | ServerConfig | loaded in `_ready` | immutable after load |
| `server_running` | bool | `false` → `true` at init | gates `_process` |
| `server_time` | float (f64) | `0.0` | accumulated `_process` delta, seconds since server start |
| `tick_timer` | float | `0.0` | fixed-tick accumulator |
| `tick_count` | int (i64) | `0` | increments at top of every tick; first tick is `1`. Never wraps (GDScript int is 64-bit) |
| `snapshot_accumulator` | float | `0.0` | snapshot cadence accumulator (tick-time seconds) |
| `snapshot_interval` | float | `1.0 / max(1, snapshot_rate_hz)`, computed **once** at init | `server_main.gd:170` |
| `snapshot_due` | bool | `false` | latched at top of tick, consumed by the broadcast step in the same tick |
| `leaderboard_timer` | float | `0.0` | advanced by `tick_interval` each tick |
| `region_status_timer` | float | `0.0` | advanced by `_process` delta |
| `region_status_request_in_flight` | bool | `false` | one outstanding HTTP POST max |
| `region_status_warning_logged` | bool | `false` | once-per-failure-streak warning latch |
| `game_entities` | Dictionary | `{}` | reserved for extra entities; **always empty today**, but its `.size()` (0) participates in the metrics `entity_count` |
| `_local_hit_report_window` | Dictionary `peer_id -> {start_ms: int, count: int}` | `{}` | sliding-window rate limiter; entry erased on disconnect |

### 3.2 `ServerBroadcastService` state (`server_broadcast_service.gd:15-68`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `aoi_radius` / `aoi_exit_radius` | float | `0.0` / `0.0` (set from config at init: 1000 / 1100) | |
| `lod_near_radius_sq` / `lod_mid_radius_sq` | float | set from config at init: `400² = 160000`, `1000² = 1000000` | pre-squared, no sqrt in hot path |
| `max_snapshot_bytes` | int | `1200` (set from config) | global fallback budget |
| `delta_caches` | Dictionary `peer_id -> DeltaStateCache` | `{}` | created on connect AND lazily; erased on disconnect |
| `client_visible_entities` | Dictionary `peer_id -> Dictionary{entity_id: true}` | `{}` | per-peer visible set for hysteresis + exit despawns |
| `snapshot_schedulers` | Dictionary `peer_id -> SnapshotScheduler` | `{}` | created lazily; erased on disconnect |
| `peer_snapshot_bytes` | Dictionary `peer_id -> int` | `{}` | resolved byte cap, set at auth; unset peers fall back to `max_snapshot_bytes` (must NEVER fall back to 0 — 0 disables the budget) |
| `_tick_entities` | Array of entity-data Dictionaries | `[]` | shared per-snapshot-tick entity list |
| `_tick_grid` | SpatialGrid or null | `null` | shared per-snapshot-tick grid |
| `last_tick_diagnostics` | Dictionary | `{entities_deferred_per_tick: 0, max_queue_age_ticks: 0, peers_at_budget_pct: 0, peers_evaluated: 0, snapshot_count_overflow: 0}` | first four overwritten each broadcast; `snapshot_count_overflow` only ever **incremented** (monotonic for service lifetime) |

**Entity-data Dictionary shape** (produced by `PlayerState.to_entity_data()` at `player_state.gd:95-102`, and equivalents on monster/projectile states):

```
{ "id": int, "type": int (EntityType), "position": Vector2, "animation": int, "flags": int (u8 bitfield) }
```

### 3.3 `SnapshotScheduler.Candidate` (`snapshot_scheduler.gd:29-41`)

| Field | Type | Notes |
|---|---|---|
| `index` | int | index into the caller's parallel `staged` array |
| `entity_id` | int | tiebreaker (ascending) |
| `entity_type` | int | EntityType |
| `lod_tier` | int | 0/1/2 |
| `delta_mask` | int | u8 |
| `encoded_size` | int | predicted on-wire bytes |
| `ticks_since_last_sent` | int | clamped `>= 0` at add (`maxi(0, x)`) |
| `priority` | int | computed at add-time |
| `pinned` | bool | pinned always selected (removals/despawns) |

`SnapshotScheduler.Result`: `selected_indices: PackedInt32Array`, `candidate_count: int`, `deferred_count: int`, `max_queue_age_ticks: int`, `bytes_used: int`, `hit_budget: bool`.

### 3.4 `DeltaStateCache` (`delta_state_cache.gd`)

Per peer. `CachedEntityState`: `entity_id`, `entity_type`, `position: Vector2 (ZERO)`, `animation_state (IDLE=0)`, `flags (0)`, `last_tick_sent (0)`, `is_new (true)`.

Cache-level: `_cache: Dictionary entity_id -> CachedEntityState`, `_baseline_tick: int = 0`, `_acked_baseline_tick: int = 0`, `_pending_baseline_tick: int = 0` (0 = none outstanding).

### 3.5 `ServerMetrics.metrics` Dictionary (`server_metrics.gd:9-32`)

| Key | Type | Initial |
|---|---|---|
| `tick_count` | int | 0 |
| `avg_tick_time_ms` / `max_tick_time_ms` | float | 0.0 (avg & max over last 30 recorded tick times) |
| `player_count` / `entity_count` | int | 0 |
| `total_bytes_sent` / `total_bytes_received` | int | 0 (cumulative, from the transport) |
| `avg_bandwidth_per_client` | float | 0.0 (bytes/sec rate, see §4.10) |
| `last_metrics_time` | float | engine-uptime seconds at construction (`Time.get_ticks_msec()/1000.0`) |
| `bytes_sent_by_type` | Dictionary MessageType -> int | `{}` (cumulative per-type bytes) |
| `sched_entities_deferred`, `sched_max_queue_age_ticks`, `sched_peers_at_budget_pct`, `sched_peers_evaluated`, `sched_snapshot_overflow` | int | 0 |

Private: `_tick_times: Array[float]` (ring of ≤30), `_prev_total_peer_bytes: int = 0`, `_prev_metrics_time: float` = engine uptime at construction.

### 3.6 Player input queue (owned by player subsystem, drained by this loop)

Per `PlayerState` (`player_state.gd`): `input_queue: Array[Dictionary]` capped at `MAX_INPUT_QUEUE_SIZE = 10` (`:106`); on overflow the **oldest** input is dropped (`pop_front`, `:110-114`). `pending_shots: Array[Dictionary]` (rising-edge SHOOT events), `_pending_dash: bool` latch, persistent `input_flags: int`, `last_input_received_tick: int`, `STALE_INPUT_TICK_LIMIT = 6` ticks (`:80`).

Input Dictionary fields (from `PLAYER_INPUT` decode, `player_input_packet.gd:153-165`): `position: Vector2`, `velocity: Vector2`, `input_flags: int (u16)`, `inputs: Dictionary` (decoded booleans), `aim_angle: float (radians)`, `aim_degrees: float`, `sequence_number: int (u8, wraps)`, `client_render_tick: int (u16)`, `client_rtt_ms: int (u16)`.

---

## 4. Algorithms

### 4.1 Server init (`server_main.gd:73-176`)

```
on ready:
  config = load ServerConfig (file precedence + env override; print config)
  if not (dedicated_server feature OR headless display): abort process exit code 1
  connect network signals (client connected / disconnected / message)
  server_running = true; server_time = 0; tick_count = 0
  construct: PlayerManager, ProjectileManager, MonsterManager(+factory/database),
             MonsterSpawner(monster_manager, player_manager, monster_spawn_rate),
             MonsterAI(player_manager, projectile_manager, config.monster_ai_difficulty),
             ServerCollisionHandler, ServerBroadcastService, ServerMetrics
  broadcast_service.aoi_radius        = config.aoi_radius            # 1000.0
  broadcast_service.aoi_exit_radius   = config.aoi_exit_radius       # 1100.0
  broadcast_service.lod_near_radius_sq = config.lod_near_radius^2    # 160000.0
  broadcast_service.lod_mid_radius_sq  = config.lod_mid_radius^2     # 1000000.0
  broadcast_service.max_snapshot_bytes = config.max_snapshot_bytes   # 1200
  broadcast_service.leaderboard_manager = new LeaderboardManager
  setup region status publisher (only if api_server_url non-empty); publish immediately once
  snapshot_interval = 1.0 / float(max(1, config.snapshot_rate_hz))   # 1/30 live
  snapshot_accumulator = 0.0
```

### 4.2 Frame loop (`_process`, `server_main.gd:180-209`)

```
every engine frame with delta (wall seconds since last frame):
  if not server_running: return
  server_time += delta
  tick_timer += delta
  tick_interval = 1.0 / config.tick_rate          # float division; 0.0333…
  while tick_timer >= tick_interval:              # UNBOUNDED catch-up loop
      tick_timer -= tick_interval
      process_server_tick()

  # 1 Hz metrics (wall-time, but see hazard H9 about mixed clock bases)
  if server_time - metrics.last_metrics_time >= 1.0:
      entity_count = game_entities.size() + projectile_count + monster_count   # NO players
      network_stats = nm.get_stats()              # {packets_sent, packets_received, bytes_sent,
                                                  #  bytes_received, ping_ms, last_ping_time,
                                                  #  bytes_sent_by_type?}
      network_stats["peer_bytes_sent"] = nm.peer_bytes_sent   # Dictionary peer_id -> int
      server_metrics.update_metrics(player_count, entity_count, tick_count,
                                    network_stats, broadcast_service.last_tick_diagnostics)
      broadcast SERVER_METRICS to all clients (skip if nm == null or player_count == 0)
      # NOTE: sent OUTSIDE any batch window (batch was already flushed inside the tick)

  region_status_timer += delta
  if region_status_timer >= 2.0:
      region_status_timer = 0.0                   # reset to 0, not -= interval
      publish_region_status()
```

Notes:
- **No tick-catch-up clamp.** After a stall of N seconds, `N * 30` ticks fire back-to-back in one frame. A port must decide whether to preserve this (spiral-of-death risk) or clamp; GDScript does not clamp.
- `tick_timer` keeps its fractional remainder, so long-run tick cadence tracks wall time exactly.

### 4.3 One tick (`_process_server_tick`, `server_main.gd:213-283`)

```
tick_start = monotonic time (µs)
tick_count += 1

# snapshot cadence (server_main.gd:221-228)
tick_dt = 1.0 / float(max(1, config.tick_rate))
snapshot_accumulator += tick_dt
if snapshot_accumulator >= snapshot_interval:
    snapshot_accumulator -= snapshot_interval
    if snapshot_accumulator > snapshot_interval:   # runaway-drift guard after a stall:
        snapshot_accumulator = 0.0                 # at most ONE snapshot fires; surplus discarded
    snapshot_due = true

batching = (nm != null) and config.packet_batching_enabled
if batching: nm.begin_batch()     # all send_to_client/broadcast_to_clients below are queued per peer

1. process_client_inputs()                          # §4.4
2. update_game_state()                              # §4.6
3. update_monster_ai()                              # §4.7
4. monster_manager.record_position_snapshot(tick_count)   # lag-comp history (monsters)
   player_manager.record_position_snapshot(tick_count)    # lag-comp history (players, 8-tick window)
   # recorded AFTER inputs+AI moved everyone, BEFORE collision resolution
5. collision_handler.process_collisions(projectile_mgr, player_mgr, monster_mgr, nm, broadcast_service)
6. if snapshot_due:
       broadcast_service.build_aoi_grid(player_mgr, projectile_mgr, monster_mgr)   # §4.8.1
       broadcast_service.broadcast_state_updates(..., tick_count)                  # §4.8.2
       snapshot_due = false
7. monster_manager.cleanup_dead_monsters()          # AFTER death state was broadcast

if batching: nm.flush_batches()    # one coalesced BATCH frame per peer

tick_time_ms = (monotonic µs now - tick_start) / 1000.0
server_metrics.record_tick_time(tick_time_ms)
```

When `tick_rate == snapshot_rate_hz` (live config), `tick_dt == snapshot_interval` bit-for-bit (both computed as `1.0/float(30)`), so the very first tick and every subsequent tick sets `snapshot_due` — snapshots every tick, accumulator returns to exactly `0.0`.

### 4.4 Input drain (`_process_client_inputs`, `server_main.gd:287-301`; `player_manager.gd:118-148`; `player_state.gd:109-212`)

```
tick_interval = 1.0 / config.tick_rate
move_results = []
for each player state in player_manager.players (any iteration order):
    if not state.authenticated: continue
    had_input = (input_queue not empty)
    while input_queue not empty:
        input = input_queue.pop_front()
        state.ingest_input(input, tick_count)       # see below
    validation = state.step(tick_interval, tick_count)   # exactly ONE movement step per tick
    if had_input:
        move_results.append({ peer_id, sequence: validation.sequence,
                              position: validation.server_position,
                              success: not validation.correction_needed,
                              cheat_detected, deviation,
                              stamina: round_to_int(movement_sm.stamina),
                              mana:    round_to_int(movement_sm.mana) })
process_shoot_inputs()            # §4.5
if move_results not empty: send move confirmations  # §4.4.1
```

`ingest_input(input, server_tick)` (`player_state.gd:147-188`):

```
if life_state == DEAD: return                       # dead players' inputs discarded entirely
new_flags    = input.get("input_flags", 0)
new_sequence = input.get("sequence_number", input.get("sequence", last_input_sequence))
new_aim      = input.get("aim_angle", aim_angle)
# rising-edge SHOOT: bit set now but not in current persistent flags
if SHOOT bit rising-edge:
    pending_shots.append({ sequence, aim_angle, client_position (Vector2 or Vector2.INF sentinel),
                           client_velocity (Vector2 or ZERO), client_render_tick, client_rtt_ms })
if new_flags has DASH bit: _pending_dash = true      # latched (OR), consumed once in step()
input_flags = new_flags                              # LAST input in the burst wins the flags
last_input_sequence = new_sequence; aim_angle = new_aim
last_client_render_tick / last_client_rtt_ms updated
last_input_received_tick = server_tick
if input.position is Vector2: last_client_position = it; has_client_position = true
```

Burst/empty-queue semantics:
- **Burst** (multiple inputs queued in one tick): all are ingested in arrival order; persistent flags/aim/sequence reflect the **last** one; every rising SHOOT edge in the burst appends to `pending_shots`; a DASH bit anywhere in the burst is latched. Only one movement `step()` runs. One `ACTION_CONFIRM` is sent, carrying the **latest** sequence.
- **Overflow**: queue capped at 10; the 11th queued input drops the **oldest**.
- **Empty queue**: `step()` still runs on the persistent flags (player keeps moving in the last commanded direction); **no** `ACTION_CONFIRM` is sent (no fresh sequence to ack).
- **Stale input** (`step`, `player_state.gd:220-221`): if `last_input_received_tick > 0` and `server_tick - last_input_received_tick > 6`, persistent `input_flags` are zeroed before stepping — a silent/stalled client stops sliding after 6 ticks (200 ms).

#### 4.4.1 Move confirmations (`_send_move_confirmations`, `server_main.gd:326-364`)

For each move result: build `ActionConfirmPacket.create_move_confirm(sequence, position, tick_count, success, stamina, mana)` — `result.get("stamina", 100)` / `result.get("mana", 100)` defaults; packet clamps stamina/mana to `[0, 255]` (`action_confirm_packet.gd:62-63`); `result_code = SUCCESS if success else FAILED_INVALID_POSITION`; `action_type = MOVE`. Send `ACTION_CONFIRM` to that peer only. Log on `cheat_detected`.

### 4.5 Shoot pipeline (`_process_shoot_inputs` + `_try_spawn_projectile`, `server_main.gd:304-490`)

```
for each player state in player_manager.get_all_players():
    fired_this_tick = false
    loop:                                            # drain ALL pending shots
        shot = state.pop_pending_shot()
        if shot empty: break
        if not fired_this_tick:
            fired_this_tick = true
            try_spawn_projectile(state, shot)        # may still fail (cooldown etc.)
        # else: duplicate same-tick rising edge — coalesced/DROPPED
    if not fired_this_tick and state.is_shoot_held() and state.can_shoot():
        try_spawn_projectile(state, state.get_held_shot_input())   # held auto-fire
```

At most ONE spawn attempt per player per tick (`SHOOT_COOLDOWN` 0.3 s makes >1 legitimate shot per 33 ms tick impossible). Note: a failed first attempt (e.g. cooldown) still sets `fired_this_tick`, suppressing held auto-fire that tick.

`can_shoot()` = `authenticated and is_alive and shoot_cooldown <= 0.0` (`player_state.gd:130-131`).

`_try_spawn_projectile(player, input)` (`server_main.gd:368-414`), exact order:

```
1. if player.life_state == INVULNERABLE: player.end_invulnerability()   # shooting drops spawn protection
2. if not player.can_shoot(): return
3. aim_angle = input.get("aim_angle", player.aim_angle)
   aim_direction = unit vector from angle (cos(a), sin(a))              # Vector2.from_angle
4. fire_origin = validated fire origin (§4.5.1); defaults to server position
5. compensation = PvE rewind resolution (§4.5.2)
   rewind_ticks = compensation.rewind_ticks (default REMOTE_ENTITY_RENDER_DELAY_TICKS=2 if key missing)
   pvp_rewind_ticks = clamp(compensation.rewind_ticks (default 0), 0, 4)
6. spawn_position = fire_origin + aim_direction * 26.0
7. projectile = projectile_manager.spawn_projectile(player.entity_id, spawn_position, aim_direction,
       tick_count, rewind_ticks, compensation.client_render_tick, compensation.client_rtt_ms,
       compensation.source, pvp_rewind_ticks)
8. if projectile != null:
       player.start_shoot_cooldown()                # shoot_cooldown = 0.3
       broadcast GAME_EVENT PROJECTILE_FIRED(source=player.entity_id,
           projectile_id=projectile.entity_id, spawn_position, server_tick=tick_count) to ALL clients
```

#### 4.5.1 Fire-origin validation (`_get_validated_fire_origin` + `_get_fire_origin_tolerance`, `server_main.gd:417-451`)

```
client_position = input.get("client_position", Vector2.INF)     # INF = sentinel for "absent"
tolerance:
    rtt = clamp(input.client_rtt_ms (default 0), 0, 65535)
    one_way_seconds = rtt * 0.0005                               # ms → s, halved
    one_way_seconds = min(one_way_seconds, 6 / tick_rate)        # cap at 0.2 s @30Hz
    predicted_gap = 320.0 * (one_way_seconds + 1/tick_rate)
    tolerance = clamp(predicted_gap + 8.0, 16.0, 75.0)
if client_position != Vector2.INF and distance(player.position, client_position) <= tolerance:
    fire_origin = client_position   (source "client_position")
else:
    fire_origin = player.position   (source "server_position")
```

#### 4.5.2 PvE lag-compensation rewind (`_get_pve_projectile_compensation` + `_resolve_client_tick_u16`, `server_main.gd:454-490`)

```
client_render_tick_16 = input.get("client_render_tick", 0) & 0xFFFF
rtt = clamp(input.client_rtt_ms (default 0), 0, 65535)
if client_render_tick_16 > 0:
    # resolve u16 wraparound against the server's full tick counter:
    server16 = tick_count & 0xFFFF
    diff = client_render_tick_16 - server16
    if diff > 32767: diff -= 65536
    elif diff < -32768: diff += 65536
    resolved = tick_count + diff
    rewind = tick_count - resolved
    if rewind >= 0:
        return { rewind_ticks: clamp(rewind, 0, 6), client_render_tick: resolved, client_rtt_ms: rtt,
                 source: "client_render_tick" if rewind <= 6 else "client_render_tick_clamped" }
    # rewind < 0 (client claims a FUTURE tick) → fall through to fallback
one_way_latency_ticks = 0
if rtt > 0: one_way_latency_ticks = ceil((rtt * 0.5) / (1000 / tick_rate))   # ceili, integer result
fallback = 2 + one_way_latency_ticks                                          # render-delay + latency
return { rewind_ticks: clamp(fallback, 0, 6), client_render_tick: 0, client_rtt_ms: rtt,
         source: "rtt_fallback" if rtt > 0 else "render_delay_fallback" }
```

### 4.6 Game-state update (`_update_game_state`, `server_main.gd:494-513`)

In order, all with `tick_interval = 1/tick_rate`:

1. `projectile_manager.update_all(tick_interval)` — advance all projectiles.
2. `monster_spawner.update(tick_interval)` — spawn accumulator at `monster_spawn_rate` (live 0.1/s).
3. Invulnerability timers — for **all** players (`get_all_players`, incl. unauthenticated).
4. Respawn (death) timers — for **authenticated** players only. Timers advance; respawn itself only happens on client `RESPAWN_REQUEST`.
5. `leaderboard_timer += tick_interval; if >= 5.0: reset to 0.0; broadcast_leaderboard(...)` — **tick-time clock**: 150 ticks, drifts from wall time only if ticks stall (they catch up, so net wall cadence holds).

### 4.7 Monster AI step (`_update_monster_ai`, `server_main.gd:517-536`)

```
if monster_ai == null or monster_manager == null: return
fire_events = monster_ai.update_all(monster_manager.get_alive_monsters(), 1/tick_rate)
for each fire_event in fire_events:
    broadcast GAME_EVENT PROJECTILE_FIRED(source = int(fire_event.source_id (default 0)),
                                          projectile_id = int(fire_event.projectile_id (default 0)),
                                          spawn_position = Vector2.ZERO,      # default arg!
                                          server_tick = 0)                    # default arg!
```

**Monster fire events carry `spawn_position = (0,0)` and `server_tick = 0`** — only player-fired events carry a real spawn position/tick (`server_main.gd:540-545` defaults). D11 invariant: monster `PROJECTILE_FIRED` must carry a **non-zero projectile id** (the client uses it for local hit detection).

### 4.8 Broadcast pipeline

#### 4.8.1 Shared grid build (`build_aoi_grid`, `server_broadcast_service.gd:79-107`)

```
entities = []
for each AUTHENTICATED player: entities.append(state.to_entity_data())
entities += projectile_manager.collect_state_updates()    # ALIVE projectiles only
entities += monster_manager.collect_state_updates()       # ALL monsters incl. dead-not-yet-cleaned
_tick_entities = entities
effective_exit = aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_radius   # strict >
cell = effective_exit / 4.0 if effective_exit > 0.0 else 256.0                     # live: 275.0
_tick_grid = new SpatialGrid(cell)
for each entity: _tick_grid.insert(entity, entity.get("position", ZERO))
```

Dead monsters are intentionally still in the list so their death animation/flags broadcast before step-7 cleanup removes them.

#### 4.8.2 Per-peer broadcast (`broadcast_state_updates`, `server_broadcast_service.gd:112-227`)

```
if player_count == 0 or network_manager == null: return
if _tick_grid == null: build_aoi_grid(...)        # defensive fallback
all_entities = _tick_entities
aoi_enabled = aoi_radius > 0.0
enter_sq = aoi_radius^2
exit_sq  = aoi_exit_radius^2 if aoi_exit_radius > aoi_radius else enter_sq
tick_total_deferred = 0; tick_max_queue_age = 0; tick_peers_at_budget = 0; tick_peers_evaluated = 0

for each AUTHENTICATED player state:
    peer_id = state.peer_id
    cache = get_or_create_delta_cache(peer_id)
    prev_visible = client_visible_entities.get(peer_id, {})
    if aoi_enabled:
        candidates = _tick_grid.query_radius(state.position,
                        aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_radius)
        {visible_entities, visible_lods} = filter_by_aoi(candidates, state, enter_sq, exit_sq,
                                                          prev_visible, tag_lod=true)   # §4.8.3
    else:
        visible_entities = all_entities            # no copy; lods stay EMPTY → all LOD_NEAR later

    current_visible_ids = { e.id: true for e in visible_entities if e.id >= 0 }
    removed_entity_ids = []
    if aoi_enabled:
        removed_entity_ids = [ id for id in prev_visible if id not in current_visible_ids ]
    client_visible_entities[peer_id] = current_visible_ids

    needs_baseline = cache.needs_full_state_for_interval(tick)        # tick - baseline_tick >= 100
                  or cache.needs_baseline_resend(tick)                # un-acked baseline ≥30 ticks old
    if needs_baseline and removed_entity_ids.is_empty():
        packet = create_full_state_packet(visible_entities, cache, tick)      # §4.8.5
    else:
        scheduler = get_or_create_scheduler(peer_id)
        peer_max = peer_snapshot_bytes.get(peer_id, max_snapshot_bytes)        # NEVER 0 fallback
        packet = create_delta_packet(visible_entities, cache, tick, removed_entity_ids,
                                     visible_lods, scheduler, out stats, peer_max)   # §4.8.6
        tick_peers_evaluated += 1
        tick_total_deferred  += stats.deferred
        tick_max_queue_age    = max(tick_max_queue_age, stats.max_queue_age)
        if stats.hit_budget: tick_peers_at_budget += 1

    network_manager.send_to_client(peer_id, STATE_UPDATE, packet)

last_tick_diagnostics.entities_deferred_per_tick = tick_total_deferred
last_tick_diagnostics.max_queue_age_ticks       = tick_max_queue_age
last_tick_diagnostics.peers_evaluated           = tick_peers_evaluated
last_tick_diagnostics.peers_at_budget_pct =
    round(100.0 * peers_at_budget / peers_evaluated) if peers_evaluated > 0 else 0
```

**Critical interleaving:** when a baseline is due but the peer also has AoI exits this tick, the **delta path runs instead** — every entity's mask comes back `FULL_STATE` from the per-entity interval check (§4.8.4), but those entries go **through the scheduler and the byte budget** (deferrable!), the packet is flagged `STATE_FLAG_IS_DELTA` with the OLD `baseline_tick`, and `reset_baseline` is NOT called — so the true baseline retries next tick (whenever a tick has no removals).

#### 4.8.3 AoI filter with hysteresis (`_filter_entities_by_aoi`, `server_broadcast_service.gd:235-278`)

```
entities = []; lods = byte array; self_seen = false
for each candidate entity:
    eid = entity.get("id", -1)
    if eid == player.entity_id:
        append entity; lod = LOD_NEAR; self_seen = true; continue   # self NEVER culled
    dist_sq = player.position.distance_squared_to(entity.position (default ZERO))
    threshold_sq = exit_sq if eid in prev_visible else enter_sq
    if dist_sq > threshold_sq: continue           # STRICT >: exactly-on-radius stays visible
    append entity; lod = classify_lod(dist_sq)
if not self_seen:                                  # cell-edge rounding safety net
    append player.to_entity_data(); lod = LOD_NEAR
return {entities, lods}                            # parallel arrays, lods[i] for entities[i]
```

`_classify_lod(dist_sq)` (`:282-287`): `NEAR` if `lod_near_radius_sq > 0 and dist_sq <= lod_near_radius_sq`; else `MID` if `lod_mid_radius_sq > 0 and dist_sq <= lod_mid_radius_sq`; else `FAR`. (If LOD radii are configured 0, everything classifies FAR.)

#### 4.8.4 Delta-mask computation (`delta_state_cache.gd:79-124`)

```
calculate_delta_mask(entity_id, current_state, current_tick):
    if entity_id not in cache: return FULL_STATE(128)
    cached = cache[entity_id]
    if cached.is_new: return FULL_STATE
    if current_tick - baseline_tick >= 100: return FULL_STATE     # per-entity interval check
    mask = 0
    if not (|cached.pos.x - cur.x| < 0.05 and |cached.pos.y - cur.y| < 0.05): mask |= POSITION(1)
    if cached.animation_state != cur.animation_state: mask |= ANIMATION(2)
    if cached.flags != cur.flags: mask |= FLAGS(4)
    return mask          # 0 = unchanged → entity skipped entirely
```

#### 4.8.5 Full-state (baseline) packet (`_create_full_state_packet`, `server_broadcast_service.gd:480-519`)

```
entity_data = []
for each entity with id >= 0:
    entity_data.append({ entity_id, entity_type (default PLAYER), position (default ZERO),
                         animation_state (default IDLE), flags (default 0),
                         delta_mask: FULL_STATE(128) })
    cache.update_cache(entity_id, {...}, tick)     # full overwrite, last_tick_sent = tick, is_new=false
cache.reset_baseline(tick)                          # baseline_tick = tick; pending_baseline_tick = tick
if entity_data.size() > 7280:                       # STATE_MAX_FULL_ENTITIES
    last_tick_diagnostics.snapshot_count_overflow += 1; warn (writer will truncate)
return { tick: tick, state_flags: STATE_FLAG_BASELINE(2), baseline_tick: tick, entities: entity_data }
```

Baselines bypass the scheduler and **all** byte budgets. The only bound is the 65535-byte wire frame (≈7280 entities); the wire writer truncates beyond it (`state_update_packet.gd:210`).

#### 4.8.6 Delta packet (`_create_delta_packet`, `server_broadcast_service.gd:526-661`)

```
scheduler.reset()
staged = []; removed_set = {}; active_entity_ids = []

# 1. AoI-exit removals — PINNED
for entity_id in removed_entity_ids:
    if entity_id < 0: continue
    removed_set[entity_id] = true
    staged.append({entity_id, delta_mask: REMOVED(64)})
    scheduler.add_candidate(index=staged_idx, entity_id, type=PLAYER(1), lod=NEAR,
                            mask=REMOVED, size=3, ticks_since=0, pinned=true)

# 2. Visible entities with a non-zero delta mask
for i in range(entities.size()):
    entity = entities[i]; entity_id = entity.id; if entity_id < 0: continue
    active_entity_ids.append(entity_id)
    current_state = {entity_type, position, animation_state, flags}    # with defaults
    delta_mask = cache.calculate_delta_mask(entity_id, current_state, tick)
    if delta_mask == 0: continue                                        # unchanged → skipped
    lod = lod_tiers[i] if lod_tiers.size() == entities.size() else NEAR
    cached = cache.get_cached_state(entity_id)
    ticks_since = (tick - cached.last_tick_sent) if cached != null else tick   # NEW entity → ≈tick_count!
    staged.append({entity_id, entity_type, position, animation_state, flags, delta_mask,
                   _current_state: current_state})
    scheduler.add_candidate(staged_idx, entity_id, entity_type, lod, delta_mask,
                            encoded_size_for_mask(delta_mask), ticks_since, pinned=false)

# 3. Stale cache entries (in cache but not in this tick's active list) — PINNED despawns.
#    SIDE EFFECT: erased from the cache immediately, even if... (they are pinned, so always sent)
stale_ids = cache.cleanup_stale_entities(active_entity_ids)
for entity_id in stale_ids:
    if entity_id in removed_set: continue
    staged.append({entity_id, delta_mask: REMOVED}); add pinned candidate as in step 1

result = scheduler.schedule(peer_max_bytes)        # §4.8.7
entity_data = []
for idx in result.selected_indices:                # PRIORITY order, not entity order
    entry = staged[idx]
    if entry has _current_state:                   # only actually-sent entries update the cache
        cache.update_cache_partial(entity_id, _current_state, delta_mask, tick)
        # mask-aware: only fields whose bit is set are written; FULL_STATE writes all;
        # last_tick_sent = tick; is_new = false  (delta_state_cache.gd:155-178)
        entry.erase("_current_state")
    entity_data.append(entry)

out_stats = {deferred, max_queue_age, bytes_used, hit_budget, candidates}
return { tick, state_flags: STATE_FLAG_IS_DELTA(1), baseline_tick: cache.get_baseline_tick(),
         entities: entity_data }
```

Deferred entities keep their stale cache entry, so their delta mask stays dirty and `ticks_since_last_sent` grows — they re-rank upward next tick (anti-starvation).

#### 4.8.7 Scheduler (`snapshot_scheduler.gd:57-173`)

```
priority = importance(entity_type)        # PLAYER 10 / PROJECTILE 8 / MONSTER 4 / other 1
         + max(0, ticks_since_last_sent)  # raw add — unbounded
         - distance_penalty(lod)          # [0, 4, 8]; out-of-range lod → 0
         + change_bonus(mask)             # FULL_STATE→6; REMOVED→6; else +2 per set bit of pos/anim/flags

schedule(max_bytes):
    sort candidates: priority DESC, entity_id ASC (deterministic total order; ids unique per call)
    bytes = 0
    for c in sorted candidates:                    # NO break — keeps trying smaller items
        max_queue_age = max(max_queue_age, c.ticks_since_last_sent)   # over ALL candidates
        fits = (max_bytes <= 0) or (bytes + c.encoded_size <= max_bytes)
        if c.pinned or fits:
            select c.index; bytes += c.encoded_size    # pinned entries CONSUME budget too
        else:
            deferred_count += 1; hit_budget = true
    bytes_used = bytes
```

`max_bytes <= 0` disables the budget (sort only, never defer). Greedy first-fit in priority order — **not** a knapsack: an oversized high-priority item is skipped while later smaller items may still be admitted.

### 4.9 Spatial grid (`spatial_grid.gd`)

```
cell_size = max(constructor arg, 1.0)              # default arg 64.0; AoI grid passes 275.0 live
cell_of(pos) = (floor(pos.x / cell_size), floor(pos.y / cell_size))   # floori — toward -inf
insert(item, pos): append item to the bucket of exactly ONE cell (no duplicates ever)
query_cell_neighbourhood(pos, ring=1): all items in the (2·ring+1)² cells around pos's cell; NO distance filter
query_radius(center, radius):
    r_cells = ceil(radius / cell_size)             # ceili
    all items in the (2·r_cells+1)² cell square around center's cell  # superset; caller filters
```

The grid stores opaque references; the AoI caller keeps the exact `distance_squared` + hysteresis test. Buckets are plain arrays; per-bucket and overall iteration order is insertion order, but **nothing downstream depends on candidate order** (the scheduler re-sorts; the filter is order-independent except output array order, which only affects wire entity order, not semantics).

### 4.10 Metrics (`server_metrics.gd`)

`record_tick_time(ms)`: append to `_tick_times`; if size > 30, drop the oldest.

`update_metrics(player_count, entity_count, tick_count, network_stats, scheduler_diagnostics)` (`:57-111`):

```
now = engine-uptime seconds (msec/1000.0); elapsed = now - _prev_metrics_time
metrics.tick_count/player_count/entity_count = args
metrics.total_bytes_sent/received = network_stats.bytes_sent/bytes_received (default 0)
if network_stats has bytes_sent_by_type: copy it (cumulative; consumers diff)
metrics.sched_* = int(scheduler_diagnostics.get(<key>, 0)) for the 5 sched keys
peer_bytes = network_stats.get("peer_bytes_sent", {})
if peer_count > 0 and elapsed > 0.0:
    total = sum(peer_bytes.values())
    delta = total - _prev_total_peer_bytes
    avg_bandwidth_per_client = delta / elapsed / peer_count   if delta >= 0 else 0.0
    _prev_total_peer_bytes = total
else:
    avg_bandwidth_per_client = 0.0; _prev_total_peer_bytes = 0     # reset on zero peers
if _tick_times non-empty: avg/max over the window
metrics.last_metrics_time = now; _prev_metrics_time = now
```

`get_metrics()` returns a **shallow** duplicate of the dict (the nested `bytes_sent_by_type` dict is shared — irrelevant for the wire encode, which reads scalars).

### 4.11 SERVER_METRICS packet (encode `network_manager.gd:871-888`, decode `:1013-1029`)

Broadcast at the 1 Hz metrics pass, only if ≥1 player connected. Payload, exact field order:

| # | Field | Wire type | Transform |
|---|---|---|---|
| 1 | `tick_count` | u32 | raw |
| 2 | `avg_tick_time_ms` | u16 | `int(value * 100)` fixed-point ×100, truncation (decode ÷100.0) |
| 3 | `max_tick_time_ms` | u16 | same ×100 fixed point |
| 4 | `player_count` | u16 | raw |
| 5 | `entity_count` | u16 | raw (= `game_entities.size()` (0) + projectiles + monsters; **excludes players**) |
| 6 | `total_bytes_sent` | u32 | raw |
| 7 | `total_bytes_received` | u32 | raw |
| 8 | `avg_bandwidth_per_client` | u32 | `int(float)` truncation |
| 9 | `sched_entities_deferred` | u16 | `min(value, 65535)` |
| 10 | `sched_max_queue_age_ticks` | u16 | `min(value, 65535)` |
| 11 | `sched_peers_at_budget_pct` | u8 | `clamp(value, 0, 255)` |
| 12 | `sched_peers_evaluated` | u16 | `min(value, 65535)` |
| 13 | `sched_snapshot_overflow` | u16 | `min(value, 65535)` |

Fields 2/3 have **no overflow guard**: an avg tick time > 655.35 ms wraps the u16 (writer masks to 16 bits). Fields 1, 6, 7 wrap u32 if cumulative counters exceed 2³²−1.

### 4.12 Connection lifecycle (`server_main.gd:609-733`)

**Connect** (`:609-629`): if `player_count >= max_players` → `nm.disconnect_client(peer_id, "Server full")`, return. Else `player_manager.add_player(peer_id)` (assigns next entity id 1,2,3,… — **never recycled**, monotonic per process; round-robin spawn position) and create the peer's delta cache.

**Auth** (`_handle_auth_request`, `:685-733`), order matters:

```
character_id   = data.get("character_id", "")
character_name = data.get("character_name", "Player_%d" % peer_id)
player_color   = data.get("player_color", Color(0.27, 0.53, 1.0))
advertised     = int(data.get("bandwidth_budget_bps", 0))
effective      = advertised if advertised > 0 else config.default_client_bandwidth_bps   # 120000
effective      = clamp(effective, config.min_client_bandwidth_bps, config.max_client_bandwidth_bps)  # [24000, 200000]
if not player_manager.authenticate_player(peer_id, ...): return    # only fails if peer unknown
rate           = config.snapshot_rate_hz                            # 30 live
per_peer_bytes = int(effective / float(max(1, rate)))               # float div, truncate toward zero
per_peer_bytes = clamp(per_peer_bytes, 256, config.max_snapshot_bytes)   # [MIN_SNAPSHOT_FLOOR, 1200]
broadcast_service.set_peer_byte_budget(peer_id, per_peer_bytes)     # stored as max(0, bytes)
state.max_snapshot_bytes = per_peer_bytes
broadcast PLAYER_INFO(new player) to ALL clients
send PLAYER_INFO of every OTHER authenticated player to the new client
leaderboard_manager.register_player(entity_id); broadcast leaderboard to all
```

There is **no actual credential validation** (`server_main.gd:702` TODO) — D9 replaces this with the Ed25519 ticket.

**Disconnect** (`:633-649`): leaderboard remove (by entity_id) + leaderboard broadcast → `player_manager.remove_player` → erase `_local_hit_report_window[peer]` → `remove_delta_cache(peer)` which erases delta cache, visible-set, scheduler, and peer byte budget (`server_broadcast_service.gd:464-468`).

**Message dispatch** (`:653-681`): messages from peers without a player state are ignored. Routes: `PLAYER_INPUT` → queue (ignored if unauthenticated, `player_manager.gd:105-107`); `CONNECT_AUTH` → auth; `REQUEST_FULL_STATE` → §4.13; `RESPAWN_REQUEST` → §4.14; `LOCAL_HIT_REPORT` → §4.15; `BASELINE_ACK` → `cache.mark_baseline_acked(int(data.baseline_tick))`; everything else ignored.

### 4.13 Full-state request (`handle_full_state_request`, `server_broadcast_service.gd:312-362`)

Collects **ALL** entities (authenticated players + alive projectiles + all monsters) with **NO AoI filter**, builds a full-state packet (updates cache + resets baseline for that peer), sends it, then re-sends `PLAYER_INFO` for **every** authenticated player (including the requester — this is how a client discovers its own entity_id) to that peer only.

### 4.14 Respawn (`_handle_respawn_request` + `_respawn_player_and_broadcast`, `server_main.gd:737-756, 840-864`)

Reject if player unknown, still alive, or `respawn_timer > 0.0`. On success: round-robin spawn position, `state.reset_for_respawn(pos)`, broadcast `GAME_EVENT RESPAWN(entity_id, position)` to all clients.

### 4.15 Local hit report (`_handle_local_hit_report` + helpers, `server_main.gd:776-836`)

Validation gauntlet, in order — any failure silently drops the report:

```
1. projectile_id = int(data.get("projectile_id", 0)); if <= 0: return
2. player = by peer; if null or not authenticated or not is_alive: return
3. rate limit (sliding window): entry = window.get(peer, {start_ms: 0, count: 0})
       if now_ms - start_ms >= 1000: start_ms = now_ms; count = 0
       count += 1; store entry; allowed iff count <= 20
4. proj = projectile_manager.projectiles.get(projectile_id); if null or not alive: return
5. if proj.owner_id < 30000: return            # HitAuthority.is_client_authoritative — monster-owned only
6. plausibility: threshold = 88.0
       flight_start = proj.position - proj.direction * proj.distance_traveled
       positions = player's recent authoritative positions (≤8 history ticks, oldest first, + live)
       plausible iff ANY position is strictly < 88.0 from its closest point on the
       segment [flight_start, proj.position]
7. apply: collision_handler.apply_player_hit(proj.owner_id, player.entity_id, player_manager,
          nm, broadcast_service, proj.position)
   projectile_manager.remove_projectile(projectile_id, "player_hit")
```

### 4.16 Region heartbeat (`server_main.gd:868-915`)

Setup (init): skipped entirely when `config.api_server_url` is empty; otherwise create the HTTP requester and publish once immediately. Then every 2.0 s of wall time:

```
publish_region_status(status="online"):
    if requester null or a request is in flight: SKIP this beat (no queueing)
    url  = api_server_url with trailing '/' stripped + "/api/regions/heartbeat"
    body = JSON { "region_id": config.region, "active_players": player_count,
                  "max_players": config.max_players,
                  "websocket_url": "ws://localhost:<config.port>",     # HARDCODED localhost
                  "status": status }
    headers = ["Content-Type: application/json"]
              + ["X-Region-Heartbeat-Token: <env REGION_HEARTBEAT_TOKEN>"] if env var non-empty
    POST; on immediate error: in_flight = false; warn once per failure streak (debug only)
    else in_flight = true
on completion: in_flight = false
    failure (result != success or code outside [200, 300)): warn once per streak (debug only)
    success: reset the warning latch
```

Fire-and-forget: responses are never parsed; failures only affect logging.

### 4.17 Shutdown (`server_main.gd:950-985`)

`shutdown(reason)`: `server_running = false` → discard any half-built batch (`nm.clear_batches()`) so DISCONNECTs leave immediately → send `DISCONNECT {reason: SERVER_SHUTDOWN (=3)}` to every player (incl. unauthenticated) → clear players/projectiles/monsters/AI/leaderboard/broadcast caches/`game_entities`/metrics. Scene-tree exit triggers `shutdown("Scene exit")` if still running.

---

## 5. Edge cases & gotchas

1. **Unbounded tick catch-up.** The `while tick_timer >= tick_interval` loop has no iteration cap (`server_main.gd:190-192`). A 5 s GC pause fires 150 consecutive ticks. The snapshot accumulator's drift guard (`:226-227`) caps the catch-up burst to **one** snapshot, but inputs/AI/collisions all run 150 times.
2. **`snapshot_due` is a one-tick latch in practice.** Set at the top of a tick, always consumed at step 6 of the same tick. It cannot carry across ticks under current code.
3. **Baseline-vs-removals dance** (§4.8.2): a due baseline with same-tick AoI exits silently downgrades to a delta packet full of FULL_STATE-masked entries that **can be deferred by the byte budget**, and the baseline interval does not reset. Pathological case: a peer with at least one AoI exit on every tick never sends a true baseline packet (entities still refresh via per-entity FULL_STATE masks, budget permitting).
4. **New-entity priority explosion.** For an entity not in the peer's cache, `ticks_since_last_sent := tick_count` (`server_broadcast_service.gd:587`) — on a server at tick 100 000 a new entity's priority is ~100 000, trumping everything. Effectively "new entities always fit first". Preserve or consciously deviate.
5. **Pinned entries can exceed the byte budget.** `schedule()` always admits pinned candidates and adds their bytes (`snapshot_scheduler.gd:98-101`); a mass AoI exit can blow past `peer_max_bytes` unconditionally. `MIN_SNAPSHOT_FLOOR = 256` exists to keep this survivable, not to prevent it.
6. **`hit_budget` flags peers with ≥1 deferral**, not peers exactly at the cap. `peers_at_budget_pct = round(100·at/evaluated)`, 0 when no peer was evaluated (e.g. every peer got a baseline that tick).
7. **`snapshot_count_overflow` is cumulative** since service construction (only `+= 1`, never reset; reset only by full service teardown at shutdown). The other four diagnostics are per-broadcast-tick.
8. **Entity id `-1`/negative is the "invalid" sentinel** throughout the broadcast path (`entity.get("id", -1)`, skip if `< 0`). Player entity ids are **never recycled** (`_next_entity_id` only increments, `player_manager.gd:44-45`); the u16 wire field overflows past id 65535 — unreachable for players (1–999 by invariant) but a port keeping monotonic ids must respect the id-range invariants (players 1–999, projectiles 10000–29999, monsters 30000–39999).
9. **`Vector2.INF` is the "no client position" sentinel** in the shoot path (`server_main.gd:418`). The comparison is exact equality against `(inf, inf)`. A Rust port should use `Option<Vec2>`; if it keeps the sentinel, beware that `distance_to(INF)` is `inf`/NaN — the GDScript guards with the equality check first.
10. **`client_render_tick` ahead of the server** (negative rewind after wraparound resolution) falls through to the RTT fallback path — it is not clamped to 0 in the render-tick branch (`server_main.gd:461-467`).
11. **Empty input queue ≠ zero input.** Persistent flags keep applying for up to 6 ticks (`STALE_INPUT_TICK_LIMIT`), after which flags zero. The very first tick after connect is exempt (`last_input_received_tick == 0` check at `player_state.gd:220`).
12. **Dead players** discard inputs at ingest, zero velocity/flags in step, and still appear in the entity list (with death flags) — they are not removed from broadcasts.
13. **AoI disabled (`aoi_radius = 0`)**: every peer gets `all_entities` (no AoI filter, **no removed-entity tracking** — only stale-cache despawns), and all entities count as LOD_NEAR (empty lods array → `has_lod_tiers` false).
14. **AoI radius comparisons are strict.** Entry: `dist_sq > enter_sq → cull` (exactly on the ring = visible). Hysteresis fallback uses `aoi_exit_radius > aoi_radius` strictly — `exit == enter` behaves as if exit were unset.
15. **Equal-radius config (`exit <= enter`)** also affects grid cell size (falls back to `enter/4`) and the query radius (uses `aoi_radius`).
16. **Division-by-zero guards present:** `maxi(1, tick_rate)` in tick_dt and snapshot interval; `maxi(1, rate)` in budget derivation; `SpatialGrid` clamps `cell_size >= 1.0`; metrics guards `elapsed > 0` and `peer_count > 0`; `peers_evaluated > 0` for the pct. **Absent:** `tick_interval = 1.0 / config.tick_rate` at `server_main.gd:188, 288, 441, 471, 495, 521` divides by the **raw config value** — `tick_rate = 0` in JSON/env yields `inf`/`nan` and breaks the loop (GDScript prints an error for `1.0/0` int divisor? No — `1.0/0` float division yields `inf` silently). A port must validate `tick_rate >= 1`.
17. **The metrics gate mixes clock bases** (`server_main.gd:195`): `server_time` (seconds since server init) vs `metrics.last_metrics_time` (engine-uptime seconds). Both advance at 1 s/s so the cadence is ~1 Hz, but the first broadcast is delayed by roughly the engine-boot-to-server-init offset, and after `clear()` the bases change again. Use a single clock in the port.
18. **The leaderboard timer advances in tick time** (`+= tick_interval` per tick), not wall time. Equivalent in the long run (ticks track wall time), but a stalled-then-bursting server fires it during the catch-up burst.
19. **Monster fire events broadcast `spawn_position=(0,0)` and `server_tick=0`** (§4.7). Clients must (and do) tolerate that; only the player-fire variant carries real values.
20. **Rate limiter quirk:** the count increments before the check, so reports 1–20 within a window pass and 21+ fail; the window restarts on the first report ≥1000 ms after `start_ms` (sliding-reset, not token bucket). First-ever report sees `start_ms = 0` → `now - 0 >= 1000` → fresh window.
21. **Full-state requests ignore AoI** (§4.13): the reply can include entities far outside the requester's AoI, and those then enter the peer's delta cache and visible-set bookkeeping only via the cache (NOT `client_visible_entities` — which means the next AoI pass will treat far entities as *not previously visible*, cull them, and the stale-cache cleanup emits REMOVED deltas for them).
22. **`process_all_inputs` confirms only on fresh input** — a client that stops sending receives no ACTION_CONFIRMs (its prediction buffer drains via the last confirmed sequence).
23. **`_process_shoot_inputs` iterates `get_all_players()`** (not just authenticated) — harmless because `can_shoot()` requires `authenticated`, but pending_shots can only exist post-auth anyway.
24. **JSON numbers are floats.** Godot's JSON parser produces 64-bit floats for all numbers; typed `int` getters truncate toward zero at the Variant→int conversion (e.g. `"tick_rate": 30.0` → 30). A Rust config loader must accept both integer and float JSON encodings.
25. **Dictionary iteration order**: GDScript Dictionaries iterate in insertion order. Player-tick processing, broadcast peer order, and grid bucket order all follow it. Nothing in this subsystem's *semantics* depends on iteration order (per-player operations are independent; the scheduler re-sorts), but **wire-visible orderings** (entity order inside packets, peer send order within a tick) will differ in a port using HashMap — acceptable, but document it for byte-level diffing.
26. **`MAX_INPUT_QUEUE_SIZE` overflow drops the OLDEST input** — under a 10+-input burst the earliest movement intents (and their rising shoot edges, since those are detected at ingest, not enqueue) are lost entirely.
27. **`update_cache_partial` with a FULL_STATE mask** rewrites all fields; with partial masks only the masked fields are committed, so unsent-field changes stay dirty and re-emit later — this is what makes deferral lossless.
28. **`needs_baseline_resend` never fires before the first baseline** (`_baseline_tick == 0` → false). Combined with `DELTA_FULL_STATE_INTERVAL`, a peer's first true baseline arrives at the first snapshot tick where `tick_count >= 100` (or via `REQUEST_FULL_STATE`, which clients send on join). Fresh joins before tick 100 rely on per-entity FULL_STATE masks inside delta packets, with `baseline_tick = 0`.

---

## 6. Cross-subsystem contracts

### 6.1 What this subsystem calls (expects from others)

| Provider | Call | Semantics required |
|---|---|---|
| PlayerManager | `process_all_inputs(delta: f32, server_tick: i64) -> Array<MoveResult>` | drains each authenticated player's queue, steps movement once, returns `{peer_id, sequence, position, success, cheat_detected, deviation, stamina, mana}` per player **that had fresh input** |
| PlayerManager | `queue_player_input(peer_id, input_dict)` | drops for unknown/unauthenticated peers; per-player FIFO cap 10, drop-oldest |
| PlayerManager | `record_position_snapshot(tick)` / `get_recent_positions(entity_id) -> Array<Vector2>` | 8-tick history + live position (oldest first) for hit plausibility |
| PlayerManager | `add_player`, `remove_player`, `get_player`, `has_player`, `authenticate_player`, `respawn_player`, `get_player_count`, `get_all_players`, `get_authenticated_players`, `clear_all` | id assignment, round-robin spawn, life-state reset |
| ProjectileManager | `spawn_projectile(owner_id, pos, dir, tick, rewind_ticks, client_render_tick, client_rtt_ms, source: String, pvp_rewind_ticks) -> ProjectileState?` | null on failure (pool/cap); projectile carries the rewind metadata |
| ProjectileManager | `update_all(delta)`, `collect_state_updates() -> alive-only entity data`, `remove_projectile(id, reason)`, `get_projectile_count()`, direct map access `projectiles.get(id)` | |
| MonsterManager | `record_position_snapshot(tick)`, `cleanup_dead_monsters()`, `get_alive_monsters()`, `collect_state_updates() -> ALL monsters`, `get_monster_count()`, `get_closest_alive_monster(pos)` (debug only) | dead monsters stay in state updates until cleanup |
| MonsterSpawner | `update(delta)` | accumulator spawning at `monster_spawn_rate` |
| MonsterAI | `update_all(alive_monsters, delta) -> Array<{source_id, projectile_id, ...}>` | fire events with **non-zero** projectile ids (D11 invariant) |
| CollisionHandler | `process_collisions(projectile_mgr, player_mgr, monster_mgr, nm, broadcast_service)` and `apply_player_hit(attacker_owner_id, victim_entity_id, player_mgr, nm, broadcast_service, hit_position)` | the shared damage path; broadcasts its own GAME_EVENTs inside the batch window |
| HitAuthority (shared `sim_core` per D11) | `is_client_authoritative(owner_id) -> bool` (= `owner_id >= 30000`); `flight_origin(pos, dir, dist) -> pos - dir*dist`; `is_hit_plausible(start, end, positions, threshold)` (any position strictly `< threshold` from its closest point on the segment) | |
| NetworkManager (transport) | signals `server_client_connected(peer_id)`, `server_client_disconnected(peer_id)`, `server_client_message(peer_id, type, dict)`; calls `send_to_client(peer_id, type, dict)`, `broadcast_to_clients(type, dict)`, `begin_batch()`, `flush_batches()`, `clear_batches()`, `disconnect_client(peer_id, reason)`, `get_stats()`, `peer_bytes_sent: Dictionary` | per-tick batch window; per-peer cumulative byte accounting |
| LeaderboardManager | `register_player(entity_id)`, `remove_player(entity_id)`, `get_top_n(10) -> [{entity_id, pvp_kills}]`, `clear()` | sorted desc by kills (entity_id asc tiebreak) |

### 6.2 What this subsystem produces (provides to clients)

| Packet | When | Payload built here |
|---|---|---|
| `STATE_UPDATE` (2) | per snapshot tick, per peer | `{tick, state_flags (1=delta / 2=baseline), baseline_tick, entities: [{entity_id, delta_mask, entity_type?, position?, animation_state?, flags?}]}` — see §4.8.5/4.8.6; entity order = scheduler priority order |
| `ACTION_CONFIRM` (5) | every tick, per peer with fresh input | move confirm: sequence (u8 space), corrected position, server tick, result code, stamina/mana (0–255) |
| `GAME_EVENT` (3) `PROJECTILE_FIRED` | on player spawn (real pos+tick) and monster fire (pos=(0,0), tick=0) | `source_id`, `target_id`=projectile_id, `{position, server_tick}` |
| `GAME_EVENT` `RESPAWN` | on granted respawn, broadcast | `target_id`=entity_id, `{position}` |
| `GAME_EVENT` `PLAYER_INFO` | on auth (broadcast + catch-up to joiner), and full-state-request replies | `target_id`=entity_id, `{character_name, position, player_color}` |
| `GAME_EVENT` `LEADERBOARD_UPDATE` | every 5 s (tick time), on auth, on disconnect | `{entries: [{entity_id, pvp_kills}] (≤10)}` |
| `SERVER_METRICS` (10) | 1 Hz, only with ≥1 player, unbatched | 13 fields, §4.11 |
| `DISCONNECT` (7) | shutdown | `{reason: 3}` (SERVER_SHUTDOWN) |

### 6.3 What it consumes from clients

| Packet | Handler | Fields used |
|---|---|---|
| `PLAYER_INPUT` (1) | queue → tick drain | `input_flags (u16)`, `sequence_number (u8)`, `aim_angle (f32 rad)`, `position`, `velocity`, `client_render_tick (u16)`, `client_rtt_ms (u16)` |
| `CONNECT_AUTH` (6) | auth | `character_id`, `character_name`, `player_color`, `bandwidth_budget_bps (u32; 0 = server decides)` |
| `REQUEST_FULL_STATE` (8) | unfiltered baseline + PLAYER_INFO replay | none |
| `RESPAWN_REQUEST` (9) | respawn gate | none |
| `BASELINE_ACK` (12) | `mark_baseline_acked` | `baseline_tick (u32)` |
| `LOCAL_HIT_REPORT` (13) | validated victim-side PvE hit | `projectile_id (u16)` |

### 6.4 Go API contract

`POST {api_server_url}/api/regions/heartbeat` every 2 s, body `{"region_id", "active_players", "max_players", "websocket_url", "status"}`, optional header `X-Region-Heartbeat-Token` from env `REGION_HEARTBEAT_TOKEN`. Response ignored except for logging. Per D13 this generalizes to instance liveness registration; the hardcoded `ws://localhost:<port>` URL is a known wart the port should replace with a configured advertise address.

---

## 7. Rust port hazards (checklist)

- [ ] **H1 — Frame-driven loop vs dedicated thread.** GDScript ticks from a per-frame callback with an unbounded catch-up `while`; D8 mandates a dedicated tick thread. Reproduce the *cadence semantics* (fixed 33.3 ms, fractional-remainder carry, multiple catch-up ticks after a stall, at most one snapshot per catch-up burst) — and decide explicitly whether to keep the unbounded catch-up (GDScript does; it can death-spiral).
- [ ] **H2 — Float precision split.** GDScript scalar floats are f64, but `Vector2` components are **f32** in standard Godot builds. All positions/distances here are f32 math with f64 scalars mixed in (e.g. `distance_squared_to` returns f32-derived value promoted to f64). `sim_core` parity (D5) needs one declared policy; the delta-cache 0.05 threshold and AoI radii comparisons are sensitive at quantization boundaries.
- [ ] **H3 — Exact accumulator arithmetic.** `tick_dt` and `snapshot_interval` are both `1.0/float(rate)`; when rates are equal the accumulator hits the threshold exactly every tick (no fp drift because subtraction returns it to exactly 0.0). With differing rates, fire pattern depends on fp rounding (e.g. 20 Hz snapshot @30 Hz tick ≈ 2-1-2-1 tick pattern). Port the guard: subtract once, and zero the accumulator if it still exceeds the interval.
- [ ] **H4 — Integer semantics.** GDScript ints are i64: `tick_count` never wraps; `& 0xFFFF` wraparound resolution for `client_render_tick` (±32767/−32768 window); `int(float)` conversions truncate toward zero (budget derivation, fixed-point metric encode); `ceili` for grid cells and latency ticks; `floori` (toward −∞) for grid cell coordinates — Rust `f32::floor() as i32`, NOT integer division (negative coordinates!).
- [ ] **H5 — Sentinels.** `Vector2.INF` = absent client fire position; entity id `< 0` = invalid; `_pending_baseline_tick == 0` = no outstanding baseline; `peer_snapshot_bytes` missing = use global default (and **never** 0, which disables the budget); `max_bytes <= 0` = budget off; `last_input_received_tick == 0` = stale-input check exempt.
- [ ] **H6 — Order of operations per tick** is load-bearing: inputs → shoot spawns → confirmations → projectiles/spawner/timers → AI (+fire events) → **position history snapshot** → collisions → broadcast → monster cleanup → flush. Moving the history record or the cleanup changes lag-comp and death-broadcast behavior respectively.
- [ ] **H7 — Scheduler determinism.** Sort must be by (priority desc, entity_id asc) — a total order, so any sort works; greedy admission has **no early break** and pinned items both bypass and consume budget; `max_queue_age` is measured over all candidates including selected ones.
- [ ] **H8 — Baseline/delta interleaving** (gotcha #3): baseline only when `needs_baseline && removals.is_empty()`; the delta path's per-entity interval check emits FULL_STATE masks without resetting the baseline. Easy to "fix" accidentally in a port; that changes wire behavior and budget pressure.
- [ ] **H9 — Clock bases.** Three different time sources today: `_process` delta accumulation (`server_time`, tick cadence, region heartbeat), engine-uptime msec (`ServerMetrics`, rate limiter, player timestamps), and µsec monotonic (tick duration). The metrics gate compares across two of them (gotcha #17). The port should consolidate to one monotonic clock and accept the (benign) phase change.
- [ ] **H10 — Batch window.** Everything sent inside a tick is coalesced per peer and flushed at end-of-tick (≤1 tick of added queueing); `SERVER_METRICS` and shutdown DISCONNECTs are sent *outside* the window. Under D2's ENet transport, BATCH dies — but the *event ordering within a tick* (events before/with the snapshot in one flush) is what clients experience today; preserve ordering per peer per tick on the reliable channel.
- [ ] **H11 — `tick_rate = 0` config** divides by zero (gotcha #16) — the GDScript misbehaves (inf interval, loop never fires); validate config in Rust instead of porting the crash.
- [ ] **H12 — u16/u8 saturation vs wrap in SERVER_METRICS**: sched fields are explicitly `min`-saturated / clamped, but the two ×100 fixed-point tick-time fields silently wrap past 655.35 ms — saturate them in the port (visible difference only in pathological cases).
- [ ] **H13 — AoI strictness and hysteresis state.** Cull only when `dist_sq > threshold_sq` (strict); `exit == enter` disables hysteresis (strict `>` in three places: exit_sq selection, grid cell sizing, query radius). Visible-set is per peer and is what defines REMOVED emissions; a port using a different visibility representation must still emit exits exactly once and pin them.
- [ ] **H14 — New-entity priority ≈ tick_count** (gotcha #4): preserve unless consciously redesigned; changing it alters which entities get starved under budget pressure.
- [ ] **H15 — Engine dependencies are minimal but real:** `HTTPRequest` (async heartbeat with one-in-flight gating), `OS.get_environment`, JSON float parsing, `Time.*` clocks, and the headless `_process` pump. None of `move_and_slide`/physics is used **in this subsystem** (movement physics lives in the player/movement subsystem — see its extraction doc); the spatial grid here is pure math and ports directly.
- [ ] **H16 — Iteration-order differences** (gotcha #25): peer processing and packet entity order may legally differ in Rust; do not promise byte-identical packets, only semantically identical (same entities, same masks, same budget outcomes given the same priorities).
- [ ] **H17 — Input burst semantics:** all queued inputs ingested per tick (last-wins flags, every rising SHOOT edge queued, DASH latched across overwrites), exactly one movement step, at most one projectile spawn attempt per player per tick, held auto-fire only if no rising edge fired that tick — and a cooldown-blocked rising edge still suppresses held auto-fire for the tick.
