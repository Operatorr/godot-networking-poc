---
name: rpg
description: Design Omega Realm's Class stats, XP curves, equipment, inventory, and persistent rewards. Use when changing progression or RPG systems while preserving Rust gameplay authority and Go API transactions.
license: Apache-2.0
---

# RPG systems for Omega Realm

Start with [progression](../../../docs/systems/PROGRESSION.md), [Classes](../../../docs/gdd/classes/index.md), [loot](../../../docs/gdd/loot.md), and [ADR 0006](../../../docs/adr/0006-softcore-hardcore-glory-economy.md). Verify formulas against current shared Rust code and JSON content: older prose can lag the implementation.

## Workflow

1. Locate the existing definition, runtime owner, and persistence boundary. Shared gameplay definitions belong in the current JSON/content pipeline; Godot Resources wrap presentation assets rather than define a second balance database.
2. Separate base values, derived values, and temporary modifiers. Give modifiers stable source identities; specify additive/multiplicative order, caps, expiry, and removal so equip/unequip and buff refresh are reversible.
3. Use the existing XP tables, level cap, Class scaling, and lifetime-XP accounting. Generic STR/DEX formulas and quadratic XP examples are design alternatives, not replacement defaults.
4. Keep combat, reward eligibility, inventory ownership, and equipment validation on the authoritative server/API path. The client renders confirmed state; previewing an item does not grant its stats.
5. Define transaction behavior for transfers and rewards: reject invalid IDs/counts/slots, prevent double spending, and handle retries and disconnects. Use the API's existing atomic/idempotent mechanisms.
6. Preserve Softcore/Hardcore and Sacrifice semantics. Local user preferences may live in `user://`; character progression and account currency do not become local saves.
7. Add quests or dialogue only for a concrete feature. If introduced, separate definitions from player progress, key objectives by stable IDs, and grant completion rewards once through the authoritative path.
8. Validate stacking/removal, XP boundaries, cap behavior, invalid equipment, and duplicate requests for the actual changed system. Update the relevant doc's client/server/prediction/replication/persistence/validation/failure/testing answers.

## References

- [Stats, combat, inventory, and optional quests](references/stats-combat-quests.md): illustrative models, not current balance.
- [Roguelike](../roguelike/SKILL.md): risk, death, runs, and account progression.
- [Server contract](../../../docs/server/contract.md): protocol, numerics, and ownership.
- [Skill selection](references/selection.md): the requested genre/discipline imports and exclusions.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/genres/rpg) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
