# Monsters & server-side AI

**Status:** Implemented (verified 2026-06-14 against `rust/server/src/sim/monster.rs`)

The POC ships one hostile monster — the **Toxic Slime** — plus a stationary **Target Dummy** prop.
Both run a small **server-authoritative** AI living entirely in the Rust `omega-server`
([`rust/server/src/sim/monster.rs`](../../rust/server/src/sim/monster.rs)): a four-state machine that
selects a target, chases, kites-and-shoots, or flees, all advanced on the
[Tick](../CONTEXT.md). Monsters are [Remote entities](../CONTEXT.md) on every client — there is
**no client-side monster AI**; clients only interpolate and animate the server's snapshot stream.
This is deliberately minimal: enough living [Remote entities](../CONTEXT.md) to add packet/entity
load for the netcode stress-test, not an interesting combat AI.

> **Authoritative reality.** The only authoritative server is the Rust `omega-server` binary
> (single-threaded synchronous **30 Hz** tick over `rusty_enet`). The retired GDScript headless
> server (`monster_ai.gd`, `monster_spawner.gd`, etc.) is the parity ground truth this module was
> ported from, but it no longer runs and is being deleted — do not cite it as live code. The Rust
> `monster.rs` is a faithful behaviour-preserving port of those scripts (the GDScript RNG and
> per-tick math are reproduced exactly), so the observable AI is unchanged.

> **Data-driven.** Stats and AI tuning are not hardcoded into the AI loop — they live on a
> `MonsterDefinition` (`monster.rs` → `MonsterDefinition`), one per archetype, read by the AI
> each Tick. Two definitions are shipped today, embedded as `static` values (`TOXIC_SLIME`,
> `TARGET_DUMMY`); unknown ids fall back to `TOXIC_SLIME`. How monsters are defined, registered,
> and spawned — and the roadmap for more — lives in
> [`monster-architecture.md`](monster-architecture.md). This page documents the runtime AI itself.
> The full design roster (95 monsters across 19 biomes, AI profiles, tiers/levels) lives in the
> GDD: [`../gdd/MONSTERS.md`](../gdd/MONSTERS.md).

## Where it runs in the Tick

All monster logic is part of the 30 Hz authoritative [Tick](../CONTEXT.md), in fixed order
(`rust/server/src/sim/world.rs`, the `tick` method):

| Step | Call (`world.rs`) | What |
|------|-------------------|------|
| 2 | `MonsterSpawner::update` (`monster.rs`) | spawn timing / placement |
| 3 | `MonsterAi::update_all` (`monster.rs`) | state machine, move, shoot → returns `FireEvent`s |
| 4 | `MonsterManager::record_position_snapshot` (`monster.rs`) | 8-tick position history for PvE [lag compensation](../CONTEXT.md) |
| 5 | `combat::process_collisions` (`rust/server/src/sim/combat.rs`) | projectile→monster / monster→player damage |
| 5b | `Backstop::update` (`combat.rs`) | D11 lenient backstop for blatant unreported monster-bullet overlaps |
| 6 | `Broadcast::broadcast_state_updates` (`rust/server/src/net/broadcast.rs`) | snapshots (incl. dead monsters' final death frame) |
| 7 | `MonsterManager::cleanup_dead_monsters` (`monster.rs`) | erase dead monsters after their final death [Snapshot](../CONTEXT.md) |

AI runs every Tick (30 Hz) for **all** alive monsters in registry order
(`MonsterAi::update_all`); it is **not** gated by the [Snapshot](../CONTEXT.md) rate. Each
monster that fires this Tick is collected into a `FireEvent` (`source_id`, non-zero
`projectile_id`); the projectile is spawned immediately and `world.rs` step 3 broadcasts a
`PROJECTILE_FIRED` [Game event](../CONTEXT.md) per fire (see
[`../server/contract.md`](../server/contract.md) §GameEvent).

## Identity & lifecycle

- Entity IDs: monsters allocate from the reserved range **30000–39999** via a monotonic cursor
  with wraparound and skip-if-live (`MonsterManager::allocate_entity_id`); freed ids recycle only
  after the cursor wraps. Distinct from players (1–999), projectiles (10000–29999), and
  world-effect entities (40000–49999). See the typed entity-id encoding (kind 2 = monster, 14-bit
  offset) in [`../server/contract.md`](../server/contract.md).
- Built by `MonsterManager::spawn_monster(position, type_id)`, which resolves the
  `&'static MonsterDefinition` (`definition()`), allocates the id, and pushes a `MonsterState`.
- Toxic Slime: health **50**, hitbox radius **16**, move speed **120** — from `TOXIC_SLIME`
  (`monster.rs`). The `sim_core` `MONSTER_*` constants
  ([`rust/sim_core/src/constants.rs`](../../rust/sim_core/src/constants.rs)) hold the same values
  and serve as the canonical defaults; a different archetype carries its own definition fields.
- Death: `MonsterState::take_damage` zeroes HP → `is_alive=false`, clears MOVING/ATTACKING flags,
  zeroes `move_direction`, sets `DEATH` animation. The dead monster stays in the manager for one
  more Tick so clients get a final death-animation [Snapshot](../CONTEXT.md) (step 6 includes ALL
  monsters, dead-pending-cleanup), then `cleanup_dead_monsters` (step 7) erases it.
- On a non-fatal hit `take_damage` sets the `HIT` animation, which the next alive AI Tick
  overwrites with the state animation.
- Replication payload: each monster rides the standard delta-`Snapshot` entity record (id + pos +
  animation + flags), per [`../server/contract.md`](../server/contract.md) §Snapshot.

## The AI state machine

Four states (`monster.rs` → `AiState::{Idle, Chase, Attack, Flee}`), dispatched per monster per
Tick (`MonsterAi::update_monster`). Each Tick also: decrements timers
(`MonsterState::update_timers` — shoot/attack/retarget/steering), drops aggro instantly if the
target turned invisible (Rogue Stealth, see below), re-selects a target if it has none or the
`retarget_interval` elapsed, refreshes the random steering offset when its timer expires, then
sets the animation to match the state (IDLE→idle, CHASE/FLEE→walk, ATTACK→attack).

| State | Behaviour | Exits to |
|-------|-----------|----------|
| **Idle** | stand still, MOVING flag off; wait for a valid target (`process_idle`) | Chase when a live target exists |
| **Chase** | move toward target at `move_speed` with steering (`process_chase`) | Flee if `dist < flee_distance`; Attack if `dist ≤ attack_range`; Idle if target lost |
| **Attack** | kite/strafe around target while shooting on cooldown (`process_attack`) | Flee if rushed (`dist < flee_distance × (0.75 + 0.25·difficulty)`); Chase if `dist > attack_range × 1.2` (hysteresis); Idle if target lost |
| **Flee** | move away from target with a strafe bias (`process_flee`) | Attack/Chase once `dist ≥ preferred_distance`; Idle if target lost |

Transitions go through `MonsterAi::transition`, which is a no-op if the state is unchanged and
otherwise sets/clears the ATTACKING/MOVING entity flags (Attack sets ATTACKING and resets the
attack timer; Idle zeroes `move_direction` and clears both flags; Chase/Flee clear ATTACKING).

**Target Dummy** short-circuits all of this: a `stationary_dummy` `ai_profile` ticks its timers,
forces `target_id = 0`, `move_direction = 0`, `Idle`, clears MOVING/ATTACKING, and never fires.

## Perception, aggro & target selection

Target selection runs on a cadence (`retarget_interval`, base **1.0 s**, difficulty-scaled) or
immediately while a monster has no target (`MonsterAi::select_target`). It is a **threat score**
over all alive, authenticated players (`MonsterAi::score_target`), not just nearest:

- Score = base **35** + distance proximity (≤45) + close-range threat (≤25) + target movement
  speed vs `PLAYER_SPRINT_SPEED` (≤10) + shooting bonus (**18** if shoot held) + low-HP bonus
  (≤8) + **target stickiness** (`18 × (0.5 + difficulty·0.5)` for the current target, to resist
  flip-flopping).
- The best-scoring player becomes the target **only if within detection range**; the
  "drop target if beyond lose-interest" branch is **effectively dead code** (every too-far
  player scores `−INF`, so the strict `>` lose-interest test never selects) — observable
  behaviour: **a targeted monster never goes Idle from distance alone**, it keeps chasing. This is
  a faithful port of the GDScript quirk (covered by the
  `targeted_monster_never_drops_target_by_distance` test in `monster.rs`).
- `detection_range` base **650**, `lose_interest_range` base **900** (Toxic Slime), both
  difficulty-scaled (see below).

**Rogue Stealth interaction:** a player with the `STEALTH` entity flag scores `−INF` (invisible to
targeting) and any monster already targeting them drops aggro the moment they go invisible.
Stealth only affects *targeting*, not collision — a stealthed player can still be hit by a bullet
they walk into.

There is no FOV, no line-of-sight, and no shared spatial broad-phase: each monster scans **every
alive authenticated player** every retarget — fine at the POC's 100-monster cap, not free at MMO
scale.

### Difficulty scaling (two axes)

The POC exposes a single per-instance **AI-tuning** knob: `monster_ai_difficulty` ∈ [0,1]
(`rust/server/src/config.rs`, default **0.85**, clamped on load), held on `MonsterAi::difficulty`.
It `lerp`s several effective ranges off the per-monster definition (`MonsterAi::_*` helpers — all
unclamped lerps, ported exactly):

- `retarget_interval`: `def.retarget_interval × 1.35` → `0.28` (faster retarget at high difficulty)
- `detection_range`: `def.detection_range × 0.8` → `def.lose_interest_range`
- `lose_interest_distance`: `def.lose_interest_range × 0.85` → `× 1.25`
- `attack_range`: `def.attack_range` → `min(PROJECTILE_MAX_DISTANCE × 0.72, 540)`
- `flee_distance`: `def.flee_distance × 0.75` → `× 1.75`
- `preferred_distance`: `def.preferred_distance` → `340`
- steering randomness, strafe intensity, kite radial pull, and aim error are also difficulty-keyed
  inline (see Movement/Shooting). Higher difficulty = faster retarget, longer reach, stickier
  targeting, tighter aim.

This is the runtime tuning axis. It is **distinct from the GDD's other difficulty axis — monster
level/tier** ([`../gdd/MONSTERS.md`](../gdd/MONSTERS.md), Biome Tier→Level guide): a monster's
*stats* (health, damage, `xp_reward`) scale with its tier/level via its definition data, while
`monster_ai_difficulty` scales how *cleverly* the AI plays those stats. Pre-alpha ships only the
Tier 1 Toxic Slime, so the level axis is not yet exercised in the running server; the data model
for it lives in the GDD roster.

## Movement (`move_speed` 120)

- Toxic Slime speed **120** = 60% of `PLAYER_SPEED` 200. Velocity = `move_direction × move_speed`,
  integrated by `delta` (one Tick) and resolved against arena bounds + obstacles via
  `sim_core::arena::move_with_obstacle_collision` (`MonsterAi::move_monster`). The MOVING flag is
  set/cleared by whether `move_direction` is non-zero.
- **Steering**: desired direction + a normalized random offset scaled by
  `def.steering_randomness × lerp(1.25, 0.35, difficulty)` (base randomness **0.15**), refreshed
  on a `0.35 .. lerp(1.5, 0.8, difficulty)` s timer (`MonsterAi::apply_steering`,
  `update_monster`).
- **Obstacle avoidance** is reactive, not pathfinding: probe a point `def.avoidance_distance`
  (**50**) ahead; reflect the steer off map edges, and if the probe would enter an obstacle, rotate
  to the best of five candidate angles (±45°, ±90°, 180°) scored by clearance
  (`MonsterAi::find_clear_steering_direction`). No navmesh, no A*.
- **Strafe**: in Attack/Flee the monster orbits rather than standing still; the strafe sign flips
  on a **1.4 s** phase keyed to `entity_id` so a pack doesn't move in lockstep
  (`MonsterAi::strafe_sign`, using server-uptime ms). `combat_move_direction` blends strafe with a
  radial pull that nudges back toward `preferred_distance` (push out below `×0.82`, draw in above
  `×1.18`), all difficulty-weighted.

## Shooting (`projectile_speed` 300, `shoot_cooldown` 0.75)

Only the Attack state fires (`MonsterAi::process_attack`):

- Gated by `MonsterState::can_shoot()` (`is_alive && shoot_cooldown ≤ 0`); firing starts a
  **0.75 s** cooldown and a **0.5 s** `attack_duration` timer (Toxic Slime values).
- **Predictive aim** (lead): `predict_target_position` solves the intercept quadratic against the
  target's server-authoritative velocity and `projectile_speed`, falling back to straight-line
  when there is no positive root, clamped to **≤2 s** lead. Aim error is then injected as a random
  rotation up to `(1 − difficulty) × 0.22` rad (`predictive_aim_direction`) — so max difficulty
  aims dead-on.
- The projectile is spawned via `ProjectileManager::spawn_projectile` with the monster as source,
  at `def.projectile_speed` (**300** = 75% of the player's 400) and
  `MONSTER_PROJECTILE_KNOCKBACK_FORCE`; the spawn offset pushes it clear of the monster's own
  hitbox to avoid self-collision. The fired projectile id is recorded on the monster and surfaced
  in the returned `FireEvent` — guaranteed non-zero (D11 invariant).
- Damage to players is `MONSTER_PROJECTILE_DAMAGE` **10**, selected by owner-id range in
  `combat::apply_player_hit`.

## Hit authority (two netcodes — the GDD's blanket line is wrong)

Monster combat sits on **both** sides of the hit-authority model
([`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md)):

- **Monster → player** (the monster's own bullets hitting you) = **client-authoritative +
  server-validated** for RotMG dodge-feel. The client reports the hit; the server validates
  plausibility and otherwise trusts it, backed only by the **D11 lenient backstop**
  (`Backstop::update`, step 5b): it applies a hit itself **only** on a true ≥24 u blatant
  authoritative overlap, after a grace of **≥15 ticks** (`backstop_grace_ticks`). It must stay
  blatant-overlap-only or it reintroduces the phantom-hit feel.
- **Player → monster** (your bullets hitting a monster) = **server-authoritative +
  lag-compensated**, rewinding monster positions through the 8-tick history recorded in step 4
  (`MonsterManager::get_alive_snapshot`, `combat::process_collisions` PvE pass →
  `apply_monster_damage`). PvP uses the same server-authoritative + lag-comp model.

The governing rule everywhere is **"the client requests, the server decides."** The GDD's older
blanket "PvE is client-authoritative" line is wrong/nuanced and has been corrected in
[`../gdd/index.md`](../gdd/index.md): only the monster→player *damage* leg is client-driven.

On a monster kill, `apply_monster_damage` → `grant_kill_experience` awards the definition's
`xp_reward` (Toxic Slime **20**) server-authoritatively to every alive, authenticated player
within `XP_SHARE_RADIUS` (**500** u), and emits the HUD "+XP" pop event (see
[`PROGRESSION.md`](PROGRESSION.md) and [`../gdd/progression/EXP_monster_table.md`](../gdd/progression/EXP_monster_table.md)).

## Spawning (`MONSTER_MAX_COUNT` 100)

`MonsterSpawner::update` runs each Tick (`monster.rs`). It accumulates time and spawns whenever
`1/spawn_rate` elapses, but the accumulator **pauses at the population cap** (no catch-up burst):
the alive-count gate is checked *before* the timer accumulates and again per spawn, capping at
`MONSTER_MAX_COUNT` **100** alive. Spawning requires at least one alive player.

> **Spawn rate.** The earlier GDScript 0.2-vs-0.4 discrepancy is **resolved** in the Rust config:
> the live `monster_spawn_rate` default is **0.1/s** (1 per 10 s) — the value of the old GDScript
> `server_main.tscn` scene override, carried forward as the Rust default
> (`config.rs`, with the rationale comment). It is config-file-overridable per instance via the
> `server_config.{arena,sanctuary}.json` files. The `sim_core` `MONSTER_SPAWN_RATE` constant
> (0.2) is now just a reference constant, not the running value.

Placement is a small three-layer director, all requiring the position to be in-bounds, clear of
obstacles (`sim_core::arena::circle_intersects_obstacle` at `MONSTER_HITBOX_RADIUS`),
non-overlapping (`MONSTER_SPAWN_SEPARATION`), and **outside** every alive player's
`MONSTER_VISIBILITY_RADIUS` **300** so monsters never pop in on screen
(`MonsterSpawner::is_valid_spawn_position`; the visibility gate counts *every* alive player,
including pre-auth bodies):

1. **Anchors** — `ARENA_MONSTER_SPAWNS` fixed arena spawn points, tried first in random order
   (`select_anchor_position`).
2. **Encounter** — pressure spawns in a `320..450` band (`MONSTER_SPAWN_MIN/MAX_DISTANCE`) around
   a random alive player: outside view but inside detection/AoI so they join the fight
   (`select_encounter_position`, `MONSTER_SPAWN_ATTEMPTS` tries).
3. **Regional** — a 4×4 grid of 500×500 cells over the 2000×2000 map keeps the rest populated,
   scored by deficit, player density, and visit recency, with a soft per-region cap of
   `MONSTER_SPAWN_REGION_SOFT_CAP` 2 (`select_regional_position`, `score_region`).

The budget split between the regional and encounter layers is `MONSTER_REGIONAL_SPAWN_RATIO`
**0.6** (`select_spawn_position`): the director prefers whichever layer has the larger deficit, and
when both are in deficit it rolls regional with probability 0.6; on failure it falls back to the
other layer. If every layer fails, the slot is consumed and the spawn is skipped this Tick.

## The eight questions

- **Client:** renders monsters as [Remote entities](../CONTEXT.md) — interpolation + animation from
  the snapshot stream only; **no** AI.
- **Server:** owns 100% of monster AI, movement, targeting, shooting, spawning, death — on the
  Tick, in the Rust `omega-server`.
- **Predicted:** nothing — monsters are never predicted; only the [Local player](../CONTEXT.md) is
  (via the shared `sim_core` crate, [`../netcode/client-prediction.md`](../netcode/client-prediction.md)).
- **Replicated:** position, animation, flags as delta-`Snapshot` entity records each Snapshot;
  fire (`PROJECTILE_FIRED`, non-zero projectile id) and damage/death as
  [Game events](../CONTEXT.md) ([`../server/contract.md`](../server/contract.md)).
- **Persisted:** nothing — monster state is server-authoritative and in-memory only; the Go API
  persists no monster data (it owns accounts/characters/leaderboard/progression).
- **Validated:** monster moves are bounds/obstacle-clamped server-side; there is no client request
  to validate for monster behaviour itself. The *monster→player hit* is the client request the
  server validates (see Hit authority).
- **Can fail:** target rescans are O(players) per monster (no broad-phase) → cost at scale; the
  spawn finder may skip a Tick if no clear off-screen slot exists; reactive avoidance can wall-hug
  (no pathfinding); the dead-code lose-interest branch means distance alone never drops a target.
- **Tested:** unit tests in `monster.rs` (`mod tests`) cover firing + non-zero projectile id, the
  never-drops-target quirk, the dummy staying idle, spawner visibility/cap, two-hit kill, and id
  allocation/wraparound — plus load-test bot swarms against the live server.

## See also

- [`monster-architecture.md`](monster-architecture.md) — the factory, data-driven definitions, schema, and the roadmap for adding monsters
- [`../gdd/MONSTERS.md`](../gdd/MONSTERS.md) — the full design roster (95 monsters, 19 biomes, AI profiles, tiers/levels)
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Tick, Remote entity, Snapshot, Game event, Lag compensation)
- [`../server/design.md`](../server/design.md) · [`../server/contract.md`](../server/contract.md) — server architecture and the wire/API contract as built
- [`../netcode/server-tick-broadcast.md`](../netcode/server-tick-broadcast.md) — the Tick loop monsters run inside
- [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) — the two-netcode hit model (monster→player vs player→monster)
- [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md) — how monsters are culled per player
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how clients render monsters as Remote entities
- [`players-movement.md`](players-movement.md) · [`combat-hits.md`](combat-hits.md) — players, and projectile/lag-comp hit resolution
