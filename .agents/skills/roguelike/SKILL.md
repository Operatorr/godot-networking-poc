---
name: roguelike
description: Design Omega Realm's real-time roguelite loop, encounter variety, loot risk, and Hardcore/Softcore consequences. Use when changing runs, death/Sacrifice, procedural dungeon progression, or account versus character rewards.
license: Apache-2.0
---

# Roguelike design for Omega Realm

Omega Realm is a real-time multiplayer bullet-hell roguelite. Read [game modes](../../../docs/gdd/game-modes.md), [loot](../../../docs/gdd/loot.md), and [ADR 0006](../../../docs/adr/0006-softcore-hardcore-glory-economy.md) before changing the loop. Design documents include future scope; confirm implementation in the owning code.

## Workflow

1. Define the player decision: enter danger, choose a route, commit resources, retreat, or Sacrifice. Describe the risk, readable warning, reward, and recovery path before adding systems.
2. Keep character state, account progression, and transient encounter state distinct. Hardcore death ends the character; Softcore death permits respawn; Sacrifice is an explicit server-validated end. Resolve rewards and deletion atomically through the Go API per the ADR.
3. Keep combat on the existing authoritative Tick. Turn schedulers, energy-based action queues, and local save deletion from traditional roguelikes do not fit this game.
4. Use authored constraints around procedural variety: safe arrivals, readable projectile lanes, reachable exits, bounded encounter density, and biome identity. Validate traversal using actual collider clearance, not just a point-sized tile flood-fill.
5. Treat loot weights as relative probabilities. Distinguish one weighted pick from independent drop rolls; validate nonnegative finite weights and a positive total. The server rolls and awards loot using the existing content definitions.
6. Tune build choices through the existing Class/ability/item systems. Identify meaningful tradeoffs and counterplay; a genre checklist is not a mandate to add hunger, identification, FOV, or more stats.
7. Evaluate repeated runs for fair deaths, repetitive openings, runaway power, and reward duplication. For persistence changes, cover disconnect at death, retries, reconnect, and repeated Sacrifice requests.

## References

- [Generation, optional FOV, and loot](references/generation-fov-loot.md): algorithm background; FOV is an optional feature, separate from network AoI.
- [Procedural generation](../procedural-gen/SKILL.md): deterministic generation and validation.
- [RPG](../rpg/SKILL.md): existing progression and item ownership.
- [Server design](../../../docs/server/design.md) and [contract](../../../docs/server/contract.md): implementation boundaries.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/genres/roguelike) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
