# Classes — the seven archetypes

**Status:** Implemented (2026-06-13). A player picks one of **seven Classes** at character creation.
Each Class has its own base stats, **per-level stat scaling**, and a unique **Class ability** bound
to the right mouse button and paid for in **Mana**. Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md)
("Classes & abilities"): the **Class ability** is the RMB active, distinct from the shared primary
attack (LMB).

> **Single source of truth for numbers.** Every value on this page is mirrored in
> `client/data/classes/<id>.json` (consumed by the Godot client) and the Rust server constants
> (the authority). When they disagree, the **Rust server wins** — fix the doc and the JSON.
> Stat scaling is defined per [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md); the ability
> system as a whole is documented in [`../systems/abilities.md`](../systems/abilities.md).

## Class enum order

The `class` byte on the wire (ConnectAuth / PLAYER_INFO, protocol v3+) and the JSON file order:

| id | Class | File | Page |
|---|---|---|---|
| 0 | Zealot | [`zealot.json`](../../client/data/classes/zealot.json) | [zealot.md](zealot.md) |
| 1 | Void Hunter | [`void_hunter.json`](../../client/data/classes/void_hunter.json) | [void_hunter.md](void_hunter.md) |
| 2 | Engineer | [`engineer.json`](../../client/data/classes/engineer.json) | [engineer.md](engineer.md) |
| 3 | Plague Seer | [`plague_seer.json`](../../client/data/classes/plague_seer.json) | [plague_seer.md](plague_seer.md) |
| 4 | Warrior | [`warrior.json`](../../client/data/classes/warrior.json) | [warrior.md](warrior.md) |
| 5 | Rogue | [`rogue.json`](../../client/data/classes/rogue.json) | [rogue.md](rogue.md) |
| 6 | Mage | [`mage.json`](../../client/data/classes/mage.json) | [mage.md](mage.md) |

The server clamps an out-of-range `class` byte to `0` (Zealot) on join.

## Base stats & per-level scaling

A stat at level `L` is `base + per_lvl * (L - 1)`; **max level is 50** (see PROGRESSION.md). Mana
max is **100 for all** Classes (the listed Mana figure is the flavor `mana_pool`, not the gameplay
`mana_max`); Mana regen is **8/s** for all; stamina max is **100** for all. Primary cooldown is
**0.3 s** and projectile speed **400** for all Classes.

| Class | HP base / +lvl | Move speed base / +lvl | Mana (flavor) | Primary dmg base / +lvl |
|---|---|---|---|---|
| Zealot | 120 / +8 | 195 / +0.5 | 100 | 22 / +2 |
| Void Hunter | 90 / +5 | 205 / +0.7 | 100 | 26 / +2.5 |
| Engineer | 100 / +6 | 195 / +0.5 | 110 | 24 / +2 |
| Plague Seer | 95 / +5 | 195 / +0.5 | 120 | 20 / +2 |
| Warrior | 130 / +9 | 200 / +0.6 | 90 | 25 / +2.5 |
| Rogue | 85 / +4 | 215 / +0.9 | 100 | 24 / +2 |
| Mage | 80 / +4 | 195 / +0.5 | 130 | 28 / +3 |

## Class abilities at a glance

All ability damage and spawned world effects are **server-authoritative**. Warrior **Charge** and
Rogue **Shadowstep** blink are **predicted movement** (the client runs the same `sim_core` motion
the server does); everything else (orbs, explosions, mines, zones, hitscan, stealth) is decided by
the server and replicated via the `ABILITY_EFFECT` event.

| Class | Ability | Mana | Cooldown | One-liner |
|---|---|---|---|---|
| Zealot | **Spinning Bibles** | 35 | 8 s | 3 orbs orbit you for 5 s, sweep-damaging monsters (15/hit, re-hit 0.4 s). |
| Void Hunter | **Multishot** | 30 | 5 s | 5 piercing projectiles (pierce 4) in a 28° spread, 18 each. |
| Engineer | **Mine** | 35 | 8 s | Drop a proximity mine; arms in 0.5 s, blasts for 60 in radius 120. |
| Plague Seer | **Plague Zone** | 35 | 7 s | A DoT AOE at the cursor for 5 s, 12 dps, radius 100. |
| Warrior | **Charge** | 40 | 9 s | Hold to dash (invulnerable); AOE blast (50) on contact or at max distance. |
| Rogue | **Shadowstep** | 30 | 10 s | Blink to the nearest monster for an 85 hitscan, or go Stealth 5 s if none. |
| Mage | **Mageblast** | 40 | 6 s | Instant AOE explosion at the cursor, 55 in radius 120. |

## See also

- [`../systems/abilities.md`](../systems/abilities.md) — the RMB ability system (input, wire, dispatch, effects).
- [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md) — levels, per-level scaling, XP→Glory, max level 50.
- [`../systems/players-movement.md`](../systems/players-movement.md) — movement, prediction, Mana/stamina resources.
- [`../adr/0006-softcore-hardcore-glory-economy.md`](../adr/0006-softcore-hardcore-glory-economy.md) — Softcore/Hardcore + Glory.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary ("Classes & abilities", "Combat & survival").
