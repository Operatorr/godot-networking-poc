---
name: game-feel
description: Polish Omega Realm's client feedback with bounded shake, flashes, animation, particles, and sound. Use for hit/shot/pickup/death feedback while keeping prediction, networking, and server gameplay uninterrupted.
license: Apache-2.0
---

# Game feel

Apply [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries). This skill layers presentation onto existing events; authoritative hit resolution, knockback, damage, and cooldowns remain in the server/shared simulation.

## Workflow

1. Identify the event owner and whether the cue is predicted, confirmed, or remote. Give each cue a single playback path so reconciliation and repeated Snapshots do not double its feedback.
2. Start with two or three useful channels: sound, sprite flash, particles, number pop, or restrained camera motion. Prioritize incoming-projectile and hazard readability over spectacle.
3. Scale feedback by importance and listener proximity. Bound simultaneous particles, sounds, damage numbers, and shake accumulation for crowded multiplayer scenes.
4. Animate a dedicated visual child/material or camera offset. Preserve the simulated body and collider; gameplay knockback requires a server feature, not a cosmetic impulse.
5. Keep networking, input sampling, prediction, and interpolation running. Never use global Engine.time_scale or SceneTree pause for online hit-stop. If needed, briefly hold only an owned visual animation with cancellable cleanup.
6. Compose shake after follow with a clamped, decaying intensity; reset offset/rotation to the intended baseline when it ends. Use time-based envelopes, not fixed numbers of render Frames.
7. Keep one active tween/envelope per affected property, cancel superseded effects, and restore the original tint/scale/material values on pool return, death, scene travel, or teardown.
8. Respect reduced motion/flashing preferences. Test dense combat, rapid repeated events, rejected predicted actions, scene changes, and low/high FPS. Confirm aiming and readable telegraphs survive the effect.

## References

- [Feedback recipes](references/feedback-recipes.md): easing, shake, and presentation tiers.
- [Animation](../godot-animation/SKILL.md), [shaders](../godot-shaders/SKILL.md), and [audio design](../audio-design/SKILL.md): the individual feedback channels.
- [Camera systems](../camera-systems/SKILL.md): owns follow and shake composition.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/game-feel) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
