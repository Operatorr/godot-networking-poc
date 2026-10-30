---
name: godot-physics
description: Configure Godot 4.7 2D client collision shapes, layers, Area2D triggers, and ray queries. Use when debugging client overlap detection or visual/offline physics; authoritative movement and hit math belong in Rust sim_core.
license: Apache-2.0
---

# Godot Client Physics

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Read `docs/server/design.md` and the relevant movement/hit contract before touching gameplay collision. Use `sim_core` and the existing prediction/reporting path for online movement and hits.
2. Inspect current layer/mask definitions before changing them. Layer means membership; mask means what this object scans for. Area detection can be one-way.
3. For client triggers, verify the shape, layers/masks, `monitoring`, and `monitorable` independently. An overlap can request an action or drive feedback; it cannot independently award loot or change authoritative HP.
4. Pool deactivation must handle shapes and Area monitoring explicitly. Hiding a node or disabling its processing does not by itself remove its collision participation.
5. Perform direct space-state queries during physics processing. Configure `collision_mask`, area/body flags, and `exclude` RIDs deliberately; null/empty results are expected.
6. Defer collision-property or tree changes when handling physics callbacks to avoid flushing-query errors.
7. Keep optional decorative physics detached from shared movement. Reproduce a collision issue with a small scene or relevant integration check before changing constants.

Read [bodies and queries](references/bodies-and-queries.md) for the 2D body choices, collision helpers, and ray/shape query APIs. This skill does not select or configure a 3D physics engine.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-physics) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
