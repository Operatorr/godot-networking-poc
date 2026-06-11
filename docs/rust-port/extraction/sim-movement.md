# Extraction: sim-movement (player movement, dash, stamina/mana, knockback, state machine, obstacle collision, client prediction stepping)

> Generated extraction notes for the Rust port — derived from GDScript at commit `9e66149` on branch `feature/rust-port`. Source of truth is the GDScript until cutover.

Audience: the Rust engineer implementing the shared `sim_core` movement crate (migration spec D5/D8).
This document is self-contained — you should not need to read GDScript. Exact values, exact order of
operations, and exact float semantics are the point. Where behavior depends on Godot engine internals
the **observable** behavior is described and flagged `ENGINE-DEPENDENT`.

All source paths are relative to the repo root. Line numbers refer to commit `9e66149`.

---

## 1. Overview

This subsystem is the **player movement simulation**: how a player's input flags become a velocity,
how that velocity is integrated against the arena bounds and the 16 static obstacles, and how the
exact same step runs in three places:

1. **Server, authoritative** — `PlayerState.step()` (`client/scripts/server/player_state.gd:217`),
   called exactly once per player per server Tick (30 Hz) from
   `PlayerManager.process_all_inputs()` (`client/scripts/server/player_manager.gd:118`), which is
   step 1 of the server tick loop (`client/scripts/server/server_main.gd`, `_process_server_tick`).
2. **Client, predicted** — `PredictionController._apply_local_prediction()`
   (`client/scripts/client/prediction.gd:324`), called once per client physics frame. The client's
   physics clock is forced to `SERVER_TICK_RATE` (30 Hz) at startup
   (`client/autoload/game_manager.gd:70`: `Engine.physics_ticks_per_second = int(GameConstants.SERVER_TICK_RATE)`),
   so prediction steps at the same 30 Hz with the same fixed delta `1.0/30.0`.
3. **Client, reconciliation replay** — `PredictionController._replay_input()`
   (`prediction.gd:683`), which re-simulates buffered inputs after a server correction using a
   **simplified ground-speed-only model** (deliberately NOT the full state machine — see §4.9).

The core pieces:

- **`MovementStateMachine`** (`client/scripts/shared/player/movement_state_machine.gd`) — a
  deterministic 7-state machine (IDLE / WALKING / SPRINTING / DASHING / KNOCKED_BACK / STUNNED /
  ABILITY_MOVEMENT) owning dash, knockback, stun, stamina, and mana. One instance per server-side
  `PlayerState`, one identical predicted instance per local client player. It never reads input
  devices; all inputs arrive as `tick()` arguments. It returns the velocity to integrate this step.
- **Analytic collision** (`client/scripts/shared/game_constants.gd:525`,
  `move_with_obstacle_collision`) — a pure function (no physics engine) that clamps to map bounds
  and slides axis-separated along obstacles. Used identically by server step, client prediction,
  and replay. **This is the function the Rust sim must reproduce bit-for-bit in intent.**
- **Prediction bookkeeping** (`prediction.gd`) — input flag capture, dash latching, 8-bit wrapping
  sequence numbers, input snapshot buffer, ACTION_CONFIRM / STATE_UPDATE reconciliation, and visual
  correction smoothing.

Per-tick vs per-frame: **everything that moves the player runs at the fixed 30 Hz physics/tick
rate** with delta exactly `1.0/30.0` (an f64 division; see hazards). Client `_process` (per render
Frame) only does cosmetics (camera zoom lerp, entity visuals) and never moves the player.

---

## 2. Constants

### 2.1 Tick / cadence

| Constant | Value | Unit | Source |
|---|---|---|---|
| `SERVER_TICK_RATE` | `30.0` | Hz (f64) | `game_constants.gd:22` |
| `SERVER_TICK_INTERVAL` | `1.0 / 30.0` (= 0.0333333333333333328707…, f64) | s | `game_constants.gd:25` |
| `INPUT_SEND_INTERVAL` | `= SERVER_TICK_INTERVAL` | s | `prediction.gd:78` |
| Client physics rate | `int(SERVER_TICK_RATE)` = 30 | Hz | `game_manager.gd:70` (project.godot fallback `physics_ticks_per_second=30`) |
| Server tick delta passed to step | `1.0 / config.tick_rate` (tick_rate is `int`, default `int(SERVER_TICK_RATE)` = 30; JSON config can override) | s | `server_main.gd` `_process_client_inputs`, `server_config.gd:13,63` |

### 2.2 Movement speeds

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_SPEED` | `200.0` | units/s | `game_constants.gd:53` |
| `PLAYER_SPRINT_MULTIPLIER` | `1.6` | — | `game_constants.gd:56` |
| `PLAYER_SPRINT_SPEED` | `200.0 * 1.6` = `320.0` | units/s | `game_constants.gd:59` |

### 2.3 Dash

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_DASH_MULTIPLIER` | `3.6` | — | `game_constants.gd:70` |
| `PLAYER_DASH_SPEED` | `200.0 * 3.6` = `720.0` | units/s | `game_constants.gd:73` |
| `PLAYER_DASH_DURATION` | `0.4` | s | `game_constants.gd:76` |
| `PLAYER_DASH_COOLDOWN` | `5.5` | s, **START-relative** (clock starts when the dash starts; usable gap ≈ 5.1 s) | `game_constants.gd:80` |

### 2.4 Knockback

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_KNOCKBACK_DECAY` | `9.0` | 1/s (exponential decay rate: `v *= exp(-9.0 * delta)` per tick) | `game_constants.gd:89` |
| `PLAYER_KNOCKBACK_END_SPEED` | `12.0` | units/s (at or below ⇒ knockback ends) | `game_constants.gd:92` |
| `PLAYER_KNOCKBACK_BASE_FORCE` | `450.0` | units/s (initial speed when no caller-specific force) | `game_constants.gd:96` |

### 2.5 Stamina / mana

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_STAMINA_MAX` | `100.0` | points | `game_constants.gd:104` |
| `PLAYER_STAMINA_DRAIN_PER_SEC` | `35.0` | points/s (while SPRINTING) | `game_constants.gd:107` |
| `PLAYER_STAMINA_REGEN_PER_SEC` | `20.0` | points/s (while NOT SPRINTING) | `game_constants.gd:110` |
| `PLAYER_STAMINA_SPRINT_MIN` | `5.0` | points (sprint requires `stamina > 5.0`, **strict**) | `game_constants.gd:113` |
| `PLAYER_MANA_MAX` | `100.0` | points | `game_constants.gd:121` |
| `PLAYER_MANA_REGEN_PER_SEC` | `10.0` | points/s | `game_constants.gd:124` |
| `PLAYER_MANA_ABILITY_COST` | `25.0` | points | `game_constants.gd:127` |

### 2.6 Speed modifier bounds (status effects, placeholder but live code)

| Constant | Value | Source |
|---|---|---|
| `PLAYER_SPEED_MULT_MIN` | `0.25` | `game_constants.gd:135` |
| `PLAYER_SPEED_MULT_MAX` | `2.5` | `game_constants.gd:136` |

### 2.7 Movement validation thresholds (server) and prediction config (client)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `POSITION_TOLERANCE` | `75.0` | units (soft, currently informational only — not branched on in `_validate_position`) | `game_constants.gd:161` |
| `CORRECTION_THRESHOLD` | `112.5` | units (deviation `>` ⇒ correction packet) | `game_constants.gd:165` |
| `TELEPORT_THRESHOLD` | `150.0` | units (deviation `>` ⇒ cheat flag + correction) | `game_constants.gd:169` |
| `interpolation_speed` (client export default) | `12.0` | 1/s (visual correction lerp rate) | `prediction.gd:27` |
| `max_buffer_size` (client export default) | `256` | inputs (logical cap = sequence space; never enforced as a hard limit — pruning keeps it bounded) | `prediction.gd:29` |
| `teleport_threshold` (client export default) | `150.0` | units (visual snap vs smooth correction) | `prediction.gd:35` |
| `server_position_epsilon` (client export default) | `4.0` | units (ignore drift at or below; reconcile strictly above) | `prediction.gd:37` |
| Smooth-correction stop distance | `1.0` | units (hardcoded) | `prediction.gd:743` |

### 2.8 Map bounds & arena

| Constant | Value | Source |
|---|---|---|
| `MAP_MIN` | `Vector2(-1000.0, -1000.0)` | `game_constants.gd:177` |
| `MAP_MAX` | `Vector2(1000.0, 1000.0)` | `game_constants.gd:180` |
| `PLAYER_HITBOX_RADIUS` | `16.0` units | `game_constants.gd:343` |
| `ARENA_TILE_COLUMNS` / `ROWS` | `40` / `40` | `game_constants.gd:188-189` |
| `ARENA_TILE_SIZE` | `50.0` units | `game_constants.gd:190` |

**Boundary walls at ±1005** (`client/scenes/shared/arena/arena_base.tscn:97-114`): a `StaticBody2D`
"Boundaries" on collision layer 8, four `RectangleShape2D`s — Top at `(0, -1005)` size `2020×10`,
Bottom at `(0, 1005)` size `2020×10`, Left at `(-1005, 0)` size `10×2020`, Right at `(1005, 0)` size
`10×2020`. **These walls are engine-physics scenery only and play NO role in the networked sim** —
the authoritative sim clamps the player center to ±1000 analytically (`clamp_to_bounds`). The Rust
sim does not need them. (See §5.10 for the offline-mode caveat: the player's collision mask doesn't
even include layer 8, so `move_and_slide` never touches these walls either.)

### 2.9 Arena player spawns (`game_constants.gd:199-210`, static, world coords)

```
(-800,-800) (0,-800) (800,-800) (-800,0) (800,0)
(-800,800)  (0,800)  (800,800)  (-450,450) (450,-450)
```
All 10 pass the spawn validity filter (`is_valid_player_spawn_position`,
`game_constants.gd:295`: circle radius 16 fully within ±1000 AND not intersecting any obstacle).
Spawn selection is `randi() % count` over the cached list (`arena_base.gd:1174-1177`) — uniform
random, engine RNG, not part of deterministic sim.

### 2.10 Arena obstacles — THE EXACT LAYOUT (`game_constants.gd:480-502`)

16 axis-aligned rectangles, `Rect2(position, size)` where `position` is the **top-left corner** and
`size` is width×height (y grows downward). Order matters only for which intersection is reported
first; the movement result does not depend on order (any hit ⇒ blocked). Stored as f32 internally
(Godot `Vector2`/`Rect2` are single-precision).

| # | Name | position (x, y) | size (w, h) | extents (x0..x1, y0..y1) |
|---|---|---|---|---|
| 0 | Center north pillar | (-20, -200) | (40, 160) | -20..20, -200..-40 |
| 1 | Center south pillar | (-20, 40) | (40, 160) | -20..20, 40..200 |
| 2 | Center west pillar | (-200, -20) | (160, 40) | -200..-40, -20..20 |
| 3 | Center east pillar | (40, -20) | (160, 40) | 40..200, -20..20 |
| 4 | NW horizontal | (-700, -700) | (150, 30) | -700..-550, -700..-670 |
| 5 | NW vertical | (-700, -700) | (30, 150) | -700..-670, -700..-550 |
| 6 | NE horizontal | (550, -700) | (150, 30) | 550..700, -700..-670 |
| 7 | NE vertical | (670, -700) | (30, 150) | 670..700, -700..-550 |
| 8 | SW horizontal | (-700, 670) | (150, 30) | -700..-550, 670..700 |
| 9 | SW vertical | (-700, 550) | (30, 150) | -700..-670, 550..700 |
| 10 | SE horizontal | (550, 670) | (150, 30) | 550..700, 670..700 |
| 11 | SE vertical | (670, 550) | (30, 150) | 670..700, 550..700 |
| 12 | NW mid barrier | (-450, -350) | (100, 25) | -450..-350, -350..-325 |
| 13 | NE mid barrier | (350, -350) | (100, 25) | 350..450, -350..-325 |
| 14 | SW mid barrier | (-450, 325) | (100, 25) | -450..-350, 325..350 |
| 15 | SE mid barrier | (350, 325) | (100, 25) | 350..450, 325..350 |

The tile map drawn from these (border tiles at the outermost 50-unit ring, obstacle tiles where a
tile rect intersects an obstacle including border-touching, `game_constants.gd:269-291`) is
**visual only** — gameplay collision uses the rectangles above directly.

### 2.11 Input flag bits (wire `u16`; `client/scripts/shared/networking/packet_types.gd:56-64`)

| Flag | Bit | Value | Key |
|---|---|---|---|
| `INPUT_FLAG_MOVE_UP` | 0 | 1 | W |
| `INPUT_FLAG_MOVE_DOWN` | 1 | 2 | S |
| `INPUT_FLAG_MOVE_LEFT` | 2 | 4 | A |
| `INPUT_FLAG_MOVE_RIGHT` | 3 | 8 | D |
| `INPUT_FLAG_SHOOT` | 4 | 16 | LMB |
| `INPUT_FLAG_ABILITY` | 5 | 32 | RMB |
| `INPUT_FLAG_SPRINT` | 6 | 64 | Shift |
| `INPUT_FLAG_INTERACT` | 7 | 128 | E (captured/sent; not consumed by movement) |
| `INPUT_FLAG_DASH` | 8 | 256 | Space — edge-triggered, latched (see §4.8) |

### 2.12 Entity flag bits replicated from movement (`packet_types.gd:67-74`)

| Flag | Bit | Set when |
|---|---|---|
| `ENTITY_FLAG_ALIVE` | 0 | `is_alive` |
| `ENTITY_FLAG_MOVING` | 1 | `velocity.length_squared() > 0.01` |
| `ENTITY_FLAG_ATTACKING` | 2 | SHOOT input flag held |
| `ENTITY_FLAG_INVULNERABLE` | 3 | life_state == INVULNERABLE |
| `ENTITY_FLAG_STUNNED` | 4 | SM state == STUNNED |
| `ENTITY_FLAG_VISIBLE` | 5 | always set today |
| `ENTITY_FLAG_DASHING` | 6 | SM state == DASHING |
| `ENTITY_FLAG_KNOCKED_BACK` | 7 | SM state == KNOCKED_BACK |

### 2.13 Server input plumbing

| Constant | Value | Source |
|---|---|---|
| `STALE_INPUT_TICK_LIMIT` | `6` ticks (flags cleared when `server_tick - last_input_received_tick > 6`) | `player_state.gd:80` |
| `MAX_INPUT_QUEUE_SIZE` | `10` (overflow drops the OLDEST queued input) | `player_state.gd:106` |
| `SHOOT_COOLDOWN` | `0.3` s (decremented in step; gates fire, not movement) | `game_constants.gd:364` |
| `RESPAWN_DELAY` | `3.0` s | `game_constants.gd:367` |
| `INVULNERABILITY_DURATION` | `3.0` s | `game_constants.gd:370` |

### 2.14 Geometry epsilons (hardcoded in `game_constants.gd`)

| Where | Value | Meaning |
|---|---|---|
| `_line_rect_intersection` axis-parallel guard | `abs(dir.x) < 0.0001` (same for y) | treat ray as axis-parallel |
| `closest_point_on_segment` degenerate guard | `length_squared() <= 0.0001` | segment treated as a point |
| `_movement_hits_obstacle` zero-move guard | `from.is_equal_approx(to)` | Godot epsilon compare, see §5.7 |

---

## 3. Data structures

### 3.1 `MovementStateMachine` (`movement_state_machine.gd:52-77`) — one per player, both sides

State enum (`movement_state_machine.gd:23-31`): `IDLE=0, WALKING=1, SPRINTING=2, DASHING=3,
KNOCKED_BACK=4, STUNNED=5, ABILITY_MOVEMENT=6`.

| Field | Type | Initial | Range / notes |
|---|---|---|---|
| `state` | enum | `IDLE` | one of the 7 states |
| `stamina` | f64 | `100.0` | [0, 100] |
| `mana` | f64 | `100.0` | [0, 100] |
| `_dash_time_left` | f64 | `0.0` | [0, 0.4]; decremented `maxf(0.0, x - delta)` |
| `_dash_cooldown_left` | f64 | `0.0` | [0, 5.5]; START-relative |
| `_stun_time_left` | f64 | `0.0` | ≥ 0; decremented only while STUNNED |
| `_dash_velocity` | Vector2 (f32) | `(0,0)` | set on dash start, magnitude `720 * _speed_multiplier` |
| `_knockback_velocity` | Vector2 (f32) | `(0,0)` | decays exponentially |
| `_ability_velocity` | Vector2 (f32) | `(0,0)` | externally owned |
| `_speed_multiplier` | f64 | `1.0` | clamped [0.25, 2.5] when set via `apply_speed_modifier` |
| `_prev_dash_held` | bool | `false` | internal edge detector |
| `_prev_ability_held` | bool | `false` | internal edge detector |

`reset()` (`movement_state_machine.gd:391-403`) restores every field above to its initial value.
Called on spawn, respawn, and death (server `_mark_dead`).

Signals (Rust: events/callbacks, only needed client-side for HUD/audio): `movement_state_changed`,
`dash_started(dir)`, `dash_ended`, `sprint_started`, `sprint_ended`, `knockback_started(dir, force)`,
`knockback_ended`, `stun_started(duration)`, `stun_ended`, `stamina_changed(cur,max)`,
`mana_changed(cur,max)`.

### 3.2 `PlayerState` — server-side movement-relevant fields (`player_state.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `entity_id` | int | 0 | players 1–999 |
| `position` | Vector2 (f32) | spawn position | authoritative |
| `velocity` | Vector2 (f32) | (0,0) | realized velocity (post-collision) |
| `aim_angle` | f64 | 0.0 | radians, from client packet |
| `movement_sm` | MovementStateMachine | fresh | authoritative instance |
| `input_flags` | int | 0 | persistent — re-applied EVERY tick until overwritten or stale |
| `last_input_sequence` | int | 0 | echoed in ACTION_CONFIRM |
| `last_client_position` | Vector2 | (0,0) | latest client-reported pos |
| `has_client_position` | bool | false | gates validation |
| `last_input_received_tick` | int | 0 | 0 = never; stale gate |
| `_pending_dash` | bool | false | latched on ingest, consumed once in step |
| `input_queue` | Array<Dictionary> | [] | cap 10, FIFO, drop-oldest |
| `pending_shots` | Array<Dictionary> | [] | SHOOT rising edges (combat subsystem) |
| `life_state` | enum {ALIVE=0, DEAD=1, INVULNERABLE=2} | ALIVE | |
| `shoot_cooldown` | f64 | 0.0 | decremented in step |
| `invulnerability_timer` / `respawn_timer` | f64 | 0.0 | |
| `health` / `max_health` | int | 100 / 100 | |
| `is_alive` | bool | true | |
| `animation_state` | int (u8 on wire) | IDLE=0 | see §4.6 |
| `entity_flags` | int (u8 on wire) | ALIVE\|VISIBLE = 0x21 | see §4.6 |

### 3.3 `PredictionController` — client state (`prediction.gd:41-94`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `local_entity_id` | int | -1 | set at Authority sync |
| `predicted_position` | Vector2 (f32) | setup arg | the logical predicted position |
| `predicted_velocity` | Vector2 (f32) | (0,0) | realized (post-collision) |
| `has_authoritative_position` | bool | false | prediction inert until first server pos |
| `last_ack_sequence` | int | -1 | -1 = none |
| `current_sequence` | int | 0 | 0..255 wrapping |
| `input_buffer` | Dictionary<int seq, InputSnapshot> | {} | pruned on ack |
| `correction_target` | Vector2 | setup arg | |
| `is_correcting` | bool | false | smooth-correction in flight |
| `last_server_tick` | int | 0 | |
| `input_send_timer` | f64 | 0.0 | accumulator; send when ≥ 1/30, then `-= 1/30` |
| `current_input_flags` | int | 0 | this frame's captured flags |
| `_dash_latched` | bool | false | held until next send |
| `prediction_enabled` | bool | true | |

### 3.4 `InputSnapshot` (`prediction.gd:99-120`) — one per SENT input

| Field | Type | Notes |
|---|---|---|
| `sequence` | int | 0..255 |
| `input_flags` | int | flags at send time |
| `position_before` | Vector2 | predicted_position at send time |
| `position_after` | Vector2 | precomputed replay end (updated on each replay) |
| `velocity` | Vector2 | ground-model velocity (updated on replay) |
| `aim_angle` | f64 | at send time |
| `delta` | f64 | always `INPUT_SEND_INTERVAL` (1/30) |
| `timestamp` | f64 | wall clock, debug only |

### 3.5 Input packet payload (client → server, `prediction.gd:487-505`)

```
{ position: Vector2,            # predicted_position at send time
  velocity: Vector2,            # predicted_velocity (realized)
  keys: {up,down,left,right,shoot,ability,sprint,interact,dash: bool},  # encoded to the u16 flags
  aim_angle: f64,               # radians, atan2(mouse - predicted_position)
  sequence: int,                # 0..255
  client_render_tick: int,      # u16-masked render tick (lag comp; other subsystem)
  client_rtt_ms: int }
```

### 3.6 Validation result (server step return, `player_state.gd:310-336`)

```
{ valid: bool, deviation: f64, correction_needed: bool,
  server_position: Vector2, cheat_detected: bool, sequence: int }
```

---

## 4. Algorithms

All pseudocode preserves exact order, comparisons (strict vs non-strict), and early returns.
`Vector2` math is f32 (Godot single-precision `real_t`); scalar GDScript floats are f64. See §7.

### 4.1 `clamp_to_bounds(pos)` (`game_constants.gd:234-238`)

```
return ( clamp(pos.x, -1000.0, 1000.0), clamp(pos.y, -1000.0, 1000.0) )
```
Note: clamps the **center**; the 16-unit radius is NOT subtracted, so the player circle may
protrude 16 units outside the playfield at the edges. This is the authoritative bound; the ±1005
scene walls are irrelevant to the sim.

### 4.2 `circle_intersects_obstacle(center, radius)` (`game_constants.gd:514-520`)

```
for obs in ARENA_OBSTACLES (in table order):
    expanded = Rect2(obs.position - (radius, radius), obs.size + (2*radius, 2*radius))
    if expanded.has_point(center): return true
return false
```
**`Rect2.has_point` semantics (ENGINE-DEPENDENT, reproduce exactly):** lower edges inclusive,
upper edges **exclusive**:
`p.x >= pos.x && p.y >= pos.y && p.x < pos.x+size.x && p.y < pos.y+size.y`.
So this is a **Chebyshev (square) expansion**, not a true circle-vs-rect test — a circle near an
obstacle corner is blocked as if it were a 32×32 axis-aligned box. **Do NOT "fix" this with
closest-point-on-rect math in Rust; parity requires the expanded-rect point test.**

### 4.3 `_line_rect_intersection(from, to, rect)` (`game_constants.gd:593-632`) — slab method

Returns the first intersection point of segment `from→to` with `rect`, or the sentinel
`Vector2.INF` (`(+inf, +inf)`) for no hit.

```
dir = to - from
t_min = 0.0; t_max = 1.0
# X slab
if abs(dir.x) < 0.0001:
    if from.x < rect.pos.x or from.x > rect.pos.x + rect.size.x: return INF   # NOTE: inclusive both edges here
else:
    t1 = (rect.pos.x - from.x) / dir.x
    t2 = (rect.pos.x + rect.size.x - from.x) / dir.x
    if t1 > t2: swap(t1, t2)
    t_min = max(t_min, t1); t_max = min(t_max, t2)
    if t_min > t_max: return INF
# Y slab — identical shape
...
if t_min >= 0.0 and t_min <= 1.0: return from + dir * t_min
return INF
```
Notes:
- If `from` is **inside** the rect, slabs leave `t_min = 0` ⇒ returns `from` itself (≠ INF ⇒ hit).
- The slab test treats rect edges as **inclusive**; `has_point` treats upper edges as exclusive.
  This asymmetry is part of observed behavior (see §5.4).
- Division by `dir.x` is safe (guarded by the 0.0001 axis-parallel check). Both branches use the
  raw `from`/`rect` f32 components; no normalization.

### 4.4 `_movement_hits_obstacle(from, to, radius)` (`game_constants.gd:548-559`)

```
if from.is_equal_approx(to):                 # Godot epsilon compare, §5.7
    return circle_intersects_obstacle(to, radius)
for obs in ARENA_OBSTACLES (in order):
    expanded = obs grown by radius on all sides (as in 4.2)
    if expanded.has_point(to): return true                       # end inside ⇒ hit
    if _line_rect_intersection(from, to, expanded) != Vector2.INF: return true   # swept crossing ⇒ hit
return false
```
The swept test means you cannot tunnel through a thin obstacle in one tick regardless of speed.

### 4.5 `move_with_obstacle_collision(from, to, radius)` (`game_constants.gd:525-544`) — THE mover

```
target = clamp_to_bounds(to)                            # clamp FIRST, then test obstacles
if not _movement_hits_obstacle(from, target, radius):
    return target                                       # free move

# blocked: try axis-separated slide
x_target = clamp_to_bounds( (target.x, from.y) )        # horizontal component only
y_target = clamp_to_bounds( (from.x, target.y) )        # vertical component only
best_position = from
best_distance = distance_squared(from, target)

if not _movement_hits_obstacle(from, x_target, radius):
    best_position = x_target
    best_distance = distance_squared(x_target, target)

if not _movement_hits_obstacle(from, y_target, radius):
    y_distance = distance_squared(y_target, target)
    if y_distance < best_distance:                      # STRICT <  ⇒ ties favor the X axis
        best_position = y_target

return best_position
```
Observable behavior: moving diagonally into a wall slides along it at the **full axis component
speed** (no velocity re-projection, no friction). If both axis moves are blocked the player does
not move at all this tick. After the mover runs, callers recompute velocity as
`(result - from) / delta`, so the replicated/realized velocity reflects the slide.

### 4.6 `MovementStateMachine.tick(delta, move_dir, sprint_held, dash_held, ability_held, attacking, aim_dir) -> Vector2` (`movement_state_machine.gd:88-118`)

Contract: `move_dir` is the **already-normalized** WASD vector (may be exactly `(0,0)`); `aim_dir`
is the normalized aim direction. The SM does NOT renormalize `move_dir` (it trusts the caller).
Exact order:

```
1. _update_timers(delta):                                   # :151-157
     _dash_time_left     = max(0.0, _dash_time_left - delta)
     _dash_cooldown_left = max(0.0, _dash_cooldown_left - delta)
     if state == STUNNED:
         _stun_time_left = max(0.0, _stun_time_left - delta)
         if _stun_time_left <= 0.0: _transition_to(IDLE)

2. _update_stamina(delta):                                  # :160-168
     # NOTE: uses LAST tick's state — runs before this tick's state re-derivation
     if state == SPRINTING: stamina = max(0.0, stamina - 35.0*delta)
     else:                  stamina = min(100.0, stamina + 20.0*delta)
     emit stamina_changed if changed (is_equal_approx compare, §5.7)

3. _update_mana(delta):                                     # :171-176
     if mana >= 100.0: return
     mana = min(100.0, mana + 10.0*delta)
     emit mana_changed   # unconditionally when below max (no epsilon check)

4. dash_edge    = dash_held    and not _prev_dash_held      # :95-98
   ability_edge = ability_held and not _prev_ability_held
   _prev_dash_held = dash_held; _prev_ability_held = ability_held

5. if dash_edge:    try_dash(move_dir, aim_dir)             # :100-101, may transition to DASHING
6. if ability_edge: try_use_mana(25.0)                      # :102-103, spend-only; no movement effect today
7. if attacking and state == SPRINTING: end_sprint()        # :104-105 → transition WALKING (see §5.3!)

8. match state:                                             # :107-118 — dispatch on the (possibly just-changed) state
     IDLE | WALKING | SPRINTING -> _tick_grounded(move_dir, sprint_held)
     DASHING                    -> _tick_dashing()
     KNOCKED_BACK               -> _tick_knockback(delta)
     STUNNED                    -> return (0,0)
     ABILITY_MOVEMENT           -> return _ability_velocity
```

`_tick_grounded` (`:121-131`):
```
if move_dir == (0,0):                # EXACT equality, not epsilon
    _transition_to(IDLE); return (0,0)
want_sprint = sprint_held and stamina > 5.0          # STRICT >
_transition_to(SPRINTING if want_sprint else WALKING)
return move_dir * get_ground_speed(want_sprint)      # ground speed × _speed_multiplier
```
`get_ground_speed(is_sprinting)` (`:344-346`): `(320.0 if is_sprinting else 200.0) * _speed_multiplier`.

`_tick_dashing` (`:134-138`):
```
if _dash_time_left <= 0.0: _transition_to(IDLE); return (0,0)
return _dash_velocity
```

`_tick_knockback` (`:141-146`):
```
_knockback_velocity *= exp(-9.0 * delta)             # decay FIRST, then test, then move
if _knockback_velocity.length() <= 12.0:             # length is f32 sqrt
    _transition_to(IDLE); return (0,0)
return _knockback_velocity
```

### 4.6.1 Transition guard & side effects (`:182-220`)

```
_can_transition(to):
    if state == STUNNED and to != IDLE: return false           # stun releases only via its timer
    if state == KNOCKED_BACK and to not in {IDLE, STUNNED, ABILITY_MOVEMENT}: return false
    return true

_transition_to(to):
    if state == to: return
    if not _can_transition(to): return
    from = state; state = to
    if to == SPRINTING: emit sprint_started
    match from:   # exit effects
        SPRINTING:    emit sprint_ended
        DASHING:      emit dash_ended
        KNOCKED_BACK: emit knockback_ended
        STUNNED:      emit stun_ended
    emit movement_state_changed(from, to)
```

### 4.6.2 `try_dash(move_dir, aim_dir) -> bool` (`:227-241`)

```
if _dash_cooldown_left > 0.0: return false
if state in {STUNNED, KNOCKED_BACK, ABILITY_MOVEMENT}: return false
dir = move_dir if move_dir != (0,0) else aim_dir     # EXACT zero compare
if dir == (0,0): return false
dir = dir.normalized()                                # safe re-normalize (already nonzero)
_dash_velocity     = dir * (720.0 * _speed_multiplier)
_dash_time_left    = 0.4
_dash_cooldown_left = 5.5                             # cooldown starts NOW (start-relative)
_transition_to(DASHING)                               # exits SPRINTING ⇒ sprint_ended fires
emit dash_started(dir)
return true
```
Because step 8 dispatches on the new state, dash velocity (720 u/s) applies **the same tick** the
edge arrives. No stamina/mana cost. Dash direction is the move direction, or the aim direction
when standing still.

### 4.6.3 `apply_knockback(direction, force, multiplier=1.0)` (`:245-251`)

```
if direction == (0,0) or force <= 0.0: return
dir = direction.normalized()
_knockback_velocity = dir * (force * multiplier)
_transition_to(KNOCKED_BACK)        # blocked while STUNNED (guard table)
emit knockback_started(dir, force*multiplier)
```
The only live caller: `server_collision_handler.gd:70` — on surviving projectile damage,
`apply_knockback(target.position - impact_position, 450.0)` with a `knock_dir.length() > 0.01`
pre-guard and `impact_position.is_finite()` check. **Replaces** (does not add to) any in-flight
knockback velocity. A dash is cancelled by knockback (DASHING → KNOCKED_BACK is legal);
`_dash_time_left` keeps ticking down in the background.
**The client never calls `apply_knockback`** — knockback is server-only and reaches the local
player purely through position corrections (see §5.6).

### 4.6.4 Others

- `end_sprint()` (`:255-258`): only if state == SPRINTING → transition WALKING.
- `apply_stun(duration)` (`:307-313`): if duration <= 0 return; `_stun_time_left = duration`;
  `_dash_time_left = 0.0` (cancels dash); transition STUNNED; emit. `apply_root`/`apply_daze`
  alias to `apply_stun`. No current caller in the live game loop (future status effects).
- `start_ability_movement(v)` / `set_ability_velocity(v)` / `end_ability_movement()`
  (`:262-278`): external velocity ownership; blocked while STUNNED; no current caller.
- `try_use_mana(cost)` (`:282-289`): `cost <= 0 ⇒ true`; `mana < cost ⇒ false`;
  else `mana = max(0, mana - cost)`, emit, true.
- `apply_speed_modifier(m)` (`:297-299`): `_speed_multiplier = clamp(m, 0.25, 2.5)`. Affects
  ground speed AND dash speed (dash velocity computed at dash start). No current caller.
- `set_resources(stamina, mana)` (`:379-387`): clamp both to [0,100]; assign+emit only if NOT
  `is_equal_approx` to current. Client-only path (ACTION_CONFIRM resource sync).
- `is_input_locked()` (`:349-351`): state ∈ {DASHING, KNOCKED_BACK, STUNNED, ABILITY_MOVEMENT}.
  (Informational; nothing in the sim path calls it.)

### 4.7 Server: `PlayerState` per-tick

#### 4.7.1 `ingest_input(input, server_tick)` (`player_state.gd:147-189`) — once per drained packet

```
if life_state == DEAD: return                       # dead players' inputs discarded entirely

new_flags    = input.get("input_flags", 0)
new_sequence = input.get("sequence_number", input.get("sequence", last_input_sequence))
new_aim      = input.get("aim_angle", aim_angle)
client_position = input.get("position", null)

# SHOOT rising edge across packets (combat subsystem; uses the PERSISTENT flags as 'previous')
if (new_flags has SHOOT) and not (input_flags has SHOOT): append pending_shots entry

if new_flags has DASH: _pending_dash = true          # latch — survives same-tick overwrite

input_flags = new_flags                              # persistent; re-applied every tick
last_input_sequence = new_sequence
aim_angle = new_aim
last_client_render_tick / last_client_rtt_ms updated
last_input_received_tick = server_tick

if client_position is Vector2:
    last_client_position = client_position; has_client_position = true
```
Queueing: `queue_input` (`:109-114`) caps at 10, dropping the **oldest** on overflow. The drain
loop (`player_manager.gd:128-129`) ingests **every** queued packet in FIFO order before stepping,
so with multiple packets per tick only the LAST packet's flags persist (dash is latch-protected;
shoot edges are caught per-packet because `input_flags` updates between ingests).

#### 4.7.2 `step(delta, server_tick) -> validation` (`player_state.gd:217-289`) — exactly once per tick

```
1. if last_input_received_tick > 0 and server_tick - last_input_received_tick > 6:
       input_flags = 0                                # stale: stop sliding (note: _pending_dash NOT cleared here)

2. if life_state == DEAD:
       velocity = (0,0); input_flags = 0; _pending_dash = false
       _update_entity_flags()
       return {valid:true, deviation:0.0, correction_needed:false,
               server_position:position, cheat_detected:false, sequence:last_input_sequence}

3. if shoot_cooldown > 0.0: shoot_cooldown = max(0.0, shoot_cooldown - delta)

4. if life_state == INVULNERABLE and has_active_input(): end_invulnerability()
   # has_active_input (:478-482) = any of MOVE_UP/DOWN/LEFT/RIGHT or SHOOT.
   # SPRINT, DASH, ABILITY, INTERACT alone do NOT break invulnerability.

5. dash_held = (input_flags has DASH) or _pending_dash
   _pending_dash = false                              # consumed exactly once

6. velocity = movement_sm.tick(
       delta,
       _calculate_movement_direction(input_flags),    # §4.7.3
       input_flags has SPRINT,
       dash_held,
       input_flags has ABILITY,
       input_flags has SHOOT,                          # 'attacking'
       Vector2.from_angle(aim_angle))                  # (cos a, sin a)

7. previous_position = position
   server_position = move_with_obstacle_collision(previous_position,
                       previous_position + velocity * delta, 16.0)
8. if delta > 0.0: velocity = (server_position - previous_position) / delta   # realized velocity
9. position = server_position

10. if has_client_position: validation = _validate_position(last_client_position, server_position)
    else: validation = {valid:true, deviation:0.0, correction_needed:false,
                        server_position, cheat_detected:false, sequence:last_input_sequence}

11. _update_animation_state(); _update_entity_flags()
12. return validation
```

#### 4.7.3 `_calculate_movement_direction(flags)` (`:293-305`) — identical to client `_get_direction_from_flags` (`prediction.gd:368-380`)

```
d = (0,0)
if UP: d.y -= 1;  if DOWN: d.y += 1;  if LEFT: d.x -= 1;  if RIGHT: d.x += 1
return d.normalized()      # Godot: zero vector normalizes to (0,0); diagonals to (±0.7071..,±0.7071..)
```
Opposite keys cancel exactly (W+S ⇒ y = 0). Diagonals are not faster.

#### 4.7.4 `_validate_position(client_pos, server_pos)` (`:310-336`)

```
deviation = distance(client_pos, server_pos)          # f32 sqrt
result = {valid:true, deviation, correction_needed:false, server_position:server_pos,
          cheat_detected:false, sequence:last_input_sequence}
if deviation > 150.0:  result.valid=false; result.correction_needed=true; result.cheat_detected=true; return
if deviation > 112.5:  result.valid=false; result.correction_needed=true; return
return result                                          # POSITION_TOLERANCE (75) is never branched on
```
The deviation compares the client's latest **reported** position against the server's
**post-step** position; both strict `>`.

#### 4.7.5 `_update_animation_state()` (`:340-351`) — priority order

```
if not is_alive:                       DEATH(5)
elif SHOOT flag held:                  ATTACK(3)
elif velocity.length_squared() > 0.01: RUN(2) if SPRINT flag held else WALK(1)   # flag-based, not SM-state-based
else:                                  IDLE(0)
```

#### 4.7.6 `_update_entity_flags()` (`:355-380`)

Rebuilt from zero each call: ALIVE if alive; MOVING if `velocity.length_squared() > 0.01`;
ATTACKING if SHOOT flag; INVULNERABLE if life_state INVULNERABLE; then exactly one of
DASHING / KNOCKED_BACK / STUNNED from `movement_sm.state`; always VISIBLE.

#### 4.7.7 Lifecycle resets

- `reset_for_respawn(spawn)` (`:384-402`): position=spawn; velocity=0; health=max; alive;
  life_state=INVULNERABLE; invulnerability_timer=3.0; `movement_sm.reset()`; clears
  input_flags/queue/pending_shots/_pending_dash; `has_client_position=false`;
  `last_input_received_tick=0`; animation SPAWN(6); flags ALIVE|VISIBLE|INVULNERABLE.
- `_mark_dead(killer)` (`:426-444`): idempotent; zero velocity; `movement_sm.reset()`; clears all
  input state; respawn_timer=3.0; animation DEATH.
- `update_invulnerability(delta)` (`:457-465`): `invulnerability_timer -= delta` (may go negative,
  no clamp); at `<= 0.0` ⇒ `end_invulnerability()`. Called from the server's
  `_update_game_state` (tick step 2), i.e. AFTER movement.

#### 4.7.8 Server tick loop ordering (movement-relevant; `server_main.gd`, `_process_server_tick`)

```
tick_count += 1                       # first tick is 1
1. _process_client_inputs:
     for each authenticated player (Dictionary insertion order = connect order):
         drain input_queue → ingest_input(each, tick_count)
         validation = state.step(1.0/tick_rate, tick_count)
         if any input was ingested this tick: collect move_result
              {peer_id, sequence, position, success: !correction_needed,
               cheat_detected, deviation,
               stamina: roundi(movement_sm.stamina), mana: roundi(movement_sm.mana)}
     _process_shoot_inputs()          # combat
     _send_move_confirmations(move_results)  # ACTION_CONFIRM per player WITH fresh input only
2. _update_game_state                 # respawn/invulnerability timers etc.
3. monster AI
4. record position history (lag comp) — players recorded POST-movement, PRE-collision
5. collisions → may call movement_sm.apply_knockback (takes effect NEXT tick's step)
6. snapshot broadcast (on snapshot-due ticks)
7. cleanup
```
ACTION_CONFIRM is `ActionConfirmPacket.create_move_confirm(seq, position, tick, success,
roundi(stamina), roundi(mana))` — stamina/mana are rounded to int and clamped 0..255 on the wire;
`result_code = SUCCESS(0)` or `FAILED_INVALID_POSITION(1)`
(`client/scripts/shared/networking/action_confirm_packet.gd:54-64`).

### 4.8 Client: per-physics-frame prediction loop (`prediction.gd:158-198`, 30 Hz)

```
if player_node == null: return
if not connected: emit visual_position_updated(player.position, false); return
if not is_active():                       # prediction_enabled && entity_id >= 0 && has_authoritative_position
    current_input_flags = 0; predicted_velocity = (0,0); emit visual...; return

1. previous_flags = current_input_flags
   current_input_flags = _capture_input_flags()       # :203-232
      # WASD/shoot/ability/sprint/interact from held keys.
      # DASH: on the press edge (is_action_just_pressed) set _dash_latched = true;
      #       while _dash_latched, set the DASH bit. Cleared only after a send (§4.8.1).
2. cosmetic shoot feedback (no sim effect)
3. _apply_local_prediction(current_input_flags, delta):   # :324-357
      position_before = predicted_position
      direction = _get_direction_from_flags(flags)        # same as §4.7.3
      aim_dir = Vector2.from_angle( predicted_position.angle_to_point(mouse_world) )
              # angle_to_point(p) = atan2(p.y - self.y, p.x - self.x)
      predicted_velocity = movement_sm.tick(delta, direction,
          SPRINT flag, DASH flag, ABILITY flag, SHOOT flag, aim_dir)
      predicted_position = move_with_obstacle_collision(
          predicted_position, predicted_position + predicted_velocity * delta, 16.0)
      if delta > 0: predicted_velocity = (predicted_position - position_before) / delta
      if not is_correcting: player_node.position = predicted_position
4. if is_correcting: _apply_smooth_correction(delta)      # §4.10
5. input_send_timer += delta
   if input_send_timer >= INPUT_SEND_INTERVAL:
       _send_input_to_server(); input_send_timer -= INPUT_SEND_INTERVAL
6. emit visual_position_updated(player_node.position, false)
```
Since the physics clock equals the tick rate, the send fires every frame in practice (`delta` =
`1/30` ≥ interval), i.e. input is sampled AND sent at 30 Hz. The SM instance used is
`player_node.movement_sm` (the `Player` node creates one in `_ready`, `player.gd:96`); the
fallback stateless model (`prediction.gd:344-345`) only applies to non-Player test nodes.

#### 4.8.1 `_send_input_to_server()` (`prediction.gd:457-516`)

```
seq = current_sequence; current_sequence = (current_sequence + 1) & 0xFF
aim_angle = predicted_position.angle_to_point(mouse_world)
# Build the REPLAY snapshot with the simplified ground model (NOT the SM):
replay_velocity = _get_direction_from_flags(flags) * _get_speed_from_flags(flags)   # §4.9
replay_end = move_with_obstacle_collision(predicted_position,
                 predicted_position + replay_velocity * (1/30), 16.0)
store InputSnapshot{seq, flags, position_before=predicted_position,
                    position_after=replay_end, velocity=replay_velocity,
                    aim_angle, delta=1/30}
prune acknowledged inputs
send packet (§3.5)
_dash_latched = false        # DASH bit appears in exactly ONE outbound packet per press
```
Dash-latch lifecycle: the latch is set on the key press edge, keeps the DASH bit set in
`current_input_flags` for every physics frame until the next send, then clears. The SM's internal
`_prev_dash_held` edge detector ensures the dash triggers once even though the bit is held across
frames. The server sees the bit in one packet and additionally latches `_pending_dash` to survive
same-tick packet overwrites.

### 4.9 Replay model — deliberately simplified (`prediction.gd:388-394, 683-700`)

`_get_speed_from_flags(flags)`:
```
sprint = flags has SPRINT
sprint = sprint and movement_sm.stamina > 5.0       # gate on CURRENT stamina (not snapshot-time)
return movement_sm.get_ground_speed(sprint)         # 320 or 200, × _speed_multiplier
```
`_replay_input(snapshot)`:
```
direction = _get_direction_from_flags(snapshot.input_flags)
velocity  = direction * _get_speed_from_flags(snapshot.input_flags)
position_before = predicted_position
predicted_position = move_with_obstacle_collision(predicted_position,
                       predicted_position + velocity * snapshot.delta, 16.0)
if snapshot.delta > 0: velocity = (predicted_position - position_before) / snapshot.delta
snapshot.position_after = predicted_position; snapshot.velocity = velocity
```
Replay uses **ground speed only** — it never replays dash/knockback/stun velocities. This is a
documented, intentional approximation ("transient states are brief and rarely span a correction;
any residual is fixed by the next snapshot"). The Rust port must keep this asymmetry: live
prediction = full SM; replay = ground model.

### 4.10 Reconciliation (`prediction.gd:529-747`)

`_handle_action_confirm(data)` (`:529-564`):
```
only ActionType.MOVE(0) is handled
if data has "stamina": movement_sm.set_resources(f64(stamina), f64(mana))   # clamped, epsilon-gated
last_ack_sequence = sequence; last_server_tick = server_tick
if result_code != SUCCESS(0):                       _reconcile(sequence, corrected_position)
elif not has_authoritative_position:                force_sync(corrected_position)
elif distance(predicted, corrected) > 4.0:          _reconcile(sequence, corrected_position)   # STRICT >
else:                                               prune acknowledged inputs only
```

`_handle_state_update` / `_process_own_state_update` (`:567-609`): on each Snapshot containing the
local entity (delta packets without a position field are skipped):
```
if not has_authoritative_position: force_sync(server_position); return
if input_buffer.is_empty():        _apply_authoritative_position_without_replay(server_position); return
if distance(predicted, server_position) > 4.0: _reconcile(last_ack_sequence, server_position)
```

`_reconcile(ack_sequence, server_position)` (`:614-662`):
```
1. predicted_position = server_position; has_authoritative_position = true
2. unacked = sequences from (ack_sequence+1)&0xFF up to (exclusive) current_sequence,
   in wrap order, max 256 iterations, keeping only those present in the buffer  (:665-680)
3. for each: _replay_input(snapshot)                # §4.9
4. correction_amount = distance(player_node.position, predicted_position)   # VISUAL distance
5. if correction_amount > 150.0: instant snap (player.position = predicted; reset physics interp;
                                  emit visual(…, discontinuous=true); is_correcting=false)
   else: is_correcting = true; correction_target = predicted_position       # smooth
6. emit correction_applied / reconciliation_complete
7. prune acknowledged inputs        # erase every seq with wrap-aware (seq ≤ last_ack): :406-445
```
Wrap-aware compare (`_sequence_less_than`, `:439-445`): `forward = (b - a) & 0xFF;
a<b ⟺ 0 < forward < 128`.

`_apply_smooth_correction(delta)` (`:729-747`), runs each physics frame while `is_correcting`:
```
correction_target = predicted_position                       # moving target
new_visual = player.position.lerp(correction_target, 12.0 * delta)   # UNCLAMPED lerp weight (0.4 at 1/30)
if distance(new_visual, correction_target) < 1.0: player.position = correction_target; is_correcting = false
else: player.position = new_visual
```
Note the order within a frame: prediction moves `predicted_position` first (step 3) but skips the
visual write while correcting; then step 4 lerps the visual toward the new predicted position.

`_apply_authoritative_position_without_replay(server_pos)` (`:827-839`):
```
discrepancy = distance(predicted, server_pos)
predicted_position = server_pos; correction_target = server_pos; has_authoritative_position = true
if discrepancy > 150.0: instant snap
elif discrepancy > 4.0: start smooth correction
else: write visual = predicted (if not correcting)
```

`force_sync(server_pos)` (`:753-766`): clears the buffer, slams predicted/visual/correction state,
`has_authoritative_position = true`, emits `visual(…, discontinuous=true)`. Used at Authority sync,
respawn, and recovery. `set_prediction_enabled(false)` (`:800-809`) zeroes flags/velocity/timer,
clears the buffer, stops correcting (used on death).

### 4.11 Derived timing facts (worked out, for test fixtures)

With delta = `1.0/30.0` f64 and sequential `maxf(0.0, x - delta)` decrements:

- **Dash**: `0.4 - 12*(1/30)` accumulates to a tiny **positive** residue in f64 (`0.4` and `1/30`
  are both inexact; sequential subtraction leaves ~2.8e-17), so `_dash_time_left > 0` still holds
  on the 12th decrement ⇒ the dash returns 720 u/s for **13 ticks** (the edge tick + 12), ending on
  the 14th. Nominal displacement ≈ 13 × 720/30 = **312 units** (obstacles permitting). This
  off-by-one lives entirely in float rounding — see hazard list.
- **Knockback** (force 450): per-tick decay factor `exp(-0.3)` ≈ 0.740818. Speeds decay
  450→333.4→247.0→…; speed ≤ 12.0 first on the **13th** decayed tick (≈ 9.11 u/s) ⇒ 12 ticks of
  motion, total ≈ 41 units displacement, ≈ 0.43 s.
- **Sprint from full stamina**: drain 35/30 ≈ 1.1667/tick; sprint stops when stamina ≤ 5.0 at the
  start-of-tick update ⇒ ~82 ticks ≈ 2.7 s of sprinting.
- **Dash cooldown**: 5.5 s = 165 ticks from dash start (same float-residue caveat).

---

## 5. Edge cases & gotchas

1. **Zero input** ⇒ `_calculate_movement_direction` returns exactly `(0,0)` (Godot
   `Vector2.ZERO.normalized() == ZERO`), `_tick_grounded` transitions IDLE and returns zero
   velocity; the mover is still called with `from == to`, takes the `is_equal_approx` early path,
   and returns `clamp_to_bounds(position)` — i.e. a stationary player is *re-clamped* every tick
   (a no-op unless something put them out of bounds).
2. **Stationary dash** uses `aim_dir`; if both `move_dir` and `aim_dir` are zero the dash is
   refused (returns false) and — importantly — the **cooldown is NOT started**. On the server
   `aim_dir = Vector2.from_angle(aim_angle)` is never zero (cos/sin), so server-side refusal can
   only come from cooldown/state. On the client the aim fallback also never yields zero.
3. **"Attacking ends sprint" is speed-neutral while sprint is held.** Step 7 of `tick()`
   transitions SPRINTING→WALKING, but step 8's `_tick_grounded` immediately re-derives
   `want_sprint` and transitions straight back to SPRINTING, returning **sprint speed**. Net
   effect per tick: `sprint_ended` + `sprint_started` + two `movement_state_changed` signals fire,
   state ends the tick as SPRINTING, stamina keeps draining, speed stays 320. Shooting while
   sprinting does NOT slow you. Reproduce the end-of-tick state; the signal flapping only matters
   if Rust-side events feed audio/UI.
4. **Edge inclusivity asymmetry**: `Rect2.has_point` excludes the right/bottom edges (so a center
   exactly on an expanded obstacle's max-x/max-y edge "does not intersect"), while the slab
   line test treats all edges as inclusive and the axis-parallel rejection uses `<`/`>` (inclusive
   band). A swept move that exactly grazes an expanded edge can therefore "hit" where the endpoint
   test would not. Port the two tests independently and exactly; do not unify them.
5. **Stuck-inside-expanded-rect freeze (no resolution, by design absence)**: if `from` is ever
   inside an expanded obstacle, every non-degenerate move (direct, x-slide, y-slide) reports a hit
   (slab returns `from` at t=0), so `move_with_obstacle_collision` returns `from` — the player is
   **permanently frozen** until teleported. There is **no depenetration code anywhere**. In
   practice unreachable (moves never end inside; spawns are validated), but the Rust port must
   not "helpfully" add depenetration, and must preserve the t_min=0 inside-counts-as-hit behavior.
6. **Knockback is never predicted.** Only `server_collision_handler.gd:70` calls
   `apply_knockback`. The local client's SM never enters KNOCKED_BACK; the player feels knockback
   as a stream of >4-unit position corrections (smooth-lerped). The remote view gets
   `ENTITY_FLAG_KNOCKED_BACK`. A comment in the collision handler claims the client predicts it —
   that comment is wrong; trust this document and the call graph.
7. **Epsilon semantics** (`is_equal_approx`, ENGINE-DEPENDENT — reimplement exactly):
   scalar: `if a == b: true; tol = max(CMP_EPSILON, CMP_EPSILON * |a|); return |a-b| < tol` with
   `CMP_EPSILON = 0.00001`; note the tolerance scales with **|a| only** (asymmetric).
   `Vector2.is_equal_approx` applies the scalar test per component (f32 components, f64 math in
   the scalar helper). Used in: `_movement_hits_obstacle` zero-move path, `_update_stamina`
   signal gate, `set_resources` assignment gate.
8. **Bounds clamp before obstacle test** (§4.5): a move that exits the map is first pulled back
   to the ±1000 box and only then obstacle-checked. The player center reaches ±1000 exactly; the
   sprite may protrude. No obstacle touches the boundary so clamped positions never collide.
9. **Stale input**: after 6 ticks of silence (`> 6`, so the 7th tick), `input_flags` zeroes — the
   player stops walking, but an in-flight dash/knockback continues (the SM keeps returning its own
   velocity regardless of flags). `_pending_dash` survives the stale clear and will fire a dash
   whenever the next step runs (it is consumed every step though, so in practice it fires on the
   very next tick after ingest, stale or not). `last_input_received_tick == 0` (fresh
   connect/respawn) disables the stale check entirely.
10. **Offline modes diverge (and the Rust port supersedes them).** Offline practice/sandbox use
    `Player._physics_process` → `velocity = movement_sm.tick(...)` → **`move_and_slide()`**
    (`player.gd:151-173`, 30 Hz physics). ENGINE-DEPENDENT and observably DIFFERENT from the
    networked sim: the player scene is `CharacterBody2D`, `MOTION_MODE_FLOATING`,
    `collision_layer=1`, `collision_mask=6` (`player.tscn:58-60`), CircleShape2D radius 16. Mask 6
    = layers 2 (monsters) + 4 (projectiles) and does **NOT** include layer 8 (tilemap walls +
    ±1005 boundary walls, `arena_base.gd:12`, `arena_base.tscn:97`), so the offline player slides
    against monster bodies but walks **through obstacles and out of bounds** — no analytic mover
    runs offline. Per migration-spec D5 the offline modes will instead reuse Rust `sim_core`;
    do not replicate `move_and_slide`.
11. **Death / disconnect**: dead players discard all ingested input and their step returns a
    synthetic valid result at the frozen position. `_mark_dead` resets the SM (cancelling
    dash/knockback instantly — zero velocity next snapshot). On disconnect the PlayerState is
    removed by PlayerManager (out of scope); the stale-input clear covers the gap.
12. **Invulnerability**: broken by movement or SHOOT input (not sprint/dash/ability alone —
    `has_active_input`, `player_state.gd:478-482`) at step 4 of step(), or by attempting to fire,
    or by the 3 s timer (which is decremented WITHOUT clamping and may pass through negative
    values within the ending tick).
13. **Sequence-number traps**: `last_input_sequence` initial 0; client sequences start at 0 and
    wrap at 256; ack compare uses the forward-distance rule (`(b-a)&0xFF` in `(0,128)`). A
    sequence exactly 128 apart is treated as NOT-before (`forward == 128` fails `< 128`).
    `_get_unacknowledged_sequences` walks from `(ack+1)&0xFF` to `current_sequence` exclusive
    (max 256 steps) — if `ack == current_sequence` it yields nothing.
14. **ACTION_CONFIRM cadence**: the server only sends a confirm for players that ingested ≥1 fresh
    packet that tick. With packets in flight every tick this is effectively 30/s per player. The
    stamina/mana ride along as `roundi()` integers (round-half-away-from-zero) clamped 0..255 —
    the client overwrites its predicted f64 resources with those quantized values whenever the
    epsilon gate passes; predicted stamina therefore "staircases" slightly. Port must keep the
    round-trip quantization identical or HUD bars will jitter differently.
15. **Mover ties favor X**: when both axis-slides are valid and equidistant from the target
    (`y_distance < best_distance` strict), the X slide wins. Corner-exact diagonals therefore
    slide horizontally.
16. **The mover never re-tests the combined slide**: sliding picks ONE axis per tick; there is no
    second iteration. Velocity output after a slide includes only the surviving axis component
    (realized-velocity recompute), which is what MOVING flags/animation see.
17. **`POSITION_TOLERANCE` (75) is dead** in the current validation branch — only 112.5 and 150
    matter. Keep the constant for docs/HUD parity but do not branch on it.
18. **First server tick is `tick_count = 1`** (incremented before processing). The
    "allow the very first tick after connect" comment refers to `last_input_received_tick == 0`.

---

## 6. Cross-subsystem contracts

### 6.1 Consumes

- **Input packets** (transport/protocol subsystem): dictionaries with `input_flags: u16`,
  `sequence_number (or sequence): int`, `aim_angle: f64`, `position: Vector2`, `velocity: Vector2`,
  `client_render_tick: int`, `client_rtt_ms: int`. Movement consumes flags/sequence/aim/position;
  render_tick/rtt and `pending_shots` belong to combat/lag-comp (see the sim-combat extraction).
- **Knockback trigger** (combat subsystem): `movement_sm.apply_knockback(direction: Vector2,
  force: f64, multiplier: f64 = 1.0)` — called by the server collision handler with
  `direction = target.position - impact_position` (guarded `length() > 0.01`) and
  `force = 450.0`, only when the target survived the damage and `impact_position.is_finite()`.
- **Spawn positions**: `GameConstants.ARENA_PLAYER_SPAWNS` filtered by
  `is_valid_player_spawn_position` (circle-16 in bounds + not in obstacle).

### 6.2 Provides

- **Per-tick step result** (server): the validation dict (§3.6) consumed by PlayerManager to build
  move_results: `{peer_id, sequence, position, success = !correction_needed, cheat_detected,
  deviation, stamina: roundi(sm.stamina), mana: roundi(sm.mana)}` → one
  `ACTION_CONFIRM(action_type=MOVE(0), result_code = 0|1, corrected_position, server_tick,
  stamina: u8, mana: u8)` per fresh-input player per tick.
- **Authoritative `position` / `velocity` / `animation_state` (u8) / `entity_flags` (u8)** for the
  snapshot/broadcast subsystem (`to_entity_data`, `player_state.gd:95-102`). Movement-derived
  flags: MOVING, DASHING, KNOCKED_BACK, STUNNED (§2.12).
- **Position history hook**: `player_manager.record_position_snapshot(tick)` is called AFTER all
  steps and BEFORE collisions — lag compensation rewinds read the post-movement positions.
- **Fire origin**: combat reads `player.position` (post-step) and `get_aim_direction()
  = Vector2.from_angle(aim_angle)` for projectile spawning; muzzle offset
  `PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0 = 26.0` units is combat's, not movement's.
- **Client HUD**: `stamina_changed` / `mana_changed` signals (predicted SM) drive the bars;
  ACTION_CONFIRM `set_resources` corrections flow through the same signals.
- **Camera/visuals**: `visual_position_updated(position, is_discontinuous)` once per physics frame
  (discontinuous=true on instant corrections/force_sync, telling the camera to snap instead of
  interpolate).

### 6.3 Suggested Rust `sim_core` surface (derived, not prescriptive)

```rust
fn movement_sm_tick(sm: &mut MovementSm, dt: f64, move_dir: Vec2, sprint_held: bool,
                    dash_held: bool, ability_held: bool, attacking: bool, aim_dir: Vec2) -> Vec2;
fn move_with_obstacle_collision(from: Vec2, to: Vec2, radius: f32) -> Vec2;   // pure, uses static OBSTACLES
fn player_step(state: &mut PlayerSimState, dt: f64, server_tick: u64) -> Validation;
```
Client prediction calls the same `movement_sm_tick` + mover through the GDExtension (D5/D6).

---

## 7. Rust port hazards (checklist)

- [ ] **Mixed float precision.** Godot `Vector2`/`Rect2` components are **f32** (standard
  single-precision build); GDScript scalars (`stamina`, timers, `delta`, `aim_angle`, distance
  *results* returned to GDScript) are **f64**. Vector ops (`length`, `normalized`, `distance_to`,
  `dot`, `*`, `lerp`) compute in f32; scalar arithmetic (`maxf`, `exp`, timer decrements,
  `0.4 - delta`) computes in f64. A pure-f64 Rust port WILL diverge from the GDScript over time
  (mostly harmlessly while GDScript remains authoritative, but golden-trace comparisons must
  account for it). Decide and document: match (f32 vectors + f64 scalars) for trace parity.
- [ ] **`Vector2.normalized()` on zero returns zero**, not NaN. Diagonal = (±0.70710678…f32).
- [ ] **`Rect2.has_point` upper-edge exclusivity** vs **slab-test inclusivity** (§5.4) — two
  different edge conventions in the same mover; port both verbatim.
- [ ] **Chebyshev circle test**: obstacle collision expands rects by the radius and point-tests —
  square corners, not rounded. Do not substitute true circle-vs-AABB.
- [ ] **Slide tie-break is strict `<`** (X axis wins ties); slide picks one axis, never iterates.
- [ ] **Clamp-to-bounds happens BEFORE obstacle tests**, on the raw target and on each axis target.
- [ ] **Bounds clamp the center** (±1000), radius not subtracted; ±1005 scene walls are not sim.
- [ ] **Order inside `MovementStateMachine.tick`**: timers → stamina (using PREVIOUS state) →
  mana → edges → dash/ability/attack actions → state dispatch. Dash applies its velocity the same
  tick; stamina drain for a new sprint starts the NEXT tick.
- [ ] **Float-residue off-by-one ticks**: dash runs 13 ticks (not 12) at 30 Hz because
  `0.4 - 12*(1/30) > 0` in f64 sequential subtraction. If Rust changes the op order
  (e.g. `time_left = 0.4 - n*dt`) the dash shortens by one tick = 24 units of travel. Use the
  identical `x = max(0.0, x - dt)` accumulation.
- [ ] **`exp(-9.0 * delta)` per-tick knockback decay** — multiply-accumulate on the f32 vector
  with an f64 exponent each tick; end condition `length() <= 12.0` (f32 sqrt, non-strict).
- [ ] **Strict comparisons**: sprint gate `stamina > 5.0`; reconcile gate `distance > 4.0`;
  validation `deviation > 112.5` / `> 150.0`; stale `elapsed > 6`. Off-by-one on any of these
  changes observable behavior.
- [ ] **`is_equal_approx` asymmetric epsilon** (tolerance scaled by |a| only, floor 1e-5) in the
  zero-move mover path and resource-signal gates.
- [ ] **Edge detection lives in the SM**, fed by HELD flags: client latches dash from press to
  next send; server ORs in `_pending_dash`; the SM's `_prev_dash_held` makes it a one-shot. Three
  layers — drop any one and dashes double-fire or drop under packet loss.
- [ ] **Replay ≠ prediction**: reconciliation replay uses the ground-speed model (sprint gated by
  CURRENT stamina), never dash/knockback. Keep the asymmetry.
- [ ] **8-bit sequence wrap**: `(x+1)&0xFF`; before-compare via forward distance `(b-a)&0xFF ∈
  (0,128)`; unacked walk is exclusive of `current_sequence`, 256-step bounded.
- [ ] **Persistent input flags**: the server re-applies the last flags EVERY tick until a new
  packet or the 6-tick stale timeout — a lost packet does not stop the player.
- [ ] **Per-tick fixed dt**: everything uses `1.0/30.0` (or `1.0/tick_rate` from config). Never
  use wall-clock frame delta in the sim. Client physics rate is forced to the same 30.
- [ ] **`roundi` + 0..255 clamp** on stamina/mana in ACTION_CONFIRM (round half away from zero);
  client re-ingests through clamped `set_resources`.
- [ ] **Realized-velocity recompute** `(pos_after - pos_before)/dt` after the mover on BOTH sides —
  feeds MOVING flag, animation, and the velocity field in the input packet.
- [ ] **`Vector2.INF` sentinel** for "no intersection" — use `Option<Vec2>` in Rust, but make sure
  an intersection AT `from` (inside-rect, t=0) still counts as a hit.
- [ ] **No depenetration anywhere** — frozen-if-overlapping is the (theoretically unreachable)
  contract; do not add rescue logic.
- [ ] **Knockback replaces velocity** (no stacking) and is refused while STUNNED (guard table) —
  and the guard table itself: STUNNED only → IDLE; KNOCKED_BACK only → IDLE/STUNNED/ABILITY.
- [ ] **`move_and_slide` is NOT part of the networked sim** — engine physics only matters for the
  offline modes, which D5 retires onto `sim_core`. The only collision the Rust crate needs is
  `move_with_obstacle_collision` + the 16 rect table + the ±1000 clamp.
- [ ] **Dictionary iteration order**: Godot Dictionaries iterate in insertion order; player step
  order = connection order. Per-player movement is independent, so ordering only matters for
  downstream tie-breaks (e.g. who fires first within a tick) — keep a stable order (slotmap/Vec
  insertion order) anyway.
- [ ] **Smooth-correction lerp weight `12.0 * dt` is unclamped** (0.4 at 30 Hz). It is visual-only
  (stays GDScript-side post-port), but if reimplemented, clamp or match exactly; stop snap at
  `< 1.0` unit.
