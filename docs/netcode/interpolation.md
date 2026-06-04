# Entity interpolation & render delay

**Status:** Partial (verified 2026-06-03 against code). Interpolation works, but it
runs on **stale 20 Hz constants** and **interpolates the newest two Snapshots**
instead of straddling `client_time − Render delay`, so it micro-stutters under
variable Snapshot spacing.

> This doc is about how **Remote entities** are *drawn* — the smoothing between
> Snapshots and the deliberate [Render delay](../CONTEXT.md). It is **not** the
> "looks like 30 fps" complaint: that is a separate render-pacing bug owned by
> [`smoothness-render.md`](smoothness-render.md). Even a perfect interpolator here
> would still step at 30 Hz until physics interpolation is enabled. The two are
> felt together but fixed independently.

## What this covers

The Local player is **predicted** (see [`client-prediction.md`](client-prediction.md))
and is explicitly skipped here (`interpolation_controller.gd:208`). Everything else —
other players, monsters, projectiles — is a **Remote entity**: never predicted, drawn
purely by blending buffered Snapshots a fixed amount of server time in the past.

## The pipeline

```
STATE_UPDATE ─► InterpolationController._process_state_update  (per Snapshot, ~20 Hz live)
                  ├─ reconstruct delta → full state            (:214, :242)
                  ├─ new id?  → entity_spawned ─► ClientEntityManager  (:344 → cem:107)
                  └─ known id → EntityStateBuffer.add_snapshot  (:376 → esb:103)

_physics_process (30 Hz) ─► _interpolate_all_entities(tick_progress)   (:111, :135)
                  └─ per entity: _calculate_interpolated_position       (:451, :459)
                        └─ buffer.get_interpolation_data(render_tick)   (:461 → esb:159)
                        └─ node.position = blended                      (:454)
```

`ClientEntityManager` owns the visual node and registers it back into the controller
(`client_entity_manager.gd:157`); thereafter the controller writes `node.position`
each physics tick. Animation/flags are **not** interpolated — they snap to the latest
Snapshot, pulled per-frame in `update_entity_visuals` (`client_entity_manager.gd:362-364`,
`remote_player.gd:54`).

## Render delay (fixed)

| Property | Value | Source |
|---|---|---|
| Render delay | `2` ticks = **66.7 ms** @30 Hz | `game_constants.gd:20`, `interpolation_controller.gd:11` |
| `render_tick` | `max(0, server_tick − 2)` | `interpolation_controller.gd:186` |
| Adaptive? | **No** — constant 2 ticks regardless of jitter/RTT | — |

`current_server_tick` advances only when a newer Snapshot arrives, and `render_tick`
is recomputed from it (`:175-187`). The controller draws Remote entities at
`render_tick`, so it almost always has a *newer* Snapshot to interpolate *toward*.

## EntityStateBuffer — 5-slot ring

Per entity, a `RefCounted` ring buffer (`entity_state_buffer.gd`):

| Property | Value | Source |
|---|---|---|
| `BUFFER_SIZE` | **5** snapshots, pre-allocated, no realloc | `entity_state_buffer.gd:11, :88` |
| Depth @30 Hz | ~166 ms (the comment says "250ms at 20Hz" — **stale**) | `entity_state_buffer.gd:9` |
| Duplicate ticks | dropped (`server_tick == last_tick_added`) | `entity_state_buffer.gd:117` |
| Bracket search | scans all 5 slots for `before ≤ render_tick < after` | `entity_state_buffer.gd:167-177` |

`get_interpolation_data(render_tick)` returns `[before, after, factor]` where
`factor = (render_tick − before.tick) / (after.tick − before.tick)`, clamped 0..1
(`entity_state_buffer.gd:188-194`). With Render delay = 2 and a 5-slot buffer, two
slots cover the delay and ~3 give jitter headroom.

## Sub-tick blend (smoother than 30 Hz commits)

Snapshots are integer-tick, but `_physics_process` runs at 30 Hz between them, so the
controller adds a sub-tick pass (`interpolation_controller.gd:128-135, :488-505`):

1. `tick_accumulator += delta`; `tick_progress = clamp(accumulator / estimated_tick_interval, 0, 1)` (`:128-132`).
2. Compute the blended position at `render_tick` **and** at `render_tick + 1`, then
   `lerp(current, next, tick_progress)` (`:492-505`).

This is *intra-buffer* smoothing only — it does not change the Render delay or the
draw latency. Note the **two different `tick_progress` semantics** below are a known
correctness smell (one is "how far into a server tick", the other lerps between two
*render* ticks).

## Underrun: extrapolate 2 ticks, then freeze

When `render_tick` is past the newest Snapshot (`after == null`, `factor ≥ 1.0`):

| Case | Behaviour | Source |
|---|---|---|
| `ticks_past ≤ 2` | linear **extrapolate** from last two snapshots' velocity | `interpolation_controller.gd:475-477` → `entity_state_buffer.gd:261-293` |
| `ticks_past > 2` | **freeze** at `before.position` | `interpolation_controller.gd:479-480` |
| `< 2` snapshots | hold latest position (cannot derive velocity) | `entity_state_buffer.gd:262-264` |

`MAX_EXTRAPOLATION_TICKS = 2` (comment says "100ms" — that's the stale 20 Hz figure;
it's actually **66.7 ms** @30 Hz, `interpolation_controller.gd:19`).

## Despawn after 3 missing updates

In **full** (non-delta) Snapshots, an entity absent from the update increments its
missing counter; at `DESPAWN_THRESHOLD = 3` it despawns (`interpolation_controller.gd:382-398`,
`:15`). In **delta** Snapshots, unchanged entities are simply not sent, so this path is
skipped (`:232`) and removal relies on an explicit `DELTA_MASK_REMOVED` marker
(`:203, :417`). A position jump over `TELEPORT_THRESHOLD = 150` clears the buffer and
snaps the node instead of interpolating across (`:361-373`, `game_constants.gd:55`).

## Why this is tagged Partial

1. **Stale 20 Hz seed constants → micro-stutter.** Two interval constants assume a
   20 Hz server, but the server runs at 30 Hz (`game_constants.gd:12`):
   - `entity_state_buffer.gd:14` `TICK_INTERVAL_SEC = 0.05`
   - `entity_state_buffer.gd:81` `estimated_tick_interval_ms = 50.0`
   - `interpolation_controller.gd:75` `estimated_tick_interval = 0.05` ("20Hz default")

   The interval is recalibrated by EMA (`interpolation_controller.gd:177-183`,
   `entity_state_buffer.gd:120-133`), so it converges — but it **starts wrong** and
   drifts toward the *live Snapshot* spacing (20 Hz / 50 ms, since
   `data/config/server_config.json:10` sets `snapshot_rate_hz=20` while the tick is
   30 Hz). Until the EMA settles, `tick_progress` is mis-scaled and motion micro-stutters.
   All "20Hz"/"250ms"/"150ms"/"100ms" comments in these two files are stale.

2. **Fixed, non-adaptive Render delay.** 66.7 ms is a constant
   (`game_constants.gd:20`). It does not widen under jitter or shrink on a clean LAN,
   so it is simultaneously *too small* under bursty loss (causes extrapolation/freeze)
   and *too large* on localhost (needless latency — see
   [`latency-budget.md`](latency-budget.md)).

3. **Interpolates newest-two, not straddle-by-time.** `get_interpolation_data` brackets
   by **integer `render_tick`** (`entity_state_buffer.gd:167-177`), and `render_tick`
   only steps when a Snapshot arrives. It does **not** straddle a continuous
   `client_time − Render delay` clock. With uneven Snapshot spacing (the live case:
   30 Hz tick, 20 Hz send, plus per-tick BATCH coalescing on the server), the blend
   factor jumps in discrete steps instead of advancing smoothly with wall-clock time —
   visible as janky pacing under variable spacing.

## Planned fixes

| Fix | What | Status |
|---|---|---|
| Seed from `SERVER_TICK_INTERVAL` | Replace hard-coded `0.05`/`50.0` with `GameConstants.SERVER_TICK_INTERVAL` (or the live Snapshot interval) so cold-start is correct | Planned |
| Adaptive Render delay | Size delay from measured jitter + RTT instead of a constant 2 ticks | Planned |
| Larger buffer (8–10) | Raise `BUFFER_SIZE` 5→8–10 to absorb bursts at 30 Hz tick / 20 Hz send | Planned |
| Time-based straddle search | Drive a continuous `client_time − delay` render clock and straddle by timestamp, not integer tick | Planned |

These are tracked in
[`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md).

## The eight questions

- **Client:** all of it — buffering, Render delay, sub-tick blend, extrapolate/freeze, despawn.
- **Server:** none here; it only emits `STATE_UPDATE` Snapshots that feed the buffers.
- **Predicted:** nothing — Remote entities are never predicted (Local player is, elsewhere).
- **Replicated:** position (interpolated), animation/flags (snapped to latest), via Snapshots.
- **Persisted:** nothing — buffers are in-memory `RefCounted` rings, cleared on disconnect.
- **Validated:** teleport guard (>150 units clears buffer) and delta-chain baseline checks.
- **Can fail:** stale 20 Hz seed → cold-start stutter; underrun past 2 ticks → freeze; uneven Snapshot spacing → janky non-straddled pacing.
- **Tested:** no automated interpolation test today; verified visually against bot swarm motion.

## See also

- [`smoothness-render.md`](smoothness-render.md) — **different problem**: 30 Hz render pacing, not Render delay
- [`latency-budget.md`](latency-budget.md) — where the 66.7 ms Render delay sits in the end-to-end budget
- [`client-prediction.md`](client-prediction.md) — the Local player path this doc deliberately skips
- [`server-tick-broadcast.md`](server-tick-broadcast.md) · [`wire-protocol.md`](wire-protocol.md) — what produces the Snapshots being interpolated
