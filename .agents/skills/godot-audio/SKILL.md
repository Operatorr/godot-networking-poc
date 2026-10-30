---
name: godot-audio
description: Play and mix Godot 4.7 client music and sound effects through the existing AudioManager. Use when editing audio buses, pooled SFX playback, procedural WAV generation, crossfades, volume settings, or positional 2D sound.
license: Apache-2.0
---

# Godot Client Audio

Apply the shared [client boundaries](../godot-gdscript-patterns/SKILL.md#client-boundaries) before implementation. Target Godot 4.7; consult Context7 for that version when available, otherwise the versioned official docs.

## Workflow

1. Read `docs/systems/audio.md`, `client/autoload/audio_manager.gd`, and the relevant `client/scripts/systems/audio/` code. Reuse current buses, pools, and settings.
2. Route non-positional UI/music through AudioStreamPlayer and positional effects through AudioStreamPlayer2D only when needed. Bound concurrent combat sounds at load-test entity counts.
3. Map linear settings to decibels deliberately. Handle zero as mute or clamp before logarithms/tweens; validate `get_bus_index()` before using it.
4. Respect predicted versus confirmed sound ownership. Reconciliation, repeated Snapshots, and reconnects must not replay the same one-shot or start duplicate loops.
5. Keep one owner for sustained ability audio. Stop/reset loops on ability end, pool return, death, and scene/session transitions.
6. Cancel an existing crossfade before replacing it and restore the intended per-track level; check rapid track changes and mute changes during fades.
7. Treat playback/beat timing as presentation. Server Ticks and authoritative gameplay timing do not depend on local audio playback.
8. Check overlap, clipping, settings persistence, and transition cleanup in the client; retain the current headless audio-disable behavior.

Read [buses and effects](references/buses-and-effects.md) for bus APIs, polyphony, procedural playback, and positional audio.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-audio) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: narrowed scope to the Godot 4.7 client, integrated project ownership/lifecycle rules, and removed unrelated skill dependencies. Bundled reference modifications are marked in each file.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
