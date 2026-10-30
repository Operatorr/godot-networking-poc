# Genre and discipline skill selection

Reviewed the two genres and fourteen disciplines explicitly requested by the user.
All twelve selected folders come from
[gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills)
at commit `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
No other skills were installed as dependencies.

PR #55 has merged; the checkout is on master at `7c00953` and matched origin/master
when this batch was installed. Godot **4.7** is the client target. Earlier Godot skill
work remains intact; see its [selection record](../../godot-gdscript-patterns/references/selection.md).

## Added as requested

- [roguelike](../../roguelike/SKILL.md): run risk, procedural variety, loot distributions,
  and character/account separation. Adapted from turn-based assumptions to real-time
  multiplayer and ADR 0006 Softcore/Hardcore/Sacrifice semantics.
- [rpg](../SKILL.md): stat layers, equipment, progression, inventory, and reward transactions.
  Existing shared JSON/Rust formulas and API persistence supersede generic formulas/local saves.

## Added disciplines

- [create-game-assets](../../create-game-assets/SKILL.md): art-family consistency,
  briefs, manifests, alpha/grid inspection, and contact-sheet helpers. Complements
  imagegen and engine asset APIs with the project's style guides and production checks.
- [game-ai](../../game-ai/SKILL.md): FSM transitions, target validity, steering, pathfinding,
  and cost control. Applied to Rust monster AI; clients render interpolated entities.
- [procedural-gen](../../procedural-gen/SKILL.md): bounded seeded generation, connectivity,
  noise, and decoration. Separates cosmetic streams from server/shared gameplay geometry.
- [audio-design](../../audio-design/SKILL.md): cue hierarchy, voice priority, variation,
  masking, and musical transitions beyond the existing Godot playback skill.
- [level-design](../../level-design/SKILL.md): combat spacing, landmarks, route clarity,
  greyboxing, and encounter pacing grounded in current movement/camera metrics.
- [input-systems](../../input-systems/SKILL.md): action semantics, remapping, context routing,
  device prompts, and accessibility through existing prediction and preference paths.
- [game-feel](../../game-feel/SKILL.md): event-owned, bounded visual/audio feedback with
  pool cleanup. Global time-scale changes and client-authoritative impulses are excluded.
- [game-ui-ux](../../game-ui-ux/SKILL.md): information hierarchy, pending/error states,
  navigation, and accessibility above the existing Control/widget skill.
- [camera-systems](../../camera-systems/SKILL.md): framing, bounds, shake composition,
  and discontinuities while preserving the current physics/interpolation camera path.
- [performance-optimization](../../performance-optimization/SKILL.md): repeatable measurement
  across client Frames, server Ticks, and network/load metrics.

## Not installed

- [ai-behavior-trees-utility-ai](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/ai-behavior-trees-utility-ai):
  substantial C# tree/blackboard/utility runtime guidance exceeds the current Rust FSM need.
  The selected game-ai reference already explains reactive priorities, memory, and utility.
  Reconsider if a concrete monster feature outgrows the FSM.
- [dialogue-systems](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/dialogue-systems):
  branching narrative, Ink/Yarn, and conversation runners are not required by current hub
  interactions. Reconsider when implementing authored branching dialogue or quests.
- [shader-programming](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/shader-programming):
  broad GLSL/HLSL/3D examples duplicate the installed Godot canvas_item/material guidance.
  Current town/projectile shaders are better served by that focused skill.
- [physics-tuning](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/physics-tuning):
  rigid-body solver, gravity, and generic timestep tuning do not fit shared Rust movement
  and fixed 30 Hz authority. Existing sim/numerics docs and godot-physics cover current needs.

## Packaging and corrections

Each imported folder includes upstream Apache-2.0 LICENSE and NOTICE. Entrypoints were
rewritten for project use; adapted references carry modification notices.
The asset templates, interface metadata, and two Python QA scripts are retained unchanged.
Helpers require Python 3.10+ and Pillow; they are not invoked automatically by the skills.

Corrections include server/API permadeath ownership, bounded cardinal random walks,
signed noise ranges and spacing claims, audio alignment/volume setter behavior, visual-only
hit holds, modal cleanup/empty-stack handling, stretch semantics, and CPU draw-call cost.
References remain illustrative; future implementation must consult the relevant engine
or library docs and validate behavior in the project.

## Import validation

- Skill metadata, entrypoint size, code fences, licenses/notices, and 208 local links
  passed across these twelve and the eleven existing Godot skills.
- Upstream Git blob hashes match for the retained asset helpers, templates, interface
  metadata, and license/notice copies.
- Raster helper fixtures covered valid input, wrong dimensions, missing/opaque alpha,
  excess colors, missing files, and corrupt files. Contact sheets were reproducible,
  deduplicated inputs, and left source files unchanged.
- The corrected cardinal walk passed connectivity/target checks for 50 seeds and rejected
  invalid dimensions, impossible targets, and exhausted step budgets.
- No game runtime code changed in this batch; game build/load tests were not rerun.
