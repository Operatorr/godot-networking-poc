# Render smoothness — "looks like 30 fps at 100 fps"

**Status:** Verified against code (2026-06-03). Root cause **confirmed**, fix **not yet applied**.

> This is a **smoothness** problem, separate from the **latency** problem in
> [`latency-budget.md`](latency-budget.md). They are commonly felt together ("everything is
> lagging / clipping around on low fps"), but they have different causes and different fixes.
> This one is the more visceral of the two, and the fix is the smallest, highest-impact change
> in the whole investigation.

## Symptom

The FPS counter reads ~100, but **motion** looks like ~30 fps — entities visibly step/jump
rather than glide. Reported as: *"it feels like I'm playing on less than 30 fps while I should be
at 100 fps… everything is clipping around on low fps."*

## Root cause (confirmed)

**Every visible position is written only inside `_physics_process`, which runs at 30 Hz, and
Godot's built-in physics interpolation is off.** Nothing advances node positions on render
frames. So on a 100 fps display, every group of ~3.3 consecutive frames draws the **identical**
world transform — motion updates 30×/sec while the GPU draws 100×/sec.

Mechanism, end to end:

1. `project.godot` sets `physics/common/physics_ticks_per_second = 30` and has **no**
   `physics/common/physics_interpolation` key → it defaults to **off**. `project.godot:100-103`
2. **Local player:** `PredictionController` runs only in `_physics_process`
   (`prediction.gd:142`) and writes `player_node.position` there (`prediction.gd:602-607`, and
   the correction lerp at `:622-640` uses the 30 Hz physics `delta`). No `_process` pass exists,
   so between Ticks the node never moves.
3. **Remote entities:** `InterpolationController` also runs only in `_physics_process`
   (`interpolation_controller.gd:111`) and assigns `node.position` for every entity
   (`:454`). It computes a sub-tick blend, but the result is *committed* only 30×/sec.
4. **Camera / world scroll:** `arena_base._process` runs every frame but only updates animation
   flags (`client_entity_manager.gd:350-384`), and sets the camera from `local_player.position`
   (`arena_base.gd:122-123`) — a value that itself only changes 30×/sec. So the whole world,
   which scrolls with the camera, also steps at 30 Hz. Camera `position_smoothing` partially
   masks the Local player but does nothing for Remote entities.

**Net:** 30 distinct world transforms per second, regardless of FPS. That is the stutter.

### Why this is *not* the same as the 66.7 ms Render delay

The [Render delay](../CONTEXT.md) (stage 4 of the latency budget) makes remote entities appear
*late*. This makes *all* motion appear *choppy*. You can have either without the other. Even after
you make the Render delay adaptive, motion would still step at 30 Hz until this is fixed.

## The fix (decisive, small)

**Enable Godot 4 built-in physics interpolation.** Because positions are already written only in
`_physics_process`, the engine can interpolate every node's transform on render frames between
the last two physics states automatically — smooth motion at any FPS, with near-zero per-node code.

1. In `project.godot` `[physics]`: `common/physics_interpolation = true`.
2. **Reset interpolation on every discontinuity** (spawn / teleport / hard correction), or the
   node will visibly lerp *across* the jump. Call `node.reset_physics_interpolation()` at:
   - interpolation teleport-snap (`interpolation_controller.gd:~370`) and entity registration (`:~518`)
   - prediction force-sync (`prediction.gd:~646`) and instant correction (`prediction.gd:~615`)
3. **Camera:** stop reading the raw `local_player.position` each frame. In 2D,
   `get_global_transform_interpolated()` is not available; either parent the camera to the player
   so it inherits the player's interpolated transform, or drive Camera2D from the local player's
   post-prediction physics-tick visual position and let Camera2D interpolate between those states.
   Otherwise the camera (and the whole world) still steps.
4. Optional polish: set `application/run/max_fps` (or `Engine.max_fps`) now that smoothness no
   longer depends on raw frame count.

### Alternatives (and why they're second choice)

- **Manual `_process` interpolation** — keep physics writes, store `prev`/`curr` per node, lerp
  in `_process` by `Engine.get_physics_interpolation_fraction()`. Same visual result but you
  hand-maintain buffers for prediction, interpolation, *and* the camera, plus the same reset
  handling. More code, more bug surface. Choose only if you need per-entity control the engine
  setting can't give.
- **Raise `physics_ticks_per_second` 30→60** — halves the stepping (60 updates/sec) and helps,
  but still steps on a 100/144 Hz display, and it doubles client prediction/interpolation CPU and
  shifts input cadence (`INPUT_SEND_INTERVAL` derives from `SERVER_TICK_INTERVAL`,
  `prediction.gd:71`). A complementary knob, **not** the primary fix.

> Recommended: built-in physics interpolation (decisive) **plus** consider 60 Hz later for input
> responsiveness — but interpolation alone resolves the "looks like 30 fps" complaint.

## Verification

1. Apply the setting + resets + camera change.
2. Run client at uncapped/100+ fps; move the Local player and watch a Remote bot strafe.
3. Motion should be glassy at 100 fps from an unchanged 30 Hz sim. Confirm no visual "rubber"
   across spawns/teleports (that means a missing `reset_physics_interpolation()`).
4. Confirm the camera no longer steps (world scroll is smooth).

## The eight questions

- **Client:** owns all rendering; this bug and fix are entirely client-side.
- **Server:** unaffected — it still ticks at 30 Hz; smoothness is a pure render concern.
- **Predicted / replicated / persisted / validated:** unchanged by this fix.
- **Can fail:** missing `reset_physics_interpolation()` on a discontinuity → visible lerp across
  teleports; camera not using interpolated transform → world still steps.
- **Tested:** visual; add a manual check to the smoke test. No automated frame-pacing test today.

## See also

- [`latency-budget.md`](latency-budget.md) — the latency problem felt alongside this
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md)
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — this is fix #1
