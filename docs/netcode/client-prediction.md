# Client prediction & reconciliation

**Status:** Partial (verified 2026-06-03 against code)

> Built and live, but tagged **Partial** for two reasons:
> 1. A second integrator (`Player.gd`) also moves the Local player, fighting the predictor —
>    the "steering boat" feel. Full bug + fix in [`../systems/players-movement.md`](../systems/players-movement.md).
> 2. Input is sampled *and* sent at 30 Hz, coupling responsiveness to the Tick rate.
>    Where that lands in the latency stack: [`latency-budget.md`](latency-budget.md).

The **Local player** is predicted: the client simulates its own input immediately and corrects
to the server later. Every **Remote entity** is interpolated instead, never predicted — see
[`interpolation.md`](interpolation.md). This doc is entirely client-side; the authority that
the client reconciles *against* lives in [`server-tick-broadcast.md`](server-tick-broadcast.md).

`PredictionController` (`prediction.gd`) owns the whole loop. It is attached as a child of the
Local player node and initialised by `setup()` once authority syncs (`arena_base.gd:368-371`).

## The loop (one `_physics_process`, 30 Hz)

Everything happens inside `_physics_process` (`prediction.gd:142`), which Godot runs at
`physics_ticks_per_second = 30`. There is no `_process` pass — a cause of the separate render
stutter in [`smoothness-render.md`](smoothness-render.md). Per Tick, in order:

| Step | What | Evidence |
|------|------|----------|
| 1 | Sample input into a bitmask (`_capture_input_flags`) | `prediction.gd:157`, `:177-200` |
| 2 | Apply local prediction immediately (move predicted_position) | `prediction.gd:162`, `:262-281` |
| 3 | If mid-correction, advance the visual lerp | `prediction.gd:165-166`, `:622-640` |
| 4 | Every `INPUT_SEND_INTERVAL`, stamp a sequence and send the input | `prediction.gd:169-172` |

`INPUT_SEND_INTERVAL = GameConstants.SERVER_TICK_INTERVAL` (`prediction.gd:71`,
`game_constants.gd:15`) = 1/30 s. Because the gate equals the physics interval, **input is sampled
and sent once per Tick — 30 Hz both ways.** Mouse aim is resolved at send time
(`_get_aim_angle`, `prediction.gd:203-208`).

## Prediction (Step 2)

Input flags → direction → speed → integrate `predicted_position` analytically with obstacle
collision, then derive velocity from the actual delta moved (`prediction.gd:262-281`):

- Direction from WASD flags, normalised (`_get_direction_from_flags`, `:283-295`).
- Speed: `PLAYER_SPEED` 200, or `PLAYER_SPRINT_SPEED` 320 when the sprint flag is set
  (`_get_speed_from_flags`, `:298-301`; `game_constants.gd:32,38`).
- Move via `GameConstants.move_with_obstacle_collision(... PLAYER_HITBOX_RADIUS)` — the **same**
  analytic mover used on replay, so prediction and replay stay byte-for-byte consistent.

The visual node follows `predicted_position` directly (`_update_player_visual`, `:602-607`) —
*unless* a smooth correction is in flight (Step 3 owns the node then).

## Input buffering & sequence numbers

Each sent input is stored as an `InputSnapshot` keyed by its sequence
(`_store_input`, `prediction.gd:306-310`; class at `:83-104`). The snapshot records the
flags, the predicted positions before/after, velocity, aim, and the `delta` used
(`INPUT_SEND_INTERVAL`) so replay re-simulates the identical step.

| Property | Value | Evidence |
|----------|-------|----------|
| Sequence width | 8-bit, wraps at 256 | `_advance_sequence` `prediction.gd:356-359` |
| Replay buffer cap | 256 (`max_buffer_size`, == sequence range) | `prediction.gd:22` |
| Wraparound compare | forward-distance < 128 ⇒ "before" | `_sequence_less_than` `:346-352` |
| Pruning | erase any seq ≤ `last_ack_sequence` | `_prune_acknowledged_inputs` `:313-329` |

The buffer is a `Dictionary` (`prediction.gd:60`), so 256 is a logical cap matching the sequence
space, not a ring; acked entries are pruned each ack/reconcile. The wire packet carries
position, velocity, flags, aim, `sequence_number`, `client_render_tick`, and `client_rtt_ms`
(`player_input_packet.gd:1-11,79-86`).

## Reconciliation

Two server messages drive correction (`_on_server_message`, `prediction.gd:423-428`):

- **`ACTION_CONFIRM`** — per-input ack carrying `sequence_number` + `corrected_position`
  (`_handle_action_confirm`, `:431-461`). Updates `last_ack_sequence`. If the server flags a
  non-`SUCCESS` result, or the predicted position has drifted past the epsilon, it reconciles.
- **`STATE_UPDATE`** — the Local player's own entity inside a Snapshot
  (`_handle_state_update`, `:464-506`). If there are no unacked inputs it snaps directly
  (`_apply_authoritative_position_without_replay`, `:702-714`); otherwise it reconciles on drift.

**Drift gate:** reconciliation only fires when
`predicted_position.distance_to(server_position) > server_position_epsilon` (= **4 units**,
`prediction.gd:30,458,503`). Below that, the quantised server position (0.1-unit wire precision)
is treated as jitter and ignored — no correction.

**Reconcile = snap + replay** (`_reconcile`, `prediction.gd:511-559`):

1. Snap `predicted_position` to the server's authoritative position (`:521`).
2. Collect unacked sequences after the ack, in order (`_get_unacknowledged_sequences`, `:562-577`).
3. Re-simulate each (`_replay_input`, `:580-597`) with the *same* mover and `delta` used originally,
   so the predictor catches back up to "now" from the authoritative base.
4. Decide how the **visual** node reaches the new predicted position (smoothing, below).
5. Prune acked inputs.

### Smoothing the correction

The reconcile updates the logical `predicted_position` instantly, but the visible node is eased
so corrections don't pop — unless the jump is large:

| Case | Behaviour | Evidence |
|------|-----------|----------|
| visual→predicted distance > `teleport_threshold` (**150 u**) | instant snap | `prediction.gd:543-544`, `_apply_instant_correction` `:615-619` |
| otherwise | exponential lerp toward predicted | `_start_smooth_correction` `:610-612` |
| lerp rate | `interpolation_speed` = **12.0** (`current.lerp(target, 12.0 * delta)`) | `prediction.gd:20`, `_apply_smooth_correction` `:632` |
| stop condition | within 1.0 u of target | `prediction.gd:636-638` |

`force_sync` (`prediction.gd:646-657`) is the hard reset used at authority sync / recovery:
clears the buffer, slams position, and snaps the node — no smoothing.

## Status caveats (why Partial)

### Double-movement ("steering boat")

After authority sync, `arena_base.gd` calls `local_player.set_input_enabled(true)` (`:374`, also
`:418`, `:493`). That re-arms `Player.gd._physics_process`, which independently reads the *same*
input and drives the **same** node via `_handle_movement` + `move_and_slide`
(`player.gd:103-109,119-127`, speed 200 at `:24`). So two integrators write the node each Tick —
the `CharacterBody2D` physics mover *and* the predictor's analytic `predicted_position`
(`prediction.gd:271-280`) — and they leapfrog. Fix: the `PredictionController` must be the **sole**
owner of Local-player motion; do not re-enable `Player.gd` movement for the networked Local player.
Full writeup: [`../systems/players-movement.md`](../systems/players-movement.md).

(Local projectile spawning is *correctly* disabled here — `set_local_projectile_spawning_enabled(false)`
at `arena_base.gd:220`, `player.gd:145-147` — so this is a movement-only double-ownership, not a
shooting one.)

### 30 Hz input coupling

Input is sampled and sent strictly at the Tick interval (`prediction.gd:71,157,170`). At 30 Hz a
keypress waits up to ~33 ms before it is even sampled, before any network or server time. Raising
`physics_ticks_per_second` lowers that floor but doubles prediction/replay CPU and shifts the send
cadence with it. Where this sits in the end-to-end budget: [`latency-budget.md`](latency-budget.md).

## The eight questions

- **Client:** samples input, predicts Local-player motion, buffers inputs, reconciles, eases the visual.
- **Server:** the authority being reconciled against — sends `ACTION_CONFIRM` + `STATE_UPDATE` (see [`server-tick-broadcast.md`](server-tick-broadcast.md)).
- **Predicted:** the Local player's position/velocity only; Remote entities are interpolated, never predicted.
- **Replicated:** the Local player's authoritative position arrives via Snapshot/ack and overrides prediction on drift.
- **Persisted:** nothing — prediction is transient client state; the Go API persists no gameplay position.
- **Validated:** server-side (movement validation), not here; the client only requests, the server decides.
- **Can fail:** the double-movement leapfrog (`Player.gd` + predictor) and 30 Hz sample latency; replay desync if the mover diverges from the server's.
- **Tested:** no automated reconciliation test today; exercised via the live arena and bot swarm.

## See also

- [`../systems/players-movement.md`](../systems/players-movement.md) — the double-movement bug + fix in full
- [`latency-budget.md`](latency-budget.md) — where 30 Hz input sampling lands in perceived delay
- [`smoothness-render.md`](smoothness-render.md) — why 30 Hz physics writes look choppy regardless of FPS
- [`interpolation.md`](interpolation.md) — the Remote-entity counterpart (interpolated, not predicted)
- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the authority side: ack + Snapshot generation
