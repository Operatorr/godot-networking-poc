# Warrior (class id 4)

**Status:** Implemented (2026-06-13). The tankiest Class — highest HP, smallest flavor Mana pool, and
a gap-closing **Charge** Class ability that is a _predicted movement_ (invulnerable while dashing)
ending in an AOE blast. Numbers mirror [`warrior.json`](../../../client/data/classes/warrior.json) and the
Rust server constants.

> Vocabulary: [`../../CONTEXT.md`](../../CONTEXT.md). Stat scaling: [`../systems/PROGRESSION.md`](../../systems/PROGRESSION.md).
> The ability system: [`../systems/abilities.md`](../../systems/abilities.md).

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; max level **50**.

| Stat          | Base  | Per level          | At L50 |
| ------------- | ----- | ------------------ | ------ |
| HP            | 130   | +9                 | 571    |
| Move speed    | 200   | +0.6               | 229.4  |
| Mana max      | 100   | — (flavor pool 90) | 100    |
| Mana regen    | 2 /s  | —                  | 2 /s   |
| Stamina max   | 100   | —                  | 100    |
| Stamina regen | 20 /s | —                  | 20 /s  |
| Hitbox radius | 16    | —                  | 16     |

## Primary attack (LMB)

|                | Base | Per level | At L50 |
| -------------- | ---- | --------- | ------ |
| Primary damage | 25   | +2.5      | 147.5  |

Cooldown 0.3 s, projectile speed 400 (shared). Projectile reach is **560** units — a deliberate
30% cut below the 800 baseline (`projectile_max_distance`), so this melee bruiser must close in
while the Mage and ranged kits poke from outside its range.

## Class ability (RMB) — Charge

**Hold RMB** to charge **toward the cursor**. The charge **steers** — each tick it re-aims toward the
live mouse position, so moving the mouse turns the charge (you can charge around corners). The Warrior
is **invulnerable** for the duration and travels up to a maximum distance; on charge end (release, max
distance) **or** on contact with an enemy, an AOE blast fires at the Warrior's position.

| Param                                    | Value |
| ---------------------------------------- | ----- |
| `mana_cost` (activation, buys a min charge) | 30    |
| `charge_mana_drain` (over the draining 60%) | 10    |
| min drain-free distance (`CHARGE_MIN_DISTANCE_FRACTION`) | 40% (~378 u) |
| `cooldown`                               | 4.5 s |
| `charge_speed`                           | 720   |
| `max_distance`                           | 945   |
| `blast_radius`                           | 120   |
| `blast_damage`                           | 50    |
| `invulnerable_while_charging`            | true  |

**Mana economy.** Activation costs **30**, which always buys a **guaranteed minimum charge**: the
first **40%** of the distance (`CHARGE_MIN_DISTANCE_FRACTION`, ~378 u) is **drain-free**, so a
low-mana cast still delivers a real gap-close instead of fizzling. **Beyond** that minimum the charge
**drains mana per unit travelled**, totalling **10** (`charge_mana_drain`) over the remaining 60% of a
full charge (~**40** total). Mana **does not regenerate while charging**. If mana runs out in the
draining zone, the charge **ends there and fires the blast** — so once you're past the guaranteed
minimum, mana (not just the distance cap) bounds how far you charge.

**Behavior.** The Charge is **predicted, steerable movement** (the `Charging` state in the shared
`sim_core` `MovementSm::tick_charging`): each tick the charge velocity re-aims toward `aim_dir` (the
cursor direction the client computes and sends, identical on both sides), so the Warrior follows the
mouse. A near-instant aim reversal (~≥105°) is **refused** — the charge coasts straight — so reaching
or overshooting the cursor doesn't flip-flop the heading. The client predicts the steering immediately
while the server runs the identical motion as authority. The mana drain lives in the shared sim too
(`tick_charging` bleeds `charge_mana_drain` per unit and ends the charge — flagging the blast — when
mana hits 0), so the client predicts the early end in lockstep; the server clearing the `DASHING`
flag also slaves the predicted charge end. The server owns everything _else_: it validates
Mana/cooldown and starts the charge, drives the body at 720 up to 945 (`max_distance`), holds the
`INVULNERABLE` flag while charging, and on charge end (release / max distance / **mana depletion**) or
enemy contact deals 50 (`blast_damage`) to every monster within 120 (`blast_radius`) — an AOE — then
ends the state and starts the cooldown. Invulnerability and damage are server-authoritative; the
steering motion and mana drain are shared.

**Audio.** A low looping rumble plays **while charging** (`AudioManager.play_charge_loop` /
`stop_charge_loop`, driven by the predicted charge edges in `prediction.gd`), and the `charge` impact
SFX fires on the `CHARGE_BLAST` effect when it connects.

**VFX.** The blast plays a generated orange fiery-nova sprite animation (`charge_blast`) via
`BlastEffect`, and a **shader-driven GPU particle trail** (`ChargeTrail`) streams orange embers
behind the Warrior while charging (created on the same predicted charge edges as the rumble). Both
are render-only; see
[`arena-visuals.md`](../../systems/arena-visuals.md#ability-blast-effects--charge-trail-implemented-2026-06-17).

### The eight questions (this ability)

- **Client:** holds the ability flag + cursor in `PlayerInput`; **predicts the dash motion** via `sim_core`; renders the `INVULNERABLE` flash and the blast `ABILITY_EFFECT`.
- **Server:** authoritative — validates Mana/cooldown, runs the identical charge motion, holds invulnerability, caps distance, fires the AOE blast (50 in radius 120) on end/contact.
- **Predicted:** the Warrior's **steerable charge movement** and the **mana drain / early charge end** (same `sim_core` motion the server runs — zero divergence by construction); **not** the invulnerability or the blast damage.
- **Replicated:** position (charge motion is in the normal player snapshot), the `INVULNERABLE` entity flag, and an `ABILITY_EFFECT` event for the blast.
- **Persisted:** nothing — the charge state is Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed, server-side; the server caps the dash distance even if the client over-predicts.
- **Can fail:** insufficient Mana or on cooldown ⇒ no-op; if the client mispredicts the dash end the server correction snaps it back (rare — same `sim_core`).
- **Tested:** protocol round-trip for the ability flag + `ABILITY_EFFECT`; predicted-charge parity via the prediction-snap monitor; blast + invuln by play-test.

## See also

- [`index.md`](index.md) · [`../systems/abilities.md`](../../systems/abilities.md) · [`../systems/players-movement.md`](../../systems/players-movement.md) · [`../CONTEXT.md`](../../CONTEXT.md)
