---
name: input-systems
description: Design Omega Realm input actions, rebinding, device prompts, context routing, and accessibility. Use for keyboard/gamepad controls, held-versus-pressed behavior, settings, or lost/duplicate input.
license: Apache-2.0
---

# Input systems

Target Godot 4.7. Inspect `client/project.godot` actions, `client/scripts/utils/user_preferences.gd`, current settings UI, and `client/scripts/network/prediction.gd`. Follow [movement ownership](../../../docs/systems/players-movement.md) and the [wire contract](../../../docs/server/contract.md).

## Workflow

1. Express gameplay intent as named InputMap actions. Preserve existing physical-key binding semantics and user overrides; choose logical keys only for a deliberate text/layout requirement.
2. Distinguish held axes/buttons from discrete edges. Trace how a press becomes a PlayerInput command, is numbered, replayed, and acknowledged before adding buffering.
3. Keep one owner for online movement: PredictionController feeds shared simulation. UI/gamepad/touch adapters feed the same action path, not another transform writer.
4. Route context deliberately: gameplay, menus, chat/text entry, and rebinding capture. A modal consumes its UI action without also firing a weapon; device loss/focus loss must release held state.
5. Preserve protocol semantics when buffering an edge. Bound the window, consume once when appropriate, and clear on context/session changes. Server cooldown/resource validation remains decisive; extra client buffering must not duplicate actions during replay.
6. Rebind with conflict handling, cancel, reset-to-default, and usable navigation after remapping. Persist supported overrides through UserPreferences; preserve unrelated device events and settings.
7. Offer hold/toggle choices and adjustable sensitivity/deadzones where applicable. Swap glyphs on deliberate device activity, not idle stick noise. Add controller/touch support only within requested platform scope.
8. Verify short taps between Ticks, held actions, key repeat, focus loss, text entry, modal transitions, reconnect, duplicate bindings, and persistence. Test supported devices and report gaps.

## References

- [Buffering, devices, and accessibility](references/buffering-and-accessibility.md): concepts; platformer jump/coyote recipes are outside the current controller.
- [UI controls](../godot-ui-control/SKILL.md) and [UI/UX](../game-ui-ux/SKILL.md): settings and focus.
- [GDScript](../godot-gdscript/SKILL.md): implementation conventions and versioned API checks.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/input-systems) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
