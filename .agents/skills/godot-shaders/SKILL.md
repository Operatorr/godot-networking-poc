---
name: godot-shaders
description: Write Godot 4.7 canvas_item shaders for client visuals. Use when editing .gdshader files, ShaderMaterial uniforms, town sway/glow, projectile effects, or screen-reading effects.
license: Apache-2.0
---

# Godot 2D Shaders

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Inspect existing `client/assets/shaders/town/` and `client/assets/shaders/effects/` plus the project's renderer before selecting features.
2. Use `shader_type canvas_item;` for the 2D client. Keep shaders visual: displacement and glow must not change authoritative geometry or hide gameplay telegraphs unintentionally.
3. Use `source_color` for color uniforms and appropriate sampler filtering/repeat hints. Preserve sprite tint/modulation intentionally when replacing `COLOR`.
4. Decide whether a ShaderMaterial is shared before setting parameters. Duplicate or localize it when only one entity should flash/fade; shared material mutation affects all users.
5. Shader `TIME` is presentation time, not server time; it continues through SceneTree pause and wraps. Pass an explicit uniform for effects that need controlled time.
6. Profile overdraw and screen texture passes at realistic entity counts. Avoid allocating a unique material per projectile without measuring the cost.
7. Check the effect in the actual renderer, on light/dark backgrounds, and with overlapping entities. Validate shader compilation and art readability.

Read [shading language](references/shading-language.md) for built-ins, uniforms, render modes, and vertex/fragment data flow. Its spatial-shader examples are background reference, not a reason to introduce 3D systems.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-shaders) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
