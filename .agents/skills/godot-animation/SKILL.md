---
name: godot-animation
description: Animate Godot 4.7 client sprites, effects, and UI with AnimationPlayer, AnimationTree, SpriteFrames, and Tween. Use when editing animation playback, blend parameters, visual transitions, or tween lifetimes.
license: Apache-2.0
---

# Godot Client Animation

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Inspect existing sprite/animation controllers before adding an AnimationTree. Choose AnimationPlayer for clips, AnimatedSprite2D/SpriteFrames for sheet playback, and Tween for short procedural effects.
2. Drive visual states from prediction or replicated state. Keep movement, cooldowns, damage, and spawning authority in the existing simulation/network paths.
3. Animate a visual child rather than a position owned by prediction or interpolation. Animation method tracks may trigger presentation; they must not independently commit combat effects.
4. Give one system ownership of each animated property. When AnimationTree drives playback, avoid competing AnimationPlayer calls on the same tracks.
5. Retain and kill replaceable tweens before starting replacements. Pool return and scene teardown must clear old callbacks/tweens so they cannot affect reused entities.
6. An awaited `animation_finished` may never arrive for looping or interrupted clips. Match the expected clip and use an explicit cancellation/lifetime path when necessary.
7. Use `create_tween()`/`finished` and, where useful, Godot 4.7 `tween_await()` with a timeout. For Container UI, use the 4.7 offset-transform properties or animate an inner visual Control under a layout-owned wrapper.

Read [animation and tweens](references/animation-tree-and-tween.md) for parameter paths, SpriteFrames, track types, and chaining.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-animation) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
