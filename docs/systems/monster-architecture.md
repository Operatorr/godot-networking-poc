# Monster architecture — factory, data-driven definitions, roadmap

**Status:** Foundation **Implemented** (verified 2026-06-03 against code) · advanced patterns **Planned/Vision**

This doc is the **map for adding monsters**. The runtime AI of the one shipped monster lives in
[`monsters-ai.md`](monsters-ai.md); this page covers the *content pipeline* — how a monster is
**defined as data** and **built by a factory** — and the **roadmap** of MMO monster patterns,
status-tagged so we build the right amount for a netcode POC and no more.

> **Scale check.** This is a netcode stress-test, not an RPG. Gameplay is intentionally minimal
> (see [`../../AGENTS.md`](../../AGENTS.md)). The foundation below is built so monsters are added
> by **data, not inheritance**; the advanced systems (behavior trees, threat tables, loot, etc.)
> are documented as a roadmap, **not** built. Don't implement a Planned/Vision row without a
> reason tied to the netcode goal.

## The pipeline (Implemented)

```
res://data/monsters/<id>.json          ← designer edits this (the data sheet)
        │  index.json manifest lists the ids
        ▼
MonsterDefinition.from_dict()          ← typed, GameConstants-backed defaults
   (shared/monster/monster_definition.gd)
        ▼
MonsterDatabase  (id → MonsterDefinition, shared singleton)
   (shared/monster/monster_database.gd)
        ▼
MonsterFactory.create(type_id, entity_id, pos) → MonsterState
   (server/monster_factory.gd)
        ▼
MonsterManager.spawn_monster(pos, type_id)   ← allocates id, tracks state
   (server/monster_manager.gd)
        ▼
MonsterAI reads monster.definition each Tick  (server/monster_ai.gd)
```

There is **one** `MonsterState` and **one** `MonsterAI`. Monsters differ by **data**, not by a
subclass tree — this is the component/data-driven choice from the brief (no
`Monster→Undead→Skeleton→FireSkeleton` inheritance). New archetype = new JSON file.

### Patterns in play

| Pattern (from the brief) | How it shows up here | Where |
|---|---|---|
| **Factory** | `MonsterFactory.create()` assembles a `MonsterState` from a definition; the single spawn seam. | `server/monster_factory.gd` |
| **Prototype / data-driven** | `MonsterDefinition` parsed from JSON; numbers are data, not hardcode. | `shared/monster/monster_definition.gd`, `data/monsters/*.json` |
| **Registry** | `MonsterDatabase` loads the catalogue and resolves `id → definition`. | `shared/monster/monster_database.gd` |
| **Component-ish composition** | One `MonsterState` + one `MonsterAI` parameterised by the definition's fields (stats / perception / combat / movement groups) rather than a class per monster. | `monster_state.gd`, `monster_ai.gd` |
| **Server-authoritative AI** | All decisions on the server Tick; clients only render. | see [`monsters-ai.md`](monsters-ai.md) |

## Adding a monster (the whole job)

1. **Create** `client/data/monsters/<id>.json` (copy `toxic_slime.json`, change the numbers).
2. **Register** the id in `client/data/monsters/index.json` (`monsters` array) — this is the
   export-safe source of truth; the in-editor DirAccess scan also auto-discovers the file.
3. That's it for **server behaviour**: `spawn_monster(pos, "<id>")` now produces a fully-tuned
   monster and `MonsterAI` drives it from the definition.

**Not yet automatic — the visual.** The wire carries `EntityType.MONSTER` with **no archetype
byte** (see the seam below), so every monster currently renders with the **default** appearance
(`MonsterDatabase.get_default_definition()`). A second *visually distinct* monster needs the
archetype on the wire first.

### The wire-archetype seam (Planned)

To render multiple archetypes, add a 1-byte archetype id to the monster entity payload:

- **Where:** the monster branch of `STATE_UPDATE` full-state encoding
  (`shared/networking/packets/state_update_packet.gd`) + a matching `EntityType`/subtype field
  in [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md).
- **Client:** `client_entity_manager._spawn_monster` reads the archetype → picks the definition →
  `ProceduralSprites.create_monster_frames_from_colors(def.core_color, def.glow_color, def.shell_color)`
  (already data-driven and ready). Kill-feed already resolves the display name from the catalogue.
- **Cost:** +1 byte/monster/snapshot. Cheap, but it **is** a protocol change — do it deliberately
  when monster #2 lands, not speculatively.

## The definition schema

Parsed by `MonsterDefinition.from_dict()`. Every field falls back to the matching
`GameConstants.MONSTER_*` value, so a partial JSON still yields a valid, behaviour-preserving
monster. Groups mirror the designer spec template below.

| JSON path | Type | Default (GameConstants) | Consumed by |
|---|---|---|---|
| `id` | string | `"toxic_slime"` | registry key |
| `display_name` | string | `"Toxic Slime"` | kill feed (`arena_base.gd`) |
| `archetype` | string | `"ranged_grunt"` | taxonomy / future visual select |
| `faction` | string | `"hostile_fauna"` | **Planned** faction system |
| `tier` | int | `1` | **Planned** stat scaling |
| `ai_profile` | string | `"ranged_kiter"` | selects FSM/strategy (one today) |
| `stats.max_health` | int | `MONSTER_HEALTH` 50 | `MonsterState` |
| `stats.move_speed` | float | `MONSTER_SPEED` 120 | `MonsterAI._move_monster` |
| `stats.hitbox_radius` | float | `MONSTER_HITBOX_RADIUS` 16 | AI movement/avoidance/spawn-offset |
| `perception.detection_range` | float | `MONSTER_DETECTION_RANGE` 650 | target select |
| `perception.lose_interest_range` | float | `MONSTER_LOSE_INTEREST_DISTANCE` 900 | drop target / soft leash |
| `perception.retarget_interval` | float | `MONSTER_RETARGET_INTERVAL` 1.0 | retarget cadence |
| `perception.leash_range` | float | `0.0` (disabled) | **Planned** hard leash |
| `combat.attack_range` | float | `MONSTER_ATTACK_RANGE` 200 | FSM transitions |
| `combat.flee_distance` | float | `MONSTER_FLEE_DISTANCE` 100 | FLEE transition |
| `combat.preferred_distance` | float | `MONSTER_PREFERRED_DISTANCE` 150 | kiting |
| `combat.shoot_cooldown` | float | `MONSTER_SHOOT_COOLDOWN` 0.75 | `MonsterState.start_shoot_cooldown` |
| `combat.attack_duration` | float | `MONSTER_ATTACK_DURATION` 0.5 | attack timer |
| `combat.projectile_speed` | float | `MONSTER_PROJECTILE_SPEED` 300 | projectile spawn + aim lead |
| `combat.projectile_damage` | int | `MONSTER_PROJECTILE_DAMAGE` 10 | **see coupling note** |
| `movement.steering_randomness` | float | `MONSTER_STEERING_RANDOMNESS` 0.15 | steering |
| `movement.avoidance_distance` | float | `MONSTER_AVOIDANCE_DISTANCE` 50 | obstacle probe |
| `appearance.core_color` / `glow_color` / `shell_color` | hex string | toxic-green palette | client sprite |
| `abilities` / `loot` / `spawn` / `networking` | object/array | preserved verbatim | **Planned** (documentation only today) |

> **Coupling note — projectile damage.** `combat.projectile_damage` is the canonical value, but
> the **live** damage applied on hit still comes from `GameConstants.MONSTER_PROJECTILE_DAMAGE`
> because projectiles don't carry per-source damage yet
> (`server/server_collision_handler.gd` keys damage off the owner-id range). Making damage
> per-type means storing damage on `ProjectileState` — a small **Planned** follow-up. Keep the
> JSON value equal to the constant until then.

## Archetype taxonomy (Planned vocabulary)

Reusable AI buckets so many monsters share one `ai_profile`. **Only `ranged_grunt` exists today**
(the Toxic Slime). The rest are the agreed naming for future content:

`melee_grunt` · `ranged_grunt` · `tank` · `fast_ambusher` · `swarm` · `caster` · `support` ·
`summoner` · `exploder` · `stealth` · `burrower` · `elite` · `mini_boss` · `boss` · `world_boss` ·
`neutral_wildlife` · `passive` · `quest` · `training_dummy`.

An **AI profile** maps an archetype to behaviour, e.g. *Aggressive Melee* (patrol → aggro on
sight → chase → melee in range → leash home), reused by many melee monsters.

## Pattern roadmap (status-tagged)

The brief's full pattern checklist, scoped honestly to this POC:

| Pattern | Status | Note |
|---|---|---|
| Server-authoritative AI | **Implemented** | All monster decisions on the Tick. |
| Component/data-driven definitions | **Implemented** | This doc. |
| Factory + registry spawning | **Implemented** | `MonsterFactory` + `MonsterDatabase`. |
| Finite state machine (simple mobs) | **Implemented (4-state)** | IDLE/CHASE/ATTACK/FLEE — see [`monsters-ai.md`](monsters-ai.md). |
| FSM (full 9-state) | **Planned** | Add Patrol/Alert/Investigate/Retreat/Stunned/Dead to the enum + dispatch. |
| Threat / aggro table | **Partial** | A per-Tick threat **score** exists (`monster_ai._score_target`); no persistent threat table. |
| Leash / reset system | **Partial** | `lose_interest_range` is a soft leash; no home-anchored hard leash yet (`leash_range` field reserved). |
| Faction system | **Planned** | `faction` field carried, unused. |
| Spawn table | **Partial** | 3-layer spawn director exists (`monster_spawner.gd`); not yet weighted per-type via `spawn`. |
| Object pooling | **Partial** | Client pools projectiles; monsters are not pooled (cap 100). |
| Interest management (AoI) | **Implemented** | See [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md). |
| Behavior tree (bosses/elites) | **Vision** | Not needed for the POC. |
| Blackboard (shared AI memory) | **Vision** | — |
| Strategy objects (movement/targeting) | **Vision** | Today's strategy variance is the difficulty lerp + `ai_profile` string. |
| NavMesh / pathfinding | **Vision** | Reactive obstacle avoidance only; no A*. |
| Telegraph / cooldown ability select | **Planned** | One ability (toxic spit) on a fixed cooldown; `abilities` array reserved. |
| Loot tables / XP | **Planned** | `loot` carried, unused; no economy in the POC. |
| Group AI / boss phases | **Vision** | — |
| Debug tools / designer tuning | **Partial** | Edit JSON + restart; `monster_ai_difficulty` config knob; no live tuner. |

## Designer spec template

For each new monster, fill this (it maps 1:1 onto the JSON groups above):

```
Identity:    id · display_name · archetype · faction · tier · ai_profile
Stats:       max_health · move_speed · hitbox_radius
Perception:  detection_range · lose_interest_range · retarget_interval · leash_range
Combat:      attack_range · flee_distance · preferred_distance ·
             shoot_cooldown · attack_duration · projectile_speed · projectile_damage
Movement:    steering_randomness · avoidance_distance   (reactive avoidance; no navmesh)
Abilities:   [ { id, type, damage, cooldown, telegraph } ]      (Planned)
Appearance:  core_color · glow_color · shell_color  (client render only)
Loot/Spawn:  xp · table · weight · biomes            (Planned)
Networking:  server_authoritative · replicated[] · client_predicted
```

## Edge cases (server-authoritative answers)

| Situation | Behaviour |
|---|---|
| Target player disconnects / dies | `MonsterAI` drops the target → IDLE; reselects next Tick (`monster_ai._get_target`). |
| Monster gets stuck on geometry | Reactive avoidance rotates to the best of 5 candidate angles; no pathfinding, so wall-hugging is possible (known limit). |
| Monster pulled too far | Beyond `lose_interest_range` the target is dropped (soft leash). Hard home-leash is **Planned**. |
| All players dead/absent | Spawner requires ≥1 alive player (`monster_spawner.gd`); idle monsters stand still. |
| Damaged while returning home | No "returning" state yet (no hard leash); it simply reacquires a target if one is in range. |
| Unknown `type_id` requested | `MonsterDatabase.get_definition` warns and falls back to the default definition (never null). |
| JSON missing / malformed | Loader warns, skips the file, and `_ensure_default()` guarantees the Toxic Slime exists. |

## The eight questions

- **Client:** reads `display_name` (kill feed) and `appearance` colors (sprite) from the shared
  catalogue; renders one archetype until the wire carries a subtype. No AI.
- **Server:** owns the catalogue, the factory, and 100% of AI driven from each monster's definition.
- **Predicted:** nothing — monsters are never predicted.
- **Replicated:** position, animation, flags (unchanged 9-byte entity); **not** the archetype yet.
- **Persisted:** nothing — definitions are content (res://), monster *state* is in-memory only.
- **Validated:** monster moves are bounds/obstacle-clamped; definitions fall back field-by-field,
  so bad data degrades to defaults rather than crashing.
- **Can fail:** missing JSON from an export (mitigated by the manifest + default); per-type damage
  not wired (documented coupling); no hard leash / navmesh (documented limits).
- **Tested:** compiles clean under `godot --headless --editor --quit`; behaviour preserved by
  construction (the Toxic Slime JSON reproduces the prior constants). No isolated AI unit tests.

## See also

- [`monsters-ai.md`](monsters-ai.md) — the runtime AI state machine, perception, movement, shooting.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Tick, Remote entity, Snapshot).
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — where the archetype byte would go.
- `client/data/monsters/toxic_slime.json` — the reviewable data sheet.
