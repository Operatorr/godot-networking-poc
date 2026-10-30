---
name: godot-gdscript-patterns
description: Apply Omega Realm's Godot 4.7 client architecture and lifecycle patterns. Use when designing client systems, pooling entities, choosing scene/event boundaries, or coordinating multiple Godot features; use topic skills for individual APIs.
license: MIT
---

# Omega Realm Godot client patterns

## Client boundaries

Read the repository's [AGENTS.md](../../../AGENTS.md) and the relevant system doc before implementation. The architectural sources of truth are [server design](../../../docs/server/design.md), [wire and numerics contract](../../../docs/server/contract.md), and [glossary](../../../docs/CONTEXT.md).

- The client requests, the server decides. Godot owns input, rendering, UI, prediction, and interpolation; the Rust server owns authoritative gameplay, and the Go API owns durable persistence.
- Online Local player movement belongs to `PredictionController` using `sim_core` through the GDExtension. Remote entities use interpolation. Keep one transform writer; do not add a second GDScript controller.
- Follow the existing hit-report/validation model in the server docs. Local collision signals and animation tracks do not independently commit damage, loot, or progression.
- Shared gameplay content uses the existing JSON definitions/loaders. Resources serve client assets and wrappers without creating a separate balance source.
- Reuse existing SceneManager, EventBus, AudioManager, entity maps, and pools. Preserve their reconnect, scene travel, and teardown behavior.
- Target Godot 4.7. Consult Context7 for the relevant version before code changes when available; otherwise use [versioned official documentation](https://docs.godotengine.org/en/4.7/). A skill example is not an API or simulation contract.
- Prefer `class_name` types. If headless class resolution requires a preload, name the constant exactly like the class (for example, `const Projectile := preload("res://scripts/entities/projectiles/projectile.gd")`).

## Topic skills

Read only the topic needed by the task:

- [GDScript](../godot-gdscript/SKILL.md): typing, annotations, lifecycle, and async syntax.
- [Nodes and scenes](../godot-nodes-scenes/SKILL.md): composition, instancing, ownership, reference checking.
- [Signals and groups](../godot-signals-groups/SKILL.md): event boundaries and connection lifetimes.
- [TileMapLayer](../godot-tilemap/SKILL.md): client terrain and matching shared geometry.
- [Client physics](../godot-physics/SKILL.md): shapes, masks, triggers, and queries.
- [UI controls](../godot-ui-control/SKILL.md): layout, themes, focus, and dropdown spacing.
- [Animation](../godot-animation/SKILL.md): sprite playback and visual tween lifetimes.
- [Shaders](../godot-shaders/SKILL.md): 2D materials, uniforms, and rendering costs.
- [Resources](../godot-resources/SKILL.md): asset sharing, duplication, loading, and UIDs.
- [Audio](../godot-audio/SKILL.md): existing buses, pooled sounds, and transitions.

For pooled entities, presentation state machines, and hot-path choices, read [client patterns](references/client-patterns.md).

## Working approach

1. Trace the existing owner and data path before adding a new abstraction. Read the corresponding `docs/systems/` or `docs/netcode/` document.
2. Keep presentation state machines separate from the shared simulation. Add states/components only when they simplify an actual lifecycle.
3. Use typed signals across reusable scene boundaries and direct calls within a clear owner/component relationship.
4. For reusable entities, define activation, reset, and deactivation behavior including asynchronous work and collision participation.
5. Verify the actual changed behavior: relevant Godot parse/runtime checks, scene/reference checks for moved resources, or prediction/hit regression checks for simulation changes. Profile performance changes with representative entity counts.
6. For UI work, check desktop/mobile widths, long labels, and focus/input behavior. Follow the dropdown rule in the UI skill.

## Sources and selection

Adapted from the existing local copy of [Seth Hobson's Godot patterns skill](https://github.com/wshobson/agents/tree/main/plugins/game-development/skills/godot-gdscript-patterns); its original imported commit was not recorded. See [MIT license](LICENSE).

Modified for Omega Realm: replaced generic single-player movement, damage, save, and pause implementations with client architecture constraints and focused references. Ten topic skills were selected exclusively from the eleven gamedev-skills links requested by the user; their revisions, licenses, and adaptations are recorded in each skill.

See [review and selection](references/selection.md) for all eleven decisions and compatibility notes.
