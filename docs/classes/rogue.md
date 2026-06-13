# Rogue (class id 5)

**Status:** Implemented (2026-06-13). The fastest, most fragile Class — a hit-and-run assassin whose
**Shadowstep** Class ability either blinks to a target for a big hitscan or, with no target, grants
**Stealth**. The blink is *predicted movement*. Numbers mirror
[`rogue.json`](../../client/data/classes/rogue.json) and the Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 85 | +4 | 281 |
| Move speed | 215 | +0.9 | 259.1 |
| Mana max | 100 | — (flavor pool 100) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 24 | +2 | 122 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Shadowstep

Blink to the **closest monster within a radius of the cursor** and deal a big hitscan hit. If **no
monster** is in that radius, the Rogue instead enters **Stealth** (invisible to AI targeting —
monsters/bots drop aggro) for a few seconds.

| Param | Value |
|---|---|
| `mana_cost` | 30 |
| `cooldown` | 10 s |
| `cursor_search_radius` | 160 |
| `hitscan_damage` | 85 |
| `stealth_duration` | 5 s |
| `stealth_breaks_on_damage_dealt` | true |

**Behavior.** On cast the server validates Mana/cooldown and deducts Mana, then searches for monsters
within 160 (`cursor_search_radius`) of the cursor point:

- **Target found:** the Rogue **blinks** to the closest one (predicted movement — the client moves the
  body immediately; the server runs the same teleport as authority) and the server applies an 85
  (`hitscan_damage`) hitscan hit to it.
- **No target:** the server sets the `STEALTH` entity flag (bit 9) for 5 s (`stealth_duration`).
  Monster/bot AI treats a stealthed player as untargetable and drops aggro. Stealth **breaks early**
  the moment the Rogue deals damage (primary or ability).

The blink destination/teleport is predicted; the hitscan damage and the Stealth state are
server-authoritative.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; **predicts the blink teleport** via `sim_core`; renders the hitscan `ABILITY_EFFECT` and the Stealth visual (own translucency); learns Stealth from the replicated flag.
- **Server:** authoritative — validates Mana/cooldown, picks the closest monster in `cursor_search_radius`, applies the 85 hitscan **or** sets `STEALTH` for 5 s, and breaks Stealth on the Rogue's next damage dealt.
- **Predicted:** the Rogue's **blink movement** (same `sim_core` teleport the server runs); **not** the hitscan damage, the target choice, or the Stealth state.
- **Replicated:** position (the blink lands in the normal player snapshot), the `STEALTH` entity flag (bit 9), and an `ABILITY_EFFECT` event for the hitscan/blink VFX.
- **Persisted:** nothing — the blink and Stealth are Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed; target selection and Stealth eligibility are server-side; the client cannot self-declare Stealth.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; if the client predicts a blink to a target the server rejects, the correction snaps the Rogue back.
- **Tested:** protocol round-trip for the ability flag, `ABILITY_EFFECT`, and the `STEALTH` flag bit; aggro-drop + early break by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../systems/abilities.md) · [`../systems/players-movement.md`](../systems/players-movement.md) · [`../CONTEXT.md`](../CONTEXT.md)
