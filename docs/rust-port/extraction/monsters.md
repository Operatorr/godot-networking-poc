# Monsters — behavioral extraction for the Rust port

> Generated extraction notes for the Rust port — derived from GDScript at commit `9e66149` on branch `feature/rust-port`. Source of truth is the GDScript until cutover.

This document specifies the **monster subsystem** of the authoritative game server: the data-driven
monster catalogue, per-monster state, the four-state AI, steering/movement, predictive shooting,
the three-layer spawn director, monster entity-id allocation (30000–39999), the 8-tick position
history used for player-projectile lag compensation, and the `PROJECTILE_FIRED` broadcast monsters
emit. It is written for a Rust engineer who cannot read GDScript. Per migration-spec **D8** all of
this runs inside the single synchronous 30 Hz tick thread; per **D5** the collision helpers it
shares with players (`move_with_obstacle_collision`, bounds checks) live in the shared `sim_core`
crate; per **D11** the invariant *"monster `PROJECTILE_FIRED` carries a non-zero projectile id"*
must be preserved.

Source files covered (all paths repo-relative):

| File | Role |
|---|---|
| `client/scripts/server/monster_ai.gd` | AI state machine, targeting, steering, shooting |
| `client/scripts/server/monster_spawner.gd` | spawn cadence + 3-layer placement director |
| `client/scripts/server/monster_manager.gd` | id allocation, registry, position history, cleanup |
| `client/scripts/server/monster_state.gd` | per-monster authoritative state + damage/death |
| `client/scripts/server/monster_factory.gd` | definition → state assembly |
| `client/scripts/shared/monster/monster_database.gd` | JSON catalogue loader |
| `client/scripts/shared/monster/monster_definition.gd` | archetype data (stats/AI tuning) |
| `client/scripts/shared/monster/monster.gd` | **client-side render-only** node (no AI) |
| `client/data/monsters/{index,toxic_slime,target_dummy}.json` | shipped archetype data |

---

## 1. Overview

Monsters are **100 % server-authoritative**. The client never simulates them; it only interpolates
positions and plays animations from snapshots (`monster.gd:1-3`). Per server tick (30 Hz,
`tick_interval = 1.0 / config.tick_rate`), the monster subsystem runs in this fixed order inside
`_process_server_tick` (`server_main.gd:213-283`):

| Tick step | Call | What happens |
|---|---|---|
| 2 | `_update_game_state` → `monster_spawner.update(tick_interval)` (`server_main.gd:501`) | spawn timing + placement; new monsters registered |
| 3 | `_update_monster_ai` → `monster_ai.update_all(alive_monsters, tick_interval)` (`server_main.gd:517-536`) | per-monster: timers, retarget, steering refresh, state machine, movement, shooting. Returns fire events; each is broadcast as `PROJECTILE_FIRED` |
| 4 | `monster_manager.record_position_snapshot(tick_count)` (`server_main.gd:253`) | record alive-monster positions into the 8-tick lag-comp history (post-AI-movement, pre-collision) |
| 5 | `collision_handler.process_collisions(...)` (`server_main.gd:257`) | player projectiles vs (lag-rewound) monsters → damage/kill; monster projectiles vs players handled elsewhere (client-reported, D11) |
| 6 | snapshot broadcast (only on snapshot-due ticks) | `monster_manager.collect_state_updates()` feeds the AoI/delta snapshot builder |
| 7 | `monster_manager.cleanup_dead_monsters()` (`server_main.gd:276`) | erase dead monsters **after** their death state was broadcast (dead monsters survive exactly until the cleanup at the end of the tick they died in) |

Important ordering facts:

- The spawner runs **before** the AI in the same tick, and `_update_monster_ai` fetches
  `get_alive_monsters()` after spawning, so a monster spawned this tick is AI-updated **this same
  tick** (it immediately runs target selection because `target_id == 0`).
- The position history is recorded **after** AI movement and **before** collisions, so the snapshot
  reflects end-of-tick positions.
- AI is only run for **alive** monsters (`server_main.gd:522`, `monster_ai.gd:63-64`), so a dead
  monster's `DEATH` animation/flags persist unchanged into its final snapshot.

There is exactly one AI implementation and one state struct; archetypes differ only by **data**
(`MonsterDefinition`, loaded from JSON). The shipped catalogue has two archetypes: `toxic_slime`
(the only one the live spawner produces) and `target_dummy` (offline practice; AI profile
`stationary_dummy`).

---

## 2. Constants

### 2.1 Global constants (`client/scripts/shared/game_constants.gd`)

All distances/positions are world units (1 unit = 1 px at zoom 1); times are seconds; speeds are
units/second. Values are exact — do not round.

| Constant | Value | Unit | Source |
|---|---|---|---|
| `SERVER_TICK_RATE` | `30.0` | Hz | game_constants.gd:22 |
| `SERVER_TICK_INTERVAL` | `1.0 / 30.0` | s | game_constants.gd:25 |
| `PLAYER_SPEED` | `200.0` | u/s | game_constants.gd:53 |
| `PLAYER_SPRINT_SPEED` | `320.0` (= 200.0 × 1.6) | u/s | game_constants.gd:59 |
| `MAP_MIN` | `(-1000.0, -1000.0)` | u | game_constants.gd:177 |
| `MAP_MAX` | `(1000.0, 1000.0)` | u | game_constants.gd:180 |
| `PROJECTILE_SPEED` | `400.0` | u/s | game_constants.gd:329 |
| `PROJECTILE_MAX_DISTANCE` | `800.0` | u | game_constants.gd:332 |
| `PROJECTILE_RADIUS` | `8.0` | u | game_constants.gd:335 |
| `PROJECTILE_ENTITY_ID_START` / `_END` | `10000` / `29999` | — | game_constants.gd:339-340 |
| `PLAYER_HITBOX_RADIUS` | `16.0` | u | game_constants.gd:343 |
| `MONSTER_SPAWN_RATE` | `0.2` | monsters/s | game_constants.gd:379 |
| `MONSTER_MAX_COUNT` | `100` | monsters | game_constants.gd:382 |
| `MONSTER_ENTITY_ID_START` | `30000` | — | game_constants.gd:386 |
| `MONSTER_ENTITY_ID_END` | `39999` | — | game_constants.gd:387 |
| `MONSTER_VISIBILITY_RADIUS` | `300.0` | u | game_constants.gd:390 |
| `MONSTER_SPAWN_MIN_DISTANCE` | `320.0` | u | game_constants.gd:394 |
| `MONSTER_SPAWN_MAX_DISTANCE` | `450.0` | u | game_constants.gd:395 |
| `MONSTER_REGIONAL_SPAWN_RATIO` | `0.6` | fraction | game_constants.gd:399 |
| `MONSTER_SPAWN_REGION_COLUMNS` | `4` | — | game_constants.gd:402 |
| `MONSTER_SPAWN_REGION_ROWS` | `4` | — | game_constants.gd:403 |
| `MONSTER_SPAWN_REGION_SOFT_CAP` | `2` | monsters/region | game_constants.gd:406 |
| `MONSTER_SPAWN_REGION_CANDIDATES` | `8` | samples | game_constants.gd:409 |
| `MONSTER_SPAWN_ATTEMPTS` | `20` | attempts | game_constants.gd:412 |
| `MONSTER_HEALTH` | `50` | HP (int) | game_constants.gd:415 |
| `MONSTER_HITBOX_RADIUS` | `16.0` | u | game_constants.gd:418 |
| `MONSTER_SPAWN_SEPARATION` | `36.0` (= 16.0 × 2.25) | u | game_constants.gd:422 |
| `MONSTER_SPEED` | `120.0` | u/s | game_constants.gd:430 |
| `MONSTER_PROJECTILE_SPEED` | `300.0` | u/s | game_constants.gd:433 |
| `MONSTER_PROJECTILE_DAMAGE` | `10` | HP (int) | game_constants.gd:436 |
| `PLAYER_PROJECTILE_DAMAGE` | `25` | HP (int) | game_constants.gd:439 |
| `MONSTER_ATTACK_RANGE` | `200.0` | u | game_constants.gd:442 |
| `MONSTER_FLEE_DISTANCE` | `100.0` | u | game_constants.gd:445 |
| `MONSTER_PREFERRED_DISTANCE` | `150.0` | u | game_constants.gd:448 |
| `MONSTER_DETECTION_RANGE` | `650.0` | u | game_constants.gd:453 |
| `MONSTER_SHOOT_COOLDOWN` | `0.75` | s | game_constants.gd:456 |
| `MONSTER_ATTACK_DURATION` | `0.5` | s | game_constants.gd:459 |
| `MONSTER_AVOIDANCE_DISTANCE` | `50.0` | u | game_constants.gd:462 |
| `MONSTER_STEERING_RANDOMNESS` | `0.15` | factor | game_constants.gd:465 |
| `MONSTER_RETARGET_INTERVAL` | `1.0` | s | game_constants.gd:468 |
| `MONSTER_LOSE_INTEREST_DISTANCE` | `900.0` | u | game_constants.gd:471 |

Arena monster spawn anchors (`ARENA_MONSTER_SPAWNS`, game_constants.gd:213-226), 12 fixed points:

```
(-450,-800) (450,-800) (-900,-450) (900,-450) (-900,450) (900,450)
(-450,800) (450,800) (0,-500) (0,500) (-500,0) (500,0)
```

Arena obstacles (`ARENA_OBSTACLES`, game_constants.gd:480-502) — 16 axis-aligned rects
`Rect2(position, size)`; the monster AI and spawner collide against these (full list needed by
`sim_core` anyway; reproduced here for completeness):

```
(-20,-200, 40x160) (-20,40, 40x160) (-200,-20, 160x40) (40,-20, 160x40)        # center cross
(-700,-700, 150x30) (-700,-700, 30x150) (550,-700, 150x30) (670,-700, 30x150)  # NW/NE corners
(-700,670, 150x30) (-700,550, 30x150) (550,670, 150x30) (670,550, 30x150)      # SW/SE corners
(-450,-350, 100x25) (350,-350, 100x25) (-450,325, 100x25) (350,325, 100x25)    # mid barriers
```

### 2.2 Runtime configuration / export defaults

| Setting | Live default | Source |
|---|---|---|
| `monster_spawn_rate` (export var on ServerMain) | `GameConstants.MONSTER_SPAWN_RATE * 2.0` = **`0.4` monsters/s** (1 per 2.5 s = 75 ticks) | server_main.gd:11-13 |
| → export range metadata | `0.05 .. 5.0` step `0.05` (editor-only; does not clamp at runtime) | server_main.gd:12 |
| → spawner floor | spawner clamps to `maxf(rate, 0.01)` | monster_spawner.gd:40 |
| `monster_ai_difficulty` (server_config.json key) | `0.85`, clamped `0.0..1.0` on read | server_config.gd:49, 96-97 |
| `MonsterAI._init` difficulty default | `0.85`, clamped `0.0..1.0` | monster_ai.gd:35-38 |
| `MonsterSpawner.enabled` | `true` | monster_spawner.gd:26 |
| `MonsterManager.POSITION_HISTORY_TICKS` | `8` | monster_manager.gd:38 |
| `MonsterDatabase.DEFAULT_MONSTER_ID` | `"toxic_slime"` | monster_database.gd:17 |

> **Spawn-rate trap:** the canonical constant is 0.2/s but the **live** rate is 0.4/s because the
> `ServerMain` export default doubles it. There is no JSON override. The Rust port must reproduce
> the live 0.4/s.

### 2.3 Monster archetype data (the database)

`MonsterDefinition` fields, their GDScript-side defaults (which exactly equal the Toxic Slime JSON
— behaviour-preserving), and the `target_dummy` values. Defaults at
`monster_definition.gd:17-62`; JSON at `client/data/monsters/*.json`.

| Field | Type | Default / `toxic_slime` | `target_dummy` |
|---|---|---|---|
| `id` | string | `"toxic_slime"` | `"target_dummy"` |
| `display_name` | string | `"Toxic Slime"` | `"Target Dummy"` |
| `archetype` | string | `"ranged_grunt"` | `"practice_dummy"` |
| `faction` | string | `"hostile_fauna"` | `"training_construct"` |
| `tier` | int | `1` | `0` |
| `ai_profile` | string | `"ranged_kiter"` | `"stationary_dummy"` |
| `max_health` | int | `50` | `100` |
| `move_speed` | float | `120.0` | `0.0` |
| `hitbox_radius` | float | `16.0` | `18.0` |
| `detection_range` | float | `650.0` | `0.0` |
| `lose_interest_range` | float | `900.0` | `0.0` |
| `retarget_interval` | float | `1.0` | `999.0` |
| `leash_range` | float | `0.0` (**unused** — roadmap, never read by AI) | `0.0` |
| `attack_range` | float | `200.0` | `0.0` |
| `flee_distance` | float | `100.0` | `0.0` |
| `preferred_distance` | float | `150.0` | `0.0` |
| `shoot_cooldown` | float | `0.75` | `999.0` |
| `attack_duration` | float | `0.5` | `0.0` |
| `projectile_speed` | float | `300.0` | `0.0` |
| `projectile_damage` | int | `10` (**not used for live damage** — see §6.4) | `0` |
| `steering_randomness` | float | `0.15` | `0.0` |
| `avoidance_distance` | float | `50.0` | `0.0` |
| `core_color` | color | `#5fbf3f` = `(0.372549, 0.749020, 0.247059)` | `#c18b3f` |
| `glow_color` | color | `#aaff33` = `(0.666667, 1.0, 0.2)` | `#ffd16a` |
| `shell_color` | color | `#16240c` = `(0.086275, 0.141176, 0.047059)` | `#4d2511` |
| `abilities` / `loot` / `spawn` / `raw` | array/dict | preserved verbatim from JSON, **never read by the runtime** | — |

**XP / score / loot:** `toxic_slime.json` declares `loot.xp = 10` but the runtime **never consumes
it** (`monster_definition.gd:64-68` "Not yet consumed by the runtime"). The only progression effect
of killing a monster today is `killer.monster_kills += 1` on the killing player's state
(`server_collision_handler.gd:127-129`). There is **no XP system and no score value granted** —
do not invent one in the port.

JSON parsing rules (`monster_definition.gd:83-191`):
- Numbers: a key is accepted if the JSON value is float **or** int; `_get_float` casts to float,
  `_get_int` casts to int (Godot's `int(float)` **truncates toward zero**). Missing/wrong-typed
  keys keep the GameConstants-backed defaults.
- Strings: accepted only if a **non-empty** string; otherwise default kept.
- Colors: accepted as `#rrggbb` string via `Color.from_string`, fall back to default.
- Sections are nested dictionaries: `stats`, `perception`, `combat`, `movement`, `appearance`.
- `id` falls back to the filename (without `.json`) if the JSON omits it.

Database loading (`monster_database.gd:37-99`): ids come from `data/monsters/index.json`
(`{"monsters": ["toxic_slime", "target_dummy"]}`) plus any extra `*.json` discovered on disk;
duplicates skipped; a built-in default `toxic_slime` definition is inserted if missing; unknown id
lookups warn and return the default definition (never null). For the Rust port, embedding the two
shipped JSON files (or their parsed values) is sufficient; preserve the "unknown id → default"
fallback.

### 2.4 Difficulty-scaled effective values

`MonsterAI` scales per-definition base ranges by the global `difficulty` (`d`, default 0.85) via
**unclamped linear interpolation** `lerpf(a, b, t) = a + (b - a) * t` (monster_ai.gd:178-203):

| Helper | Formula | Effective @ d=0.85, toxic_slime |
|---|---|---|
| `_get_retarget_interval(def)` | `lerp(def.retarget_interval * 1.35, 0.28, d)` | `0.4405` s |
| `_get_detection_range(def)` | `lerp(def.detection_range * 0.8, def.lose_interest_range, d)` | `843.0` u |
| `_get_lose_interest_distance(def)` | `lerp(def.lose_interest_range * 0.85, def.lose_interest_range * 1.25, d)` | `1071.0` u |
| `_get_attack_range(def)` | `lerp(def.attack_range, min(PROJECTILE_MAX_DISTANCE * 0.72, 540.0), d)` — the min is `min(576.0, 540.0) = 540.0` | `489.0` u |
| `_get_flee_distance(def)` | `lerp(def.flee_distance * 0.75, def.flee_distance * 1.75, d)` | `160.0` u |
| `_get_preferred_distance(def)` | `lerp(def.preferred_distance, 340.0, d)` | `311.5` u |

Other difficulty couplings (formulas in §4):
steering randomness multiplier `lerp(1.25, 0.35, d)` (= `0.485` @ 0.85); steering refresh upper
bound `lerp(1.5, 0.8, d)` (= `0.905` @ 0.85); attack-state flee factor `0.75 + d*0.25`; strafe
weight `0.75 + d*0.45`; flee strafe bias `0.25 + d*0.45`; retreat radial `0.85 + d*0.35`; approach
radial `0.25 + d*0.25`; target stickiness `18 * (0.5 + d*0.5)`; max aim error `(1 - d) * 0.22` rad.

### 2.5 Protocol-facing constants (`client/scripts/shared/networking/packet_types.gd`)

| Constant | Value | Source |
|---|---|---|
| `EntityType.MONSTER` | `2` | packet_types.gd:36-40 |
| `AnimationState`: `IDLE`=0, `WALK`=1, `RUN`=2, `ATTACK`=3, `HIT`=4, `DEATH`=5, `SPAWN`=6 | u8 | packet_types.gd:43-51 |
| `ENTITY_FLAG_ALIVE` | `1` (bit 0) | packet_types.gd:67 |
| `ENTITY_FLAG_MOVING` | `2` (bit 1) | packet_types.gd:68 |
| `ENTITY_FLAG_ATTACKING` | `4` (bit 2) | packet_types.gd:69 |
| `ENTITY_FLAG_VISIBLE` | `32` (bit 5) | packet_types.gd:72 |
| `GameEventType.DAMAGE` | `1` | packet_types.gd:97 |
| `GameEventType.KILL` | `2` | packet_types.gd:98 |
| `GameEventType.PROJECTILE_FIRED` | `12` | packet_types.gd:108 |

---

## 3. Data structures

### 3.1 `MonsterState` (`monster_state.gd:8-70`) — one per live monster

| Field | Type | Initial value (via `create_from_definition`) | Valid range / notes |
|---|---|---|---|
| `entity_id` | int | allocated id | `30000..=39999` |
| `type_id` | string | `definition.id` | catalogue key |
| `definition` | ref to `MonsterDefinition` | the archetype definition (never null after factory) | — |
| `position` | Vector2 (f32 components) | spawn position | inside `MAP_MIN..MAP_MAX` (enforced by movement) |
| `health` | int | `definition.max_health` | `0..=max_health` |
| `max_health` | int | `definition.max_health` | > 0 |
| `is_alive` | bool | `true` | — |
| `spawn_time` | float | `0.0` | **always 0.0 — never written, dead field** |
| `animation_state` | int (u8 on wire) | `AnimationState.IDLE` (0) | 0..6 |
| `entity_flags` | int (u8 on wire) | `ENTITY_FLAG_ALIVE \| ENTITY_FLAG_VISIBLE` = `33` | bitfield |
| `ai_state` | int | `0` (IDLE) | 0=IDLE 1=CHASE 2=ATTACK 3=FLEE |
| `target_id` | int | `0` | 0 = no target, else a player entity id (1–999) |
| `shoot_cooldown` | float | `0.0` | ≥ 0 (clamped in `update_timers`) |
| `last_fired_projectile_id` | int | `0` | projectile entity id of the most recent shot; 0 = none |
| `attack_timer` | float | `0.0` | ≥ 0 (clamped) |
| `retarget_timer` | float | `0.0` | grows unbounded until reset |
| `move_direction` | Vector2 | `(0,0)` | normalized or zero |
| `steering_offset` | Vector2 | `(0,0)` | normalized random direction |
| `steering_timer` | float | `0.0` | **may go negative** (decremented without clamp) |

Note: there is also a legacy `MonsterState.create(entity_id, position, health=50)`
(monster_state.gd:75-87) that uses the built-in default definition; the live spawn path is
`create_from_definition` via the factory. If `p_definition` is null, `create_from_definition`
substitutes `MonsterDefinition.default()` (monster_state.gd:93).

### 3.2 `MonsterManager` (`monster_manager.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `monsters` | Dictionary `entity_id -> MonsterState` | empty | insertion-ordered iteration (GDScript Dictionaries preserve insertion order; no algorithm below depends on order except documented tie-breaks) |
| `_next_entity_id` | int | `30000` | monotonic with wraparound to 30000 after 39999 |
| `_position_history` | Dictionary `server_tick -> Array[MonsterPositionSnapshot]` | empty | lag-comp |
| `_position_history_ticks` | Array[int] | empty | FIFO of recorded tick numbers, max len 8 |

`MonsterPositionSnapshot` (`monster_manager.gd:8-18`): `{ entity_id: int, position: Vector2,
is_alive: bool }` — `is_alive` is always `true` at creation (only alive monsters are recorded).

### 3.3 `MonsterSpawner` (`monster_spawner.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `spawn_rate` | float | `maxf(initial_rate, 0.01)`; live initial = 0.4 | monsters/s |
| `_spawn_timer` | float | `0.0` | accumulator, carries remainder across ticks |
| `_director_time` | float | `0.0` | grows by delta every enabled update |
| `_regions` | Array of 16 dicts | built in `_init` | `{ index: int 0..15, rect: Rect2, last_player_time: float = -9999.0, player_count: int = 0 }` |
| `enabled` | bool | `true` | — |

Region grid (`_build_spawn_regions`, monster_spawner.gd:172-194): 4×4 cells over the 2000×2000
map, each `500×500` u; `index = y * 4 + x`, row-major from `MAP_MIN`.

### 3.4 `MonsterAI` (`monster_ai.gd`)

Stateless apart from injected refs and `difficulty: float` (clamped 0..1 at construction). All
mutable AI state lives on `MonsterState`.

---

## 4. Algorithms

All pseudocode below is language-neutral. `lerp(a,b,t) = a + (b-a)*t` (unclamped).
`clamp(v,lo,hi)`. `normalize(v)` returns the **zero vector when |v| == 0** (Godot
`Vector2.normalized()` semantics). `is_zero_approx(v)` is true when `|v.x| < 1e-5 && |v.y| < 1e-5`
(Godot `CMP_EPSILON = 0.00001`). RNG calls (`randf`, `randi`, `randf_range`) use Godot's **global,
randomly-seeded** PCG32 — outputs are intentionally non-deterministic (see §7).

### 4.1 Per-tick AI driver — `MonsterAI.update_all` (monster_ai.gd:49-57) and `_update_monster` (monster_ai.gd:62-98)

```
update_all(monsters: list of alive MonsterState, delta) -> fire_events:
  fire_events = []
  for monster in monsters (registry insertion order):
    if _update_monster(monster, delta):                 # true iff it fired this tick
      fire_events.push({ source_id: monster.entity_id,
                         projectile_id: monster.last_fired_projectile_id })
  return fire_events

_update_monster(monster, delta) -> fired:
  if not monster.is_alive: return false                 # (defensive; caller already filters)

  if monster.definition.ai_profile == "stationary_dummy":
      _process_stationary_dummy(monster, delta); return false   # see 4.2

  monster.update_timers(delta)                          # see 4.3

  # Retarget: immediately while target-less, else on cadence
  if monster.target_id == 0
     or monster.retarget_timer >= _get_retarget_interval(monster.definition):
      monster.retarget_timer = 0.0
      _select_target(monster)                           # see 4.4

  if monster.steering_timer <= 0.0:
      _update_steering_offset(monster)                  # see 4.8

  fired = false
  switch monster.ai_state:
    IDLE:   _process_idle_state(monster)                # 4.6a
    CHASE:  _process_chase_state(monster, delta)        # 4.6b
    ATTACK: fired = _process_attack_state(monster, delta)  # 4.6c
    FLEE:   _process_flee_state(monster, delta)         # 4.6d

  _update_animation(monster)                            # 4.12
  return fired
```

### 4.2 Stationary dummy — `_process_stationary_dummy` (monster_ai.gd:101-108)

Runs every tick instead of the state machine for `ai_profile == "stationary_dummy"`:

```
monster.update_timers(delta)
monster.target_id = 0
monster.move_direction = (0,0)
monster.ai_state = IDLE
monster.entity_flags &= ~MOVING; monster.entity_flags &= ~ATTACKING
monster.animation_state = IDLE
```

(Position never changes; HIT/DEATH animations set by damage are overwritten back to IDLE on the
next AI tick while alive.)

### 4.3 Timers — `MonsterState.update_timers` (monster_state.gd:145-151)

Exact order:

```
if shoot_cooldown > 0:  shoot_cooldown = max(0, shoot_cooldown - delta)
if attack_timer  > 0:  attack_timer  = max(0, attack_timer  - delta)
retarget_timer += delta
steering_timer -= delta          # NOT clamped; goes negative
```

`can_shoot()` = `is_alive && shoot_cooldown <= 0.0` (monster_state.gd:135-136).
`start_shoot_cooldown()` sets `shoot_cooldown = definition.shoot_cooldown` (falls back to the
global `0.75` only if `definition` is null) (monster_state.gd:140-141).
Tick quantization: with cooldown 0.75 s at 30 Hz the monster actually fires every **23 ticks**
(0.7667 s), because the cooldown reaches 0 only after 23 decrements of 1/30.

### 4.4 Target selection — `_select_target` (monster_ai.gd:116-145)

```
players = player_manager.get_alive_players()
if players empty:
    monster.target_id = 0; transition(IDLE); return

best_player = null; best_score = -INF
for player in players:
    score = _score_target(monster, player)              # 4.5; can be -INF
    if score > best_score: best_score = score; best_player = player

if best_player == null: return        # all scored -INF (strict '>' vs -INF fails)
                                      # → KEEPS the current target_id unchanged!

dist_sq = |best_player.position - monster.position|²
detection = _get_detection_range(def); lose = _get_lose_interest_distance(def)
if dist_sq <= detection²:
    monster.target_id = best_player.entity_id
elif dist_sq > lose²:
    monster.target_id = 0; transition(IDLE)             # effectively DEAD CODE — see §5.3
# else (between detection and lose): target unchanged (hysteresis band)
```

### 4.5 Threat score — `_score_target` (monster_ai.gd:149-164)

```
if player == null or not player.is_alive: return -INF
distance = |monster.position - player.position|
if distance > _get_lose_interest_distance(def): return -INF

distance_score  = clamp(1 - distance / _get_detection_range(def), 0, 1) * 45.0
close_threat    = clamp(1 - distance / max(1.0, _get_attack_range(def)), 0, 1) * 25.0
movement_threat = clamp(|player.velocity| / 320.0, 0, 1) * 10.0      # PLAYER_SPRINT_SPEED
shooting_threat = 18.0 if player.is_shoot_held() else 0.0            # input SHOOT bit held
weakened_bonus  = clamp(1 - player.health / max(1.0, player.max_health), 0, 1) * 8.0
stickiness      = 18.0 * (0.5 + difficulty * 0.5)  if player.entity_id == monster.target_id else 0.0

return 35.0 + distance_score + close_threat + movement_threat
            + shooting_threat + weakened_bonus + stickiness
```

`player.is_shoot_held()` = `(player.input_flags & INPUT_FLAG_SHOOT) != 0` (player_state.gd:199-200,
`INPUT_FLAG_SHOOT = 1<<4`). Note `_get_detection_range` appears as a **divisor with no guard**
(§5.6). `_get_target` (monster_ai.gd:168-171) returns null when `target_id == 0` or the player is
no longer registered.

### 4.6 State machine (monster_ai.gd:211-321)

State transitions all go through `_transition_to_state(monster, new)` (monster_ai.gd:325-349):

```
if monster.ai_state == new: return        # no re-entry side effects
monster.ai_state = new
switch new:
  ATTACK:        monster.attack_timer = 0.0; flags |= ATTACKING
  IDLE:          monster.move_direction = (0,0); flags &= ~MOVING; flags &= ~ATTACKING
  CHASE, FLEE:   flags &= ~ATTACKING
```

(MOVING is only set/cleared by `_move_monster` / IDLE / stationary dummy / death.)

**(a) IDLE — `_process_idle_state` (monster_ai.gd:211-219).**

```
monster.move_direction = (0,0); flags &= ~MOVING
if monster.target_id != 0:
    target = _get_target(monster)
    if target != null and target.is_alive: transition(CHASE)
```

**(b) CHASE — `_process_chase_state` (monster_ai.gd:223-248).**

```
target = _get_target(monster)
if target null or dead: target_id = 0; transition(IDLE); return

to_target = target.position - monster.position
distance  = |to_target|

if distance < _get_flee_distance(def):    transition(FLEE);   return
if distance <= _get_attack_range(def):    transition(ATTACK); return

monster.move_direction = _apply_steering(monster, normalize(to_target))   # 4.7
_move_monster(monster, delta)                                             # 4.9
```

**(c) ATTACK — `_process_attack_state` (monster_ai.gd:253-293).** Returns `fired`.

```
target = _get_target(monster)
if target null or dead: target_id = 0; transition(IDLE); return false

to_target = target.position - monster.position; distance = |to_target|

if distance < _get_flee_distance(def) * (0.75 + difficulty * 0.25):
    transition(FLEE); return false
if distance > _get_attack_range(def) * 1.2:        # hysteresis vs the entry '<= range'
    transition(CHASE); return false

# kite/strafe while attacking (still moves!)
desired = _combat_move_direction(monster, target, distance)               # 4.10
monster.move_direction = _apply_steering(monster, desired)
_move_monster(monster, delta)

fired = false
if monster.can_shoot():
    fired = _spawn_monster_projectile(monster,
                _predictive_aim_direction(monster, target))               # 4.11
    if fired:
        monster.start_shoot_cooldown()                  # cooldown = def.shoot_cooldown
        monster.attack_timer = def.attack_duration      # 0.5 s

# after the attack window, consider resuming chase
if monster.attack_timer <= 0.0 and monster.shoot_cooldown <= 0.0:
    if distance > _get_attack_range(def):
        transition(CHASE)
return fired
```

**(d) FLEE — `_process_flee_state` (monster_ai.gd:297-321).**

```
target = _get_target(monster)
if target null or dead: target_id = 0; transition(IDLE); return

to_target = target.position - monster.position; distance = |to_target|

if distance >= _get_preferred_distance(def):
    transition(ATTACK if distance <= _get_attack_range(def) else CHASE); return

flee_direction = -normalize(to_target)                   # ZERO if to_target ~ 0
strafe = perp(flee_direction) * _get_strafe_sign(monster)
        where perp(v) = (-v.y, v.x)
monster.move_direction = _apply_steering(monster,
        normalize(flee_direction + strafe * (0.25 + difficulty * 0.45)))
_move_monster(monster, delta)
```

### 4.7 Steering — `_apply_steering` (monster_ai.gd:357-377)

```
if is_zero_approx(desired): return (0,0)

randomness = def.steering_randomness * lerp(1.25, 0.35, difficulty)
steered = desired + monster.steering_offset * randomness    # NOT normalized yet

# boundary reflection on a lookahead probe
future = monster.position + steered * def.avoidance_distance
if future outside MAP bounds (point test, inclusive: x in [-1000,1000], y likewise):
    if future.x < -1000 or future.x > 1000: steered.x *= -1
    if future.y < -1000 or future.y > 1000: steered.y *= -1

if circle_intersects_obstacle(future, def.hitbox_radius):       # see 4.13
    steered = _find_clear_steering_direction(monster, normalize(steered))

return normalize(steered)
```

`_find_clear_steering_direction` (monster_ai.gd:381-393):

```
best_direction = -desired; best_clearance = -1.0
for offset in [+PI/4, -PI/4, +PI/2, -PI/2, PI]:          # exact order
    candidate = normalize(rotate(desired, offset))       # Godot rotated(): CCW in math coords
    probe = monster.position + candidate * def.avoidance_distance
    clearance = 0.0 if circle_intersects_obstacle(probe, def.hitbox_radius) else 1.0
    clearance += clamp(|probe - monster.position| / def.avoidance_distance, 0, 1)
                 # = +1.0 always (probe distance == avoidance_distance), EXCEPT
                 # division-by-zero if avoidance_distance == 0 → NaN (§5.6)
    if clearance > best_clearance: best_clearance = clearance; best_direction = candidate
return best_direction
```

Rotation formula (Godot `Vector2.rotated(phi)`):
`(x*cos(phi) - y*sin(phi), x*sin(phi) + y*cos(phi))`.

### 4.8 Steering offset refresh — `_update_steering_offset` (monster_ai.gd:397-402)

When `steering_timer <= 0`:

```
monster.steering_offset = normalize( (randf_range(-1,1), randf_range(-1,1)) )
       # NOTE: if both samples are exactly 0 (probability ~0), offset = (0,0)
monster.steering_timer  = randf_range(0.35, lerp(1.5, 0.8, difficulty))   # 0.35..0.905 @ d=0.85
```

### 4.9 Movement — `_move_monster` (monster_ai.gd:406-422)

```
if is_zero_approx(monster.move_direction): flags &= ~MOVING; return

velocity = monster.move_direction * def.move_speed
new_position = monster.position + velocity * delta
monster.position = move_with_obstacle_collision(monster.position, new_position,
                                                def.hitbox_radius)        # see 4.13
flags |= MOVING
```

### 4.10 Combat strafe — `_combat_move_direction` (monster_ai.gd:430-446) and `_get_strafe_sign` (monster_ai.gd:449-451)

```
to_target = target.position - monster.position
if is_zero_approx(to_target): return (0,0)

toward = normalize(to_target); away = -toward
strafe = perp(toward) * _get_strafe_sign(monster)         # perp(v) = (-v.y, v.x)
preferred = _get_preferred_distance(def)

radial = (0,0)
if   distance < preferred * 0.82: radial = away   * (0.85 + difficulty * 0.35)
elif distance > preferred * 1.18: radial = toward * (0.25 + difficulty * 0.25)

return normalize( strafe * (0.75 + difficulty * 0.45) + radial )
```

```
_get_strafe_sign(monster):
    phase = (engine_uptime_ms / 1400) + monster.entity_id   # INTEGER division of ms
    return +1.0 if phase % 2 == 0 else -1.0
```

`engine_uptime_ms` is Godot `Time.get_ticks_msec()` — **wall-clock milliseconds since process
start**, not tick-derived (§7). `%` on positive ints; both operands are always positive here.

### 4.11 Shooting

**Predictive aim — `_predictive_aim_direction` (monster_ai.gd:455-471).**

```
predicted = _predict_target_position(monster.position, target.position,
                                     target.velocity, def.projectile_speed)
direction = predicted - monster.position
if is_zero_approx(direction): direction = target.position - monster.position
if is_zero_approx(direction): direction = (1, 0)          # Vector2.RIGHT

max_error = (1.0 - difficulty) * 0.22                     # radians; 0.033 @ d=0.85
if max_error > 0.001:
    direction = rotate(direction, randf_range(-max_error, +max_error))
return normalize(direction)
```

**Intercept solve — `_predict_target_position` (monster_ai.gd:474-501).** Standard
projectile-intercept quadratic with these exact branches:

```
relative = target_position - origin
a = |target_velocity|² - projectile_speed²
b = 2 * dot(relative, target_velocity)
c = |relative|²
t = |relative| / max(1.0, projectile_speed)               # default fallback lead time

if |a| < 0.0001:                                          # near-linear case
    if |b| > 0.0001:
        linear_t = -c / b
        if linear_t > 0: t = linear_t
else:
    disc = b*b - 4*a*c
    if disc >= 0:
        root = sqrt(disc)
        t1 = (-b - root) / (2a); t2 = (-b + root) / (2a)
        best = +INF
        if t1 > 0: best = min(best, t1)
        if t2 > 0: best = min(best, t2)
        if best < +INF: t = best

t = clamp(t, 0.0, 2.0)                                    # lead capped at 2 seconds
return target_position + target_velocity * t
```

**Projectile spawn — `_spawn_monster_projectile` (monster_ai.gd:505-534).**

```
if projectile_manager == null: return false

spawn_offset   = direction * (def.hitbox_radius + PROJECTILE_RADIUS + 2.0)
                 # toxic_slime: 16 + 8 + 2 = 26 units in front
spawn_position = monster.position + spawn_offset

projectile = projectile_manager.spawn_projectile(monster.entity_id,   # owner = monster id
                                                 spawn_position, direction)
                 # remaining args default: spawn_tick=0, rewind=0, no lag comp
if projectile == null: return false

projectile.speed = def.projectile_speed       # OVERRIDE: created at 400.0, set to 300.0
                                              # before its first integration next tick
monster.last_fired_projectile_id = projectile.entity_id
return true
```

`spawn_projectile` rejects a zero-approx direction (returns null) and allocates from the projectile
range 10000–29999 (projectile_manager.gd:25-90); direction here is always normalized non-zero.
Monster-owned projectiles are identified everywhere by `owner_id >= 30000`.

### 4.12 Animation sync — `_update_animation` (monster_ai.gd:538-548)

After state processing, while alive: `IDLE→IDLE(0)`, `CHASE/FLEE→WALK(1)`, `ATTACK→ATTACK(3)`.
This runs every AI tick and therefore **overwrites** the `HIT(4)` animation set by damage on the
next tick. Dead monsters keep `DEATH(5)` (AI skips them).

### 4.13 Shared collision helpers used by monsters (in `sim_core` per D5)

From `game_constants.gd` — observable behavior, engine-independent (pure math, no Godot physics —
monsters never use `move_and_slide`):

- `is_within_bounds(p)` (242-244): `p.x ∈ [-1000, 1000] && p.y ∈ [-1000, 1000]` (inclusive).
- `clamp_to_bounds(p)` (234-238): per-component clamp to the same box.
- `circle_intersects_obstacle(center, radius)` (514-520): for each obstacle rect, expand by
  `radius` on all four sides and test `expanded.has_point(center)`. Godot `Rect2.has_point` is
  **half-open**: `p >= pos && p < pos + size` (left/top edges inclusive, right/bottom exclusive).
  Note this is a *square* expansion — circles collide with expanded rect **corners** as if they
  were squares (no corner rounding). Port this exactly; do not "fix" it to a true circle-rect test.
- `move_with_obstacle_collision(from, to, radius)` (525-544): axis-separated sliding:

```
target = clamp_to_bounds(to)
if not movement_hits_obstacle(from, target, radius): return target
x_target = clamp_to_bounds((target.x, from.y))
y_target = clamp_to_bounds((from.x, target.y))
best = from; best_d = |from - target|²
if not movement_hits_obstacle(from, x_target, radius): best = x_target; best_d = |x_target - target|²
if not movement_hits_obstacle(from, y_target, radius):
    if |y_target - target|² < best_d: best = y_target
return best                       # 'from' if both axes blocked (full stop)
```

- `_movement_hits_obstacle(from, to, radius)` (548-559): if `from ≈ to` (Godot
  `is_equal_approx`, component tolerance ~1e-5 relative), return `circle_intersects_obstacle(to,
  radius)`. Otherwise for each obstacle: expanded-rect `has_point(to)` OR segment-vs-expanded-rect
  intersection (slab method `_line_rect_intersection`, 593-632, with `abs(dir.axis) < 0.0001`
  treated as axis-parallel) → blocked.

### 4.14 Spawner cadence — `MonsterSpawner.update` (monster_spawner.gd:46-74)

Called once per tick with `delta = tick_interval`:

```
if not enabled: return
if monster_manager == null or player_manager == null: return

_director_time += delta
_update_region_player_state()                       # 4.16

if alive_monster_count >= 100: return               # accumulator PAUSED at cap (no burst later)

_spawn_timer += delta
spawn_interval = 1.0 / spawn_rate                   # 2.5 s live
while _spawn_timer >= spawn_interval:
    _spawn_timer -= spawn_interval
    if alive_monster_count >= 100: break
    _try_spawn_monster()                            # failure to place ⇒ that spawn is lost
```

`_try_spawn_monster` (78-86): `position = _select_spawn_position()`; if it is the sentinel
`Vector2.INF` (= `(+inf, +inf)`, compared with exact `==`), no spawn; else
`monster_manager.spawn_monster(position)` (default type `"toxic_slime"`).

### 4.15 Spawn placement — `_select_spawn_position` (monster_spawner.gd:90-116)

```
if no alive players: return INF                     # no spawning on an empty server

# Layer 0: fixed anchors
p = _select_anchor_spawn_position(); if p != INF: return p

# Budget split between the two procedural layers
regional_budget  = clamp(round(100 * 0.6), 0, 100)  = 60
encounter_budget = 100 - 60                         = 40
counts = _count_alive_monsters_by_layer()           # 4.17
regional_deficit  = 60 - counts.regional
encounter_deficit = 40 - counts.encounter

prefer_regional = regional_deficit > encounter_deficit
if regional_deficit > 0 and encounter_deficit > 0:
    prefer_regional = (randf() < 0.6)               # MONSTER_REGIONAL_SPAWN_RATIO

primary = regional layer if prefer_regional else encounter layer
if primary != INF: return primary
return the OTHER layer's attempt (may also be INF → spawn skipped)
```

**Anchors** (`_select_anchor_spawn_position`, 120-131): take
`get_valid_monster_spawns()` — the 12 static anchors filtered by
`is_circle_within_bounds(p, 16.0) && !circle_intersects_obstacle(p, 16.0)` (game_constants.gd:
301-321; all 12 shipped anchors pass). Pick `start = randi() % n`, scan all `n` with wraparound,
return the first passing `_is_valid_spawn_position` (4.18); else INF.

**Encounter layer** (`_select_encounter_spawn_position`, 135-152): up to **20** attempts
(`MONSTER_SPAWN_ATTEMPTS`); each attempt:

```
target_player = alive_players[randi() % count]      # uniform random player
angle    = randf() * TAU
distance = randf_range(320.0, 450.0)
position = target_player.position + (cos(angle), sin(angle)) * distance
if _is_valid_spawn_position(position): return position
```

**Regional layer** (`_select_regional_spawn_position`, 156-168): rank the 16 regions
(4.16), then for each region in rank order sample up to **8** uniform random points in its rect
(`randf_range` per axis over `[rect.pos, rect.pos+size]`); first valid point wins; all-fail → INF.

### 4.16 Region bookkeeping and ranking (monster_spawner.gd:198-299)

`_update_region_player_state` (198-209): zero every region's `player_count`; for each **alive**
player, find its region (`_get_region_index_for_position`, 342-359: out-of-bounds → −1 → skip;
`x = clamp(floor(rel.x / 2000 * 4), 0, 3)`, same for y; `index = y*4 + x`), increment
`player_count` and set `last_player_time = _director_time`.

`_count_alive_monsters_by_region` (213-220): same region indexing over alive monsters.

`_get_ranked_regions` (241-255): for each region compute
`score = _score_region(region) + randf()` (jitter), then sort **descending** by score; ties (Godot
`is_equal_approx` on floats: `|a-b| <= max(CMP_EPSILON*|a|, CMP_EPSILON)`) break ascending by
region index. (Godot `Array.sort_custom` is an **unstable** sort; with the explicit tie-break the
result is deterministic given scores.)

`_score_region` (259-274):

```
count = alive monsters in region
if count >= 2 (SOFT_CAP): return -1000.0 - count
target = min(2, 1 + region.player_count)
deficit = max(0, target - count)
time_since_visit = clamp(_director_time - region.last_player_time, 0, 120)
                   # last_player_time starts at -9999 → clamps to 120 for unvisited regions
return deficit * 100.0 + time_since_visit * 0.2 + player_count * 20.0 - count * 25.0
```

### 4.17 Layer classification — `_count_alive_monsters_by_layer` (monster_spawner.gd:224-237)

A monster counts as **encounter** if within `MONSTER_DETECTION_RANGE` (the global constant
`650.0`, **not** the difficulty-scaled value, **not** per-definition) of any alive player
(squared-distance compare, `<=`); else **regional**.

### 4.18 Spawn validity — `_is_valid_spawn_position` (monster_spawner.gd:303-316)

All four must hold, in this order (short-circuit):

1. `is_within_bounds(position)` — point test, inclusive.
2. `!circle_intersects_obstacle(position, 16.0)` — uses the **global**
   `MONSTER_HITBOX_RADIUS`, not the archetype's.
3. Not overlapping an existing monster: `_would_overlap_existing_monster` (320-329) — find the
   **closest alive** monster (`get_closest_alive_monster`, 4.20); fail if
   `dist² < 36.0²` (`MONSTER_SPAWN_SEPARATION`).
4. Not visible to any player: `_is_position_visible_to_players` (372-384) — for every **alive**
   player (iterates `get_all_players()` skipping dead), fail if `distance < 300.0`
   (`MONSTER_VISIBILITY_RADIUS`, strict `<`, non-squared `distance_to`).

### 4.19 Spawn registration — `MonsterManager.spawn_monster` (monster_manager.gd:55-71) and id allocation (75-86)

```
spawn_monster(position, type_id = "toxic_slime"):
    entity_id = _allocate_entity_id(); if entity_id < 0: warn; return null
    state = factory.create(type_id, entity_id, position)
            # = MonsterState.create_from_definition(entity_id, position,
            #       database.get_definition(type_id))    (monster_factory.gd:21-23)
    monsters[entity_id] = state
    return state

_allocate_entity_id():
    range_size = 39999 - 30000 + 1     # 10000
    repeat range_size times:
        candidate = _next_entity_id
        _next_entity_id += 1
        if _next_entity_id > 39999: _next_entity_id = 30000   # wraparound
        if candidate not in monsters: return candidate        # recycles freed ids
    return -1                                                 # all 10000 ids live
```

Note the cursor always advances even when the candidate is taken; freed ids are reused only after
the cursor wraps back around to them. A monster's id is freed at `remove_monster` (cleanup tick).

### 4.20 Registry queries (monster_manager.gd:101-185)

- `get_monster(id)` → state or null.
- `get_monster_count()` → all entries including dead-pending-cleanup;
  `get_alive_monster_count()` → only `is_alive`.
- `get_all_monsters()` / `get_alive_monsters()` → arrays in registry insertion order.
- `get_closest_alive_monster(position)` (172-185): linear scan of alive monsters, strict `<` on
  squared distance (first-encountered wins ties); null if none.

### 4.21 Position history for lag compensation (monster_manager.gd:137-168)

`record_position_snapshot(server_tick)` — called once per tick (step 4):

```
snapshot = [ {entity_id, position, is_alive: true} for each ALIVE monster ]
_position_history[server_tick] = snapshot
_position_history_ticks.push_back(server_tick)
while len(_position_history_ticks) > 8:
    old = _position_history_ticks.pop_front(); _position_history.erase(old)
```

`get_alive_monster_snapshot(server_tick)` — used by `ProjectileManager` PvE collision rewind:

```
if exact tick present: return it
best = max tick in history with tick <= server_tick
if best exists: return its snapshot
if history non-empty: return snapshot of _position_history_ticks[0]   # the OLDEST stored tick
return get_alive_monsters()        # empty history: fall back to LIVE MonsterState objects
```

The last fallback returns live `MonsterState`s, duck-typed against snapshots (the consumer reads
only `entity_id` / `position` / `is_alive`). In Rust, model the return as a common view
(id + position).

### 4.22 Damage, death, cleanup

`MonsterState.take_damage(amount) -> killed` (monster_state.gd:110-127):

```
if not is_alive or amount <= 0: return false
health = max(health - amount, 0)
if health == 0:
    is_alive = false
    move_direction = (0,0)
    flags &= ~ALIVE; flags &= ~MOVING; flags &= ~ATTACKING      # VISIBLE stays → flags = 32
    animation_state = DEATH (5)
    return true
animation_state = HIT (4)        # overwritten next AI tick while alive
return false
```

Caller (`ServerCollisionHandler._check_monster_collisions`, server_collision_handler.gd:94-144),
runs in tick step 5 over hits from `projectile_manager.check_collisions_with_monsters` (swept
segment vs lag-rewound monster position, collision distance `PROJECTILE_RADIUS +
MONSTER_HITBOX_RADIUS = 24.0`, strict `<`; only projectiles with `owner_id < 30000` test monsters):

```
for each hit { projectile_id, target_id, owner_id, position }:
    monster = get_monster(target_id); if null: continue
    killer  = player_manager.get_player_by_entity_id(owner_id)   # may be null (disconnected)
    killed  = monster.take_damage(25)                            # PLAYER_PROJECTILE_DAMAGE, flat
    damage_applied = previous_health - monster.health
    if damage_applied <= 0: continue
    broadcast GAME_EVENT DAMAGE { source: owner_id, target: target_id, amount: damage_applied }
    if killed:
        if killer != null and killer.authenticated: killer.monster_kills += 1
        broadcast GAME_EVENT KILL { source: owner_id, target: target_id }
```

A 50 HP slime dies to exactly **2** player hits. Dead monsters are erased at the end of the same
tick by `cleanup_dead_monsters` (monster_manager.gd:189-197): collect ids with `!is_alive`, then
remove each. The death-tick snapshot (step 6, if due) still contains the monster with
`flags = VISIBLE only (32)` and `animation = DEATH`; the **next** snapshot marks it removed via the
delta cache (`DELTA_MASK_REMOVED`) — that mechanism belongs to the broadcast subsystem.

**Monster damage TO players** does not go through this file: monster-projectile hits on a player
are client-detected and server-validated (`LOCAL_HIT_REPORT`, D11). When applied, the server uses
`apply_player_hit` (server_collision_handler.gd:42-91) which selects damage by owner range:
`owner_id >= 30000 → MONSTER_PROJECTILE_DAMAGE (10)`. The per-definition `projectile_damage` is
**ignored** for live damage (documented coupling, monster_definition.gd:48-51).

### 4.23 Fire-event broadcast (server_main.gd:517-559)

After `update_all` returns, for each fire event the server broadcasts to **all** clients:

```
GAME_EVENT / PROJECTILE_FIRED (event_type 12):
    source_id = monster entity id          (u16)
    target_id = projectile entity id       (u16)  — ALWAYS non-zero for monsters (D11 invariant)
    position  = Vector2.ZERO               (compressed vec2 — monsters do NOT send spawn pos)
    server_tick = 0                        (u16  — monsters do NOT send the tick)
```

Wire layout (game_event_packet.gd:140-160): `[u8 event_type][u16 source_id][u16 target_id]
[vector2_compressed position][u16 server_tick]`. Contrast: the **player** fire path calls the same
broadcast with real `spawn_position` and `tick_count` (server_main.gd:414); only the monster path
leaves them zero. Clients use `source_id`/`target_id` to attribute the projectile to a monster
for client-side incoming-hit detection; position/tick are unused on that path.

---

## 5. Edge cases & gotchas

1. **`Vector2.INF` sentinel.** Spawn-position selection uses `(+inf, +inf)` as "no position",
   compared with exact `==`/`!=`. Rust: use `Option<Vec2>` and keep the *semantics* (a failed
   placement consumes the spawn-interval slot — no retry until the accumulator next crosses the
   interval).
2. **Spawner accumulator pauses at the population cap** (monster_spawner.gd:57-61): when 100 are
   alive the early return happens *before* `_spawn_timer += delta`, so when monsters die there is
   no burst of catch-up spawns. `_director_time` and region player-state *do* still update.
3. **Lose-interest drop is effectively dead code.** `_score_target` returns `-INF` for any player
   beyond lose-interest distance, and `_select_target` early-returns (keeping the current
   `target_id`) when *every* player scored `-INF` (strict `>` against an initial best of `-INF`
   never selects). Therefore the `elif dist > lose_interest → drop target` branch can only trigger
   at exact floating-point boundary equality. **Observable behavior: once a monster has a target it
   never goes idle from distance alone** — it keeps chasing until the target dies, disconnects, or
   another player out-scores it within detection range. Port this behavior as-is (per D5/D12 the
   port must match observed behavior, not intent).
4. **Detection vs lose-interest hysteresis band.** If the best-scoring player is between
   `_get_detection_range` and `_get_lose_interest_distance`, the target is left unchanged (neither
   acquired nor dropped).
5. **Retarget cadence:** target-less monsters re-scan **every tick** (`target_id == 0` triggers the
   scan and also resets `retarget_timer`); targeted monsters re-scan every
   `_get_retarget_interval` (0.4405 s ≈ every 14 ticks at defaults). Comparison is `>=`.
6. **Division-by-zero hazards (unguarded — the port must decide, and should match):**
   - `_score_target` divides by `_get_detection_range(def)` with no guard. A definition with
     `detection_range = 0` *and* `lose_interest_range = 0` (e.g. `target_dummy` if it ever ran the
     scoring path) gives `0/0 → NaN` for a player at distance exactly 0 (any positive distance
     already returned `-INF` first). Unreachable for shipped data because `stationary_dummy`
     short-circuits, but reachable with bad JSON. GDScript float division by zero yields
     `±inf`/`NaN`, not a crash; `clampf(NaN, 0, 1)` in Godot returns NaN. Recommended port stance:
     replicate "garbage in, garbage out" or debug-assert; do NOT silently clamp.
   - `_find_clear_steering_direction` divides by `def.avoidance_distance`; zero ⇒ `0/0 = NaN`
     clearance. Same status: unreachable for shipped data, decide explicitly.
   - `_score_target` guards the *other* two divisors with `max(1.0, …)` (attack range, max
     health) — keep those guards exactly.
7. **Distance-0 flee deadlock (benign).** If a player stands exactly on a monster: CHASE sees
   `distance < flee` → FLEE; FLEE computes `flee_direction = normalize(zero) = (0,0)`, strafe
   `(0,0)`, `_apply_steering` returns `(0,0)` (zero-approx early-out), `_move_monster` early-outs
   and clears MOVING. The monster stands still (in FLEE) until the target moves. No NaN, no crash.
8. **Death/disconnect of target:** every non-idle state checks `_get_target` for null/dead at
   entry and transitions to IDLE with `target_id = 0`. PlayerManager removes disconnected players,
   so `_get_target` → null next tick.
9. **No players online:** spawner does nothing (placement requires ≥1 alive player); AI sets all
   monsters IDLE on their next retarget (empty alive-players list).
10. **Arena bounds behavior:** monsters never leave `[-1000,1000]²` — `move_with_obstacle_collision`
    clamps to bounds, and the steering probe reflects direction components near edges. Monsters do
    not collide with each other or with players; only obstacles and bounds constrain movement
    (spawn separation is checked only at spawn time).
11. **Id exhaustion:** all 10000 monster ids live ⇒ `_allocate_entity_id` returns −1 ⇒
    `spawn_monster` warns and returns null (spawner treats it as a skipped spawn). Unreachable
    while the 100-cap holds (dead monsters occupy ids at most one extra tick).
12. **Dead monsters and counts:** between death (step 5) and cleanup (step 7) a dead monster still
    counts in `get_monster_count()` (metrics) and appears in `collect_state_updates()` (its death
    snapshot) but not in alive counts, AI updates, position snapshots, or spawn-separation checks.
13. **`attack_timer` is set only when a shot actually fires** and decays in `update_timers`; the
    "resume chase" check at the bottom of ATTACK (`attack_timer <= 0 && shoot_cooldown <= 0 &&
    distance > attack_range`) is almost always pre-empted by the `distance > attack_range * 1.2`
    hysteresis exit at the top, but port it anyway — it can trigger when range drifts into the
    `(range, range*1.2]` band while both timers are zero (i.e. before the first shot in the
    state, since `_transition_to_state(ATTACK)` zeroes `attack_timer`).
14. **`HIT` animation lifetime:** set by non-lethal damage in step 5, survives into that tick's
    snapshot (step 6), overwritten by `_update_animation` in the next tick's step 3. `DEATH`
    persists because dead monsters skip AI.
15. **The spawner validates with the global 16.0 radius** even though an archetype may define a
    different `hitbox_radius` (target_dummy: 18.0). AI movement/avoidance use the per-definition
    radius. Keep this asymmetry.
16. **`steering_timer` may go arbitrarily negative** while a monster sits in IDLE? No — the refresh
    check `steering_timer <= 0` runs every tick for every alive monster regardless of state, so it
    resets within one tick of expiry. But the *first* tick after spawn always refreshes (timer
    starts 0.0).
17. **`spawn_time` is dead** (always 0.0). Do not wire it to anything.
18. **Client renders every monster as the default archetype** — the wire carries no monster type
    byte (monster.gd:34-37). If the port adds archetype to the wire it is a protocol change, not
    parity.

---

## 6. Cross-subsystem contracts

### 6.1 Provided to the tick loop (`server_main.gd`)

- `MonsterSpawner.update(delta: f32)` — call once per tick (step 2), `delta = 1/tick_rate`.
- `MonsterAI.update_all(monsters: &[MonsterState], delta: f32) -> Vec<FireEvent>` where
  `FireEvent { source_id: u16 /*monster*/, projectile_id: u16 /*non-zero*/ }` — step 3, fed with
  alive monsters only.
- `MonsterManager.record_position_snapshot(server_tick: u64)` — step 4 (after AI, before
  collisions).
- `MonsterManager.collect_state_updates() -> Vec<EntityData>` — step 6; per monster (including
  dead-pending-cleanup): `{ id: u16, type: 2 (MONSTER), position: Vec2, animation: u8,
  flags: u8 }` (monster_state.gd:155-162). This is the standard 9-byte full-state entity the
  snapshot/delta builder consumes.
- `MonsterManager.cleanup_dead_monsters()` — step 7, strictly after the broadcast step.
- `MonsterManager.clear_all()` — server shutdown/reset; also clears position history.
- `MonsterSpawner.reset()` — zero `_spawn_timer` and `_director_time`, reset all regions to
  `{last_player_time: -9999.0, player_count: 0}`.

### 6.2 Consumed from PlayerManager / PlayerState

- `get_alive_players() -> Vec<&PlayerState>`, `get_all_players()`,
  `get_player_by_entity_id(id) -> Option<&PlayerState>`.
- Per player the AI reads: `entity_id`, `position: Vec2`, `velocity: Vec2`
  (server-authoritative), `health: i32`, `max_health: i32`, `is_alive: bool`,
  `is_shoot_held() = input_flags & (1<<4) != 0`.

### 6.3 Consumed from ProjectileManager

- `spawn_projectile(owner_id, position, direction, …defaults) -> Option<&mut ProjectileState>`;
  monster path passes only the first three args; rejects zero-approx direction; allocates id in
  10000–29999. The created projectile has `speed = 400.0` which the AI immediately overrides to
  `definition.projectile_speed` (300.0) before the projectile's first movement update. In Rust,
  make speed a spawn parameter and pass the definition's value — same observable behavior since
  the override happens before any integration.

### 6.4 Provided to the collision/hit subsystem

- `get_alive_monster_snapshot(server_tick) -> impl Iterator<(entity_id, position)>` — PvE lag-comp
  rewind source (fallback chain in §4.21). Collision distance vs player projectiles:
  `8.0 + 16.0 = 24.0` (uses the global monster radius, not per-definition — note target_dummy's
  18.0 is ignored here too).
- `get_monster(id)`, `MonsterState.take_damage(amount)` (player projectile damage is the flat
  global `25`).
- `get_closest_alive_monster(position)` — spawn separation + fire diagnostics.
- Monster-owned projectiles must be skipped by the server's projectile-vs-player PvP pass and
  the projectile-vs-monster pass (`owner_id >= 30000` checks) — D11 carried invariant.
- Live monster→player damage value is the **global** `MONSTER_PROJECTILE_DAMAGE = 10` selected by
  owner-id range in `apply_player_hit`; `definition.projectile_damage` is canonical-but-unused.

### 6.5 Provided to the network layer

- `PROJECTILE_FIRED` game event per monster shot, broadcast to all peers, with the exact field
  semantics of §4.23 (monster path: zero position, zero tick, **non-zero projectile id**).
- `DAMAGE` / `KILL` game events on monster damage/death (§4.22) — emitted by the collision
  handler, not by monster code itself.
- Kill attribution side effect: `killer.monster_kills += 1` only when the killer is still
  connected and authenticated.

---

## 7. Rust port hazards (checklist)

- [ ] **RNG is global and unseeded.** `randf`/`randi`/`randf_range` (steering offset + period,
  aim error, anchor start index, encounter player/angle/distance, regional sampling, layer
  preference, region-rank jitter) use Godot's process-global randomly-seeded PCG32. Behavior is
  *stochastic by design* — trace-level parity is impossible and not required (D12 validates by
  play/load test). Port with one explicit RNG owned by the sim (seedable for tests); match the
  *distributions and call sites*, not the stream.
- [ ] **Wall-clock dependency in strafe sign.** `_get_strafe_sign` uses engine-uptime milliseconds
  (`Time.get_ticks_msec() / 1400`, integer division) + entity id, mod 2. It is frame/tick
  independent real time. Recommended port: derive from tick count (`(tick * 33) / 1400`-ish) or
  process uptime — pick one and note the divergence; the 1.4 s flip period and per-entity phase
  offset are the observable behavior.
- [ ] **Mixed float precision.** Godot `Vector2` components are **f32**; GDScript scalar floats
  (timers, scores, distances returned by `length()` etc.) are **f64** computed from f32 inputs.
  A pure-f32 Rust sim will diverge slightly. Monsters are not client-predicted, so small drift is
  invisible — but `sim_core` collision helpers (§4.13) are shared with *predicted* player movement;
  match precision there exactly (the same hazard exists in the players extraction).
- [ ] **Spawn rate is 0.4/s, not the 0.2/s constant** (ServerMain export doubles it,
  server_main.gd:13). Spawn interval 2.5 s; accumulator paused at the 100 cap; failed placement
  consumes the slot.
- [ ] **Difficulty lerp formulas** (§2.4) must be copied verbatim, including the magic factors
  `*1.35`, `0.28`, `*0.8`, `*0.85`, `*1.25`, `min(800*0.72, 540)`, `*0.75`, `*1.75`, `340.0`, and
  every `0.xx + difficulty * 0.yy` weight in §4. These are unclamped lerps over a clamped
  `difficulty ∈ [0,1]`.
- [ ] **`normalized()` on zero returns zero**, `is_zero_approx` epsilon is `1e-5`, `-INF` scoring
  sentinel with strict `>` comparison (drives the dead-code lose-interest behavior in §5.3 —
  preserve it).
- [ ] **`circle_intersects_obstacle` is a square-expanded rect test** (corners not rounded) and
  `Rect2.has_point` is half-open (min-edge inclusive, max-edge exclusive). `move_with_
  obstacle_collision` is axis-separated slide with squared-distance "best axis" choice and full
  stop when both axes blocked. Shared with players via `sim_core` (D5) — must be bit-faithful.
- [ ] **Monster projectile speed override** happens *after* spawn (400 → 300) but before first
  integration; the fire broadcast carries **position (0,0) and server_tick 0** on the monster path
  while the projectile id (target_id field) is always non-zero — D11 carried invariant, becomes a
  Rust-side test.
- [ ] **Per-definition `projectile_damage` is NOT the live damage.** Monster hits on players apply
  the flat global 10 (selected by `owner_id >= 30000`); player hits on monsters apply the flat
  global 25. `loot.xp` is parsed but never consumed; the only kill reward is
  `monster_kills += 1` on a still-connected authenticated killer.
- [ ] **Tick-order contract:** spawner → AI (same-tick AI for fresh spawns) → position-history
  record → collisions → snapshot → cleanup. Dead monsters get exactly one death snapshot; the
  HIT animation survives exactly one snapshot; position history records post-movement,
  pre-collision positions, depth 8 ticks, with the §4.21 fallback chain (including the
  live-state final fallback).
- [ ] **Id allocation:** monotonic cursor 30000→39999 with wraparound, skip-if-live, −1 when all
  10000 live; cursor advances even on skipped candidates; freed ids recycle only when the cursor
  comes back around.
- [ ] **Timer semantics:** `update_timers` order (§4.3); cooldown/attack clamped at 0,
  `retarget_timer` accumulates, `steering_timer` unclamped; `>=` vs `<=` comparisons as written;
  effective fire period quantizes to whole ticks (23 ticks @ 30 Hz for 0.75 s).
- [ ] **Division-by-zero is unguarded** in `_score_target` (detection range) and
  `_find_clear_steering_direction` (avoidance distance) — unreachable with shipped data; decide
  and document the Rust stance (recommend debug-assert) rather than silently changing behavior.
- [ ] **Spawn validation uses global radii** (16.0 monster hitbox) regardless of archetype; AI
  movement uses the per-definition radius; PvE collision uses the global 16.0. Three different
  call sites, two radii sources — keep the asymmetry.
- [ ] **`Vector2.rotated` is CCW in math coordinates** (y-down screen space makes it look CW);
  candidate-offset order in obstacle avoidance is `[+45°, −45°, +90°, −90°, 180°]`; the perp
  vector used for strafing is `(-y, x)`.
- [ ] **No Godot physics involved server-side.** Monsters never use `move_and_slide`,
  CharacterBody2D, or collision layers; all server monster collision is the pure math in §4.13.
  (The client `monster.gd` node is a CharacterBody2D but performs no movement — render only.)
