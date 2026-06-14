# Engineer (class id 2)

**Status:** Implemented (2026-06-13). A zone-control Class — average durability, the largest flavor
Mana pool, and a placed proximity-mine Class ability for denying ground. Numbers mirror
[`engineer.json`](../../../client/data/classes/engineer.json) and the Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 100 | +6 | 394 |
| Move speed | 195 | +0.5 | 219.5 |
| Mana max | 100 | — (flavor pool 110) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 24 | +2 | 122 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Mine

Drop a **proximity mine** at the Engineer's feet; after a short arm delay it explodes when a monster
enters its trigger radius.

| Param | Value |
|---|---|
| `mana_cost` | 35 |
| `cooldown` | 8 s |
| `trigger_radius` | 60 |
| `blast_radius` | 120 |
| `damage` | 60 |
| `arm_delay` | 0.5 s |
| `lifetime` | 30 s |

**Behavior.** On cast the server validates Mana/cooldown, deducts Mana, and spawns a mine world effect
(subtype `mine`, id band 40000–49999) at the Engineer's position. The mine is inert for 0.5 s
(`arm_delay`), then watches for any monster within 60 (`trigger_radius`). On trigger it deals 60 to
every monster within 120 (`blast_radius`) — an AOE — and despawns. If untriggered it despawns at 30 s
(`lifetime`). All detection and damage are server-side.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the placed mine entity + arm/blast `ABILITY_EFFECT` VFX.
- **Server:** authoritative — validates Mana/cooldown, spawns the mine, runs the arm timer, proximity check, AOE blast (60 in radius 120), and lifetime expiry.
- **Predicted:** nothing about the mine — only the Engineer's own movement is predicted.
- **Replicated:** the mine effect entity (world-effect band) + `ABILITY_EFFECT` events for spawn and blast.
- **Persisted:** nothing — the mine is Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed, server-side.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; an untriggered mine simply expires at 30 s.
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; arm/trigger/blast by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../CONTEXT.md`](../../CONTEXT.md)
