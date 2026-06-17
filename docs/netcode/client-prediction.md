# Client prediction & reconciliation

**Status:** Implemented (verified 2026-06-14 against the Rust port).

> Post-Rust-port reality: the predictor no longer integrates movement in GDScript. It drives the
> **shared compiled `sim_core` crate** through the `PredictionSim` GDExtension class, which wraps
> the **same `MovementSm` + analytic mover the authoritative Rust server runs** (`rust/sim_core/src/step.rs`,
> exposed by `rust/client_ext/src/lib.rs`). Prediction cannot diverge from the server's movement
> code by construction — there is one implementation, compiled once, called from both sides.

The **Local player** is predicted: the client simulates its own input immediately and corrects
to the server later. Every **Remote entity** is interpolated instead, never predicted — see
[`interpolation.md`](interpolation.md). This doc is entirely client-side; the authority that the
client reconciles *against* is the Rust `omega-server` — see [`server-tick-broadcast.md`](server-tick-broadcast.md)
and the wire contract in [`../server/contract.md`](../server/contract.md).

The prediction loop lives in the **prediction controller** (`client/scripts/network/prediction.gd`,
`class_name PredictionController`; slated to move under `client/scripts/network/` later — described
here by role). It is attached as a child of the Local player node and initialised by `setup()` once
Authority sync lands (entity id from `AuthResult`, or the PLAYER_INFO broadcast).

## The shared sim seam

`PredictionController` owns one `PredictionSim` instance (`prediction.gd` `_sim`), created at load.
`PredictionSim` (Rust, `rust/client_ext/src/lib.rs`) holds a `sim_core::MovementSm` and exposes two
movement entry points, both byte-identical to the server:

| Call | Backs onto | Used for |
|------|-----------|----------|
| `step(delta, position, move_dir, sprint, dash, ability, attacking, aim_dir)` | `sim_core::step_movement` (`rust/sim_core/src/step.rs`) | live per-tick prediction — full SM: dash, sprint, knockback, charge, daze, stamina/mana |
| `replay_step(position, input_flags, delta)` | `sim_core::replay_ground_step` (same file) | reconciliation replay — the deliberately-simplified ground-speed-only model |

`step_movement` runs the full stages — `MovementSm::tick` (state machine) → integrate
`velocity * dt` → `move_with_obstacle_collision` (the shared analytic mover) → recompute the
*realized* velocity from the actual delta moved (`StepResult`). This mirrors the server's
`PlayerState.step` exactly (`rust/sim_core/src/step.rs` module doc). FFI inputs are sanitized at the
boundary: a NaN/Inf position/dir/delta falls back to ZERO / the fixed tick interval rather than
corrupting the node transform (`PredictionSim::step`, `rust/client_ext/src/lib.rs`).

The connected instance's world geometry is pushed in once on scene entry via
`set_world_geometry(min, max, obstacles_enabled)` (Arena ±1000 + obstacles, Sanctuary ±3328×±3072 no
obstacles) so the predicted mover collides identically to the server. Per-class ability tuning and
base move speed are pushed via `set_ability_config` / `set_base_speed` from `CLASS_ABILITY_CONFIG`
(`prediction.gd`), so a predicted Warrior Charge / Rogue Shadowstep matches the authoritative cast.

## The loop (one `_physics_process`, 30 Hz)

Everything happens inside `_physics_process` (`prediction.gd`), which Godot runs at
`physics_ticks_per_second = 30`. Per Tick, in order:

| Step | What | Where |
|------|------|-------|
| 1 | Sample input into a bitmask (`_capture_input_flags`) + cosmetic shoot feedback | `prediction.gd` `_capture_input_flags`, `_maybe_emit_shoot_predicted` |
| 2 | Apply local prediction immediately via `PredictionSim.step` | `prediction.gd` `_apply_local_prediction` |
| 3 | If mid-correction, advance the visual lerp | `prediction.gd` `_apply_smooth_correction` |
| 4 | Every `INPUT_SEND_INTERVAL`, stamp a sequence and send the input | `prediction.gd` `_send_input_to_server` |

`INPUT_SEND_INTERVAL = GameConstants.SERVER_TICK_INTERVAL` = 1/30 s (`prediction.gd`,
`game_constants.gd`). Because the gate equals the physics interval, **input is sampled and sent once
per Tick — 30 Hz both ways.** Mouse aim is resolved at step/send time (`_get_aim_angle`); the
world-space cursor (`_get_cursor_world`) is also sent, for the server's cursor-targeted abilities
(protocol v4 PlayerInput, see [`../server/contract.md`](../server/contract.md)).

Movement is **single-owner**: the predictor is the sole integrator of the Local player. `Player.gd`
sets `prediction_owns_movement = true` for the networked Local player and **skips its own
`move_and_slide()`** (`client/scripts/entities/player/player.gd`), so the old "steering boat"
double-integration is gone — see [`../systems/players-movement.md`](../systems/players-movement.md).

## Prediction (Step 2)

`_apply_local_prediction` builds the direction from WASD flags (`_get_direction_from_flags`) and the
aim direction from the mouse, then makes **one** extension call into `PredictionSim.step` with the
sprint / dash / ability / shoot flags. The Rust SM applies speed (`PLAYER_SPEED` 200, sprint via the
SM's stamina-gated ground speed), the state machine (dash/charge/knockback/daze), and the analytic
obstacle mover — all server-identical. The returned `position` / `velocity` become
`predicted_position` / `predicted_velocity`, and `stamina` / `mana` / `exhausted` are mirrored into
the GDScript movement SM purely so the HUD bars and blink signals keep working (the Rust sim owns the
real prediction state).

The visual node follows `predicted_position` directly (`_update_player_visual`) — *unless* a smooth
correction is in flight (Step 3 owns the node then). The Local player uses Godot
`physics_interpolation` so 30 Hz physics writes render smoothly at any FPS; hard snaps call
`reset_physics_interpolation()` to avoid lerping across a discontinuity (see
[`smoothness-render.md`](smoothness-render.md)).

## Input buffering & sequence numbers

Each sent input is stored as an `InputSnapshot` keyed by its sequence (`_store_input`; class at the
top of `prediction.gd`). The snapshot records the flags, the predicted positions before/after, the
velocity, the aim, and the `delta` used (`INPUT_SEND_INTERVAL`) so replay re-simulates the identical
step. The "after" position/velocity at send time come from a `replay_step` dry-run, so the buffered
prediction and the replay model agree from the start.

| Property | Value | Where |
|----------|-------|-------|
| Sequence width | 8-bit, wraps at 256 | `_advance_sequence` (matches the wire `u8 seq`) |
| Replay buffer cap | 256 (`max_buffer_size`, == sequence range) | `prediction.gd` |
| Wraparound compare | forward-distance < 128 ⇒ "before" | `_sequence_less_than` |
| Pruning | erase any seq ≤ `last_ack_sequence` | `_prune_acknowledged_inputs` |

The buffer is a `Dictionary`, so 256 is a logical cap matching the 8-bit sequence space, not a ring;
acked entries are pruned each ack/reconcile. The PlayerInput packet (type 2, ch2 — **22 B**,
protocol v4) carries seq, input_flags, aim_angle, the predicted position+velocity, the cursor,
`client_render_tick`, and `client_rtt_ms`; it is encoded by `ProtocolCodec.encode_input`
(`rust/client_ext/src/lib.rs`). Exact layout: [`../server/contract.md`](../server/contract.md) §PlayerInput.

## Reconciliation

Two server messages drive correction (`_on_server_message`, decoded by
`ProtocolCodec.decode_server_packet` into the legacy dict shapes):

- **`ACTION_CONFIRM`** — per-input ack carrying `sequence_number`, `corrected_position`, `result_code`,
  the authoritative `stamina` / `mana`, and the authoritative `dash_cooldown` / `ability_cooldown`
  (`_handle_action_confirm`). Updates `last_ack_sequence`, feeds stamina/mana into the sim via
  `PredictionSim.set_resources`, and **reconciles the predicted dash + RMB cooldowns** (below). If the
  server flags a non-`SUCCESS` result, or the predicted position has drifted past the epsilon, it
  reconciles position too. Wire: ActionConfirm (type 66, ch0),
  [`../server/contract.md`](../server/contract.md) §ActionConfirm.
- **`STATE_UPDATE`** (the Snapshot) — the Local player's own entity record inside a Snapshot
  (`_handle_state_update` → `_process_own_state_update`). If there are no unacked inputs it snaps
  directly (`_apply_authoritative_position_without_replay`); otherwise it reconciles on drift. The
  server's own entity flags also slave local **daze** and **Warrior charge-end** (`_update_own_flags`,
  `_update_own_charge`) so prediction releases those states exactly when the server does instead of
  rubber-banding through them. Wire: Snapshot (type 65; deltas ch0, baselines ch1), with `server_ms`
  riding every snapshot for clock sync.

**Drift gate:** reconciliation only fires when
`predicted_position.distance_to(server_position) > server_position_epsilon` (= **4 units**,
`prediction.gd`). Below that, the quantised server position (0.1-unit wire precision — pos ×10
truncate-toward-zero, [`../server/contract.md`](../server/contract.md) §Numerics) is treated as
jitter and ignored — no correction.

**Reconcile = snap + replay** (`_reconcile`, `prediction.gd`):

1. Snap `predicted_position` to the server's authoritative position.
2. Collect unacked sequences after the ack, in order (`_get_unacknowledged_sequences`).
3. Re-simulate each (`_replay_input` → `PredictionSim.replay_step` → `sim_core::replay_ground_step`)
   with the same `input_flags` and `delta`, catching the predictor back up to "now" from the
   authoritative base.
4. Decide how the **visual** node reaches the new predicted position (smoothing, below).
5. Prune acked inputs.

### Why replay uses a simpler model

`replay_step` runs `replay_ground_step` (`rust/sim_core/src/step.rs`), a deliberately-simplified,
**stateless ground-speed-only** model: it applies WASD direction at the SM's ground speed (sprint
gated by the SM's *current* stamina / exhaustion / daze, not snapshot-time state) through the same
`move_with_obstacle_collision` mover, and **never replays dash, knockback, charge, or stun
velocities**. It does not mutate the SM. The rationale (`step.rs` doc comment + `prediction.gd`
`_replay_input`): those states are brief, rarely span a correction window, and any small residual
heals on the next snapshot — replaying them statefully would be both harder and less stable. For
plain WASD movement the replay model and the full `step_movement` produce identical positions, which
the crate asserts in tests (`replay_matches_walk_prediction_for_plain_movement`, `replay_never_dashes`
in `rust/sim_core/src/step.rs`).

### Cooldown reconciliation (dash / RMB ability)

The dash and RMB-ability **cooldowns** are committed by *prediction*: `try_dash` /
`try_activate_ability` set `dash_cooldown_left` / `ability_cooldown_left` the instant the client
predicts the dash/cast, and the HUD shows that *predicted* timer (mirrored from the `step` result
into the GDScript SM via `set_predicted_cooldowns`). The server decides the action independently with
its **own** cooldown, which starts ~½ RTT later.

Because the dash bit rides **one** unreliable input packet (latched on press, cleared after a single
send — `prediction.gd` `_dash_latched`), the two cooldowns drift permanently out of phase whenever
they disagree about whether a dash happened: a **lost** dash packet (the server never dashes, the
client did), or a **cooldown-boundary** press (the client predicts a dash the instant its HUD bar
empties, but the server's lagging cooldown hasn't cleared, so the server *refuses* — yet the client
has already started a fresh full cooldown). Symptom: you lunge a couple units, snap back, and the dash
never lands; then a later press *"while still on cooldown"* dashes, because the server cleared its
timer long ago. Nothing used to correct this — only position/stamina/mana were reconciled.

**Fix:** the ActionConfirm carries the server's authoritative `dash_cooldown` / `ability_cooldown`
(deciseconds), and `_handle_action_confirm` → `_reconcile_cooldowns` pulls the predicted cooldowns
back into phase via `PredictionSim.set_dash_cooldown` / `set_ability_cooldown`. The comparison is
**per-sequence, not against the live cooldown**: the confirm reports the server's cooldown for the
input it is *acking*, so it is diffed against what the client *predicted when it sent that same input*
(recorded per-sequence on the `InputSnapshot`). This is essential — a confirm still in flight for an
input sent **before** a dash legitimately reads cooldown 0 on the server, and diffing that against the
live (just-started) cooldown would cancel a correct prediction for ~1 RTT on *every* dash. A gap beyond
`COOLDOWN_RECONCILE_EPSILON` (= **0.75 s**, above typical RTT + the 0.1-s quant step, so a benign
offset never corrects) is a genuine desync: the live cooldown is shifted by that gap (the elapsed real
time since the send cancels out exactly), and the same shift is propagated to the still-in-flight
snapshots so the rest of that batch doesn't double-apply it. Heals within ~1 RTT. The setters floor
negatives to 0 and ignore non-finite (`MovementSm::set_dash_cooldown` / `set_ability_cooldown`,
`set_cooldowns_reconcile_and_floor` test) — the only *external* writers of those decrement-only timers
besides `try_dash` / `try_activate_ability`.

### Smoothing the correction

The reconcile updates the logical `predicted_position` instantly, but the visible node is eased so
corrections don't pop — unless the jump is large:

| Case | Behaviour | Where |
|------|-----------|-------|
| visual→predicted distance > `teleport_threshold` (**150 u**) | instant snap + `reset_physics_interpolation()` | `prediction.gd` `_apply_instant_correction` |
| otherwise | exponential lerp toward predicted | `prediction.gd` `_start_smooth_correction` |
| lerp rate | `interpolation_speed` = **12.0** (`current.lerp(target, 12.0 * delta)`) | `prediction.gd` `_apply_smooth_correction` |
| stop condition | within 1.0 u of target | `prediction.gd` `_apply_smooth_correction` |

`force_sync` (`prediction.gd`) is the hard reset used at Authority sync / recovery: clears the
buffer, slams position, snaps the node, and resets physics interpolation — no smoothing.

## The eight questions

- **Client:** samples input, predicts Local-player motion via the shared `sim_core` (`PredictionSim.step`), buffers inputs, reconciles, eases the visual.
- **Server:** the Rust `omega-server` authority being reconciled against — sends `ACTION_CONFIRM` + Snapshot (see [`server-tick-broadcast.md`](server-tick-broadcast.md), [`../server/contract.md`](../server/contract.md)).
- **Predicted:** the Local player's position/velocity (and predicted stamina/mana via the SM, plus predicted Warrior Charge / Rogue Shadowstep blink). Remote entities are interpolated, never predicted.
- **Replicated:** the Local player's authoritative position arrives via Snapshot/ack and overrides prediction on drift; daze and charge-end are slaved to the server's entity flags.
- **Persisted:** nothing — prediction is transient client state. The Go API persists only account/character/leaderboard/progression, never live position (server-authoritative + in-memory).
- **Validated:** server-side. The client requests; the server decides and answers with `ACTION_CONFIRM` (incl. authoritative stamina/mana). The client only corrects toward that answer.
- **Can fail:** packet loss past the 256-deep buffer; knockback is not predicted at all — while the `KNOCKED_BACK` flag is set the local player freezes prediction and follows the server position (`prediction.gd::_follow_server_through_knockback`), with a 0.75 s backstop for a lost falling-edge flag; a predicted dash/cast the server refuses or never receives (the dash bit rides one unreliable packet) — heals via cooldown reconciliation within ~1 RTT; replay can only mismatch if the buffered flags/delta differ from what the server applied — the movement *code* cannot diverge (one compiled crate).
- **Tested:** `sim_core` movement/replay parity is unit-tested in Rust (`rust/sim_core/src/step.rs`); the end-to-end reconcile loop is exercised via the live arena and the `omega-load-test` bot swarm, plus the net smoke scene.

## See also

- [`../server/contract.md`](../server/contract.md) — the wire contract (PlayerInput, ActionConfirm, Snapshot, numerics) the predictor encodes/decodes against
- [`../systems/players-movement.md`](../systems/players-movement.md) — the Local-player movement system (single-owner integration)
- [`latency-budget.md`](latency-budget.md) — where 30 Hz input sampling lands in perceived delay
- [`smoothness-render.md`](smoothness-render.md) — `physics_interpolation` + discontinuity resets for the Local player
- [`interpolation.md`](interpolation.md) — the Remote-entity counterpart (interpolated, not predicted)
- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the authority side: ack + Snapshot generation
