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

Cooldown 0.3 s, projectile speed 400 (shared). Projectile reach **800** units — full baseline,
vs the Warrior/Rogue's throttled 560, so the Mage out-ranges both melee bruisers.

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
`max_cast_range` (600) of the caster, and resolves an instant AOE at that point: every **monster**
within 144 (`radius`) takes 55 (`damage`) in a single burst. **In PvP it also hits players:** every
**other** player within the radius (the caster is never caught by their own blast) takes the same 55
and is **Dazed** — sprint and dash locked out for 1.5 s (`PLAYER_DAZE_DURATION`), the same control
debuff a sprint-hit applies; walking is unaffected. The player damage is gated by the arena PvP flag,
so it does nothing in the safe Sanctuary. There is no projectile and no lingering entity — only an
`ABILITY_EFFECT` VFX event marks the explosion, and the Daze rides the existing `DAZED` entity flag.
All damage and effects are server-side.

The Daze is wired through a reusable **on-hit effect system** (`ability::StatusEffect`, applied in
`combat::apply_player_damage`): Mageblast lists `Daze` in its `ability_effects`, and future spells
can gain Daze/slow/burn/etc. by listing them — see [`../systems/abilities.md`](../../systems/abilities.md).

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the explosion from the `ABILITY_EFFECT` event; shows the Daze star-indicator from the replicated `DAZED` flag.
- **Server:** authoritative — validates Mana/cooldown, clamps the target to range, applies the instant 55 AOE to monsters and (PvP) to other players in radius, dazing the players hit.
- **Predicted:** nothing — the explosion is instant and server-resolved; only the Mage's own movement is predicted. A victim's client slaves its local Daze to the server's `DAZED` flag edge.
- **Replicated:** an `ABILITY_EFFECT` event (blast center + radius), per-victim `DAMAGE`, and the `DAZED` entity flag on each dazed player. No persistent entity.
- **Persisted:** nothing — the blast is a one-shot.
- **Validated:** Mana ≥ cost, cooldown elapsed, cast point within `max_cast_range`, and PvP enabled for player damage — all server-side.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; an out-of-range cursor is clamped, not rejected; player damage/daze is skipped where PvP is disabled (Sanctuary).
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; unit tests for the effect dispatch + the PvP AoE (damage + daze, caster excluded, PvP-gated); AOE radius + range clamp by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../CONTEXT.md`](../../CONTEXT.md)
