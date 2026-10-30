---
name: audio-design
description: Design Omega Realm's combat sound hierarchy, variation, mix, and adaptive music. Use for crowded-scene audio readability, voice priorities, ducking, musical transitions, or sound feedback design.
license: Apache-2.0
---

# Audio design

This skill chooses what should be heard and when. Use [Godot audio](../godot-audio/SKILL.md) for playback APIs and the existing AudioManager; read [audio architecture](../../../docs/systems/audio.md) first.

## Workflow

1. Map each event to its listener and purpose: local action response, confirmed hit, incoming danger, UI acknowledgment, ambience, or music. Rank danger/readability above decorative density.
2. Give recurring sounds a coherent family with bounded pitch/volume variation and repeat avoidance. Keep important telegraphs recognizable; randomization must not disguise their meaning.
3. Budget voices by category, distance, and importance. Use existing pooling and rate limits; crowd scenes need prioritization/stealing rather than a sound per entity per Frame.
4. Define predicted versus confirmed ownership so one action sounds once. Reconciliation, repeated Snapshots, and reconnects must not replay one-shots or leak sustained loops.
5. Mix through existing buses. Test headroom, transient overlap, mute, user volume, and intelligibility at low listening levels. Set loudness targets for the actual delivery context rather than treating generic LUFS numbers as universal.
6. Duck music/ambience briefly for important cues with controlled attack/release. Cancel or replace prior fades so rapid events cannot leave a bus attenuated.
7. For adaptive music, choose aligned stems or sections; smooth intensity and use hysteresis. Use synchronized playback for stems and audio-thread transitions for strict beat timing. The audio clock is presentation, not gameplay authority.
8. Listen in calm, dense combat, rapid scene travel, death, and reconnect cases. Validate with headphones and speakers where available; record observed clipping/masking and any untested devices.

## References

- [Adaptive music](references/adaptive-music.md): layering, transitions, and intensity.
- [Game feel](../game-feel/SKILL.md): coordinated visual/sound feedback.
- [Asset provenance](../create-game-assets/references/provenance.md): source records for shipped sounds.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/audio-design) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
