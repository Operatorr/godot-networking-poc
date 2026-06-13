# Plague Seer (class id 3)

**Status:** Implemented (2026-06-13). An area-denial caster — modest HP, the second-largest flavor
Mana pool, and a placed damage-over-time zone for grinding down groups. Numbers mirror
[`plague_seer.json`](../../client/data/classes/plague_seer.json) and the Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 95 | +5 | 340 |
| Move speed | 195 | +0.5 | 219.5 |
| Mana max | 100 | — (flavor pool 120) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 20 | +2 | 118 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Plague Zone

Place an **AOE damage-over-time zone** at the cursor; monsters standing in it take steady damage for
its duration.

| Param | Value |
|---|---|
| `mana_cost` | 35 |
| `cooldown` | 7 s |
| `radius` | 100 |
| `duration` | 5 s |
| `dps` | 12 |
| `max_cast_range` | 500 |

**Behavior.** On cast the server validates Mana/cooldown, deducts Mana, clamps the cursor target to
`max_cast_range` (500) of the caster, and spawns a DoT zone world effect (subtype `dot-zone`, id band
40000–49999) at that point. Each tick, every monster within 100 (`radius`) takes the per-second rate
of 12 (`dps`) prorated over the tick. The zone expires after 5 s. All damage is server-side.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the placed zone entity + `ABILITY_EFFECT` VFX.
- **Server:** authoritative — validates Mana/cooldown, clamps the cast point to range, spawns the zone, applies 12 dps to monsters inside each tick, expires it at 5 s.
- **Predicted:** nothing about the zone — only the Plague Seer's own movement is predicted.
- **Replicated:** the DoT-zone effect entity (world-effect band) + an `ABILITY_EFFECT` event for the cast VFX.
- **Persisted:** nothing — the zone is Session-ephemeral.
- **Validated:** Mana ≥ cost, cooldown elapsed, and cast point within `max_cast_range` — all server-side.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; an out-of-range cursor is clamped, not rejected.
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; zone DoT + range clamp by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../systems/abilities.md) · [`../CONTEXT.md`](../CONTEXT.md)
