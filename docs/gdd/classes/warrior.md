# Warrior (class id 4)

**Status:** Implemented (2026-06-13). The tankiest Class — highest HP, smallest flavor Mana pool, and
a gap-closing **Charge** Class ability that is a *predicted movement* (invulnerable while dashing)
ending in an AOE blast. Numbers mirror [`warrior.json`](../../../client/data/classes/warrior.json) and the
Rust server constants.

> Vocabulary: [`../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat | Base | Per level | At L50 |
|---|---|---|---|
| HP | 130 | +9 | 571 |
| Move speed | 200 | +0.6 | 229.4 |
| Mana max | 100 | — (flavor pool 90) | 100 |
| Mana regen | 8 /s | — | 8 /s |
| Stamina max | 100 | — | 100 |
| Hitbox radius | 16 | — | 16 |

## Primary attack (LMB)

| | Base | Per level | At L50 |
|---|---|---|---|
| Primary damage | 25 | +2.5 | 147.5 |

Cooldown 0.3 s, projectile speed 400 (shared).

## Class ability (RMB) — Charge

**Hold RMB** to dash in the aim/move direction. The Warrior is **invulnerable** for the duration of
the charge and travels up to a maximum distance; on charge end (release, max distance) **or** on
contact with an enemy, an AOE blast fires at the Warrior's position.

| Param | Value |
|---|---|
| `mana_cost` | 40 |
| `cooldown` | 9 s |
| `charge_speed` | 720 |
| `max_distance` | 420 |
| `blast_radius` | 120 |
| `blast_damage` | 50 |
| `invulnerable_while_charging` | true |

**Behavior.** The Charge is **predicted movement** (an `AbilityMovement` state in the shared
`sim_core`, mirroring sprint/dash): the client predicts the dash immediately on the held flag while the
server runs the identical motion as authority — so it feels instant and never snaps. The server owns
everything *else*: it validates Mana/cooldown and starts the charge, drives the body at 720 up to 420
(`max_distance`), holds the `INVULNERABLE` flag while charging, and on charge end or enemy contact
deals 50 (`blast_damage`) to every monster within 120 (`blast_radius`) — an AOE — then ends the state
and starts the cooldown. Invulnerability and damage are server-authoritative; the motion is shared.

### The eight questions (this ability)

- **Client:** holds the ability flag + cursor in `PlayerInput`; **predicts the dash motion** via `sim_core`; renders the `INVULNERABLE` flash and the blast `ABILITY_EFFECT`.
- **Server:** authoritative — validates Mana/cooldown, runs the identical charge motion, holds invulnerability, caps distance, fires the AOE blast (50 in radius 120) on end/contact.
- **Predicted:** the Warrior's **charge movement** (same `sim_core` motion the server runs — zero divergence by construction); **not** the invulnerability or the blast damage.
- **Replicated:** position (charge motion is in the normal player snapshot), the `INVULNERABLE` entity flag, and an `ABILITY_EFFECT` event for the blast.
- **Persisted:** nothing — the charge state is Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed, server-side; the server caps the dash distance even if the client over-predicts.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; if the client mispredicts the dash end the server correction snaps it back (rare — same `sim_core`).
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; predicted-charge parity via the prediction-snap monitor; blast + invuln by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../systems/players-movement.md`](../../systems/players-movement.md) · [`../CONTEXT.md`](../../CONTEXT.md)
