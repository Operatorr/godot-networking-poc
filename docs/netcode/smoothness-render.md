# Render smoothness — "looks like 30 fps at 100 fps"

**Status:** As built (fix landed). The client renders at any FPS off an authoritative **30 Hz**
tick from the Rust `omega-server`. Two mechanisms cooperate:

1. **Local player + camera** — Godot 4 built-in **physics interpolation**
   (`project.godot` `physics/common/physics_interpolation=true`), with
   `reset_physics_interpolation()` on every discontinuity.
2. **Remote entities** (other players, monsters, projectiles, world effects) — the
   `InterpolationController` owns their rendered motion directly, every render frame, on a
   continuous fractional-tick timeline; their engine physics interpolation is turned **off**.

> This is a **smoothness** problem, separate from the **latency** problem in
> [`latency-budget.md`](latency-budget.md). They are commonly felt together ("everything is
> lagging / clipping around on low fps"), but they have different causes and different fixes.
> This one is the more visceral of the two, and the fix is the smallest, highest-impact change
> in the whole investigation. This doc is the **least Rust-coupled** of the netcode set: the
> server just ticks at 30 Hz and ships snapshots — smoothness is a pure client render concern.

## Symptom (the original bug)

The FPS counter read ~100, but **motion** looked like ~30 fps — entities visibly stepped/jumped
rather than glided. Reported as: *"it feels like I'm playing on less than 30 fps while I should be
at 100 fps… everything is clipping around on low fps."*

## Root cause (confirmed)

**Every visible position was written only inside `_physics_process`, which runs at the tick rate
(30 Hz), and Godot's built-in physics interpolation was off.** Nothing advanced node positions on
render frames. So on a 100 fps display, every group of ~3.3 consecutive frames drew the
**identical** world transform — motion updated 30×/sec while the GPU drew 100×/sec.

Mechanism, end to end (pre-fix):

1. The client physics clock is the server tick rate. `GameConstants.SERVER_TICK_RATE` (30.0,
   `client/scripts/data/game_constants.gd`) is the single authority; `game_manager._ready()`
   applies it via `Engine.physics_ticks_per_second` (`client/autoload/game_manager.gd`).
   `project.godot`'s `physics/common/physics_ticks_per_second=30` is only the fallback.
2. **Local player:** `PredictionController._physics_process` writes `player_node.position`
   (`client/scripts/network/prediction.gd`, `_update_player_visual` / corrections). No `_process`
   pass moved the node, so between Ticks it never moved.
3. **Remote entities:** `InterpolationController` assigned `node.position` for every entity but
   committed it only on the physics tick.
4. **Camera / world scroll:** the camera read the local player's position, which itself only
   changed 30×/sec, so the whole world (which scrolls with the camera) also stepped at 30 Hz.

**Net:** 30 distinct world transforms per second, regardless of FPS. That was the stutter.

### Why this is *not* the same as the Render delay

The [Render delay](../CONTEXT.md) (a stage of the latency budget) makes remote entities appear
*late*. This makes *all* motion appear *choppy*. You can have either without the other. Even with
an adaptive Render delay, motion would still step at 30 Hz until this is fixed. Cross-check
[`latency-budget.md`](latency-budget.md).

## The fix, as built

### Local player + camera — engine physics interpolation

Godot 4 built-in physics interpolation is **enabled** (`project.godot` `[physics]`
`common/physics_interpolation=true`). Because the local player's position is written only in
`_physics_process`, the engine interpolates its transform on render frames between the last two
physics states automatically — smooth motion at any FPS, with near-zero per-node code.

**Reset interpolation on every discontinuity** (spawn / teleport / hard correction), or the node
would visibly lerp *across* the jump. The local player calls `reset_physics_interpolation()` at:

- instant prediction correction — `prediction.gd` `_apply_instant_correction()`
- force-sync recovery — `prediction.gd` `force_sync()`

**Camera:** the client owns a dedicated `Camera2D` (`arena_base.gd`, `_setup_client`), it is **not**
parented to the player and does **not** read the raw `local_player.position` each frame. Instead the
`PredictionController` emits `visual_position_updated(visual_position, is_discontinuous)` from its
`_physics_process` pass (`prediction.gd` `_emit_visual_position_updated`), and `arena_base`
drives the camera off that signal (`_on_local_player_visual_position_updated`):

- the camera is configured with `position_smoothing_enabled=false`,
  `process_callback=CAMERA2D_PROCESS_PHYSICS`, and `physics_interpolation_mode=ON` — its position
  is written on physics ticks and Godot interpolates the Camera2D between those physics states on
  render frames, so the world scroll is glassy.
- on a discontinuity, `arena_base._snap_camera_to` snaps the camera and calls both
  `camera.reset_smoothing()` and `camera.reset_physics_interpolation()` so it doesn't lerp across
  the jump.

`get_global_transform_interpolated()` is a 3D helper and is **not** used here; in 2D the camera
relies on its own physics interpolation instead.

Optional polish: `application/run/max_fps` (or `Engine.max_fps`) can be set now that smoothness no
longer depends on raw frame count.

### Remote entities — render-frame interpolation on a continuous timeline

Engine physics interpolation fixed the local player but left a **beat-frequency judder** on
snapshot-driven entities, most visible on your own projectiles while running in the shoot
direction (your body is predicted and glassy; the projectile's stepping is judged against it).
Cause: snapshots and physics ticks are two **unsynchronized 30 Hz clocks** — committing positions
once per physics tick produced uneven per-tick advances (0/1/2 snapshot-intervals per tick), and
the engine's physics interpolation faithfully reproduced the unevenness.

So remote entities do **not** use engine interpolation. In `interpolation_controller.gd`:

- interpolation runs in **`_process` every render frame** (`InterpolationController._process`),
  along a continuous fractional-tick `render_timeline` that advances by wall-clock time and is
  gently pulled toward `current_server_tick + time-since-arrival − adaptive render delay` (snap
  when drift exceeds `RENDER_TIMELINE_SNAP_TICKS` = 3, exponential pull at `RENDER_TIMELINE_PULL_RATE`
  otherwise). The tick interval is seeded from `GameConstants.SERVER_TICK_INTERVAL` and re-calibrated
  from snapshot inter-arrival timing.
- the render delay is **adaptive** within `[MIN_RENDER_DELAY_TICKS=1, MAX_RENDER_DELAY_TICKS=3]`:
  it collapses toward MIN on a clean LAN/localhost link and grows toward MAX under jitter (adds
  buffer fast, sheds it slowly). The `server_ms` field that rides every snapshot (see
  [`server/contract.md`](../server/contract.md) §Snapshot) feeds clock sync; render-delay tuning
  here uses measured inter-arrival jitter.
- registered nodes (remote players, monsters, projectiles, world effects) are set to
  `physics_interpolation_mode = OFF` in `register_entity_node()` — the controller writes their
  rendered position directly each frame, so the engine must not re-interpolate from stale
  physics-tick transforms.
- teleports (a position jump > `TELEPORT_THRESHOLD`) snap the node's position directly in
  `_handle_entity_update`; **no** `reset_physics_interpolation()` is needed because these nodes
  run with engine interpolation off.

The FPS counter was never wrong (`Engine.get_frames_per_second()`); the *positions being drawn*
only changed 30×/sec.

### Alternatives (and why they're second choice)

- **Manual `_process` interpolation for the local player too** — keep physics writes, store
  `prev`/`curr`, lerp by `Engine.get_physics_interpolation_fraction()`. Same visual result but you
  hand-maintain buffers and reset handling that the engine gives for free. The local player keeps
  the engine setting precisely because it has no snapshot-clock skew (its motion is predicted, one
  write per physics tick); remote entities take the manual path because they do.
- **Raise the tick rate 30→60** — halves the stepping and helps, but still steps on a 100/144 Hz
  display, doubles client prediction/interpolation CPU, and shifts input cadence
  (`INPUT_SEND_INTERVAL` derives from `SERVER_TICK_INTERVAL`). The tick rate is a single gated
  toggle: `GameConstants.SERVER_TICK_RATE` is the one client-side authority (applied via
  `Engine.physics_ticks_per_second` in `game_manager._ready()`); the Rust server's tick rate is set
  by `server_config.json` (`tick_rate`) and reported to the client in `AuthResult` (see
  [`server/contract.md`](../server/contract.md) §AuthResult). **The default stays 30 Hz** — 60 Hz is
  unmeasured; the A/B protocol and an empty results table live in
  [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) (results PENDING). A
  complementary knob, **not** the primary fix.

> Built-in physics interpolation (local player + camera) **plus** controller-owned render-frame
> interpolation (remote entities) together resolve the "looks like 30 fps" complaint at any FPS,
> from an unchanged 30 Hz sim. Consider 60 Hz later for input responsiveness only.

## Verification

1. Run the client at uncapped/100+ fps; move the Local player and watch a Remote bot strafe (and
   your own projectiles while running in the shoot direction).
2. Motion should be glassy at 100 fps from the 30 Hz sim. Confirm no visual "rubber" across
   spawns/teleports of the local player (that means a missing `reset_physics_interpolation()`).
3. Confirm the camera no longer steps (world scroll is smooth) and snaps cleanly on respawn.
4. Confirm remote-entity motion is judder-free relative to the predicted local player.

## The eight questions

- **Client:** owns all rendering; this bug and fix are entirely client-side.
- **Server:** the Rust `omega-server` ticks at 30 Hz and ships snapshots
  ([`server/design.md`](../server/design.md)); smoothness is a pure render concern, unaffected.
- **Predicted / replicated / persisted / validated:** unchanged by this fix.
- **Can fail:** missing `reset_physics_interpolation()` on a local-player discontinuity → visible
  lerp across teleports; camera not configured for physics interpolation → world still steps; a
  remote node left with engine interpolation ON → re-introduces the beat-frequency judder.
- **Tested:** visual; the arena client smoke checks the camera follows a finite position
  (`client/scenes/test/arena_client_smoke.tscn`). No automated frame-pacing test today.

## See also

- [`latency-budget.md`](latency-budget.md) — the latency problem felt alongside this
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md)
- [`server/contract.md`](../server/contract.md) — wire format, channels, `server_ms` clock sync, AuthResult tick_rate
- [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) — the gated 30→60 tick trial, results PENDING
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — this is fix #1 (the 30→60 trial is #8)
