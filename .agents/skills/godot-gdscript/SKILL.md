---
name: godot-gdscript
description: Write typed GDScript for the Godot 4.7 client. Use when editing .gd syntax, annotations, lifecycle callbacks, Variant conversions, or asynchronous control flow.
license: Apache-2.0
---

# Godot GDScript

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Prefer `class_name` types and typed function boundaries. When `Dictionary.get()` or another API returns a Variant, declare the receiving type or validate it before use.
2. Cache fixed child references with `@onready`; use `get_node_or_null()` for genuinely optional children. After an await, recheck any node or session that may have changed.
3. In Godot 4.7 an override inherits its parent's typed return. Return an appropriate value on every path. Packed-array element mutations no longer call the property setter; reassign the array if the setter must run.
4. Distinguish `_init`, tree entry, and `_ready`. A pooled node's `_ready()` usually runs only once; reset reusable state in its activation/deactivation methods.
5. Use `_process(delta)` for presentation and existing controllers for simulation. A fixed physics callback alone does not make a new movement implementation compatible with prediction.
6. Keep `@export` tuning client-facing; shared gameplay definitions continue through the JSON loaders and server validation.
7. Use the project's existing diagnostics and a Godot 4.7 parse/runtime check appropriate to the touched scripts. Resolve the first parser error before cascades.

For example, prefer `var count: int = data.get("count", 0)` over inferring a Variant. If input is untrusted, validate its type before assignment.

Read [annotations and typing](references/annotations-and-typing.md) for export annotations, typed collections, and lifecycle details.
For event architecture use `godot-signals-groups`; for tree structure use `godot-nodes-scenes`.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-gdscript) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
