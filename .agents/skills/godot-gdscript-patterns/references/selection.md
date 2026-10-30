# Godot skill sources and selection

The user requested assessment of exactly eleven Godot skills from
`gamedev-skills/awesome-gamedev-agent-skills`. Ten are installed locally; no other skills
from that collection were installed as dependencies in that batch. Subsequent user-requested
genre and discipline imports are recorded in [their selection record](../../rpg/references/selection.md).

## Version and provenance

The selected imports are pinned to upstream commit
`19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Each installed folder contains Apache-2.0 LICENSE and upstream NOTICE files, a source
link in SKILL.md, and modification notices on adapted references. The scene/reference
checker is bundled unchanged from that revision.

The existing `godot-gdscript-patterns` originated from Seth Hobson's
[Godot patterns skill](https://github.com/wshobson/agents/tree/main/plugins/game-development/skills/godot-gdscript-patterns).
Its original imported revision was not recorded. It now provides the shared project
constraints and client lifecycle guidance, with its MIT license retained.

Target Godot **4.7**. The upgrade merged in
[PR #55](https://github.com/Operatorr/godot-networking-poc/pull/55), with
`client/project.godot` declaring 4.7. The GDExtension's lower compatibility minimum is
not the client engine version. Verify APIs against versioned Godot 4.7 documentation;
keep 4.7-specific features instead of backporting to 4.6.

## Installed

- [godot-gdscript](../../godot-gdscript/SKILL.md): typed syntax, annotations, lifecycle,
  and 4.7 return/setter changes; narrowed away from implementing independent movement.
- [godot-nodes-scenes](../../godot-nodes-scenes/SKILL.md): scene composition, ownership,
  UID/reference handling, and a read-only scene/project reference checker.
- [godot-signals-groups](../../godot-signals-groups/SKILL.md): event boundaries and
  connection lifetimes through pooling, reconnects, and scene changes.
- [godot-tilemap](../../godot-tilemap/SKILL.md): already relevant to Arena TileMapLayer
  terrain; scoped so client tile edits do not silently change shared collision geometry.
- [godot-physics](../../godot-physics/SKILL.md): useful for client masks, shapes, Areas,
  and queries; authoritative movement/hits remain in `sim_core` and server validation.
- [godot-ui-control](../../godot-ui-control/SKILL.md): HUD/menu composition, themes,
  focus, responsive layout, 4.7 offset transforms, and the user's dropdown preferences.
- [godot-animation](../../godot-animation/SKILL.md): sprite/clip playback and cancellable
  visual tweens, including 4.7 signal waits; no animation-driven combat authority.
- [godot-shaders](../../godot-shaders/SKILL.md): existing 2D town/projectile materials,
  uniform sharing, and rendering costs at representative entity counts.
- [godot-resources](../../godot-resources/SKILL.md): resource lifetime, duplication,
  loading, and UIDs; existing JSON definitions remain the shared gameplay content source.
- [godot-audio](../../godot-audio/SKILL.md): buses, pooled SFX, generated audio, and
  crossfades integrated with the current AudioManager and event ownership.

## Skipped

[godot-2d-movement](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/blob/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/godot/godot-2d-movement/SKILL.md)
centers on standalone `CharacterBody2D` controllers, direct `move_and_slide()` movement,
and platformer recipes. Our online Local player uses PredictionController with shared
Rust simulation, and remote entities use interpolation. Installing that skill would
add a competing default movement recipe; relevant collision APIs are already covered
by the scoped client physics skill. Reconsider only for an explicitly separate
controller experiment with clear ownership.

## Local adaptations

The entrypoints are concise and task-specific. Generic single-player damage, saves,
global pause, extra autoloads, and suggested dependencies are replaced with project
owners and contract pointers. Detailed examples remain behind references.

Reference corrections include unique-name rename behavior, callback/lifecycle ordering,
Variant inference wording, AnimationTree root parameter paths, valid Resource API call
syntax, and cleanup/authority notes. The 4.7 offset-transform, VirtualJoystick, and
tween-await material remains available. These examples still require verification in
the actual project; they are not a replacement for engine docs or the server contract.
