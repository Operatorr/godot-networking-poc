# Monster architecture — definitions, spawn director, roadmap

**Status:** Foundation **Implemented** (verified 2026-06-14 against `rust/`) · advanced patterns **Planned/Vision**

This doc is the **map for adding monsters**. The runtime AI of the shipped monster lives in
[`monsters-ai.md`](monsters-ai.md); this page covers the *content pipeline* — how a monster is
**defined as data**, **spawned**, and **rendered** — and the **roadmap** of MMO monster patterns,
status-tagged so we build the right amount for a netcode POC and no more.

> **Two homes, one catalogue (post-Rust-port).** Authority moved off GDScript. The only
> authoritative server is the Rust **`omega-server`** (`rust/server/`, single-threaded 30 Hz tick).
> Monster *definitions, AI, spawning, and id allocation* live in **`rust/server/src/sim/monster.rs`**.
> The Godot client keeps a **data-driven catalogue** under `client/data/monsters/*.json`, loaded by
> **`MonsterDatabase`** into **`MonsterDefinition`**, but it consumes that catalogue only for
> **rendering** (sprite colours, display name) and for the standalone **offline-sandbox** AI — never
> to drive the live server. The retired GDScript headless server (`client/scripts/server/*.gd`) no
> longer runs; do not treat it as live code.

> **Scale check.** This is a netcode stress-test, not an RPG. Gameplay is intentionally minimal
> (see [`../../AGENTS.md`](../../AGENTS.md)). The foundation below is built so monsters are added by
> **data, not inheritance**; the advanced systems (behavior trees, threat tables, loot, etc.) are
> documented as a roadmap, **not** built. Don't implement a Planned/Vision row without a reason tied
> to the netcode goal.

## The pipeline (Implemented)

The authoritative half is Rust; the client half is render-only.

```
SERVER (authoritative)                          CLIENT (render-only)
─────────────────────────────────────          ──────────────────────────────────────
rust/server/src/sim/monster.rs                      client/data/monsters/<id>.json
  static MonsterDefinition  (TOXIC_SLIME,         + index.json manifest
                             TARGET_DUMMY)              │
  definition(type_id) → &'static def                   ▼
        │   (unknown id → TOXIC_SLIME)           MonsterDefinition.from_dict()
        ▼                                          (shared/monster/monster_definition.gd)
  MonsterManager.spawn_monster(pos, id)                │  GameConstants-backed defaults
    → allocates entity id 30000–39999                  ▼
    → pushes MonsterState                       MonsterDatabase  (id → MonsterDefinition)
        │                                          (shared/monster/monster_database.gd)
        ▼                                                │
  MonsterSpawner.update()  (3-layer director)            ├─► Monster.gd      (live multiplayer render)
        │                                                └─► OfflineMonster.gd (offline-sandbox local AI)
        ▼
  MonsterAi.update_all()  reads monster.definition each tick
```

On the server there is **one** `MonsterState` and **one** `MonsterAi`. Monsters differ by **data**
(`&'static MonsterDefinition`), not by a subclass tree — the component/data-driven choice (no
`Monster→Undead→Skeleton→FireSkeleton` inheritance).

> **Important asymmetry.** The Rust server does **not** read the JSON catalogue at runtime. It ships
> a small set of `&'static MonsterDefinition` constants embedded in `monster.rs`; `definition(type_id)`
> matches on the id string and falls back to `TOXIC_SLIME` for anything unknown (mirroring
> `MonsterDatabase` semantics on the client). The JSON files in `client/data/monsters/` are the
> client-side source of truth for **appearance, display name, and offline AI**, and the human-readable
> design record for each archetype. Adding a server-driven monster therefore means editing **both**:
> a Rust `MonsterDefinition` const for behaviour **and** a JSON file for the client's render/catalogue.

### Patterns in play

| Pattern | How it shows up here | Where |
|---|---|---|
| **Prototype / data-driven** | Stats/perception/combat/movement are fields on a definition, not hardcode. Server: `&'static MonsterDefinition`. Client: `MonsterDefinition` parsed from JSON. | `rust/server/src/sim/monster.rs`, `client/data/monsters/*.json` |
| **Registry / lookup** | Server `definition(type_id)` resolves id→def (unknown→toxic_slime). Client `MonsterDatabase` loads the catalogue and resolves id→def. | `rust/server/src/sim/monster.rs`, `shared/monster/monster_database.gd` |
| **Spawn director** | `MonsterManager.spawn_monster()` allocates an id + tracks state; `MonsterSpawner` is the 3-layer placement director. | `rust/server/src/sim/monster.rs` |
| **Component-ish composition** | One `MonsterState` + one `MonsterAi` parameterised by the definition's fields rather than a class per monster. | `rust/server/src/sim/monster.rs` |
| **Server-authoritative AI** | Every monster decision runs on the server tick; clients only render. | see [`monsters-ai.md`](monsters-ai.md) |

## The shipped monsters (exactly two)

Only two definitions exist as Rust `&'static` constants, and only **two AI profiles** run:

| id | `ai_profile` | Role | Notes |
|---|---|---|---|
| `toxic_slime` | `ranged_kiter` | The live hostile test enemy (Tier 1). | The four-state FSM (Idle/Chase/Attack/Flee) — kites to its preferred distance and spits a slow toxic glob. `xp_reward = 20`. |
| `target_dummy` | `stationary_dummy` | Practice prop (Tier 0). | Never moves, never targets, never shoots; 100 HP; `xp_reward = 0`. Its branch in `MonsterAi::update_monster` short-circuits to Idle. |

Every other archetype/`ai_profile` named in [`../gdd/MONSTERS.md`](../gdd/MONSTERS.md) (the 95-monster
roster) is **aspirational** — content data only, with **no behaviour implemented**. The roster's own
guidance says it: any monster whose profile isn't implemented runs as `ranged_kiter` for now. **There
is no `melee_chaser`, `ambush_charger`, `caster_zoner`, `boss_pattern`, etc.** — those strings select
nothing today.

## Adding a monster (the whole job)

To add a **behaviourally-distinct, server-driven** monster you must touch both sides:

1. **Server behaviour (Rust).** Add a `static FOO: MonsterDefinition = …` in
   `rust/server/src/sim/monster.rs` and a match arm in `definition()` so `"foo"` resolves to it. If it
   needs new behaviour (anything other than the `ranged_kiter` FSM or the `stationary_dummy`
   short-circuit) you must also implement a new `ai_profile` branch in `MonsterAi` — the profile
   string alone does nothing. Rebuild the server (`./scripts/build_server.sh`).
2. **Client catalogue (JSON).** Create `client/data/monsters/<id>.json` (copy `toxic_slime.json`,
   change the numbers) and register the id in `client/data/monsters/index.json` (`monsters` array) —
   the export-safe source of truth; the in-editor DirAccess scan also auto-discovers the file. This
   feeds the client's render appearance, display name, and the offline-sandbox AI.
3. **Spawn it.** Have the server place it via `MonsterManager.spawn_monster(pos, "<id>")`. Note the
   live `MonsterSpawner` is hardcoded to spawn `"toxic_slime"` (`spawn_monster(pos, "toxic_slime")`);
   spawning anything else today requires a manual call site or a spawn-table change.

**Not yet automatic — the visual.** The wire carries **no archetype byte** (see the seam below), so
every live multiplayer monster renders with the **default** appearance
(`MonsterDatabase.get_default_definition()` → Toxic Slime) regardless of its server-side definition.
A second *visually distinct* monster needs the archetype on the wire first.

### The wire-archetype seam (Planned)

The wire identifies an entity's *kind* (player / projectile / monster / world-effect) from a **2-bit
kind tag packed into the typed entity id**, derived purely from the id range — monsters are
`30000–39999`. There is **no per-monster subtype/archetype field**: a monster record on the wire is
just `[typed-id][3-bit anim][16-bit entity_flags][16-bit qx][16-bit qy]` (full/baseline) or a delta
mask of those fields. See [`../server/contract.md`](../server/contract.md) (Snapshot, type 65).

To render multiple archetypes, add a 1-byte archetype id to the monster record:

- **Where:** the monster branch of the `Snapshot` entity encoding in `rust/protocol/src/snapshot.rs`
  + the matching field documented in [`../server/contract.md`](../server/contract.md). This is a
  protocol change (would bump `PROTOCOL_VERSION`).
- **Client:** `client_entity_manager._spawn_monster` (and `Monster.gd`, which today calls
  `MonsterDatabase.get_default_definition()`) would read the archetype → pick the definition →
  `ProceduralSprites.create_monster_frames_from_colors(def.core_color, def.glow_color, def.shell_color)`
  (already data-driven and ready). The kill feed already resolves display name from the catalogue.
- **Cost:** +1 byte/monster/snapshot. Cheap, but deliberate — do it when monster #2 lands, not
  speculatively.

## The definition schema

The **server** definition (`rust/server/src/sim/monster.rs`, `struct MonsterDefinition`) carries only
the fields the AI/combat actually consume. The **client** definition
(`shared/monster/monster_definition.gd`, parsed by `MonsterDefinition.from_dict()`) is a superset:
it adds render/designer fields and falls back field-by-field to the matching `GameConstants.MONSTER_*`
default, so a partial JSON still yields a valid, behaviour-preserving monster.

| JSON path | Type | Default (client `GameConstants`) | Server field (`monster.rs`) | Consumed by |
|---|---|---|---|---|
| `id` | string | `"toxic_slime"` | `id` | registry key (both sides) |
| `display_name` | string | `"Toxic Slime"` | — (server has no name) | client kill feed / HUD |
| `archetype` | string | `"ranged_grunt"` | — | client taxonomy / future visual select |
| `faction` | string | `"hostile_fauna"` | — | **Planned** faction system |
| `tier` | int | `1` | — | **Planned** stat scaling |
| `ai_profile` | string | `"ranged_kiter"` | `ai_profile` | selects the FSM (server: `ranged_kiter` or `stationary_dummy` only) |
| `stats.max_health` | int | `MONSTER_HEALTH` 50 | `max_health` | HP |
| `stats.move_speed` | float | `MONSTER_SPEED` 120 | `move_speed` | `MonsterAi::move_monster` |
| `stats.hitbox_radius` | float | `MONSTER_HITBOX_RADIUS` 16 | `hitbox_radius` | AI movement / avoidance / spawn offset |
| `perception.detection_range` | float | `MONSTER_DETECTION_RANGE` 650 | `detection_range` | target select |
| `perception.lose_interest_range` | float | `MONSTER_LOSE_INTEREST_DISTANCE` 900 | `lose_interest_range` | hysteresis band (soft leash) |
| `perception.retarget_interval` | float | `MONSTER_RETARGET_INTERVAL` 1.0 | `retarget_interval` | retarget cadence |
| `perception.leash_range` | float | `0.0` (disabled) | — (not in server struct) | **Planned** hard leash |
| `combat.attack_range` | float | `MONSTER_ATTACK_RANGE` 200 | `attack_range` | FSM transitions |
| `combat.flee_distance` | float | `MONSTER_FLEE_DISTANCE` 100 | `flee_distance` | FLEE transition |
| `combat.preferred_distance` | float | `MONSTER_PREFERRED_DISTANCE` 150 | `preferred_distance` | kiting |
| `combat.shoot_cooldown` | float | `MONSTER_SHOOT_COOLDOWN` 0.75 | `shoot_cooldown` | shot cadence |
| `combat.attack_duration` | float | `MONSTER_ATTACK_DURATION` 0.5 | `attack_duration` | attack timer |
| `combat.projectile_speed` | float | `MONSTER_PROJECTILE_SPEED` 300 | `projectile_speed` | projectile spawn + aim lead |
| `combat.projectile_damage` | int | `MONSTER_PROJECTILE_DAMAGE` 10 | — (not in server struct) | **see coupling note** |
| `movement.steering_randomness` | float | `MONSTER_STEERING_RANDOMNESS` 0.15 | `steering_randomness` | steering |
| `movement.avoidance_distance` | float | `MONSTER_AVOIDANCE_DISTANCE` 50 | `avoidance_distance` | obstacle probe |
| (server only) | — | — | `xp_reward` | XP granted on death (see below) |
| `appearance.core_color` / `glow_color` / `shell_color` | hex string | toxic-green palette | — | **client sprite only** |
| `abilities` / `loot` / `spawn` / `networking` | object/array | preserved verbatim | — | **client documentation only** (server ignores) |

> **Coupling note — projectile damage.** Monster shots still apply a **flat constant**, not the
> per-type `projectile_damage`. On hit, `combat::apply_player_hit` (`rust/server/src/sim/combat.rs`)
> selects damage by **owner-id range**: an owner id `>= 30000` (a monster) applies
> `MONSTER_PROJECTILE_DAMAGE`; otherwise `PLAYER_PROJECTILE_DAMAGE`. Projectiles don't carry
> per-source basic-attack damage for the PvE branch yet, so the JSON `combat.projectile_damage` is
> documentation/offline-only — keep it equal to the constant until a damage-on-projectile follow-up
> lands. (The offline-sandbox `OfflineMonster.gd` *does* read `definition.projectile_damage`
> directly, so the two paths can diverge if the JSON drifts from the constant.)

### XP reward (Implemented — server-authoritative)

`xp_reward` is a **server-only** field on the Rust definition (`TOXIC_SLIME = 20`, `TARGET_DUMMY = 0`).
On a kill, `combat::grant_kill_experience` awards the **full** reward (no split) to every alive,
authenticated player within `XP_SHARE_RADIUS` (500 u), accumulates it server-side, resolves level-ups,
and emits the HUD progress + a cosmetic `EXP_GAIN` floater. The client JSON's `loot.xp` field is **not**
the live value (and is in fact stale: `toxic_slime.json` says `10` while the server grants `20`) — it is
not read by the server. See [`PROGRESSION.md`](PROGRESSION.md) and
[`../gdd/progression/EXP_monster_table.md`](../gdd/progression/EXP_monster_table.md).

## Archetype taxonomy (Planned vocabulary)

Reusable AI buckets so many monsters share one `ai_profile`. **Only `ranged_kiter` and
`stationary_dummy` exist today** (the Toxic Slime and the Target Dummy). The rest are the agreed
naming for future content, carried in the catalogue/roster but inert:

`melee_grunt` · `ranged_grunt` · `tank` · `fast_ambusher` · `swarm` · `caster` · `support` ·
`summoner` · `exploder` · `stealth` · `burrower` · `elite` · `mini_boss` · `boss` · `world_boss` ·
`neutral_wildlife` · `passive` · `quest` · `training_dummy`.

An **AI profile** maps an archetype to behaviour (e.g. *Aggressive Melee*: patrol → aggro on sight →
chase → melee in range → leash home). Today every profile string other than the two implemented ones
silently falls through to the `ranged_kiter` FSM.

## Pattern roadmap (status-tagged)

Scoped honestly to this POC:

| Pattern | Status | Note |
|---|---|---|
| Server-authoritative AI | **Implemented** | All monster decisions on the Rust tick. |
| Component/data-driven definitions | **Implemented** | `&'static MonsterDefinition` (server) + JSON catalogue (client). |
| Registry / spawn director | **Implemented** | `definition()` + `MonsterManager` + `MonsterSpawner`. |
| Finite state machine (simple mobs) | **Implemented (4-state)** | Idle/Chase/Attack/Flee — see [`monsters-ai.md`](monsters-ai.md). |
| Stationary profile | **Implemented** | `stationary_dummy` short-circuits to Idle (Target Dummy). |
| FSM (full 9-state) | **Planned** | Add Patrol/Alert/Investigate/Retreat/Stunned/Dead to `enum AiState` + dispatch. |
| Additional `ai_profile`s | **Planned** | Only 2 profiles run; the roster's melee/caster/boss/etc. profiles are inert strings. |
| Threat / aggro table | **Partial** | A per-tick threat **score** exists (`MonsterAi::score_target`); no persistent threat table. |
| Leash / reset system | **Partial** | `lose_interest_range` is a soft leash; the lose-interest *drop* branch is effectively dead code (a targeted monster never goes idle from distance alone — see `monsters-ai.md`). No home-anchored hard leash. |
| Faction system | **Planned** | `faction` carried in the JSON, unused by both sides. |
| Spawn table | **Partial** | 3-layer spawn director exists (`MonsterSpawner`); it hardcodes `"toxic_slime"`, no per-type weighting yet. |
| Object pooling | **Partial** | Client pools projectiles; monsters are not pooled (cap `MONSTER_MAX_COUNT` = 100). |
| Interest management (AoI) | **Implemented** | See [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md). |
| XP / kill reward | **Implemented** | Server-authoritative `xp_reward`; radius-shared on death. |
| Behavior tree (bosses/elites) | **Vision** | Not needed for the POC. |
| Blackboard (shared AI memory) | **Vision** | — |
| Strategy objects (movement/targeting) | **Vision** | Today's variance is the difficulty lerp + the (mostly inert) `ai_profile` string. |
| NavMesh / pathfinding | **Vision** | Reactive obstacle avoidance only; no A*. |
| Telegraph / cooldown ability select | **Planned** | One ability (toxic spit) on a fixed cooldown; `abilities` array reserved (client-only doc). |
| Loot tables | **Planned** | `loot` carried in JSON, unused by the server; no item economy in the POC. |
| Group AI / boss phases | **Vision** | — |
| Debug tools / designer tuning | **Partial** | Edit Rust const (+ rebuild) and/or JSON (+ reimport); `MonsterAi.difficulty` knob; no live tuner. |

## Designer spec template

For each new monster, fill this (it maps 1:1 onto the JSON groups; the **server** half is the subset
that drives behaviour and must be mirrored into a Rust `MonsterDefinition` const):

```
Identity:    id · display_name · archetype · faction · tier · ai_profile
Stats:       max_health · move_speed · hitbox_radius                         (server-driving)
Perception:  detection_range · lose_interest_range · retarget_interval · leash_range(Planned)
Combat:      attack_range · flee_distance · preferred_distance ·
             shoot_cooldown · attack_duration · projectile_speed             (server-driving)
             projectile_damage  (client/offline only — server uses the flat constant)
Reward:      xp_reward                                                       (server-only field)
Movement:    steering_randomness · avoidance_distance   (reactive avoidance; no navmesh)
Abilities:   [ { id, type, damage, cooldown, telegraph } ]      (client doc only / Planned)
Appearance:  core_color · glow_color · shell_color  (client render only)
Loot/Spawn:  xp · table · weight · biomes            (client doc only / Planned)
Networking:  server_authoritative · replicated[] · client_predicted  (descriptive only)
```

## Edge cases (server-authoritative answers)

| Situation | Behaviour |
|---|---|
| Target player disconnects / dies | `MonsterAi` drops the target → Idle and reselects next tick (`select_target` / the per-state `target()` guards). |
| Target turns invisible (Rogue Stealth) | Monster drops aggro immediately: a `STEALTH`-flagged player scores `−∞` in `score_target` and is dropped at the top of `update_monster`. |
| Monster gets stuck on geometry | Reactive avoidance reflects off bounds and picks the best of 5 candidate angles (`find_clear_steering_direction`); no pathfinding, so wall-hugging is possible (known limit). |
| Monster pulled too far | Beyond `lose_interest_range` the *score* drops it, but the drop branch is dead code in practice — a **targeted** monster keeps chasing regardless of distance (documented in `monsters-ai.md`). |
| All players dead/absent | `MonsterSpawner::select_spawn_position` returns `None` with no alive players, so nothing spawns; existing idle monsters stand still. |
| Unknown `type_id` requested | Server `definition()` falls back to `TOXIC_SLIME`; client `MonsterDatabase.get_definition` warns and returns the default (never null). |
| JSON missing / malformed (client) | `MonsterDatabase` warns, skips the file, and `_ensure_default()` guarantees the Toxic Slime catalogue entry exists. |
| Monster id exhaustion | `allocate_entity_id` cursors 30000→39999 with wraparound, skipping live ids; returns `None` (spawn aborts) only if all 10 000 ids are live. |

## The eight questions

- **Client:** reads `display_name` (kill feed / HUD) and `appearance` colours (sprite) from the shared
  catalogue; live multiplayer monsters all render as the **default** (Toxic Slime) until the wire
  carries a subtype. No AI in multiplayer; the offline sandbox runs `OfflineMonster.gd`'s local FSM.
- **Server:** owns the definitions, the spawn director, id allocation, and 100% of AI/combat driven
  from each monster's `&'static MonsterDefinition` — all on the Rust tick.
- **Predicted:** nothing — monsters are never predicted (only the local player is).
- **Replicated:** position, animation (3-bit), entity flags (16-bit) per the `Snapshot` entity record;
  fire and death/kill arrive as `GameEvent`s. **Not** the archetype (no subtype byte yet).
- **Persisted:** nothing — definitions are content (Rust consts + `res://` JSON); monster *state* is
  in-memory only. The Go API stores no monster data (it owns accounts/characters/leaderboard/Glory).
- **Validated:** monsters are server-authored, so there is no client request to validate; their own
  moves are bounds/obstacle-clamped (`arena::move_with_obstacle_collision`). Client definitions fall
  back field-by-field, so bad JSON degrades to defaults rather than crashing.
- **Can fail:** per-type damage not wired for the PvE branch (documented coupling); `MonsterSpawner`
  hardcodes `toxic_slime`; no hard leash / navmesh (documented limits); non-implemented `ai_profile`s
  silently run as `ranged_kiter`.
- **Tested:** `rust/server/src/sim/monster.rs` has unit tests for firing/ids/damage/spawn-visibility/dummy
  behaviour (`cargo test --workspace`); the client catalogue compiles under
  `godot --headless --editor --quit`. Behaviour was preserved across the port by construction.

## See also

- [`monsters-ai.md`](monsters-ai.md) — the runtime AI state machine, perception, movement, shooting.
- [`../server/contract.md`](../server/contract.md) — the as-built wire format (Snapshot type 65; typed entity ids; where an archetype byte would go).
- [`../server/design.md`](../server/design.md) — server architecture & rationale (tick, shared sim, transport).
- [`../gdd/MONSTERS.md`](../gdd/MONSTERS.md) — the 95-monster design roster (aspirational; most profiles unimplemented).
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Tick, Remote entity, Snapshot, Game event).
- `rust/server/src/sim/monster.rs` — `MonsterDefinition` / `MonsterManager` / `MonsterAi` / `MonsterSpawner`.
- `client/data/monsters/toxic_slime.json` — the reviewable client data sheet.
