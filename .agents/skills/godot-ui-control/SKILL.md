---
name: godot-ui-control
description: Build Godot 4.7 client HUDs and menus with Control, Containers, themes, and focus. Use when editing .tscn UI layout, responsive sizing, OptionButton dropdowns, keyboard/gamepad navigation, or UI input handling.
license: Apache-2.0
---

# Godot UI and Controls

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Read `docs/systems/ui-hud.md` and inspect nearby widget scenes. Reuse `client/scripts/ui/helpers/`, existing fonts/art, and the HUD's composition.
2. Use Control/Container layouts and size flags. Containers own direct-child layout. Godot 4.7 offset transforms can animate children without fighting layout; an inner visual Control under a layout-owned wrapper is also suitable. Check transformed hit areas as well as appearance.
3. Apply shared Themes/StyleBoxes before adding overrides. Keep screen navigation with `SceneManager`; display accepted network/API state through existing controllers.
4. Give menus an initial focus target, sensible keyboard/gamepad neighbors, and focus restoration after closing dialogs. Decorative overlays should ignore mouse input where appropriate.
5. Preserve dropdown spacing: inset the caret at least 12 px from the right edge and reserve at least 36 px for the selected value. For Godot `OptionButton`, position the existing arrow through the shared theme/control; content padding alone is insufficient. Avoid adding a second caret.
6. For HTML prototypes, reuse a shared select or disable native appearance and position one caret explicitly. Keep multiple/size listboxes native.
7. Align filter controls and action buttons along their bottom edge. Check desktop/mobile widths with long selected labels; check clipping, focus, mouse, keyboard, and gamepad behavior.
8. Opening a menu in a connected session must preserve the networking/prediction lifecycle. Follow the current pause flow rather than pausing the entire SceneTree by default.

Read [layout and theming](references/layout-and-theming.md) for anchors, containers, theme overrides, focus, and CanvasLayer HUDs.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-ui-control) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
