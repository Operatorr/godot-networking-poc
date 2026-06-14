# Loot Tables (TBD — design-directional, unbuilt)

> **Status: TBD / UNBUILT.** This captures the *intended* loot design from the GDD. **No loot
> system exists in code today.** There is no item drop, item definition, inventory, equipment, or
> item-granted spell in the authoritative Rust server (`rust/server/`) or the Go API (`api/`).
> The only "drops" the live server produces are **health orbs** rolled on monster kill
> (`rust/server/src/sim/combat.rs`), which are world-effect entities, not lootable items. Treat
> everything below as a spec to build against, not as built behaviour. The legacy GDScript
> `loot_table.gd` / `item_factory.gd` / `loot_tables.json` names in the old GDD describe the
> retired design and are **not** live code.

---

## Goal

A data-driven loot table that decides **what drops, where, and for whom** when a monster dies, in
keeping with the project's data-driven content principle (items/spells/projectiles defined in
JSON/DB so designers tune drops via the CMS without a rebuild — see [`index.md`](index.md) →
Data-Driven Architecture). Pure parameter changes (drop weights, tiers, new reskin items) must be
live-editable; genuinely new item *verbs* (a spell the sim doesn't understand) still need a sim
change + deploy.

## Where it must live (authority)

When built, loot is **server-authoritative**, consistent with the governing rule **"the client
requests, the server decides."** Item generation and drops must be rolled on the omega-server (the
single authoritative instance) on monster death, alongside the existing XP/health-orb rolls in the
PvE collision pass (`apply_monster_damage` / `grant_kill_experience` in
`rust/server/src/sim/combat.rs`). Durable item ownership (inventory/equipment) would be persisted by
the Go API (Postgres), mirroring how characters/Glory are persisted today; in-world dropped items
are server-authoritative + in-memory until picked up. Clients never roll their own drops.

---

## Drop rules (intended)

### 1. Tier requirement (matches monster tier) — required

Every item carries a **minimum Tier requirement**. An item can only drop from a monster whose tier
meets that requirement, so item power scales with where you are in the world. Tiers map to biomes
and level ranges per [`BIOMES.md`](BIOMES.md):

| Biome Tier | Regular level range | Boss level |
| ---------: | ------------------: | ---------: |
| Tier 1 | 1–8 | 10 |
| Tier 2 | 9–18 | 20 |
| Tier 3 | 20–30 | 32 |
| Tier 4 | 31–40 | 42 |
| Tier 5 | 41–50 | 55 |
| Tier 6 | 51–65 | 70 |
| Tier 7 | 66–85+ | 90+ |

Worlds span tiers: Mainland T1–4, Underworld T3–7, Creators Realm T4–7.

### 2. Biome requirement — optional

Some items additionally carry a **biome restriction**: they can *only* drop in a specific biome
(e.g. a Lava-only item). Items without a biome requirement can drop from any qualifying-tier monster
in any biome. (Biome list: [`BIOMES.md`](BIOMES.md).)

### 3. Class eligibility — mostly class-agnostic, some restrictions

Loot is **for the most part equippable by all classes.** A minority of items carry a **class
restriction** limiting them to specific classes. The class byte is defined in the protocol
(0 Zealot, 1 VoidHunter, 2 Engineer, 3 PlagueSeer, 4 Warrior, 5 Rogue, 6 Mage); only **Warrior,
Rogue, Mage** are in pre-alpha scope, so class-restricted items should target those three first.

### 4. Items that grant spells/abilities

Some items **grant an equippable spell or ability** that the player can slot into the action bar.
The HUD/action-bar layout (see [`index.md`](index.md) → Action-bar): **SPACE** dash, **RMB**
class-unique ability (costs Mana; only Warrior Charge and Rogue Shadowstep are *predicted* movement
— see [`../systems/abilities.md`](../systems/abilities.md)), and **Slots 1–4** for abilities
acquired from **Glory unlocks, items, or the skill-tree**. An item-granted spell is therefore one
of three sources feeding the same four ability slots. Note the data-driven caveat: a *parameterised*
spell (`{damage, speed, radius, lifetime, pierce}`) is live-addable, but a spell with a genuinely
new behaviour (teleport, bullet-reflect) needs a `sim_core` change + deploy.

---

## Proposed item-definition fields (directional, not built)

A starting shape for the JSON/DB item definition (final schema TBD; co-design with the CMS):

| Field | Meaning |
| --- | --- |
| `id` | Stable item id |
| `name`, `sprite` | Display |
| `tier_requirement` | Min monster tier that can drop it (**required**) |
| `biome_requirement` | Optional single biome restriction (null = any) |
| `class_restriction` | Optional list of allowed class bytes (empty = all classes) |
| `slot` / `item_type` | Weapon / armor / consumable / ability-grant / etc. |
| `stats` / `affixes` | Stat modifiers |
| `granted_ability_id` | Optional ability/spell slotted into the action bar |
| `drop_weight` | Relative roll weight within its tier/biome pool |

A **loot pool** would then be a weighted set of eligible item ids resolved per monster (by tier,
biome, and any per-monster overrides), with the server rolling against it on death.

---

## Open questions (TBD)

- Rarity tiers and affix system (the old GDD references item affixes/builder pattern — undecided).
- Drop *rate* curve (how generous), boss vs trash drop differences, and dungeon-boss bonus tables.
- Whether dropped world items are tradeable/bankable in the Sanctuary at launch.
- Bind-on-pickup vs free trade; interaction with Softcore sacrifice / Hardcore permadeath
  (does loot persist across the character that earned it?).
- Exact persistence schema in the Go API for inventory/equipment.

---

## How this will be documented (the eight questions) — once built

- **Client:** requests pickups, renders ground items + tooltips; never rolls drops.
- **Server (omega-server):** rolls drops on monster death (tier/biome/class filtered), owns
  in-world dropped-item state.
- **Predicted:** nothing (loot is not latency-sensitive; no client prediction of drops).
- **Replicated:** ground-item spawn/despawn via snapshots; pickup via the request→confirm path.
- **Persisted:** inventory/equipment in the Go API (Postgres), like characters/Glory today.
- **Validated:** tier/biome/class eligibility and pickup ownership enforced server-side.
- **Fails:** entirely unbuilt today — nothing to fail yet.
- **Tested:** none yet; when built, drop-eligibility filtering and roll determinism want unit tests
  (mirror the Glory math tests in `api/internal/progression/progression_test.go`).
