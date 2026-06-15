# Mage (class id 6)

**Status:** Implemented (2026-06-13). A glass-cannon caster — lowest HP, the largest flavor Mana pool,
the highest primary damage, and a long-range burst-AOE Class ability. Numbers mirror
[`mage.json`](../../../client/data/classes/mage.json) and the Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 80 | +4 | 276 |
| Move speed | 195 | +0.5 | 219.5 |
| Mana max | 100 | — (flavor pool 130) | 100 |
| Mana regen | 2 /s | — | 2 /s |
| Stamina max | 100 | — | 100 |
| Stamina regen | 14 /s | — | 14 /s (30% below Warrior/Rogue's 20/s) |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 28 | +3 | 175 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Mageblast

An **instant AOE explosion** at the cursor — no travel time, big single burst.

| Param | Value |
|---|---|
| `mana_cost` | 40 |
| `cooldown` | 6 s |
| `radius` | 144 |
| `damage` | 55 |
| `max_cast_range` | 600 |

**Behavior.** On cast the server validates Mana/cooldown, deducts Mana, clamps the cursor target to
`max_cast_range` (600) of the caster, and resolves an instant AOE at that point: every monster within
144 (`radius`) takes 55 (`damage`) in a single burst. There is no projectile and no lingering entity —
only an `ABILITY_EFFECT` VFX event marks the explosion. All damage is server-side.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the explosion from the `ABILITY_EFFECT` event.
- **Server:** authoritative — validates Mana/cooldown, clamps the target to range, applies the instant 55 AOE within radius 144.
- **Predicted:** nothing — the explosion is instant and server-resolved; only the Mage's own movement is predicted.
- **Replicated:** an `ABILITY_EFFECT` event carrying the blast center + radius (no persistent entity).
- **Persisted:** nothing — the blast is a one-shot.
- **Validated:** Mana ≥ cost, cooldown elapsed, and cast point within `max_cast_range` — all server-side.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; an out-of-range cursor is clamped, not rejected.
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; AOE radius + range clamp by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../CONTEXT.md`](../../CONTEXT.md)
