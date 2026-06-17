# Class abilities — the RMB ability system

**Status:** Implemented (2026-06-13). Every Class has one **Class ability** bound to the right mouse
button, paid for in **Mana**, on its own cooldown. This doc is the system-level home; per-Class
parameters and behavior live in [`../classes/`](../gdd/classes/index.md). The wire additions this system
introduced bumped the protocol to **v4** — see [`../server/contract.md`](../server/contract.md).

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md) ("Classes & abilities", "Combat & survival"):
> **Class ability** is the RMB active, distinct from the shared primary attack (LMB); **Mana** pays
> for it; **AOE**, **Stealth**, **Healthorb** are combat/survival terms. Governing rule:
> **the client requests, the server decides.**

## The shape of an ability cast

1. **Input.** The client samples the RMB-held state into an **ability input flag** in `PlayerInput`
   (alongside the existing move/sprint/dash/attack flags) and, new in protocol v4, the **cursor
   target** as two `i16` (quantized world position, +4 B → `PlayerInput` is now 22 B). The cursor is
   what point-target abilities (Mageblast, Plague Zone) and target-search abilities (Shadowstep) aim
   at; movement abilities (Charge) use it as the dash direction reference.
2. **Server dispatch.** On the tick, the server reads the ability flag for the player, looks up the
   player's Class, and dispatches to that Class's ability handler. The handler first gates on
   **Mana ≥ cost** and **cooldown elapsed**; if either fails it **no-ops** (no Mana spent, no
   cooldown started). Otherwise it deducts Mana, starts the cooldown, and resolves the effect.
3. **Effect resolution.** All damage and spawns are **server-authoritative**. Effects fall into four
   shapes (see the table below): instant AOE, spawned world-effect entity, projectile spread, or a
   movement state.
4. **Replication.** The server broadcasts an **`ABILITY_EFFECT`** game event (`effect_id, x, y,
   radius`) so clients can play the VFX/SFX, plus — for abilities that leave a lingering entity — the
   world-effect entity itself in the snapshot stream.

## World-effect entities (kind 3, id band 40000–49999)

Lingering ability effects are a **fourth entity kind** on the wire (typed-id kind tag `3`, new in
protocol v4), with their own id band **40000–49999** partitioned into 2500-id sub-bands by subtype:

| Sub-band | Subtype | Source ability | Lifetime behavior |
|---|---|---|---|
| 40000–42499 | `0` healthorb | monster death drop (not an ability) | walk-over pickup heals +5 HP |
| 42500–44999 | `1` mine | Engineer — Mine | arms (0.5 s), proximity-triggers, AOE blast, expires at 30 s |
| 45000–47499 | `2` dot-zone | Plague Seer — Plague Zone | DoT 12/s within radius for 5 s |
| 47500–49999 | `3` bible | Zealot — Spinning Bibles | 3 orbs orbit the caster for 5 s, sweep-damage |

These ride the normal snapshot/AoI/delta machinery (position quantized to 0.1 unit like any entity).
Mageblast and Multishot leave **no** world-effect entity — Mageblast is instant (event-only) and
Multishot spawns ordinary projectiles (band 10000–29999).

> **Healthorb** is listed here because it shares the world-effect entity kind, but it is **not** an
> ability — it is a monster-death drop (50% chance) that heals **+5 HP** (clamped to max) on walk-over.
> Pickup is server-authoritative and reported via the `PICKUP` event (now carrying `{kind, amount}`).

## Abilities by effect shape

| Class | Ability | Shape | Predicted? | Server-authoritative |
|---|---|---|---|---|
| Mage | Mageblast | instant AOE (event only) | no | range-clamp, AOE damage to monsters **and (PvP) players**, **Daze** on players hit |
| Plague Seer | Plague Zone | spawned `dot-zone` entity | no | range-clamp, spawn, per-tick DoT |
| Engineer | Mine | spawned `mine` entity | no | spawn, arm, proximity trigger, AOE blast |
| Zealot | Spinning Bibles | spawned `bible` entities | no | spawn, orbit, sweep + re-hit gating |
| Void Hunter | Multishot | projectile spread (10000–29999) | no | spawn spread, piercing hits |
| Warrior | Charge | **steerable movement** (`Charging`, follows cursor) | **yes** (motion + mana drain) | invulnerability, distance cap (945), mana drain, blast |
| Rogue | Shadowstep | **teleport** (always) + landing AOE + Stealth | **no** (server snaps) | target pick, teleport, landing AOE, `STEALTH` flag |

**The prediction rule.** Only **Warrior Charge** is predicted, and only its *motion*: Charge runs
through the shared `sim_core` `Charging` state (`tick_charging`), which **steers toward the cursor**
each tick (re-aims along `aim_dir`, refusing near-reversals) up to `max_distance` (945). The first 40%
(`CHARGE_MIN_DISTANCE_FRACTION`) is **drain-free** — the activation guarantees that minimum charge —
then it **drains mana per unit** beyond it (ending early with a blast if mana runs out). The client
predicts the steering and the mana-bounded end with zero divergence from the server. **Rogue Shadowstep is _not_ predicted** — the teleport is fully
server-authoritative and the client snaps to the corrected position on the next snapshot. Everything
else — all damage, every spawn, invulnerability, target selection, Stealth — is decided by the server
and learned by the client through `ABILITY_EFFECT`, replicated entity flags, or the effect entities.

## On-hit status effects (Strategy dispatch)

Abilities that damage players can also inflict **status effects** through a small, extensible system —
added so Mageblast could apply **Daze** and future spells can stack new effects without touching every
hit site:

- **`ability::StatusEffect`** — an enum of effects (`Daze { secs }` today; slow/burn/silence are the
  intended next variants). It is the **Strategy expressed as an enum**: idiomatic Rust, `const`-friendly
  (no heap/vtable), dispatched by one `match` in `combat::apply_player_damage`.
- **`ClassStats::ability_effects: &'static [StatusEffect]`** — the per-class list an ability inflicts on
  every player it damages. Mage lists `&[Daze { secs: PLAYER_DAZE_DURATION }]`; the other six are empty.
- **`combat::apply_player_damage(owner, target, damage, effects, …)`** — the shared player-damage core.
  The projectile path (`apply_player_hit`) calls it with an empty effect list; instant abilities pass
  their own `damage` + `effects`. On survival it applies the sprint-hit Daze, then each listed effect,
  then knockback. Adding a new effect = one enum variant + one match arm; every ability that lists it
  gains it for free.

**Mageblast is the first ability that PvP-damages players.** Its handler calls `aoe_damage_players`
(the PvP mirror of `aoe_damage_monsters`): every *other* alive player within the blast radius takes the
ability damage and the listed effects, gated by the arena PvP flag (a no-op in the safe Sanctuary), and
the caster is never caught by their own blast. The **Daze** itself is the same `MovementSm` debuff a
sprint-hit applies (sprint/dash locked, **walk speed cut 30%** via `PLAYER_DAZE_SPEED_MULTIPLIER`,
1.5 s, re-application extends) and replicates via the existing **`DAZED`** entity flag (bit 8) — no
new wire format, and the client's daze star-indicator + prediction edge-slaving already handle it.
See [`combat-hits.md`](combat-hits.md).

## Stealth (entity flag bit 9)

**Every** Rogue Shadowstep cast sets the **`STEALTH`** entity flag (16-bit entity flags, bit 9 — the
first of the reserved bits 9–15 to be used; bit 8 is `DAZED`) **after** the landing strike — the
assassin strikes, then vanishes. A stealthed player is **invisible to AI targeting**: monster and bot
AI drop aggro and will not re-acquire while the flag is set. Stealth runs its full 5 s and **no longer
breaks** when the Rogue deals damage. The flag is server-owned and replicated.

**Client rendering is point-of-view dependent.** The **local** player sees their *own* stealth as a
translucent dim (`arena_base.gd::_sync_local_player_state`, alpha 0.35) so they can still play.
**Every other** client renders a stealthed player as **fully hidden** — sprite, name label, and daze
stars all suppressed (`remote_player.gd::_update_flags`, alpha 0). Stealth is cosmetic-only: the
hidden player's **projectiles still render**, and the server still resolves hits against them, so a
stealthed player stays fully damageable (collision is server-authoritative — see
[`monsters-ai.md`](monsters-ai.md) "Stealth only affects targeting, not collision").

**Load-test bots honor Stealth.** The `omega-load-test` swarm
(`rust/load_test/src/behavior.rs::pick_target`) excludes `STEALTH`-flagged entities from both its
sticky-target re-validation and its nearest-candidate search, so bots drop a stealthed player and
never re-acquire it — matching the server monster AI, which already skipped `STEALTH` targets.

## Cooldown & Mana accounting

- **Mana** regenerates at **2/s** for every Class (`mana_max` 100), cut 75% from the earlier 8/s —
  abilities are the Mana sink, so regen is kept low enough that casts are a real resource decision.
  Mana is Session-ephemeral (resets full on entry), server-authoritative, and surfaced to the client
  in `ActionConfirm` (the `mana` byte) and the HUD bar.
- **Cooldowns** are per-ability (5–10 s), server-tracked per player, and started only on a successful
  cast. The client mirrors the cooldown for HUD readout (the ability bar draws a clockwise wedge over
  the SPACE/dash and RMB/ability slots) but never gates the cast itself online.

## The eight questions

- **Client:** samples the RMB ability flag + cursor into `PlayerInput`; predicts only Warrior Charge
  motion via `sim_core` (Shadowstep is server-authoritative — the client snaps); renders ability VFX
  from `ABILITY_EFFECT`, world-effect entities, and replicated flags (`STEALTH`, `INVULNERABLE`);
  shows Mana/cooldown on the HUD.
- **Server:** authoritative for all ability outcomes — Mana/cooldown gating, target selection, spawns,
  AOE/DoT/hitscan damage, invulnerability, Stealth, and world-effect entity lifetimes.
- **Predicted:** Warrior Charge motion only (shared `sim_core`); Rogue Shadowstep is **not** predicted
  (the server teleports and the client snaps); no ability damage, spawn, or status is predicted.
- **Replicated:** `ABILITY_EFFECT` events (`effect_id, x, y, radius`); world-effect entities (kind 3,
  band 40000–49999) in the snapshot stream; `STEALTH`/`INVULNERABLE` entity flags; Mana via
  `ActionConfirm`; `PICKUP {kind, amount}` for Healthorb heals.
- **Persisted:** nothing — abilities, cooldowns, Mana, and all effect entities are Session-ephemeral.
- **Validated:** Mana ≥ cost and cooldown elapsed (server-side); point-target abilities clamp the
  cursor to `max_cast_range`; movement abilities are distance-capped by the server even if the client
  over-predicts; the client request is advisory throughout.
- **Can fail:** insufficient Mana or on cooldown ⇒ server no-op (no Mana spent); a dropped ability
  flag self-heals (inputs ride the replayed unreliable input channel); a mispredicted movement-ability
  end snaps back via reconciliation (rare — same `sim_core`).
- **Tested:** protocol round-trip for the v4 additions (cursor field, `ABILITY_EFFECT`, world-effect
  typed-id kind 3, `STEALTH` bit); predicted-movement parity via the prediction-snap monitor;
  per-ability effect/cooldown/Mana behavior by play-test (no automated gameplay harness for abilities
  yet — a gap to close).

## See also

- [`../classes/index.md`](../gdd/classes/index.md) — the seven Classes and their per-ability parameters.
- [`PROGRESSION.md`](PROGRESSION.md) — levels, per-level scaling, Mana regen, XP→Glory.
- [`players-movement.md`](players-movement.md) · [`players-movement-state-machine.md`](players-movement-state-machine.md) — the movement SM the two movement abilities extend.
- [`combat-hits.md`](combat-hits.md) — the projectile/hit machinery Multishot and primaries share.
- [`../server/contract.md`](../server/contract.md) — the protocol v4 wire deltas.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary.
