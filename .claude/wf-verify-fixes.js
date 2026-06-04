export const meta = {
  name: 'verify-p0-p1-fixes',
  description: 'Confirm each of the 6 P0/P1 fixes is wired in current code and define an isolating test + objective signal per fix',
  phases: [{ title: 'Verify fixes', detail: 'one verifier per fix against current committed code' }],
}

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['fix_id', 'title', 'present', 'evidence', 'glassy_confirms', 'why', 'isolating_test', 'objective_signal', 'risks'],
  properties: {
    fix_id: { type: 'string' },
    title: { type: 'string' },
    present: { type: 'string', enum: ['present-and-wired', 'present-but-suspect', 'missing-or-regressed'] },
    evidence: { type: 'array', items: { type: 'string' }, description: 'file:line facts proving the current state' },
    glassy_confirms: { type: 'string', enum: ['full', 'partial', 'none'], description: 'Does a glassy/smooth feel confirm THIS fix works?' },
    why: { type: 'string', description: 'Why glassy does/does not prove this specific fix' },
    isolating_test: { type: 'string', description: 'A concrete play-test that isolates THIS fix from the others' },
    objective_signal: { type: 'string', description: 'A non-feel signal (debug overlay field, metric, log, projectile count) that confirms it' },
    risks: { type: 'string', description: 'What could still be wrong even if it looks fixed' },
  },
}

const FIXES = [
  { id: '#1', title: 'physics_interpolation smoothness (the 30fps-look)',
    files: 'client/project.godot (physics_interpolation), client/scripts/client/interpolation_controller.gd (reset_physics_interpolation at teleport/register), client/scripts/client/prediction.gd (resets + visual_position_updated signal), client/scripts/shared/arena_base.gd (camera now driven by the signal, Camera2D physics-interp mode)',
    note: 'The camera was REWORKED after the original fix (commit 9235302): it is no longer get_global_transform_interpolated() (that is 3D-only) — it is now driven by prediction.gd visual_position_updated signal into arena_base._on_local_player_visual_position_updated/_snap_camera_to. Confirm this wiring is correct and that physics_interpolation is on. Glassy feel = this fix; assess if it is fully confirmed.' },
  { id: '#2', title: 'PredictionController sole local mover (steering-boat)',
    files: 'client/scripts/shared/player/player.gd (prediction_owns_movement guards move_and_slide), client/scripts/shared/arena_base.gd (sets local_player.prediction_owns_movement = true)',
    note: 'Confirm Player.gd does NOT run move_and_slide for the local networked player and that PredictionController is the sole position writer. Glassy smoothness does NOT prove control responsiveness — define a test for the boat-steering feel.' },
  { id: '#3', title: 'Snapshot rate 20 -> 30 Hz',
    files: 'client/data/config/server_config.json (snapshot_rate_hz), client/scripts/server/server_config.gd, client/scripts/server/server_main.gd (snapshot cadence)',
    note: 'Confirm the LIVE snapshot rate is 30 (json wins at runtime). This is a latency/cadence change invisible to local smoothness.' },
  { id: '#4', title: 'Adaptive remote render delay',
    files: 'client/scripts/client/interpolation_controller.gd (MIN/MAX_RENDER_DELAY_TICKS, render_delay_ticks_smooth, jitter EMA, render_tick computation, get_debug_info)',
    note: 'Confirm the effective render delay adapts and is used in render_tick (not the fixed const). On localhost it should settle to ~1 tick (~33ms). Glassy is local smoothness; this affects REMOTE entity trailing latency. Identify the debug-overlay field that exposes it.' },
  { id: '#5', title: 'Paired-shots dedup (fire <=1 shot/player/tick)',
    files: 'client/scripts/server/server_main.gd (_process_shoot_inputs), client/scripts/server/player_state.gd, client/scripts/server/player_manager.gd',
    note: 'Confirm at most one projectile spawns per player per tick. Glassy does not touch this — define a single-click test and an objective count.' },
  { id: '#6', title: 'Seeded interpolation timing (kill 20Hz micro-stutter)',
    files: 'client/scripts/client/entity_state_buffer.gd (TICK_INTERVAL_SEC, estimated_tick_interval_ms), client/scripts/client/interpolation_controller.gd (estimated_tick_interval seed)',
    note: 'Confirm timing is seeded from GameConstants.SERVER_TICK_INTERVAL (33.3ms), not 0.05 (20Hz). Glassy partially confirms (no remote micro-stutter) — identify the debug field (estimated_tick_interval_ms) to confirm objectively.' },
]

phase('Verify fixes')

const results = await parallel(
  FIXES.map((f) => () =>
    agent(
      `Verify P0/P1 netcode fix ${f.id} ("${f.title}") in the CURRENT committed code on branch perf/p0-p1-netcode-fixes. ` +
      `The user just play-tested and reports the game now feels "glassy" (smooth). They ask whether that proves fixes #1-#6 work. ` +
      `Your job for THIS fix: (1) Read the relevant files and confirm the fix is present and correctly wired — report present/suspect/regressed with file:line evidence. ` +
      `(2) Decide whether a "glassy/smooth" feel CONFIRMS this specific fix (full/partial/none) and explain why — be rigorous: smoothness is rendering, distinct from control responsiveness, shot-count correctness, and remote-entity latency. ` +
      `(3) Give ONE concrete play-test that ISOLATES this fix from the other five. (4) Give an OBJECTIVE signal (a debug-overlay field, a server metric, a log line, a projectile count) the user can read to confirm without relying on feel — name the exact field/source if it exists (check debug_overlay.gd / server_status / get_debug_info). (5) Note residual risks. ` +
      `IMPORTANT context: the camera was reworked after the original fix (commit 9235302) — get_global_transform_interpolated() is 3D-only and was replaced by a prediction.gd visual_position_updated signal. ${f.note} ` +
      `Files to read: ${f.files}. Also check client/scripts/shared/player/debug_overlay.gd and client/scripts/client/hud/server_status.gd for exposable signals. Return the structured result only.`,
      { label: `verify ${f.id}`, phase: 'Verify fixes', schema: SCHEMA }
    )
  )
)

return results.filter(Boolean)
