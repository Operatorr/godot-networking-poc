---
name: godot-nodes-scenes
description: Compose Godot 4.7 client scenes and manage node lifetimes. Use when editing .tscn structure, instancing PackedScenes, pooling nodes, changing scene ownership, or diagnosing missing and freed nodes.
license: Apache-2.0
---

# Godot Nodes and Scenes

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Reuse the existing scene root and components before introducing more nodes or autoloads. Route transitions through `client/autoload/scene_manager.gd`.
2. Configure fields needed by `_ready()` before `add_child()`. Set `global_position` after parenting when it depends on the parent's transform; local position before parenting is relative to the future parent.
3. Use `@onready` for stable children. A `%UniqueName` reference survives reparenting within its scene ownership scope; renaming that unique node still requires updating the reference.
4. Separate lifetime from activation. Return network projectiles through `ClientEntityManager`'s pool rather than freeing them or creating a competing pool.
5. Use `queue_free()` for owned disposable nodes; guard references that can outlive the node. `is_instance_valid()` alone does not exclude a node queued for deletion.
6. When moving files, move their `.uid` sidecars too and inspect dependent `.tscn`/`.tres` references.

For scene/reference changes, run this read-only checker from the repository root:

```bash
python3 .agents/skills/godot-nodes-scenes/scripts/check_godot_project.py client --max-issues 20
```

Fix errors introduced by the change; report unrelated pre-existing findings without broadening the task. This checks references, not GDScript parsing or runtime behavior. Validate changed scenes in Godot when needed.

Read [tree and instancing](references/tree-and-instancing.md) for scene ownership, inherited scenes, deferred changes, and node paths. The checker uses only Python 3.10+ standard library.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-nodes-scenes) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
