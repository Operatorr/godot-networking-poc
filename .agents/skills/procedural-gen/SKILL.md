---
name: procedural-gen
description: Generate reproducible Omega Realm maps, biome decoration, encounters, and loot distributions. Use for seeded generation, connectivity, noise, placement constraints, or generation budgets across Rust and Godot.
license: Apache-2.0
---

# Procedural generation

Read [biomes](../../../docs/gdd/BIOMES.md), [server design](../../../docs/server/design.md), and the affected level's geometry contract. Sanctuary has an authored [layout](../../../docs/design/sanctuary-layout.md); procedural dressing must respect it.

## Workflow

1. Define the output contract: playable geometry, encounter/loot data, or cosmetic scatter. Gameplay results belong to the server/shared simulation or a validated shared artifact; decorative client randomness cannot alter collision or rewards.
2. Record seed, algorithm/version, content version, bounds, and parameters. A seed alone does not reproduce output across Rust and Godot: RNG algorithm, operation order, ranges, floating-point behavior, and iteration order must also match.
3. Separate RNG streams for geometry, encounters, loot, and decoration so a visual edit cannot change drops. Preserve the current server RNG contract before introducing stream changes.
4. Pick the simplest generator for the desired structure: rooms/corridors for routes, BSP for partitions, cellular caves for organic space, or noise/scatter for decoration. WFC enforces local adjacency, not global reachability.
5. Bound attempts, search work, memory, and output size. Handle empty room lists, impossible dimensions, contradictory constraints, and exhausted attempts with a defined failure or known-valid fallback.
6. Validate spawn-to-exit reachability, collider clearance, safe arrival zones, encounter density, key/gate order if present, and agreement with server geometry. Connectivity repair must be revalidated.
7. Normalize noise deliberately before thresholds or powers. Use spatially coherent world coordinates for chunk seams and enforce actual minimum spacing for props; jittering a grid alone does not guarantee separation.
8. Sweep representative seeds and boundary parameters. Capture failing seeds and generation versions, assert constraints, and measure worst-case cost. Keep expensive generation outside the synchronous Tick unless explicitly budgeted.

## References

- [Dungeon families and connectivity](references/dungeon-generation.md).
- [Noise, biome fields, and scatter](references/noise.md).
- [Roguelike](../roguelike/SKILL.md): risk and loot distribution.
- [TileMapLayer](../godot-tilemap/SKILL.md): rendering the resulting terrain without creating another geometry authority.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/procedural-gen) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
