---
name: game-ui-ux
description: Design Omega Realm HUD information, menu flow, focus, responsive layouts, and pending/error states. Use for inventory, shops, settings, modal navigation, accessibility, or UI feedback from authoritative state.
license: Apache-2.0
---

# Game UI and UX

Read [HUD architecture](../../../docs/systems/ui-hud.md) and use [Godot UI controls](../godot-ui-control/SKILL.md) for Godot 4.7 widgets, themes, and the standing dropdown spacing/render checks. This skill owns information and interaction design.

## Workflow

1. Define what the player needs to know or decide. Prioritize HP, threats, action availability, and relevant rewards; keep implementation details out of the player-facing flow.
2. Trace current SceneManager/menu ownership before adding navigation. Give overlays a clear top input owner, back/cancel behavior, default focus, and return focus; extend the existing flow rather than introducing a competing UI manager.
3. Separate displayed authoritative state, local selection/preview, and pending requests. Purchases, equipment, Sacrifice, and transfers need clear success/failure behavior without granting rewards optimistically.
4. Prefer event-driven HUD updates with initial state hydration and clean rebinding after scene/session changes. Disconnect stale listeners and avoid rebuilding whole lists for one changed value.
5. Use anchors/containers, readable text, sensible minimum sizes, and content-driven sizing. Preserve the project's stretch/camera policy; a UI fix must not silently expand gameplay visibility.
6. Keep modals keyboard/controller navigable, trap focus, preserve the prior interaction state, and prevent mouse/input click-through. An online menu blocks the appropriate local controls while the network/session continues; it does not pause the world.
7. Support long labels, empty/loading/error states, larger text, and redundant shape/text cues for color-coded state. Apply the dropdown rule for every select, prototype, or mockup.
8. Verify desktop/mobile widths, supported aspect ratios, long localized text, focus restoration, reconnect, and repeated pending actions. Report the rendered sizes and interaction paths actually checked.

## References

- [Layout and flow](references/layout-and-flow.md): scaling, focus, modal patterns, accessibility.
- [Input systems](../input-systems/SKILL.md): rebinding and context routing.
- [Game feel](../game-feel/SKILL.md): transient feedback that preserves usability.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/game-ui-ux) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
