export const meta = {
  name: 'smoothness-diagnosis',
  description: 'Pin down the exact mechanism behind 30fps-looking motion, double-shots, steering-boat input, and hit-detect misses',
  phases: [{ title: 'Trace motion + input', detail: 'three readers trace render cadence, input double-action, hit detection' }],
}

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['area', 'verdict', 'mechanism', 'evidence', 'fixes'],
  properties: {
    area: { type: 'string' },
    verdict: { type: 'string', description: 'One-sentence confirm/refute of the stated hypothesis' },
    mechanism: { type: 'string', description: 'Precise mechanism, step by step, of what actually happens in code' },
    evidence: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['fact', 'location'],
        properties: { fact: { type: 'string' }, location: { type: 'string', description: 'file:line' } },
      },
    },
    fixes: {
      type: 'array',
      description: 'Concrete fixes, most impactful first',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['fix', 'effort', 'impact'],
        properties: {
          fix: { type: 'string' },
          effort: { type: 'string', enum: ['trivial', 'small', 'medium', 'large'] },
          impact: { type: 'string', enum: ['decisive', 'high', 'medium', 'low'] },
        },
      },
    },
  },
}

phase('Trace motion + input')

const tasks = [
  {
    key: 'render-cadence',
    prompt: `HYPOTHESIS TO CONFIRM OR REFUTE: All on-screen motion (local player AND remote entities) has its node position written only inside _physics_process at 30 Hz, with NO render-frame (_process) interpolation and Godot's built-in physics_interpolation DISABLED. Result: on a 100 fps display, positions update only 30x/sec and visually "step" — the game looks like 30fps even though FPS=100. This is the user's #1 complaint ("everything clipping around on low fps").

Read FULLY and trace exactly where each visible node's position/global_position is assigned and in which callback (_process vs _physics_process):
- client/scripts/client/prediction.gd  (local player: find every write to local_player.position / predicted_position application AND any smoothing pass — is the visual smoothing in _process or _physics_process?)
- client/scripts/client/interpolation_controller.gd  (remote entities: is interpolation computed and applied in _physics_process or _process? how often are node positions updated?)
- client/scripts/client/client_entity_manager.gd  (how visual nodes get their transforms)
- client/scripts/shared/player/remote_player.gd
- client/scripts/shared/player/player.gd  (does move_and_slide run in _physics_process?)
Then grep client/project.godot for: physics_interpolation, physics_ticks_per_second, max_fps, and any [rendering]/[physics] keys. Report whether physics/common/physics_interpolation is true/false/absent.

Deliver: a definitive verdict on whether motion is locked to 30 Hz visually, the exact mechanism, evidence with file:line, and ranked fixes. For fixes, evaluate BOTH (a) enabling Godot 4 physics_interpolation project setting + setting positions only in _physics_process, and (b) manually interpolating node transforms in _process between the last two physics states, and (c) raising physics_ticks_per_second to 60. State which is decisive for the "looks like 30fps" problem.`,
  },
  {
    key: 'input-double-action',
    prompt: `HYPOTHESIS TO CONFIRM OR REFUTE: After authority sync the code calls local_player.set_input_enabled(true), which makes Player.gd independently read Input and run movement (move_and_slide) AND possibly shooting, WHILE the PredictionController ALSO independently reads input and moves/shoots the same local player every tick. This double-processing causes: (1) "steering boat" delayed/odd movement because two writers fight over position with different integration, and (2) "shots come out as pairs" because shoot is triggered in two places (or predicted locally AND re-spawned from the server event and both rendered).

Read FULLY and trace one left-click and one movement key from capture to effect:
- client/scripts/client/prediction.gd (input capture _capture_input_flags, shoot edge-detection, where movement is applied, where shoot is sent/predicted)
- client/scripts/shared/player/player.gd (_handle_movement, any _handle_shoot / _input / _unhandled_input, set_input_enabled, _physics_process)
- client/scripts/shared/arena_base.gd (around set_input_enabled(true) ~line 374, and how local player input is wired)
- client/scripts/shared/networking/packets/player_input_packet.gd
- grep client/scripts/client for any other Input.is_action / get_vector / mouse-button reads
Determine precisely: Is movement integrated by BOTH Player.gd move_and_slide and PredictionController in the same frame? Is shoot detected/fired in more than one place? What is the exact cause of "shots in pairs" (double edge-detect across 30Hz sampling? local-predicted projectile + server-echoed projectile both shown? client AND server both spawning a visual?)?

Deliver verdict, exact mechanism for BOTH the steering-boat feel and the paired-shots, evidence file:line, and ranked fixes (e.g. disable Player.gd movement/shoot in networked mode so PredictionController is sole owner).`,
  },
  {
    key: 'hit-detection',
    prompt: `The user reports "hits don't detect as they should." Investigate hit/collision registration end to end and explain WHY hits feel unreliable. Read FULLY:
- client/scripts/server/server_collision_handler.gd
- client/scripts/server/projectile_manager.gd (collision detection, spatial grid, hit radii)
- client/scripts/shared/game_constants.gd (grep for HIT, RADIUS, HITBOX, COLLISION, PLAYER_RADIUS, PROJECTILE_RADIUS, MONSTER_RADIUS, SHOOT_COOLDOWN)
- client/scripts/client/prediction.gd (is there ANY client-side hit/shoot prediction, or does the client wait for a server GAME_EVENT to show a hit?)
- how the client shows a projectile and its impact (client_entity_manager.gd, projectile.gd)
Determine: Is PvP hit detection done on the CURRENT server tick with no lag compensation (so a moving target requires leading)? What are the actual hit radii and how forgiving are they? Does the shooter get any immediate client feedback, or is there a full round-trip before a hit is shown? Could the 0.3s shoot cooldown + 30Hz edge-detected input drop or double inputs (held button producing 0 or 2 shots)?

Deliver verdict on the primary reason hits feel unreliable, mechanism, evidence file:line, and ranked fixes (client-side shoot feedback, PvP lag comp, radius tuning, input edge-detection fix).`,
  },
]

const findings = await parallel(
  tasks.map((t) => () => agent(t.prompt, { label: `trace:${t.key}`, phase: 'Trace motion + input', schema: SCHEMA }))
)

return findings.filter(Boolean)
