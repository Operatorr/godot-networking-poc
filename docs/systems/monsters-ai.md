# Monsters & server-side AI

**Status:** Implemented (verified 2026-06-03 against code)

The POC has exactly **one monster type — the Toxic Slime** — with a small **server-authoritative**
AI: a four-state machine that selects a target, chases, kites-and-shoots, or flees, all run on the
[Tick](../CONTEXT.md). Monsters are [Remote entities](../CONTEXT.md) on every client — there is
**no client-side monster AI**; clients only interpolate and animate server state
(`monster.gd:1-3`). This is deliberately minimal: enough living [Remote entities](../CONTEXT.md)
to add packet/entity load for the netcode stress-test, not an interesting combat AI.

> **Data-driven now.** Stats and AI tuning are no longer hardcoded constants — they come from a
> **`MonsterDefinition`** parsed from `data/monsters/toxic_slime.json`, built by a **factory**, and
> read by the AI each Tick. The `GameConstants.MONSTER_*` values are the **fallback defaults** and
> the Toxic Slime sheet reproduces them exactly (behaviour-preserving). How monsters are defined,
> registered, and spawned — and the roadmap for more — lives in
> [`monster-architecture.md`](monster-architecture.md). This page documents the runtime AI itself.

## Where it runs in the Tick

All monster logic is part of the 30 Hz authoritative [Tick](../CONTEXT.md), in fixed order
(`server_main.gd:230-256`):

| Step | Call | What |
|------|------|------|
| 2 | `_update_game_state` → `monster_spawner.update` (`server_main.gd:461`) | spawn timing / placement |
| 3 | `_update_monster_ai` → `monster_ai.update_all` (`server_main.gd:485`) | state machine, move, shoot |
| 4 | `monster_manager.record_position_snapshot` (`server_main.gd:241`) | 8-tick position history for PvE [lag compensation](../CONTEXT.md) |
| 5 | `collision_handler.process_collisions` (`server_main.gd:244`) | projectile→monster / monster→player damage |
| 7 | `monster_manager.cleanup_dead_monsters` (`server_main.gd:256`) | erase dead monsters after final death [Snapshot](../CONTEXT.md) |

AI runs every Tick (30 Hz) for **all** alive monsters (`monster_ai.gd:47-52`); it is **not**
gated by the [Snapshot](../CONTEXT.md) rate. Monster fire events spawn projectiles immediately
and broadcast a compact fire [Game event](../CONTEXT.md) (`server_main.gd:487-488`).

## Identity & lifecycle

- Entity IDs: monsters allocate from the reserved range **30000–39999**
  (`game_constants.gd:259-260`, `monster_manager.gd`), wrapping when exhausted. Distinct
  from players (1–999) and projectiles (10000–29999).
- Built by `MonsterFactory.create` from the archetype's `MonsterDefinition`; `MonsterManager`
  allocates the id and tracks the `MonsterState`, which now carries `type_id` + `definition`
  (`monster_factory.gd`, `monster_manager.gd` `spawn_monster`, `monster_state.gd`
  `create_from_definition`).
- Health **50**, hitbox radius **16** — for the Toxic Slime these come from
  `data/monsters/toxic_slime.json` (`stats.max_health` / `stats.hitbox_radius`), defaulting to
  `GameConstants` (`game_constants.gd:288,291`) if absent.
- Death: `take_damage` zeroes HP → `is_alive=false`, clears MOVING/ATTACKING flags, sets
  `DEATH` animation (`monster_state.gd:77-94`). The dead monster stays in the manager for one
  more Tick so clients get a final death-animation [Snapshot](../CONTEXT.md) before the despawn
  delta, then `cleanup_dead_monsters` erases it (`monster_manager.gd:170-192`).
- Per-monster network payload is the standard 9-byte full-state entity (id+type+pos+anim+flags),
  via `to_entity_data` (`monster_state.gd:122-129`).

## The AI state machine

Four states (`monster_ai.gd:9-14`), dispatched per monster per Tick (`monster_ai.gd:76-84`).
Each Tick also: decrements timers (`monster_state.gd:112-118`), re-selects a target if it has
none or `retarget_timer` elapsed (`monster_ai.gd:66-68`), refreshes the random steering offset
when its timer expires (`monster_ai.gd:71-72`), and sets the animation to match the state
(`monster_ai.gd:508-518`: IDLE→idle, CHASE/FLEE→walk, ATTACK→attack).

| State | Behaviour | Exits to |
|-------|-----------|----------|
| **IDLE** (0) | stand still, MOVING flag off; wait for a valid target (`monster_ai.gd:187-195`) | CHASE when a live target exists |
| **CHASE** (1) | move toward target at `MONSTER_SPEED` with steering (`monster_ai.gd:199-224`) | FLEE if `dist < flee`; ATTACK if `dist ≤ attack range`; IDLE if target lost |
| **ATTACK** (2) | strafe/kite around target while shooting on cooldown (`monster_ai.gd:229-269`) | FLEE if rushed; CHASE if `dist > attack range × 1.2` (hysteresis); IDLE if target lost |
| **FLEE** (3) | move away from target with a strafe bias (`monster_ai.gd:273-297`) | ATTACK/CHASE once `dist ≥ preferred`; IDLE if target lost |

Transitions go through `_transition_to_state`, which sets/clears the ATTACKING/MOVING entity
flags and (with `debug_logging`) logs `old→new` (`monster_ai.gd:301-325`).

## Perception, aggro & target selection

Target selection runs on a cadence (`MONSTER_RETARGET_INTERVAL` 1.0 s base, scaled by
difficulty) or immediately while a monster has no target (`monster_ai.gd:66-68`,
`:154-155`). It is a **threat score** over all alive players (`monster_ai.gd:97-144`), not just
nearest:

- Score = base 35 + distance proximity (≤45) + close-range threat (≤25) + target movement speed
  (≤10) + shooting bonus (18 if shoot held) + low-HP bonus (≤8) + **target stickiness** (~18 for
  the current target, to resist flip-flopping) (`monster_ai.gd:130-144`).
- The best-scoring player becomes the target **only if within detection range**; a target beyond
  `lose_interest_distance` is dropped → IDLE (`monster_ai.gd:118-126`). `MONSTER_DETECTION_RANGE`
  650, `MONSTER_LOSE_INTEREST_DISTANCE` 900 (`game_constants.gd:326,344`).

There is no FOV, no line-of-sight, and no shared spatial broad-phase: each monster scans **every
alive player** every retarget (`monster_ai.gd:107-111`) — fine at the POC's 100-monster cap, not
free at MMO scale.

### Difficulty scaling

A single `difficulty` ∈ [0,1] (config `monster_ai_difficulty`, default **0.85**,
`server_config.gd:35`, wired in `server_main.gd`) `lerp`s several ranges: retarget interval,
detection / lose-interest / attack / flee / preferred distances, steering randomness, strafe
intensity, and aim error (`monster_ai.gd` `_get_*` helpers, `_apply_steering`,
`_predictive_aim_direction`). Higher difficulty = faster retarget, longer reach, stickier
targeting, tighter aim. The **base** values being lerped are now per-monster:
`difficulty` scales the `MonsterDefinition` fields (`monster.definition.detection_range`, etc.),
not global constants — so a different archetype tunes its own ranges via its JSON.

## Movement (`MONSTER_SPEED` 120)

- Speed **120** = 60% of `PLAYER_SPEED` 200 (`game_constants.gd:303`). Velocity =
  `move_direction × MONSTER_SPEED`, integrated by `delta` (one Tick) and resolved against arena
  bounds + obstacles via `move_with_obstacle_collision` (`monster_ai.gd:381-397`).
- **Steering**: desired direction + a random offset (`MONSTER_STEERING_RANDOMNESS` 0.15, refreshed
  every ~0.35–1.5 s) for non-robotic paths (`monster_ai.gd:333-339`, `:372-377`).
- **Obstacle avoidance** is reactive, not pathfinding: probe a point
  `MONSTER_AVOIDANCE_DISTANCE` 50 ahead; reflect off map edges, and if it would enter an obstacle,
  rotate to the best of five candidate angles (±45°, ±90°, 180°) (`monster_ai.gd:341-368`). No
  navmesh, no A*.
- **Strafe**: in ATTACK/FLEE the monster orbits rather than standing still; strafe sign flips on
  a ~1.4 s phase keyed to `entity_id` so a pack doesn't move in lockstep (`monster_ai.gd:405-426`).

## Shooting (`MONSTER_PROJECTILE_SPEED` 300, `MONSTER_SHOOT_COOLDOWN` 0.75)

Only the ATTACK state fires (`monster_ai.gd:257-261`):

- Gated by `can_shoot()` (`shoot_cooldown ≤ 0`, `monster_state.gd:102-103`); firing starts a
  **0.75 s** cooldown (`game_constants.gd:329`) and a `MONSTER_ATTACK_DURATION` 0.5 s attack timer.
- **Predictive aim** (lead): solves the intercept quadratic against the target's
  server-authoritative velocity and projectile speed, falling back to straight-line if no positive
  root, clamped to ≤2 s lead (`monster_ai.gd:430-476`). Aim error injected as a random rotation up
  to `(1−difficulty)×0.22` rad (`monster_ai.gd:443-446`) — so max difficulty aims dead-on.
- Projectile spawned through `projectile_manager.spawn_projectile` with the monster as source,
  then its speed overridden to **300** (75% of the player's 400) (`monster_ai.gd:480-504`);
  damage to players is `MONSTER_PROJECTILE_DAMAGE` 10 (`game_constants.gd:309`). Spawn offset
  pushes it clear of the monster's own hitbox to avoid self-collision (`monster_ai.gd:485-486`).

Monster→player hits are not lag-compensated (players are authoritative-current). Note the inverse:
**player projectiles vs monsters ARE lag-compensated** using `record_position_snapshot`'s 8-tick
history (`monster_manager.gd:119-150`, `server_main.gd:241`) — documented under combat, not here.

## Spawning (`MONSTER_MAX_COUNT` 100, base rate 0.2/s)

`MonsterSpawner.update` runs each Tick (`monster_spawner.gd:46-74`). It accumulates time and
spawns whenever the interval `1/spawn_rate` elapses, but never above `MONSTER_MAX_COUNT` **100**
alive (`game_constants.gd:255`, `monster_spawner.gd:57,71`). It requires at least one alive player
(`monster_spawner.gd:91-93`).

> **Spawn-rate discrepancy (flag):** `GameConstants.MONSTER_SPAWN_RATE` = **0.2/s** (1 per 5 s,
> `game_constants.gd:252`), but `ServerMain` exports `monster_spawn_rate =
> MONSTER_SPAWN_RATE * 2.0` (`server_main.gd:13`) and passes that into the spawner
> (`server_main.gd:131`). No JSON override exists, so the **live** spawn rate is **0.4/s**
> (1 per 2.5 s). The canonical 0.2/s is the constant, not the running value.

Placement is a small three-layer director, all requiring the position to be in-bounds, clear of
obstacles, non-overlapping (`MONSTER_SPAWN_SEPARATION`), and **outside** every player's
`MONSTER_VISIBILITY_RADIUS` 300 so monsters never pop in on screen (`monster_spawner.gd:303-384`):

1. **Anchors** — shared arena spawn points, tried first (`monster_spawner.gd:120-131`).
2. **Encounter** — pressure spawns in a 320–450 band around a random player: outside view but
   inside detection/AoI so they join the fight (`monster_spawner.gd:135-152`,
   `game_constants.gd:267-268`).
3. **Regional** — a 4×4 grid keeps the rest of the 2000×2000 map populated, scored by deficit,
   player density, and visit recency, with a soft per-region cap of 2 (`monster_spawner.gd:156-299`).

The split between regional and encounter budget is `MONSTER_REGIONAL_SPAWN_RATIO` 0.6
(`game_constants.gd:272`, `monster_spawner.gd:99-116`). If every layer fails, the spawn is skipped
this Tick.

## The eight questions

- **Client:** renders monsters as [Remote entities](../CONTEXT.md) — interpolation + animation
  from `STATE_UPDATE` only; **no** AI (`monster.gd:1-3`).
- **Server:** owns 100% of monster AI, movement, targeting, shooting, spawning, death — on the Tick.
- **Predicted:** nothing — monsters are never predicted; only the [Local player](../CONTEXT.md) is.
- **Replicated:** position, animation, flags as 9-byte full-state entities each Snapshot
  (`monster_state.gd:122-129`); fire and death as [Game events](../CONTEXT.md).
- **Persisted:** nothing — monster state is in-memory only; the Go API stores no monster data.
- **Validated:** N/A — monsters are server-authored, so there is no client request to validate;
  their own moves are bounds/obstacle-clamped (`monster_ai.gd:390-394`).
- **Can fail:** target rescans are O(players) per monster (no broad-phase) → cost at scale; spawn
  finder may skip a Tick if no clear off-screen slot exists; reactive avoidance can wall-hug
  (no pathfinding); the 0.2-vs-0.4 spawn-rate gap above.
- **Tested:** via load-test bot swarms exercising the live server; no isolated unit tests for the
  state machine today.

## See also

- [`monster-architecture.md`](monster-architecture.md) — the factory, data-driven definitions, schema, and the roadmap for adding monsters
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Tick, Remote entity, Snapshot, Game event, Lag compensation)
- [`../netcode/server-tick-broadcast.md`](../netcode/server-tick-broadcast.md) — the Tick loop monsters run inside
- [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md) — how monsters are culled per player
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how clients render monsters as Remote entities
- [`players-movement.md`](players-movement.md) · [`combat-hits.md`](combat-hits.md) — players, and projectile/lag-comp hit resolution
