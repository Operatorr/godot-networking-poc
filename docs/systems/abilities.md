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
| Mage | Mageblast | instant AOE (event only) | no | range-clamp, AOE damage |
| Plague Seer | Plague Zone | spawned `dot-zone` entity | no | range-clamp, spawn, per-tick DoT |
| Engineer | Mine | spawned `mine` entity | no | spawn, arm, proximity trigger, AOE blast |
| Zealot | Spinning Bibles | spawned `bible` entities | no | spawn, orbit, sweep + re-hit gating |
| Void Hunter | Multishot | projectile spread (10000–29999) | no | spawn spread, piercing hits |
| Warrior | Charge | **movement** (`AbilityMovement`) | **yes** (motion) | invulnerability, distance cap, blast |
| Rogue | Shadowstep | **movement** (blink) or Stealth | **yes** (blink motion) | target pick, hitscan, `STEALTH` flag |

**The prediction rule.** Only the two **movement** abilities are predicted, and only their *motion*:
Warrior Charge and Rogue Shadowstep's blink run through the shared `sim_core` `AbilityMovement` state,
so the client predicts the dash/teleport with zero divergence from the server. Everything
else — all damage, every spawn, invulnerability, target selection, Stealth — is decided by the server
and learned by the client through `ABILITY_EFFECT`, replicated entity flags, or the effect entities.

## Stealth (entity flag bit 9)

Rogue Shadowstep with no target sets the **`STEALTH`** entity flag (16-bit entity flags, bit 9 — the
first of the reserved bits 9–15 to be used; bit 8 is `DAZED`). A stealthed player is **invisible to
AI targeting**: monster and bot AI drop aggro and will not re-acquire while the flag is set. Stealth
runs 5 s and **breaks early** the moment the Rogue deals damage. The flag is server-owned and
replicated; the client renders its own translucency from it.

## Cooldown & Mana accounting

- **Mana** regenerates at **8/s** for every Class (`mana_max` 100), down 20% from the pre-ability
  10/s — abilities are the new Mana sink, so regen was nerfed to keep cast cadence meaningful.
  Mana is Session-ephemeral (resets full on entry), server-authoritative, and surfaced to the client
  in `ActionConfirm` (the `mana` byte) and the HUD bar.
- **Cooldowns** are per-ability (5–10 s), server-tracked per player, and started only on a successful
  cast. The client mirrors the cooldown for HUD readout but never gates the cast itself.

## The eight questions

- **Client:** samples the RMB ability flag + cursor into `PlayerInput`; predicts only the two movement
  abilities' motion via `sim_core`; renders ability VFX from `ABILITY_EFFECT`, world-effect entities,
  and replicated flags (`STEALTH`, `INVULNERABLE`); shows Mana/cooldown on the HUD.
- **Server:** authoritative for all ability outcomes — Mana/cooldown gating, target selection, spawns,
  AOE/DoT/hitscan damage, invulnerability, Stealth, and world-effect entity lifetimes.
- **Predicted:** Warrior Charge motion and Rogue Shadowstep blink motion only (shared `sim_core`); no
  ability damage, spawn, or status is predicted.
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
