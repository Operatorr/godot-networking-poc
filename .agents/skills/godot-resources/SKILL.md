---
name: godot-resources
description: Manage Godot 4.7 client Resource loading, sharing, duplication, UIDs, and .tres assets. Use when editing materials, themes, SpriteFrames, PackedScenes, or diagnosing shared-resource mutations and loading hitches.
license: Apache-2.0
---

# Godot Client Resources

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Inspect the existing loaders and definitions under `client/scripts/data/`. Shared gameplay content remains in `client/data/` JSON with its schemas; a Resource wrapper must not create a second balance source.
2. Use Resources for client assets such as themes, textures, materials, audio, and SpriteFrames. Keep definitions separate from mutable per-entity runtime state.
3. Loaded resources are cached/shared. Decide what needs isolation before mutating; use `resource_local_to_scene` or intentional duplication.
4. `duplicate(true)` recursively copies containers and internal resources while external resource files can stay shared. Use `duplicate_deep(Resource.DEEP_DUPLICATE_ALL)` only when those external resources also need copies.
5. Reuse `SceneManager`'s loading flow for scene transitions. For separate asset loading, check request errors/status and call `load_threaded_get()` only when loaded; handle failed and cancelled consumers.
6. Preserve UIDs and move sidecars with scripts/shaders. Runtime writes go to `user://` for local preferences/cache; durable progression stays behind the Go API.
7. Check returned Error values for ResourceSaver/PackedScene operations and verify a saved asset can reload.

Read [resource patterns](references/resource-patterns.md) for threaded loading, local-to-scene resources, UIDs, and serialization APIs.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-resources) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
