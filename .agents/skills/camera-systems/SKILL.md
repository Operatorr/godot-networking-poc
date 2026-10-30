---
name: camera-systems
description: Tune Omega Realm's Godot 4.7 Camera2D framing, bounds, shake composition, and discontinuity handling. Use for camera jitter, follow latency, zoom, teleports, or level-edge visibility.
license: Apache-2.0
---

# Camera systems

Read [render smoothness](../../../docs/netcode/smoothness-render.md) and inspect `client/scripts/levels/arena_base.gd` plus `client/scripts/network/prediction.gd` before changing follow behavior. The existing online camera has a deliberate physics/interpolation owner.

## Workflow

1. Reproduce the visual issue and separate follow lag, render judder, network interpolation delay, and actual low FPS. Capture at low/high render rates before adding smoothing.
2. Preserve the current path: PredictionController emits visual-position updates on physics Ticks; the dedicated Camera2D uses engine physics interpolation. It is not parented to the player and does not chase raw physics positions every render Frame.
3. Keep existing position smoothing disabled unless changing the design deliberately. Another low-pass filter adds latency; generic late-update follow or a second transform writer can reintroduce jitter.
4. On spawn, teleport, hard correction, and scene travel, snap/reset the follow history and existing smoothing/interpolation state through the current discontinuity path.
5. Frame the top-down play space using actual zoom, viewport, and shared level bounds. For a level smaller than the view, center that axis. Consider whether zoom or aspect changes expose more threats than intended.
6. If adding look-ahead/deadzone, specify aim-versus-motion priority and bounded offsets. Use time-based easing and test direction reversals; integrate with the existing camera owner.
7. Compose optional shake after follow on presentation offsets; reset it on completion and discontinuity. Keep cursor-to-world aim conversion consistent with the visible camera.
8. Verify sustained movement, sprint/dash, rapid aim changes, edges/corners, resizing, death/respawn, and teleport at low/high FPS. Check both player and world scrolling.

## References

- [Follow and framing](references/follow-and-framing.md): general math; only the 2D framing concepts apply by default.
- [Game feel](../game-feel/SKILL.md): shake triggers and accessibility.
- [Latency budget](../../../docs/netcode/latency-budget.md): distinguish smoothing from network delay.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/camera-systems) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
