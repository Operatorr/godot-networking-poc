---
name: godot-tilemap
description: Edit Godot 4.7 TileMapLayer and TileSet client terrain. Use when changing Arena tiles, atlas cells, terrain peering, map coordinate conversions, or tile collision setup.
license: Apache-2.0
---

# Godot TileMapLayer

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Inspect `client/scripts/levels/arena_base.gd` and `client/scripts/data/game_constants.gd` before changing Arena tiles. Use `TileMapLayer`, one node per layer.
2. Keep visual terrain separate from authoritative geometry. Any change to walkable bounds or obstacles must agree with `rust/sim_core` and the server contract.
3. Sanctuary props are drawn by the existing town generator. Preserve its walk-through geometry and consult `docs/design/sanctuary-layout.md` before adding tile collisions.
4. Define atlas source IDs, coordinates, physics layers, and custom-data types before calling `set_cell()` or reading tile data. Empty/non-atlas cells can return null.
5. Convert world coordinates with `to_local()` before `local_to_map()`. For mouse events use `make_input_local()`; viewport coordinates ignore camera scroll/zoom.
6. Terrain connect/path painting needs complete peering combinations. Inspect edges and corners after edits.
7. Batch runtime tile changes. `update_internals()` and runtime tile-data overrides are expensive; restrict them to actual needs.
8. Validate changed terrain visually and check collision against the shared geometry when collision changes.

Read [TileSets and terrains](references/tileset-and-terrains.md) for source types, Y sorting, terrains, and runtime tile-data overrides.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-tilemap) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
