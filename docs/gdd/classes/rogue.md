# Rogue (class id 5)

**Status:** Implemented (2026-06-15). The fastest, most fragile Class — a hit-and-run assassin whose
**Shadowstep** Class ability **always teleports**: it strikes from the shadows (an AOE on landing),
then **vanishes** into Stealth. The teleport is **server-authoritative — not predicted** (the client
snaps to the corrected position on the next snapshot). Numbers mirror
[`rogue.json`](../../../client/data/classes/rogue.json) and the Rust server constants.

> Vocabulary: [`../../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 85 | +4 | 281 |
| Move speed | 215 | +0.9 | 259.1 |
| Mana max | 100 | — (flavor pool 100) | 100 |
| Mana regen | 2 /s | — | 2 /s |
| Stamina max | 100 | — | 100 |
| Stamina regen | 20 /s | — | 20 /s |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 24 | +2 | 122 |

Cooldown 0.3 s, projectile speed 400 (shared). Projectile reach is **560** units — a deliberate
30% cut below the 800 baseline (`projectile_max_distance`), so this short-range assassin must
close in while the Mage and ranged kits poke from outside its range.

## Class ability (RMB) — Shadowstep

**Always teleports.** Find the **nearest character to the cursor** (monster **or** other player/bot)
within a search radius; **land behind it**, deal an **AOE strike to nearby monsters**, then **vanish**
into Stealth. With nothing near the cursor, the Rogue still blinks — toward the cursor, capped at the
blink range. Every cast ends in Stealth (invisible to AI targeting — monsters/bots drop aggro).

| Param | Value |
|---|---|
| `mana_cost` | 30 |
| `cooldown` | 10 s |
| `cursor_search_radius` | 160 |
| `blink_range` (empty-ground cap) | 450 |
| `landing_aoe_radius` | 100 |
| `landing_aoe_damage` | 85 |
| `stealth_duration` | 5 s |

**Behavior.** On cast the server validates Mana/cooldown and deducts Mana, then:

1. **Pick a target.** Search for the **nearest-to-cursor alive character within 160
   (`cursor_search_radius`) of the cursor**, considering **both monsters and other players/bots**
   (the caster is excluded; projectiles/world entities are never targeted).
2. **Land.**
   - **Target found:** teleport **behind** it — opposite its **facing**, one
     `PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS` (= 32) away — the same offset for every target
     type. *Facing* = the target's **shoot/aim
     direction** if it is currently attacking (player: aim direction while the SHOOT flag is held;
     monster: the direction to its current target while attacking); else its **travel/velocity
     direction**; else (idle) it falls back to the direction **back toward the Rogue's origin**.
   - **No target:** teleport to the **cursor, clamped to `blink_range` (450)** from the Rogue.
   - Either way the landing point is **clamped to arena bounds**, the Rogue's velocity is zeroed, and
     its movement state is interrupted to idle.
3. **Strike.** Deal **85 (`landing_aoe_damage`)** as an **AOE to all alive monsters within 100
   (`landing_aoe_radius`) of the landing point** — **PvE only** (players/bots are never damaged). The
   radius is ≥ 32 by construction, so the monster the Rogue landed behind is always hit, plus a small
   splash. Kills roll Healthorbs on the shared PvE path.
4. **Vanish.** **After** the strike the server sets the `STEALTH` entity flag (bit 9) for 5 s
   (`stealth_duration`). Monster/bot AI treats a stealthed player as untargetable and drops aggro.
   Stealth runs its full duration — it **no longer breaks** on dealing damage.

The whole teleport + strike + Stealth is **server-authoritative**; the client snaps to the corrected
position on the next snapshot and renders the `ABILITY_EFFECT` VFX at the landing point.

### The eight questions (this ability)

- **Client:** sends the ability flag + cursor; renders the `ABILITY_EFFECT` at the landing point and the Stealth visual (own translucency); learns the new position from the snapshot and Stealth from the replicated flag.
- **Server:** authoritative — validates Mana/cooldown, picks the nearest character to the cursor, lands the Rogue behind it (or blinks toward the cursor capped at `blink_range`), applies the 85 landing AOE to monsters, then sets `STEALTH` for 5 s.
- **Predicted:** **nothing** — the teleport is *not* client-predicted (unlike Warrior Charge). The body moves only when the server snapshot arrives.
- **Replicated:** position (the teleport lands in the normal player snapshot), the `STEALTH` entity flag (bit 9), and an `ABILITY_EFFECT` event for the strike/blink VFX.
- **Persisted:** nothing — the teleport and Stealth are Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed; target selection, landing point, and Stealth are entirely server-side; the client cannot self-declare position or Stealth.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op. There is no "stand still" outcome — a valid cast always teleports.
- **Tested:** Rust unit tests in `world.rs` — empty-ground blink is capped at `blink_range`; lands behind a target given a known facing; the landing AOE kills the targeted monster; every cast enters Stealth and the flag replicates. Load-test bots now skip `STEALTH` targets (`load_test/behavior.rs`).

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../systems/players-movement.md`](../../systems/players-movement.md) · [`../CONTEXT.md`](../../CONTEXT.md)
