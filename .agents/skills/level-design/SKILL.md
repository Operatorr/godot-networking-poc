---
name: level-design
description: Design Omega Realm's top-down combat spaces, Sanctuary routes, encounter pacing, and readable greyboxes. Use for level layouts, landmarks, safe arrival areas, biome traversal, and playtest criteria.
license: Apache-2.0
---

# Level design

Read the relevant [game mode](../../../docs/gdd/game-modes.md), [biome](../../../docs/gdd/BIOMES.md), and [Sanctuary layout](../../../docs/design/sanctuary-layout.md). Read the affected system's status and code to distinguish implemented geometry from planned content.

## Workflow

1. State the space's purpose and player route: safe hub navigation, combat arena, teaching encounter, or risky exploration. Identify entry, destination, optional branches, exits, and landmarks.
2. Derive metrics from current movement speed, dash reach, collider radius, projectile travel/telegraph time, and camera framing. Generic jump gaps and platformer reach tables are not this game's metrics.
3. Greybox before detailed art. Check routes at player speed, with real collision clearance, camera bounds, and representative multiplayer occupancy.
4. Structure pressure and relief around readable enemy patterns and escape lanes. Put a safe introduction before a lethal combination. Treat save points as a separate persistence decision, not decorative pacing props.
5. Match visual affordances to actual geometry. Sanctuary's walk-through town and shared bounds must remain consistent with the server; introducing blocking props requires a coordinated shared-geometry change.
6. Keep spawn placement and encounter legality server-owned. Consider off-screen warnings, crowded entrances, spawn camping, projectile clutter, and visibility across supported aspect ratios.
7. Use contrast, silhouettes, lighting, and repeated landmarks to guide movement while preserving projectile readability. Check the relevant [style guide](../../../docs/design/STYLEGUIDE.md) before dressing.
8. Playtest traversal, dead ends, escape options, repeated routes, and dense fights. Record where players get lost or take unreadable damage; change the responsible layout/telegraph and repeat that scenario.

## References

- [Pacing, flow, teaching, and guidance](references/pacing-and-flow.md).
- [Procedural generation](../procedural-gen/SKILL.md): connectivity and generation constraints.
- [Camera systems](../camera-systems/SKILL.md): framing and bounds.
- [Server contract](../../../docs/server/contract.md): shared geometry and numerics.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/level-design) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
