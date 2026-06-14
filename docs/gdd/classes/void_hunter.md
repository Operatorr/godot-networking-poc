# Void Hunter (class id 1)

**Status:** Implemented (2026-06-13). A mobile ranged skirmisher — fast, fragile, highest primary
damage of the projectile Classes, with a burst-spread Class ability. Numbers mirror
[`void_hunter.json`](../../../client/data/classes/void_hunter.json) and the Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 90 | +5 | 335 |
| Move speed | 205 | +0.7 | 239.3 |
| Mana max | 100 | — (flavor pool 100) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 26 | +2.5 | 148.5 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Multishot

Fire **5 piercing projectiles** in a spread centered on the aim direction.

| Param | Value |
|---|---|
| `mana_cost` | 30 |
| `cooldown` | 5 s |
| `projectiles` | 5 |
| `spread_degrees` | 28° |
| `pierce` | 4 |
| `damage` | 18 (each) |

**Behavior.** On cast the server validates Mana/cooldown, deducts Mana, and spawns 5 projectiles fanned
across 28° centered on the cursor/aim direction. Each projectile deals 18 on hit and passes through up
to 4 monsters before expiring. Projectiles use the normal projectile id band (10000–29999) and the
server-authoritative collision pass.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the 5 projectiles + `ABILITY_EFFECT` VFX.
- **Server:** authoritative — validates Mana/cooldown, spawns the spread, resolves piercing hits (18 each, up to 4 monsters per projectile).
- **Predicted:** nothing about the projectiles — only the Void Hunter's own movement is predicted.
- **Replicated:** the 5 projectile entities + an `ABILITY_EFFECT` event for the cast VFX.
- **Persisted:** nothing — projectiles are Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed, server-side.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op (no Mana spent).
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; spread/pierce by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../CONTEXT.md`](../../CONTEXT.md)
