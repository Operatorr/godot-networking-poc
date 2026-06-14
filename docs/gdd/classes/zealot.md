# Zealot (class id 0)

**Status:** Implemented (2026-06-13). The frontline Class — high HP, average everything else, and a
defensive-zone Class ability (orbiting orbs that punish anything that closes in). Numbers mirror
[`zealot.json`](../../../client/data/classes/zealot.json) and the Rust server constants (the authority).

> Vocabulary: [`../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 120 | +8 | 512 |
| Move speed | 195 | +0.5 | 219.5 |
| Mana max | 100 | — (flavor pool 100) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

Shared model across Classes: a projectile on a **0.3 s** cooldown at **400** speed. Damage scales:

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 22 | +2 | 120 |

## Class ability (RMB) — Spinning Bibles

Spawn **3 orbs** that orbit the Zealot for **5 s**, sweep-damaging monsters they pass through.

| Param | Value |
|---|---|
| `mana_cost` | 35 |
| `cooldown` | 8 s |
| `orbs` | 3 |
| `orbit_radius` | 80 |
| `angular_speed` | 3.0 rad/s |
| `duration` | 5 s |
| `damage` | 15 / hit |
| `rehit_interval` | 0.4 s |

**Behavior.** On cast the server checks ≥ 35 Mana and the cooldown, deducts Mana, starts the
cooldown, and spawns 3 orb world effects (subtype `bible`, id band 40000–49999) parented to the
Zealot, evenly phased around the orbit. Each orb sweeps; a monster overlapped by an orb takes 15
damage, then cannot be re-hit by the *same* orb for 0.4 s. The orbs expire after 5 s. All hit
resolution is server-side.

### The eight questions (this ability)

- **Client:** sends the RMB ability flag + cursor in `PlayerInput`; renders the orbiting orbs from
  the `ABILITY_EFFECT` event + replicated effect entities; plays VFX/SFX.
- **Server:** authoritative — validates Mana/cooldown, spawns the orbs, sweeps them each tick, applies
  15-damage hits with per-orb 0.4 s re-hit gating, expires them at 5 s.
- **Predicted:** nothing about the orbs (no damage, no spawn) — only the Zealot's own movement is
  predicted, unchanged by the cast.
- **Replicated:** the orb effect entities (position via the kind-3 world-effect band) and an
  `ABILITY_EFFECT` event for the spawn VFX.
- **Persisted:** nothing — orbs are Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed, server-side; the client request is advisory.
- **Can fail:** insufficient Mana or ability on cooldown ⇒ the server no-ops the cast (no Mana spent).
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; sweep/re-hit by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../CONTEXT.md`](../../CONTEXT.md)
