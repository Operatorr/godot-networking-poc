---
name: godot-signals-groups
description: Wire typed client events and node groups in Godot 4.7. Use when connecting UI or entity lifecycle signals, managing pooled listeners, avoiding duplicate callbacks, or choosing signals versus direct calls.
license: Apache-2.0
---

# Godot Signals and Groups

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Emit from reusable children and connect in the owner. Use direct calls for an explicit owner/component relationship; use the existing `EventBus` for events that cross scenes.
2. Declare typed signal parameters and connect method Callables. `bind()` appends context after emitted arguments; `unbind()` removes trailing arguments.
3. Keep connection ownership explicit during reconnect, scene travel, and pool reuse. The same Callable normally cannot be connected twice; check `is_connected()` before reconnecting. Fresh bound/lambda Callables can still accumulate callbacks.
4. Store lambdas that need disconnection and account for captured nodes being freed. Automatic disconnection of a freed listener does not protect arbitrary objects captured by a still-live lambda.
5. Groups span the SceneTree. Avoid repeated `get_nodes_in_group()` scans in entity hot paths; existing entity maps/pools serve network entity lookup.
6. Treat pickup, death, and HP signals as presentation of accepted state or requests through the existing network path. Signal emission does not grant authority.
7. Await only events with a known completion/cancellation path. Pool reuse and reconnects need request/generation identity so an old completion cannot act on a new entity.

Read [signal patterns](references/signal-patterns.md) for connection flags, bind/unbind, lifetime handling, and timeout tradeoffs.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-signals-groups) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
