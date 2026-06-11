# Combat — projectiles, hit authority, damage, death/respawn

> Generated extraction notes for the Rust port — derived from GDScript at commit on branch
> feature/rust-port. Source of truth is the GDScript until cutover.

Audience: the Rust implementer of `sim_core` + `server` (per migration-spec D5/D8/D11). Everything
below is the OBSERVABLE behavior of the GDScript; do not read the GDScript — read this. Where a
behavior is engine-dependent or float-sensitive it is flagged explicitly.

Source files (all paths repo-relative):

- `client/scripts/shared/hit_authority.gd` — pure authority/geometry predicates (shared client+server)
- `client/scripts/server/server_collision_handler.gd` — damage/kill application + event broadcast
- `client/scripts/server/projectile_manager.gd` — projectile registry, id allocation, collision passes
- `client/scripts/server/projectile_state.gd` — per-projectile authoritative state + integration
- `client/scripts/client/local_hit_detector.gd` — client-side incoming monster-bullet detection
- `client/scripts/shared/projectile/projectile.gd` — pooled client visual node (Area2D)
- `client/scripts/shared/player/hp_component.gd` — client-side HP mirror component
- supporting: `server_main.gd`, `player_state.gd`, `player_manager.gd`, `monster_manager.gd`,
  `monster_state.gd`, `monster_ai.gd`, `game_constants.gd`, packet files.

---

## 1. Overview

Combat implements the **two-netcode hit-authority model**
(`docs/netcode/hit-authority-model.md`): *authority is chosen per projectile, by its owner id*.

| Projectile owner | Target | Authority | Lag comp |
|---|---|---|---|
| Monster (id ≥ 30000) | Player | **Client-authoritative + server-validated** — victim's client detects in its rendered frame, sends `LOCAL_HIT_REPORT`, server plausibility-gates and applies | none (judged in client render frame) |
| Player (id < 1000) | Player | **Server-authoritative** swept + rewound | rewind capped at **4 ticks** |
| Player (id < 1000) | Monster | **Server-authoritative** swept + rewound | rewind capped at **6 ticks** |

Monster-owned projectiles never participate in any server collision pass; they die only by
max-distance / out-of-bounds / obstacle / a validated client hit report (and, post-port, the D11
backstop). Player-owned projectiles are tested server-side against rewound player and monster
rosters every tick.

**Position in the 30 Hz server tick** (`server_main.gd:213-283`, exact order is load-bearing):

1. **Inputs** (`_process_client_inputs`, :241): drain input queues → `PlayerState.step()` (moves
   players, decrements shoot cooldowns) → `_process_shoot_inputs()` (**player projectiles spawn
   here**) → send `ACTION_CONFIRM` move confirms.
2. **Game state** (`_update_game_state`, :244): `projectile_manager.update_all(tick_interval)`
   (**all projectiles integrate here** — a player projectile spawned in step 1 moves on its spawn
   tick), monster spawner, invulnerability timers, respawn timers, periodic leaderboard.
3. **Monster AI** (`_update_monster_ai`, :247): monster movement + firing (**monster projectiles
   spawn here, AFTER integration — they do not move on their spawn tick**); fire events broadcast.
4. **Position history** (:253-254): `monster_manager.record_position_snapshot(tick_count)` then
   `player_manager.record_position_snapshot(tick_count)` — end-of-tick, post-movement,
   pre-collision positions.
5. **Collisions** (:257): `collision_handler.process_collisions(...)` — players pass first, then
   monsters pass; damage/kill events broadcast inside.
6. **Snapshot broadcast** (only on snapshot-due ticks).
7. **Cleanup**: `monster_manager.cleanup_dead_monsters()` — dead monsters stay visible to
   broadcast for one tick, then are erased.

On the client, `LocalHitDetector.update()` runs **once per render frame** (not per tick), from
`arena_base._process` *after* entity visuals are updated for that frame (`arena_base.gd:123-124`).

---

## 2. Constants

All from `client/scripts/shared/game_constants.gd` unless noted. Distances are world units
(1 unit = 1 px at zoom 1), times in seconds, rates in Hz. Values are exact — do not round.

### Tick / lag compensation

| Constant | Value | Unit | Source |
|---|---|---|---|
| `SERVER_TICK_RATE` | `30.0` | Hz | game_constants.gd:22 |
| `SERVER_TICK_INTERVAL` | `1.0 / 30.0` | s | game_constants.gd:25 |
| `REMOTE_ENTITY_RENDER_DELAY_TICKS` | `2` | ticks | game_constants.gd:33 |
| `MAX_PVE_PROJECTILE_COMPENSATION_TICKS` | `6` | ticks (≈200 ms @30 Hz) | game_constants.gd:40 |
| `MAX_PVP_PROJECTILE_COMPENSATION_TICKS` | `4` | ticks (≈133 ms @30 Hz) | game_constants.gd:45 |
| `config.tick_rate` (runtime) | `int(SERVER_TICK_RATE)` = `30` default; JSON `server_config.json` overrides | Hz | server_config.gd:13,63-64 |
| `POSITION_HISTORY_TICKS` (players) | `8` | ticks | player_manager.gd:25 |
| `POSITION_HISTORY_TICKS` (monsters) | `8` | ticks | monster_manager.gd:38 |

### Projectiles

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PROJECTILE_SPEED` | `400.0` | u/s | game_constants.gd:329 |
| `PROJECTILE_MAX_DISTANCE` | `800.0` | u | game_constants.gd:332 |
| `PROJECTILE_RADIUS` | `8.0` | u | game_constants.gd:335 |
| `PROJECTILE_ENTITY_ID_START` | `10000` | id | game_constants.gd:339 |
| `PROJECTILE_ENTITY_ID_END` | `29999` | id (inclusive) | game_constants.gd:340 |
| `MONSTER_PROJECTILE_SPEED` | `300.0` | u/s (via `MonsterDefinition.projectile_speed` default) | game_constants.gd:433, monster_definition.gd:47 |
| `GRID_CELL_SIZE` | `64.0` | u (spatial hash cell) | projectile_manager.gd:20 |
| Muzzle offset (player) | `PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0` = `26.0` | u | server_main.gd:392 |
| Muzzle offset (monster) | `definition.hitbox_radius + PROJECTILE_RADIUS + 2.0` = `26.0` default | u | monster_ai.gd:510 |

### Hitboxes / hit windows

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_HITBOX_RADIUS` | `16.0` | u | game_constants.gd:343 |
| `MONSTER_HITBOX_RADIUS` | `16.0` | u (via `MonsterDefinition.hitbox_radius` default) | game_constants.gd:418, monster_definition.gd:31 |
| PvP hit window | `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS` = `24.0`, strict `<` | u | projectile_manager.gd:316 |
| PvE (vs monster) hit window | `PROJECTILE_RADIUS + MONSTER_HITBOX_RADIUS` = `24.0`, strict `<` | u | projectile_manager.gd:383 |
| Client incoming-hit window | `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS` = `24.0`, strict `<` | u | local_hit_detector.gd:77 |
| `PVP_DEFENDER_FAVOR` | `0.25` | unitless lerp factor [0..1] | game_constants.gd:356 |

### Damage / HP / death

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_PROJECTILE_DAMAGE` | `25` | HP (int) | game_constants.gd:439 |
| `MONSTER_PROJECTILE_DAMAGE` | `10` | HP (int) | game_constants.gd:436 |
| Player `health` / `max_health` | `100` / `100` | HP (int) | player_state.gd:58-59 |
| `MONSTER_HEALTH` | `50` | HP (int, via `MonsterDefinition.max_health` default) | game_constants.gd:415, monster_definition.gd:29 |
| `SHOOT_COOLDOWN` | `0.3` | s | game_constants.gd:364 |
| `MONSTER_SHOOT_COOLDOWN` | `0.75` | s (via `MonsterDefinition.shoot_cooldown` default) | game_constants.gd:456, monster_definition.gd:45 |
| `MONSTER_ATTACK_DURATION` | `0.5` | s (via definition `attack_duration`) | game_constants.gd:459 |
| `RESPAWN_DELAY` | `3.0` | s | game_constants.gd:367 |
| `INVULNERABILITY_DURATION` | `3.0` | s | game_constants.gd:370 |
| `PLAYER_KNOCKBACK_BASE_FORCE` | `450.0` | u/s impulse | game_constants.gd:96 |
| Knockback direction guard | `knock_dir.length() > 0.01` | u | server_collision_handler.gd:69 |

### Hit-report validation (server) & client detector

| Constant | Value | Unit | Source |
|---|---|---|---|
| `LOCAL_HIT_REPORT_MAX_PER_SECOND` | `20` | reports/peer/1 s window | server_main.gd:760 |
| `LOCAL_HIT_VALIDATION_MARGIN` | `64.0` | u | server_main.gd:766 |
| Plausibility threshold | `8.0 + 16.0 + 64.0` = `88.0`, strict `<` | u | server_main.gd:831 |
| `REPORT_RESOLVE_TIMEOUT_MS` | `500` | ms (wall clock) | local_hit_detector.gd:28 |
| `LocalHitDetector.enabled` default | `true` | — | local_hit_detector.gd:22 |

### Fire-origin validation (player shots)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `PLAYER_SPRINT_SPEED` | `320.0` (= 200.0 × 1.6) | u/s | game_constants.gd:59 |
| `POSITION_TOLERANCE` | `75.0` | u (upper clamp of fire-origin tolerance) | game_constants.gd:161 |
| Fire-origin tolerance lower clamp | `PROJECTILE_RADIUS * 2.0` = `16.0` | u | server_main.gd:449 |
| RTT clamp for tolerance/compensation | `[0, 65535]` | ms | server_main.gd:439,456 |

### Input / misc

| Constant | Value | Source |
|---|---|---|
| `INPUT_FLAG_SHOOT` | `1 << 4` = `16` | packet_types.gd:60 |
| `STALE_INPUT_TICK_LIMIT` | `6` ticks | player_state.gd:80 |
| `MAX_INPUT_QUEUE_SIZE` | `10` | player_state.gd:106 |
| `MAP_MIN` / `MAP_MAX` | `(-1000.0, -1000.0)` / `(1000.0, 1000.0)` (inclusive bounds) | game_constants.gd:177-180 |
| `POSITION_SCALE` (wire quantization) | `10.0` (i16, 0.1-u precision, **truncating** `int()` cast) | packet_writer.gd:15,126-128 |
| `closest_point_on_segment` degeneracy epsilon | `length_squared <= 0.0001` | game_constants.gd:568 |
| `monster_ai_difficulty` default | `0.85`, clamped `[0.0, 1.0]` | server_config.gd:49,96-97 |
| `HPComponent.max_hp` (export default) | `100` | hp_component.gd:13 |
| `projectile_manager.debug_logging` default | `true` (overwritten by `config.debug_logging` at boot, server_main.gd:131) | projectile_manager.gd:15 |

---

## 3. Data structures

### 3.1 ProjectileState (`projectile_state.gd:8-57`) — server-authoritative, one per live projectile

| Field | Type | Initial (via `create`, :61-95) | Notes / range |
|---|---|---|---|
| `entity_id` | int | allocated id | 10000–29999 |
| `owner_id` | int | spawner's entity id | player 1–999 or monster 30000–39999 |
| `position` | Vec2 (f64 pair in GDScript; Godot Vector2 is f32 — see hazards) | spawn position | world units |
| `previous_position` | Vec2 | = spawn position | start of this tick's travel segment |
| `direction` | Vec2 | `p_direction.normalized()` | unit vector; spawn rejects zero-approx input |
| `speed` | float | `PROJECTILE_SPEED` (400.0) — monster AI overrides to `definition.projectile_speed` (300.0 default) *after* create | u/s |
| `distance_traveled` | float | `0.0` | accumulates `|movement|` per tick; [0, ~800+13.34) |
| `alive` | bool | `true` | |
| `spawn_tick` | int | `tick_count` for player shots; **`0` for monster shots** (default arg) | |
| `simulation_ticks` | int | `0` | increments once per `update()` call, including the death tick |
| `collision_rewind_ticks` | int | derived (player shots); `0` (monster shots) | [0, 6] |
| `pvp_collision_rewind_ticks` | int | derived (player shots); `0` (monster shots) | [0, 4] |
| `client_render_tick` | int | resolved client tick or 0 | diagnostics + lag-comp record |
| `client_rtt_ms` | int | [0, 65535] | diagnostics |
| `lag_compensation_source` | String | one of `"none"`, `"client_render_tick"`, `"client_render_tick_clamped"`, `"rtt_fallback"`, `"render_delay_fallback"` | diagnostics only |
| `removal_reason` | String | `""` | `"player_hit"`, `"monster_hit"`, `"max_distance"`, `"out_of_bounds"`, `"obstacle"`, `"inactive"`, `"removed"`, `"expired"` |
| `closest_distance_to_monster` | float | `+INF` | diagnostics only (debug logging) |
| `closest_monster_id` | int | `-1` | diagnostics |
| `closest_monster_position` | Vec2 | `(0,0)` | diagnostics |
| `closest_projectile_position` | Vec2 | spawn position | diagnostics |
| `closest_monster_tick` | int | `-1` | diagnostics |

### 3.2 ProjectileManager (`projectile_manager.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `projectiles` | Dict<int, ProjectileState> | `{}` | **insertion-ordered** in GDScript — see hazards |
| `_next_entity_id` | int | `10000` | wraps to 10000 after 29999; advances past every candidate inspected |
| `debug_logging` | bool | `true` (set to `config.debug_logging` at boot) | gates diagnostics tracking |

### 3.3 Position history (players: `player_manager.gd:8-25`; monsters: `monster_manager.gd:8-38`)

- `_position_history`: Dict<server_tick:int, Array<Snapshot>>; `_position_history_ticks`:
  ordered Array<int> (append per tick, pop_front beyond 8 entries).
- `PlayerPositionSnapshot` = `{ entity_id: int, position: Vec2 }`.
- `MonsterPositionSnapshot` = `{ entity_id: int, position: Vec2, is_alive: bool (always true) }`.
- Snapshots contain only entities that were **authenticated && alive** (players) / **alive**
  (monsters) at record time.

### 3.4 Combat-relevant PlayerState fields (`player_state.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `health` / `max_health` | int | `100` / `100` | health ∈ [0, 100] |
| `is_alive` | bool | `true` | |
| `life_state` | enum {ALIVE=0, DEAD=1, INVULNERABLE=2} | `ALIVE` | |
| `shoot_cooldown` | float | `0.0` | counts down in `step()` via `maxf(0.0, cd - delta)` |
| `invulnerability_timer` | float | `0.0` | |
| `respawn_timer` | float | `0.0` | set to 3.0 on death |
| `pending_shots` | Array<Dict> | `[]` | rising-edge SHOOT queue (see 4.4) |
| `pvp_kills`, `monster_kills`, `deaths` | int | `0` | |
| `last_killer_id` | int | `-1` | entity id of last damage source that killed |
| `aim_angle` | float | `0.0` | radians, atan2 convention |

Pending-shot dict shape (player_state.gd:164-171):
`{ sequence: int, aim_angle: float, client_position: Vec2 or Vec2(INF,INF), client_velocity: Vec2, client_render_tick: int, client_rtt_ms: int }`.

### 3.5 Server hit-report rate window (`server_main.gd:769`)

`_local_hit_report_window`: Dict<peer_id, { start_ms: int, count: int }>. Erased on peer
disconnect (server_main.gd:644).

### 3.6 LocalHitDetector (client, `local_hit_detector.gd:30-39`)

| Field | Type | Notes |
|---|---|---|
| `enabled` | bool = true | A/B toggle |
| `_last_positions` | Dict<projectile_id, Vec2> | last rendered position per bullet (swept segment start) |
| `_reported_ids` | Dict<projectile_id, true> | bullets already reported this life (report at most once) |
| `_pending_reports` | Dict<projectile_id, ms_timestamp> | awaiting server verdict |

All three cleared by `reset()` (called on local respawn, arena_base.gd:541-542).

### 3.7 HPComponent (client visual mirror, `hp_component.gd`)

`max_hp: int = 100` (export), `current_hp: int = 100`, `is_dead: bool = false`. Signals
`hp_changed(new_hp, max_hp)`, `died()`. This is **not** authoritative — it mirrors server DAMAGE
events / reconciliation on the client. Port relevance: the Rust server replaces `PlayerState`
HP, not this; document kept for the client contract.

### 3.8 Hit event dict (internal, collision passes → handler)

`{ projectile_id: int, target_id: int, owner_id: int, position: Vec2 }` — `position` is the
closest point on the projectile's travel segment to the (compensated) target center
(projectile_manager.gd:324-329, 391-396).

---

## 4. Algorithms

Notation: `·` dot product, `|v|` length. All comparisons reproduce the GDScript exactly
(strict `<` vs `<=` matters).

### 4.1 Shared geometry: `closest_point_on_segment` (game_constants.gd:565-572)

The single shared primitive — client detection and server collision MUST use byte-identical math.

```
fn closest_point_on_segment(point, seg_start, seg_end) -> Vec2:
    segment = seg_end - seg_start
    length_sq = segment.length_squared()
    if length_sq <= 0.0001:           # degenerate (segment shorter than 0.01 u) → point test
        return seg_start
    t = clamp((point - seg_start) · segment / length_sq, 0.0, 1.0)
    return seg_start + segment * t
```

### 4.2 HitAuthority pure predicates (hit_authority.gd) — these go into `sim_core` (D11)

```
# Authority split (hit_authority.gd:17-18). A projectile is client-authoritative
# for the victim's dodge iff monster-owned. Note: -1 ("unknown owner" sentinel on
# the client) is NOT client-authoritative.
fn is_client_authoritative(owner_id: int) -> bool:
    return owner_id >= 30000            # MONSTER_ENTITY_ID_START

# Client swept hit test (hit_authority.gd:24-26). Strict <.
fn swept_hit(self_pos, prev_pos, cur_pos, hit_radius) -> bool:
    closest = closest_point_on_segment(self_pos, prev_pos, cur_pos)
    return distance(self_pos, closest) < hit_radius

# Flight reconstruction (hit_authority.gd:34-35). Exact for a still-alive
# straight-flying bullet (obstacle clamp kills the bullet, so alive ⇒ exact).
fn flight_origin(current_position, direction, distance_traveled) -> Vec2:
    return current_position - direction * distance_traveled

# Server plausibility (hit_authority.gd:42-47). Strict <. Returns true if ANY
# recent position is within threshold of the flight segment. Empty array → false.
fn is_hit_plausible(flight_start, flight_end, recent_positions: [Vec2], threshold) -> bool:
    for pos in recent_positions:
        closest = closest_point_on_segment(pos, flight_start, flight_end)
        if distance(pos, closest) < threshold:
            return true
    return false
```

Regression expectations (from `client/scripts/test/hit_authority_test.gd` — port as Rust tests):
ids 30000/35000 client-auth; 1/500/29999/-1 not; swept catches a crossing whose endpoints are both
~100 u away but path passes 5 u off; 30 u lateral pass is a miss; degenerate point segment at 10 u
hits / 50 u misses (radius 24); origin of (200,0) dir (1,0) traveled 400 is (-200,0); plausibility
threshold 88 is **exclusive** (exactly 88 u off-path → rejected, 87 → accepted); past positions in
history vindicate a hit; empty history rejects.

### 4.3 Projectile id allocation & recycling (projectile_manager.gd:78-89)

```
fn allocate_entity_id() -> int:
    range_size = 29999 - 10000 + 1          # 20000
    repeat range_size times:
        candidate = _next_entity_id
        _next_entity_id += 1
        if _next_entity_id > 29999: _next_entity_id = 10000
        if candidate not in projectiles: return candidate
    return -1                                # all 20000 ids live
```

The cursor monotonically advances (wrapping), skipping live ids; a freed id is reused only after
the cursor wraps around to it. `-1` ⇒ spawn fails with a warning, returns null.

### 4.4 Player shoot path

**(a) Edge detection at input ingest** (`player_state.gd:147-188`). For each drained input packet:
if `life_state == DEAD` discard entirely. Else compute
`was_shooting = (old input_flags & SHOOT) != 0`, `is_shooting = (new flags & SHOOT) != 0`; on
rising edge (`is_shooting && !was_shooting`) append a pending-shot dict capturing that packet's
sequence/aim/client_position/client_render_tick/client_rtt_ms. Then overwrite persistent
`input_flags`, `aim_angle`, timing metadata. Multiple packets drained in one tick each compare
against the running flags — held SHOOT across packets yields one edge; release+press across two
packets in one tick yields two queued edges (coalesced below).

**(b) Per-tick fire selection** (`server_main.gd:304-322`) — at most ONE spawn attempt per player
per tick:

```
for each player state:
    fired_this_tick = false
    loop:
        shot = state.pop_pending_shot()          # FIFO
        if shot is empty: break
        if not fired_this_tick:
            fired_this_tick = true               # set BEFORE knowing if spawn succeeds!
            try_spawn_projectile(state, shot)
        # surplus same-tick edges: drained and dropped
    if not fired_this_tick and state.is_shoot_held() and state.can_shoot():
        try_spawn_projectile(state, state.get_held_shot_input())
```

`can_shoot() = authenticated && is_alive && shoot_cooldown <= 0.0` (player_state.gd:130-131).
Note: a pending edge during cooldown *consumes* the tick's fire opportunity (latch set even though
`try_spawn` returns without firing) and the edge is NOT re-queued. Held auto-fire re-fires every
time the cooldown reaches 0 while SHOOT is held. `get_held_shot_input()` (player_state.gd:205-212)
synthesizes the shot dict from the latest persistent state (no `client_render_tick`?? — it DOES
include it, plus rtt and last client position; `client_velocity` absent).

**(c) `_try_spawn_projectile`** (`server_main.gd:368-414`):

```
if player.life_state == INVULNERABLE: player.end_invulnerability()   # shooting breaks invuln,
                                                                      # even if cooldown blocks the shot
if not player.can_shoot(): return

aim_angle  = input.aim_angle (fallback: player.aim_angle)
aim_dir    = Vec2(cos(aim_angle), sin(aim_angle))                     # Vector2.from_angle — unit length
origin     = validated_fire_origin(player, input)                     # (d)
comp       = pve_projectile_compensation(input)                       # (e)
rewind     = comp.rewind_ticks                                        # already clamped [0, 6]
pvp_rewind = clamp(comp.rewind_ticks, 0, 4)                           # re-clamped to PvP cap

spawn_pos  = origin + aim_dir * 26.0                                  # 16 + 8 + 2
proj = projectile_manager.spawn_projectile(player.entity_id, spawn_pos, aim_dir,
        tick_count, rewind, comp.client_render_tick, comp.client_rtt_ms, comp.source, pvp_rewind)
if proj != null:
    player.start_shoot_cooldown()                                     # shoot_cooldown = 0.3
    broadcast PROJECTILE_FIRED(source=player.entity_id, projectile=proj.entity_id,
                               position=spawn_pos, server_tick=tick_count)
```

`spawn_projectile` (projectile_manager.gd:25-74) rejects `direction.is_zero_approx()`
(component-wise |x|,|y| < ~1e-5) → null; id exhaustion → null. On failure: **no cooldown started,
no broadcast** (but the pending edge was already consumed).

**(d) Fire-origin validation** (`server_main.gd:417-451`). The client stamps its predicted
position on each input; the server uses it as the muzzle origin if close enough:

```
fn fire_origin_tolerance(input) -> float:
    rtt           = clamp(input.client_rtt_ms, 0, 65535)
    one_way_s     = min(rtt * 0.0005, 6 / tick_rate)        # ≤ MAX_PVE ticks of seconds (0.2 s @30)
    tick_interval = 1 / tick_rate
    predicted_gap = 320.0 * (one_way_s + tick_interval)     # PLAYER_SPRINT_SPEED
    return clamp(predicted_gap + 8.0, 16.0, 75.0)           # + PROJECTILE_RADIUS; [2*radius, POSITION_TOLERANCE]

fn validated_fire_origin(player, input) -> Vec2:
    client_pos = input.client_position (default Vec2(INF, INF))
    if client_pos != Vec2(INF, INF) and distance(player.position, client_pos) <= tolerance:
        return client_pos                                    # note: <= (inclusive)
    return player.position
```

**(e) Lag-comp rewind derivation** (`server_main.gd:454-490`):

```
fn pve_projectile_compensation(input) -> {rewind_ticks, client_render_tick, client_rtt_ms, source}:
    crt16 = input.client_render_tick & 0xFFFF
    rtt   = clamp(input.client_rtt_ms, 0, 65535)
    if crt16 > 0:
        resolved = resolve_client_tick_u16(crt16)            # u16 wrap-around resolve, below
        rewind   = tick_count - resolved
        if rewind >= 0:
            return { rewind_ticks: clamp(rewind, 0, 6),
                     client_render_tick: resolved, client_rtt_ms: rtt,
                     source: rewind <= 6 ? "client_render_tick" : "client_render_tick_clamped" }
        # client tick AHEAD of server (negative rewind): fall through to fallback
    one_way_ticks = rtt > 0 ? ceil((rtt * 0.5) / (1000 / tick_rate)) : 0     # ceiling, integer
    return { rewind_ticks: clamp(2 + one_way_ticks, 0, 6),                   # RENDER_DELAY + latency
             client_render_tick: 0, client_rtt_ms: rtt,
             source: rtt > 0 ? "rtt_fallback" : "render_delay_fallback" }

fn resolve_client_tick_u16(crt16) -> int:                    # server_main.gd:483-490
    diff = crt16 - (tick_count & 0xFFFF)
    if diff > 32767:  diff -= 65536
    if diff < -32768: diff += 65536
    return tick_count + diff
```

### 4.5 Monster shoot path (monster_ai.gd:281-285, 505-534)

Inside the AI ATTACK state, when `monster.can_shoot()` (alive && shoot_cooldown <= 0):

```
dir = predictive_aim_direction(monster, target)              # below; always unit length
spawn_pos = monster.position + dir * (hitbox_radius + 8 + 2) # 26.0 default
proj = spawn_projectile(monster.entity_id, spawn_pos, dir)   # spawn_tick=0, all rewinds=0,
                                                             # client_* = 0, source "none"
if proj != null:
    proj.speed = definition.projectile_speed                 # 300.0 default — OVERRIDE after create
    monster.last_fired_projectile_id = proj.entity_id
    monster.start_shoot_cooldown()                           # definition.shoot_cooldown, 0.75 default
    monster.attack_timer = definition.attack_duration        # 0.5 default
```

`MonsterAI.update_all` (monster_ai.gd:49-57) returns `{source_id, projectile_id}` per fire;
`server_main._update_monster_ai` (:517-536) broadcasts `PROJECTILE_FIRED(source_id, projectile_id)`
with **spawn_position = (0,0)** and **server_tick = 0** (defaults, server_main.gd:540-544). The
**non-zero projectile id is load-bearing** — invariant #3.

Predictive aim (monster_ai.gd:455-501), part of combat parity because it sets the projectile
direction:

```
fn predictive_aim_direction(monster, target) -> Vec2:
    predicted = predict_target_position(monster.position, target.position,
                                        target.velocity, definition.projectile_speed)
    dir = predicted - monster.position
    if dir is zero-approx: dir = target.position - monster.position
    if dir is zero-approx: dir = (1, 0)                      # Vector2.RIGHT
    max_error = (1.0 - difficulty) * 0.22                    # radians; difficulty default 0.85 → 0.033
    if max_error > 0.001: dir = dir.rotated(uniform_random(-max_error, max_error))   # RNG!
    return dir.normalized()

fn predict_target_position(origin, tpos, tvel, pspeed) -> Vec2:    # quadratic intercept
    rel = tpos - origin
    a = |tvel|² - pspeed²;  b = 2 * rel·tvel;  c = |rel|²
    t = |rel| / max(1.0, pspeed)                              # default guess; div-by-zero guard
    if |a| < 0.0001:
        if |b| > 0.0001 and (-c / b) > 0: t = -c / b
    else:
        disc = b² - 4ac
        if disc >= 0:
            t1 = (-b - sqrt(disc)) / (2a); t2 = (-b + sqrt(disc)) / (2a)
            best = min over {t1, t2 | > 0}; if any: t = best
    t = clamp(t, 0.0, 2.0)
    return tpos + tvel * t
```

### 4.6 Projectile integration: `ProjectileState.update(delta)` (projectile_state.gd:100-134)

Called once per projectile per tick by `update_all(tick_interval)`; returns "should remove".
Order of checks is exact:

```
fn update(delta) -> bool:
    if not alive:
        if removal_reason == "": removal_reason = "inactive"
        return true
    old = position
    previous_position = old
    movement = direction * speed * delta
    position += movement
    distance_traveled += |movement|
    simulation_ticks += 1
    if distance_traveled >= 800.0:                  # inclusive >=; position stays overshot
        alive = false; removal_reason = "max_distance"; return true
    if not is_within_bounds(position):              # bounds INCLUSIVE: x,y ∈ [-1000, 1000]
        alive = false; removal_reason = "out_of_bounds"; return true
    hit = line_intersects_obstacle(old, position)   # nearest intersection of segment with any
                                                    # ARENA_OBSTACLES rect (slab test, game_constants.gd:577-632)
    if hit != Vec2(INF, INF):
        position = hit                              # clamp to wall contact point
        alive = false; removal_reason = "obstacle"; return true
    return false
```

Per-tick advance at defaults: player bullet `400/30 ≈ 13.333` u, monster bullet `300/30 = 10.0` u.
Lifetime is distance-based only — no time-based expiry. Max range 800 u ⇒ exactly 60 ticks (player,
last movement crosses the 800 threshold on tick 60) — there is no tick-count cap.

`update_all` (projectile_manager.gd:108-124) iterates `projectiles` in insertion order, collects
removals, then `remove_projectile(id, reason)` for each. Obstacle geometry is the static
`ARENA_OBSTACLES` list (16 axis-aligned rects, game_constants.gd:480-502) — pure math, no Godot
physics involved (good: no engine dependency to replicate).

### 4.7 Server collision pass

Driver (`server_collision_handler.gd:12-20`): players pass first, then monsters pass.

**Spatial grid** (projectile_manager.gd:129-152): cell key = `(floor(x/64), floor(y/64))`
(`floori` — true floor, correct for negatives). Build: bucket each roster entity by its position.
Query: union of the 3×3 cell neighbourhood around a query point. Grids and rosters are built
**lazily per collision_tick per pass invocation** (memoized in per-call dicts). The query is
anchored at the projectile's **current** position (`proj.position` — segment END), not the
segment; one tick of travel (≤13.34 u) is far less than the 64 u cell margin, so coverage holds.

**Roster rewind with fallback** (player_manager.gd:274-289, monster_manager.gd:153-168):

```
fn get_alive_snapshot(server_tick):
    if history has server_tick: return it
    best = max tick in history with tick <= server_tick; if any: return it
    if history non-empty: return history[oldest tick]        # NOTE: oldest, even if > requested
    return live alive-entity list                            # heterogeneous fallback (live states)
```

**PvP pass — `check_collisions_with_players`** (projectile_manager.gd:267-343):

```
hits = []
for (entity_id, proj) in projectiles (insertion order):
    if not proj.alive: continue
    if is_client_authoritative(proj.owner_id): continue      # *** THE SKIP — invariant #1 ***
    collision_tick = proj.get_lag_compensated_player_tick()
    nearby = query 3x3 of player grid for collision_tick at proj.position
    for player in nearby (grid bucket order):
        if proj.owner_id == player.entity_id: continue       # never hit owner
        test_position = player.position                      # rewound snapshot position
        if PVP_DEFENDER_FAVOR > 0.0:                         # 0.25 → branch taken
            live = live player by entity_id (linear scan; null if disconnected)
            if live != null:
                test_position = lerp(player.position, live.position, 0.25)
                # lerp(a,b,t) = a + (b-a)*t, per-component
        hit_point = closest_point_on_segment(test_position, proj.previous_position, proj.position)
        if distance(test_position, hit_point) < 24.0:        # strict <
            proj.alive = false; proj.removal_reason = "player_hit"
            hits.append({projectile_id, target_id: player.entity_id, owner_id: proj.owner_id,
                         position: hit_point})
            break                                            # one target per projectile
remove all hit projectiles (reason "player_hit")
return hits
```

**PvE pass — `check_collisions_with_monsters`** (projectile_manager.gd:349-412): identical shape;
skip condition is `proj.owner_id >= 30000` (only player projectiles hit monsters); rewind via
`get_lag_compensated_monster_tick()`; no defender-favor lerp; window `8 + 16 = 24.0` strict `<`;
reason `"monster_hit"`. When `debug_logging`, a closest-approach diagnostic is tracked per
projectile (no behavioral effect).

**Lag-comp tick getters** (projectile_state.gd:149-161) — "the delayed world advances with the
projectile's age":

```
fn get_lag_compensated_monster_tick() -> int:
    if collision_rewind_ticks <= 0: return spawn_tick + simulation_ticks
    return max(0, spawn_tick - collision_rewind_ticks + simulation_ticks)

fn get_lag_compensated_player_tick() -> int:    # same with pvp_collision_rewind_ticks
```

Timing note: a player projectile spawned at tick T has `simulation_ticks = 1` by the collision
step of tick T (it integrated in step 2). With rewind 0 the getter yields `T + 1` — a tick not yet
in history — and the fallback resolves to tick T's snapshot. With rewind R it tests tick
`T − R + age`, walking forward one tick per tick so the rewound world replays in order.

### 4.8 Damage application — `apply_player_hit` (server_collision_handler.gd:42-90)

Shared by the PvP collision path AND the validated client report path (and the future backstop).

```
fn apply_player_hit(owner_id, target_id, ..., impact_position = Vec2(INF, INF)):
    target = player by entity_id; if null or not authenticated: return
    damage = owner_id >= 30000 ? 10 : 25                 # MONSTER vs PLAYER projectile damage
    previous = target.health
    killed = target.take_damage(damage, owner_id)        # 4.9
    applied = previous - target.health
    if applied <= 0: return                              # dead/invulnerable target → NO event at all
    if not killed and impact_position.is_finite():
        knock_dir = target.position - impact_position
        if |knock_dir| > 0.01:
            target.movement_sm.apply_knockback(knock_dir, 450.0)   # movement subsystem contract;
                                                                    # direction passed unnormalized
    broadcast GAME_EVENT DAMAGE(source=owner_id, target=target_id, amount=applied, damage_type=0)
    if killed: broadcast_player_kill(owner_id, target_id, ...)     # 4.10
```

Note the **broadcast amount is `applied`, not nominal damage** (a 5-HP player hit for 25
broadcasts 5).

### 4.9 `PlayerState.take_damage(amount, source_id)` (player_state.gd:407-444)

```
fn take_damage(amount, source_id = -1) -> killed: bool:
    if not is_alive or amount <= 0: return false
    if life_state == INVULNERABLE: return false           # no damage, no event
    health = max(0, health - amount)
    if health <= 0: mark_dead(source_id); return true
    animation_state = HIT; return false

fn mark_dead(killer_id):                                  # idempotent
    if life_state == DEAD: return
    is_alive = false; life_state = DEAD; health = 0; velocity = (0,0)
    movement_sm.reset(); input_flags = 0; input_queue.clear(); pending_shots.clear()
    _pending_dash = false; shoot_cooldown = 0.0
    respawn_timer = 3.0                                    # RESPAWN_DELAY
    deaths += 1; last_killer_id = killer_id
    animation_state = DEATH; update entity flags (ALIVE bit cleared, VISIBLE stays)
```

### 4.10 Kill broadcast — `_broadcast_player_kill` (server_collision_handler.gd:147-183)

```
fn broadcast_player_kill(killer_id, victim_id, ...):
    if killer_id < 30000:                                  # player killer (PvP)
        if killer_id == victim_id: return                  # self-kill: no event
        killer = player by entity_id                       # may be null (disconnected after firing)
        if killer != null and not killer.authenticated: return
        broadcast GAME_EVENT KILL_PVP(source=killer_id, target=victim_id)   # sent even if killer gone
        if killer == null: return                          # no stat/leaderboard updates
        killer.pvp_kills += 1
        leaderboard.record_pvp_kill(killer_id, victim_id); broadcast leaderboard
    else:                                                  # monster killer
        broadcast GAME_EVENT KILL(source=killer_id, target=victim_id)
```

### 4.11 Monster damage path — `_check_monster_collisions` (server_collision_handler.gd:94-143)

For each hit from the PvE pass:

```
monster = monster_manager.get_monster(hit.target_id); if null: continue   # projectile already consumed!
killer  = player by hit.owner_id                                          # may be null
previous = monster.health
killed = monster.take_damage(25)                  # PLAYER_PROJECTILE_DAMAGE, fixed
applied = previous - monster.health
if applied <= 0: continue                         # already-dead monster (ghost hit) → no event
broadcast GAME_EVENT DAMAGE(source=hit.owner_id, target=hit.target_id, amount=applied, damage_type=0)
if killed:
    if killer != null and killer.authenticated: killer.monster_kills += 1
    broadcast GAME_EVENT KILL(source=hit.owner_id, target=hit.target_id)   # even if killer gone
```

`MonsterState.take_damage(amount)` (monster_state.gd:110-127): `if !is_alive or amount <= 0 →
false`; `health = max(health - amount, 0)`; `health == 0` → `is_alive = false`, clear
ALIVE/MOVING/ATTACKING flags, DEATH animation, `move_direction = (0,0)`, return true; else HIT
animation, false. Dead monsters are erased at end-of-tick `cleanup_dead_monsters()`
(monster_manager.gd:189-197) so the death state broadcasts once.

### 4.12 `LOCAL_HIT_REPORT` server validation (server_main.gd:776-836)

Gate order is exact and observable (e.g. rate-limit quota is consumed before projectile checks):

```
fn handle_local_hit_report(peer_id, data):
    projectile_id = int(data.projectile_id);  if projectile_id <= 0: return
    player = player by peer_id
    if player == null or not player.authenticated or not player.is_alive: return
    if not allow_local_hit_report(peer_id): return          # consumes quota
    proj = projectiles.get(projectile_id)
    if proj == null or not proj.alive: return               # idempotent: removed bullet can't re-apply
    if not is_client_authoritative(proj.owner_id): return   # reject player-owned (no PvP via report)
                                                            # *** invariant #2 ***
    if not local_hit_is_plausible(proj, player.entity_id): return
    apply_player_hit(proj.owner_id, player.entity_id, ..., impact_position = proj.position)
        # NOTE: target is ALWAYS the reporting peer's own entity — the packet carries no target id
    remove_projectile(projectile_id, "player_hit")          # despawn for everyone, UNCONDITIONALLY
                                                            # (even if invuln target took 0 damage)

fn allow_local_hit_report(peer_id) -> bool:                 # fixed (not sliding) 1 s window
    now = monotonic_ms()
    {start_ms, count} = window.get(peer_id, {0, 0})
    if now - start_ms >= 1000: start_ms = now; count = 0
    count += 1; window[peer_id] = {start_ms, count}
    return count <= 20

fn local_hit_is_plausible(proj, entity_id) -> bool:
    threshold = 8.0 + 16.0 + 64.0                           # 88.0
    flight_start = flight_origin(proj.position, proj.direction, proj.distance_traveled)
    positions = player_manager.get_recent_positions(entity_id)   # below
    return is_hit_plausible(flight_start, proj.position, positions, threshold)
```

`get_recent_positions(entity_id)` (player_manager.gd:295-305): for each tick in the 8-tick history
window (oldest first), the entity's recorded position if present; then **append the live position**
— up to 9 positions. A freshly-connected player on an empty server still gets ≥1 (live) position.

The plausibility test runs against the bullet's **full reconstructed flight** (spawn → current),
not just the last tick, because the report arrives ~render-delay + RTT after contact and the live
bullet is downrange of the contact point. The 64 u margin is an anti-grief bound — invariant #4:
**do not tighten it** toward the true 24 u window.

### 4.13 Client detection loop — `LocalHitDetector.update()` (local_hit_detector.gd:57-137)

Per render frame, after visuals:

```
fn update():
    if not enabled: return
    if prediction == null or not prediction.is_active(): return
    if local_player invalid: return
    if local_player.hp_component != null and hp_component.is_dead: return
    if entity_manager == null: return

    resolve_pending_reports()                               # below — runs FIRST

    self_pos  = prediction.get_rendered_position()          # the on-screen position
                                                            # (player_node.position; falls back to
                                                            # predicted_position) — *** invariant #6 ***
    hit_radius = 24.0
    snapshots = entity_manager.get_monster_projectile_snapshots()
        # [{id, position}] of projectiles whose registered source is monster-owned
        # (is_client_authoritative(source); unknown source -1 excluded) AND currently visible
        # (a locally-hidden reported bullet is excluded) — client_entity_manager.gd:517-527

    seen = {}
    for snap in snapshots:
        id = snap.id; cur = snap.position; seen[id] = true
        if id in _reported_ids: continue                    # report each bullet at most once per life
        prev = _last_positions.get(id, cur)                 # first sighting → degenerate point segment
        _last_positions[id] = cur
        if swept_hit(self_pos, prev, cur, hit_radius):
            report_hit(id)
    prune _last_positions and _reported_ids of ids not in seen

fn report_hit(id):
    _reported_ids[id] = true
    _pending_reports[id] = monotonic_ms()
    entity_manager.hide_projectile_locally(id)              # cosmetic instant impact
    send LOCAL_HIT_REPORT { projectile_id: id }             # wire: [u16 projectile_id]

fn resolve_pending_reports():                               # invariant #7
    now = monotonic_ms()
    for (id, t) in _pending_reports:
        if now - t < 500: continue                          # REPORT_RESOLVE_TIMEOUT_MS
        erase _pending_reports[id]
        if entity_manager.is_projectile_active(id):         # still live ⇒ server rejected / report lost
            entity_manager.show_projectile_locally(id)      # un-hide
            erase _reported_ids[id]; erase _last_positions[id]   # re-arm detection
        # else: server confirmed (despawned) — nothing to restore
```

`reset()` clears all three maps — called on local respawn so a fresh life can be hit by a bullet id
that was reported in the previous life.

Ownership reaches the client via `PROJECTILE_FIRED`: `arena_base._handle_projectile_fired_event`
(arena_base.gd:630-650) reads `source_id` (packet `source_id`) and `projectile_id` (packet
**`target_id`** — field reuse!) and calls
`client_entity_manager.register_projectile_source(projectile_id, source_id)` which ignores
non-positive ids (client_entity_manager.gd:506-510).

### 4.14 Death → respawn flow

1. Death: `mark_dead` (4.9) sets `respawn_timer = 3.0`. Dead players: inputs discarded at ingest,
   `step()` zeroes velocity/flags and returns a no-correction validation
   (player_state.gd:224-236).
2. Each tick, `update_respawn_timer(delta)` decrements toward 0 with `maxf(0.0, t - delta)`
   (player_state.gd:448-453) — **respawn is never automatic**.
3. Client sends `RESPAWN_REQUEST` (type 9, empty payload). Server `_handle_respawn_request`
   (server_main.gd:737-756): reject if state null, if `is_alive`, or if `respawn_timer > 0.0`.
4. `respawn_player` (player_manager.gd:225-236): pick next round-robin spawn from the 10-entry
   `ARENA_PLAYER_SPAWNS` list filtered for validity (`_spawn_index % len`, then advance), call
   `reset_for_respawn(spawn_pos)` (player_state.gd:384-402): position = spawn, velocity 0,
   `health = max_health`, `is_alive = true`, `life_state = INVULNERABLE`,
   `invulnerability_timer = 3.0`, movement SM reset, respawn_timer 0, shoot_cooldown 0, input
   state cleared, `last_killer_id = -1`, SPAWN animation, flags ALIVE|VISIBLE|INVULNERABLE.
5. Broadcast `GAME_EVENT RESPAWN(target_id = entity_id, position)` (server_main.gd:840-864).
6. Invulnerability ends when: timer expires (`update_invulnerability`, decremented every tick for
   all players, player_state.gd:457-465); OR the player has active input (any MOVE flag or SHOOT
   — `has_active_input`, checked inside `step()` :243-244); OR a pending/held shot reaches
   `_try_spawn_projectile` (ends invuln before the cooldown check, server_main.gd:369-370).
   While INVULNERABLE, `take_damage` returns false (zero damage, no event), but a reported monster
   bullet is still despawned (4.12).

### 4.15 Projectile replication data (projectile_state.gd:169-181)

```
fn to_entity_data() -> { id, type: PROJECTILE(3), position, animation, flags }:
    angle = atan2(direction.y, direction.x)                 # (-π, π]
    animation = int(fmod(angle + π, 2π) / (2π) * 8) % 8     # truncating int(); octant 0..7
                                                            # +x direction → 4; angle π → 0
    flags = alive ? ENTITY_FLAG_VISIBLE (32) : 0            # note: ALIVE bit never set for projectiles
```

Only `alive` projectiles are included in state updates (`collect_state_updates`,
projectile_manager.gd:417-424).

### 4.16 The lenient server backstop (D11 — **OFF in GDScript today, the port turns it ON**)

There is **no implementation in the GDScript** — today a hacked client that never sends
`LOCAL_HIT_REPORT` is immune to monster damage (the doc's "accepted hole"). Under D10 permadeath
this is escalated to *mitigated*. Intended semantics (from migration-spec D11 +
hit-authority-model.md:190-194), to be implemented Rust-side:

- **Scope:** monster-owned projectiles vs players only. PvP and player→monster paths are untouched.
- **Trigger:** the projectile's **authoritative** swept path **blatantly overlaps** a player's
  authoritative position, AND **no `LOCAL_HIT_REPORT` for that projectile arrives from that player
  within N ticks** of the overlap.
- **Action:** the server applies the hit through the **same shared path** as a validated report —
  `apply_player_hit(owner_id, victim_entity_id, ..., impact = projectile position)` + despawn the
  projectile — so DAMAGE/KILL/knockback semantics are identical.
- **Hard constraint (invariant #4 / D11):** it must stay **lenient / blatant-overlap-only**. A
  tight backstop re-decides hits on authoritative positions and reintroduces the exact
  phantom-hit / pass-through feel the client-authoritative path exists to prevent.
- **Constants are deliberately unspecified** (no GDScript precedent — tune in mixed-ping
  play-tests). Guidance consistent with the docs: the overlap threshold must be **no looser than
  the true 24.0 u hit window** (i.e. clearly tighter than the 88.0 u plausibility bound —
  "blatant" means the bullet visibly passed through the player on the authoritative timeline),
  and N must **comfortably exceed render-delay + RTT at target ping** so legitimate reports always
  win the race — at least the client's own resolve window, 500 ms ≈ **15 ticks @30 Hz**, is the
  documented floor for "the verdict has had time to arrive".
- Bookkeeping implied: per (projectile, player) overlap tick recording, suppressed when a report
  for that projectile was already honoured (the projectile despawns) or the player died. A
  backstop hit must be idempotent with a late-arriving report (projectile gone ⇒ report no-ops —
  already guaranteed by the `proj == null` gate in 4.12).
- The companion *statistical* anti-cheat ("flags accounts taking ≈zero monster damage over time")
  is a detection/ban workstream, **not** part of the sim — do not build it into the tick.

### 4.17 Carried-forward invariants — verbatim from `docs/netcode/hit-authority-model.md` ("Intended invariants")

> 1. `check_collisions_with_players` **must** early-`continue` on `owner_id >= MONSTER_ENTITY_ID_START`.
>    If that skip is removed, monster hits double-apply.
> 2. `_handle_local_hit_report` **must** reject `owner_id < MONSTER_ENTITY_ID_START` (no PvP via client
>    report) and **must** apply to the *reporting* peer's own entity only (never a target id from the
>    client).
> 3. Monster `PROJECTILE_FIRED` **must** carry a non-zero projectile id, or the client never tags the
>    bullet monster-owned and the whole PvE path silently no-ops (you'd take *no* monster damage).
> 4. The plausibility slack (`LOCAL_HIT_VALIDATION_MARGIN`) is a coarse anti-grief bound; it must stay
>    comfortably larger than the prediction+interpolation offset at target ping. It is **not** a hit
>    re-check.
> 5. PvP/PvE-on-monster hit detection **must** remain entirely server-side and lag-compensated; never
>    route them through `LOCAL_HIT_REPORT`.
> 6. The client hit test **must** use the **rendered** local-player position
>    (`prediction.get_rendered_position()`), not `predicted_position`. The two diverge during a smooth
>    correction; testing against the prediction would judge the hit in a frame the player never saw.
> 7. A reported bullet that the server does **not** despawn within `REPORT_RESOLVE_TIMEOUT_MS` **must**
>    be un-hidden and made detectable again (`LocalHitDetector._resolve_pending_reports`). A locally
>    hidden bullet that is never restored is both an invisible projectile and a free dodge of a hit the
>    server rejected.

(D11 adds: these become Rust-side tests, and the client tests against the rendered position, not
the predicted one.)

---

## 5. Edge cases & gotchas

- **Sentinel values.** `Vector2.INF` = `(inf, inf)` is the "no value" sentinel throughout:
  `line_intersects_obstacle` returns it for "no hit" (compared with `!=` — IEEE `inf == inf` is
  true, so the comparison works); `client_position` defaults to it in shot dicts;
  `apply_player_hit` default `impact_position` is it and is screened with `is_finite()` (any
  non-finite component ⇒ skip knockback). `closest_distance_to_monster` starts at `+INF`;
  `closest_monster_id`/`closest_monster_tick` start at `-1`. Client unknown projectile source is
  `-1` (must NOT be client-authoritative).
- **Projectile id recycling.** Ids cycle through 10000–29999 with live-id skip; a recycled id can
  reappear quickly under heavy fire. Client-side, `_spawn_projectile` early-returns if the id is
  already active (client_entity_manager.gd:266-267) — if a reused id arrives before the old
  visual's despawn delta is processed, the new projectile silently fails to spawn client-side until
  the removal lands. The detector's per-id maps are pruned when an id leaves the rendered set, so a
  recycled id is detectable again.
- **Spawn failure consumes the trigger.** Zero-approx direction or id exhaustion ⇒
  `spawn_projectile` returns null; the pending shot edge was already consumed and the tick's
  `fired_this_tick` latch already set, but **cooldown does not start and no PROJECTILE_FIRED is
  broadcast**.
- **Pending edge during cooldown is dropped, not deferred** (see 4.4b). Held SHOOT auto-fires when
  the cooldown reaches zero; a tap during cooldown produces nothing.
- **Shoot cooldown float residue.** `shoot_cooldown = 0.3`, decremented by `maxf(0.0, cd - 1.0/30.0)`
  each tick; `can_shoot` requires `<= 0.0`. Whether 9 subtractions of f64 `1.0/30.0` from f64 `0.3`
  lands exactly at ≤0 depends on rounding — replicate the same op order in f64 or accept a ±1-tick
  cadence difference (~9 vs 10 ticks between auto-fire shots).
- **Monster projectiles never enter either server collision pass** (owner ≥ 30000 skips both), so
  they cannot hit monsters or (server-side) players. They die only by max-distance (800 u even
  though their speed is 300), bounds, obstacle, or a validated report. Their
  `spawn_tick = 0` / rewinds = 0 are therefore harmless garbage — do not "fix" them into the
  collision tick math.
- **Monster projectiles spawn after integration** (tick step 3 vs step 2) ⇒ first movement happens
  on the tick after spawn; player projectiles move on their spawn tick. Preserve this or muzzle
  feel and report plausibility shift by one tick.
- **Ghost hits.** The PvE pass tests rewound monster snapshots; a monster that died (and was
  cleaned up) after the rewound tick still consumes the projectile — the hit row is produced, the
  projectile is removed, but `get_monster` returns null (or `take_damage` on a dead monster applies
  0) ⇒ **no damage, no event, bullet gone**. Same for PvP: a hit on a rewound snapshot of a player
  who has since disconnected (entity lookup fails) or died/invulnerable (`applied <= 0`) consumes
  the projectile silently.
- **Invulnerable/dead report target still despawns the bullet.** In `_handle_local_hit_report` the
  projectile removal is unconditional after plausibility — a report from a player who becomes
  invulnerable mid-flight consumes the bullet with zero damage and no DAMAGE event. (Dead reporters
  are rejected earlier by the `is_alive` gate.)
- **Rate-limit quota is consumed before projectile existence/ownership checks** — 20 garbage
  reports/second exhaust the window even if all are rejected. Window is a fixed 1 s bucket, not
  sliding; state erased on disconnect.
- **`fired_this_tick` + multiple same-tick edges:** surplus rising edges drained in the same tick
  are dropped (the paired-shots fix). `SHOOT_COOLDOWN` 0.3 s makes >1 legit shot per 33 ms tick
  impossible anyway.
- **Two projectiles, one victim, one tick:** both produce hit rows (each breaks only its own inner
  loop); processing order = projectile insertion (spawn) order. The first may kill; the second then
  applies 0 (`take_damage` on dead returns false) ⇒ no second DAMAGE event, but both projectiles
  are consumed. Kill credit goes to the first in iteration order — **GDScript Dictionaries iterate
  in insertion order; the Rust container must preserve spawn order for parity.**
- **Self-kill:** PvP self-hit is impossible via collision (owner skip); `_broadcast_player_kill`
  still guards `killer_id == victim_id` → no event, no stats.
- **Disconnected shooter:** already-fired projectiles stay authoritative; on a kill the KILL_PVP /
  KILL event still broadcasts, but stats/leaderboard updates are skipped when the shooter is gone
  (4.10, 4.11).
- **Stale input:** after 6 ticks without input, `input_flags = 0` (player_state.gd:220-221) — held
  auto-fire stops for silent/disconnecting clients.
- **Arena bounds:** inclusive `[-1000, 1000]` on both axes for projectiles
  (`is_within_bounds`); a projectile at exactly x = 1000 survives; at 1000.0001 dies
  `out_of_bounds` *without* position clamp (its final broadcast position may be outside the
  arena). An obstacle death clamps position to the wall-contact point.
- **Division-by-zero guards present:** `closest_point_on_segment` (length_sq ≤ 1e-4 → point),
  `predict_target_position` (`max(1.0, pspeed)`, `|a| < 1e-4`, `|b| > 1e-4` branches),
  `_line_rect_intersection` (`|dir.x| < 1e-4` / `|dir.y| < 1e-4` slab branches), velocity
  recompute `if delta > 0.0`. **Guard absent:** none in this subsystem divides unguarded; but note
  `int(data.get(...))` casts on packets accept any int — entity ids are not range-validated beyond
  the documented gates.
- **`Vector2.normalized()` on a zero vector returns `(0,0)` in Godot** — relevant only at spawn
  (screened by `is_zero_approx`) and in monster AI fallbacks (explicit `Vector2.RIGHT` fallback).
- **u16 tick wrap:** `client_render_tick` rides the wire as u16; `_resolve_client_tick_u16` maps it
  to the nearest absolute tick within ±32768 of `tick_count`. A client tick that resolves AHEAD of
  the server (negative rewind) silently falls back to the RTT path.
- **`tick_count` starts at 0 and is pre-incremented** — the first processed tick is 1
  (server_main.gd:215). Position history starts populating from tick 1.
- **Monster AI fire uses RNG** (aim error ±0.033 rad at difficulty 0.85, steering offsets) — not
  reproducible across runs; parity here is statistical, not bitwise. Player-shot combat math is
  RNG-free.
- **HPComponent.set_hp can resurrect** (`hp > 0 && is_dead → is_dead = false`,
  hp_component.gd:71-72) — client-side reconciliation semantics, mirror if the client keeps it.
- **`Projectile` (client node) is cosmetic in online play:** spawned from the pool with
  `process_mode = DISABLED`, `monitoring/monitorable = false` (client_entity_manager.gd:270-274);
  its position is driven by the interpolation controller. Its self-movement
  (`_physics_process`: `pos += dir * speed * delta`, deactivate at `max_distance`) and
  `body_entered → hit → deactivate` collision behavior are used only by the offline modes. The
  Rust server replaces none of this; the port must NOT add client-side authoritative collision.

---

## 6. Cross-subsystem contracts

### Inbound (what combat consumes)

| From | Contract |
|---|---|
| Input pipeline | `PLAYER_INPUT` fields used here: `input_flags` (u16 bitfield; SHOOT = bit 4), `sequence_number`, `aim_angle` (f32 radians), `position` (client predicted pos, quantized 0.1 u), `client_render_tick` (u16), `client_rtt_ms` (u16). Drained per tick by `PlayerManager.process_all_inputs(delta, server_tick)`. |
| Movement subsystem | `PlayerState.position/velocity` (authoritative, post-`step()`); `movement_sm.apply_knockback(direction: Vec2 /*unnormalized*/, force: f32 = 450.0)`; `GameConstants.move_with_obstacle_collision` (players/monsters only — projectiles use the segment-vs-rect test instead). |
| Monster subsystem | `MonsterManager.get_alive_monsters()`, `get_monster(id)`, `record_position_snapshot(tick)`, `get_alive_monster_snapshot(tick)`, `cleanup_dead_monsters()`; `MonsterDefinition { max_health=50, hitbox_radius=16.0, projectile_speed=300.0, shoot_cooldown=0.75, attack_duration=0.5 }`. |
| Client prediction | `prediction.is_active() -> bool`; `prediction.get_rendered_position() -> Vec2` (= `player_node.position`, the on-screen transform; falls back to `predicted_position` if no node — prediction.gd:793-796). |
| Client entity manager | `register_projectile_source(projectile_id > 0, source_id > 0)`; `get_monster_projectile_snapshots() -> [{id: int, position: Vec2}]` (monster-owned AND visible only); `hide_projectile_locally(id)` / `show_projectile_locally(id)` (visibility toggle); `is_projectile_active(id) -> bool`. |

### Outbound packets (exact wire shapes; header `[u8 type][u16 payload_len]`, positions quantized `i16 = int(x * 10.0)` — **truncating** cast, packet_writer.gd:126-128)

| Packet | Type id | Payload | Sent when |
|---|---|---|---|
| `LOCAL_HIT_REPORT` (C→S) | 13 | `[u16 projectile_id]` | client detector hit (network_manager.gd:897-902, decode :1035-1037). **`is_valid_type` must accept 13** — the historical bug was the range check capping at 12 (packet_types.gd:141-142). |
| `GAME_EVENT DAMAGE` (S→C, broadcast) | 3 / event 1 | `[u8 event=1][u16 source_id][u16 target_id][u16 amount][u8 damage_type=0]` | every applied hit; `amount` = damage actually applied |
| `GAME_EVENT KILL` (S→C) | 3 / event 2 | `[u8 2][u16 killer][u16 victim]` (no extra data) | monster killed a player, or player killed a monster |
| `GAME_EVENT KILL_PVP` (S→C) | 3 / event 10 | `[u8 10][u16 killer][u16 victim]` | player killed a player |
| `GAME_EVENT PROJECTILE_FIRED` (S→C) | 3 / event 12 | `[u8 12][u16 source_id][u16 **projectile_id in the target_id field**][i16 x][i16 y][u16 server_tick]` | every successful spawn. Player shots: real spawn pos + tick. Monster shots: position (0,0), tick 0 — only the ids matter. |
| `GAME_EVENT RESPAWN` (S→C) | 3 / event 3 | `[u8 3][u16 source=0][u16 entity_id][i16 x][i16 y]` | accepted respawn |
| `RESPAWN_REQUEST` (C→S) | 9 | empty | dead client asks to respawn |
| `ACTION_CONFIRM` (S→C, per-peer) | 5 | `[u8 sequence][u8 action_type][i16 x][i16 y][u8 result_code][u16 server_tick][u8 stamina][u8 mana]` | **today only `action_type = MOVE(0)`** is ever sent — one per player per tick that ingested input (server_main.gd:326-354). `create_shoot_confirm` (action_confirm_packet.gd:68-75) exists but is **never called**: there is **no explicit hit/shoot confirm packet**. Hit confirmation to the reporting client is implicit — the projectile's removal delta in the next STATE_UPDATE plus the DAMAGE event; the detector treats "projectile gone within 500 ms" as the confirm (4.13). |

Events broadcast every tick (not gated by snapshot rate). Projectile state replication rides
STATE_UPDATE snapshots via `to_entity_data()` (4.15); despawn reaches clients as a removal delta
(`DELTA_MASK_REMOVED`) from the broadcast subsystem.

---

## 7. Rust port hazards (checklist)

1. **Float width.** Godot `Vector2` components are **f32**; GDScript scalar `float` is **f64**.
   Combat math mixes them (segment math in Vector2 ops = f32; cooldowns/timers = f64). `sim_core`
   must pick one convention and keep client/server identical (D5 makes this trivially true — but
   unit tests comparing against GDScript captures must tolerate the f32/f64 seam).
2. **Strict `<` everywhere.** Hit windows (24.0), plausibility (88.0), knockback guard (`> 0.01`),
   segment epsilon (`length_sq <= 0.0001`), `distance_traveled >= 800.0`, inclusive map bounds.
   The test suite pins the 88-exclusive boundary explicitly.
3. **Truncating casts.** GDScript `int(f)` truncates toward zero — wire quantization
   (`int(x * 10.0)`), projectile animation octant. Using `round()` changes wire bytes and visuals.
4. **Iteration order.** GDScript Dictionaries iterate in insertion order. Hit processing, kill
   attribution, and `update_all` removal order all follow projectile spawn order. Use an ordered
   container (Vec/slotmap in id-insertion order), not HashMap.
5. **Tick-step ordering** (Section 1): inputs/player-spawn → integrate → monster AI/monster-spawn
   → record history → collide → broadcast → cleanup. Player projectiles move on spawn tick;
   monster projectiles don't. History records post-move, pre-collision positions.
6. **`fired_this_tick` latch semantics:** set before the spawn attempt; cooldown-blocked pending
   edges are dropped and suppress held auto-fire that tick.
7. **Lag-comp tick math:** `max(0, spawn_tick − rewind + simulation_ticks)` with the `<= 0` rewind
   early-return; the roster fallback chain (exact → newest ≤ requested → **oldest** → live).
   PvE cap 6, PvP cap 4, derived per-shooter per-shot from `client_render_tick` (u16
   wrap-resolved) with RTT fallback `2 + ceil(rtt/2 / tick_ms)`.
8. **`PVP_DEFENDER_FAVOR` lerp** runs only when `> 0.0` (it is 0.25): rewound→live lerp per
   component, skipped silently when the live defender is gone.
9. **Authority skips are inverted traps:** the players pass skips monster-owned; the monsters pass
   skips monster-owned (i.e. keeps player-owned). Getting either backwards double-applies or
   disables a whole path. Port `HitAuthority` once into `sim_core` and call it from both (D11).
10. **`LOCAL_HIT_REPORT` gate order** (4.12) is observable: quota burns before projectile lookup;
    plausibility uses the FULL reconstructed flight; the target is always the reporting peer's
    entity; removal is unconditional after acceptance.
11. **DAMAGE broadcasts applied damage, not nominal** — and zero-applied hits (dead/invuln) emit
    no event at all while still consuming the projectile.
12. **No engine physics in server combat.** Projectile/world collision is pure math
    (slab test vs 16 static rects), not Godot physics — nothing to emulate from `move_and_slide`.
    The only Godot-physics object (`Projectile` Area2D `body_entered`) is client/offline cosmetic.
13. **Monster projectile speed override happens after creation** (create at 400, then set 300) —
    `distance_traveled`/`flight_origin` stay exact regardless; max range stays 800 u for both.
14. **Time bases differ:** the detector and rate limiter use wall-clock ms
    (`Time.get_ticks_msec()`, monotonic), everything server-sim uses tick counts and
    `tick_interval` seconds. Don't convert the 500 ms resolve window or the 1 s rate window into
    ticks server-side (the rate window is wall-clock on the server too).
15. **The backstop (4.16) is new code with constraints, not a port:** lenient, blatant-overlap-only,
    N ≥ ~15 ticks grace, same shared apply path, idempotent with late reports. Do not let it
    re-decide ordinary hits (invariant #4/#5).
16. **Cooldown float residue** (hazard for auto-fire cadence) — see Section 5; replicate f64 op
    order or document the ±1-tick difference.
17. **Id allocation:** cursor advances past inspected candidates and wraps at 29999→10000;
    exhaustion returns failure, not a panic. Monster ids share the same pattern in 30000–39999.
18. **u16 wrap of `client_render_tick` / `server_tick` wire fields** — `tick_count` is unbounded
    internally; resolve client ticks via the ±32768 window, and remember `PROJECTILE_FIRED.server_tick`
    truncates to u16 on the wire.
19. **RNG in monster aim** — keep it out of `sim_core` determinism claims; player-side combat math
    must be bit-deterministic, monster aim need only be distribution-equivalent.
20. **Client detector preconditions** (enabled, prediction active, not dead, manager present) and
    the *resolve-before-detect* ordering inside `update()` — re-arming a rejected bullet must
    happen before this frame's sweep so the un-hidden bullet is testable next frame (it reappears
    in snapshots only once visible again).
