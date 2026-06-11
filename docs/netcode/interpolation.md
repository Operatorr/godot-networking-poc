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

_process (every render frame) ─► _interpolate_all_entities(frac)
                  ├─ render_timeline += delta / estimated_tick_interval (continuous fractional ticks,
                  │    pulled toward current_server_tick + since-arrival − adaptive delay)
                  └─ per entity: _calculate_interpolated_position
                        └─ buffer.get_interpolation_data(render_tick)
                        └─ node.position = blended
```

`ClientEntityManager` owns the visual node and registers it back into the controller
(`client_entity_manager.gd:157`); thereafter the controller writes `node.position`
**every render frame** (2026-06-12 — previously once per 30 Hz physics tick, which beat against
the unsynchronized 30 Hz snapshot arrival clock and juddered; see
[`smoothness-render.md`](smoothness-render.md)). Registered nodes run
`physics_interpolation_mode = OFF` — the controller owns their rendered motion directly.
Animation/flags are **not** interpolated — they snap to the latest Snapshot, pulled per-frame in
`update_entity_visuals` (`client_entity_manager.gd:362-364`, `remote_player.gd:54`).

## Render delay (adaptive)

| Property | Value | Source |
|---|---|---|
| Render delay | **adaptive 1–3 ticks** (≈33–100 ms @30 Hz); seed `2` | `interpolation_controller.gd:206-226`, `MIN/MAX` `:16-17` |
| `render_tick` | `max(0, server_tick − round(render_delay_ticks_smooth))` | `interpolation_controller.gd:226` |
| Adaptive? | **Yes** — sized to measured *jitter* (`1 interval + 2× jitter`), clamped 1–3 ticks, asymmetric fast-grow/slow-shrink | `:206-218` |
| Driven by | inter-arrival **jitter**, not raw ping (a stable 90 ms link buffers no more than a stable 10 ms one) | `:209-212` |

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

## Continuous render timeline (2026-06-12)

Snapshots are integer-tick; rendering happens at arbitrary wall-clock times. The controller keeps
`render_timeline` (fractional server ticks): it advances by `delta / estimated_tick_interval`
every render frame and is pulled toward the snapshot-derived target
(`current_server_tick + time-since-arrival/interval − render_delay_ticks_smooth`) — snap when
drift exceeds `RENDER_TIMELINE_SNAP_TICKS = 3`, exponential pull (`RENDER_TIMELINE_PULL_RATE =
4/s`) otherwise. Each frame: `render_tick = floor(render_timeline)`, `frac = render_timeline −
render_tick`; position = `lerp(pos(render_tick), pos(render_tick + 1), frac)`, where each
`pos(t)` is the buffer's bracketing lerp — exactly piecewise-linear interpolation along the
snapshot polyline, advancing with wall-clock time instead of stepping on snapshot arrival.

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

2. **Render delay — RESOLVED, now adaptive.** Previously a fixed 66.7 ms (2 ticks). It is now
   sized to measured inter-arrival jitter and clamped to 1–3 ticks, with asymmetric adaptation
   (grow fast on a jitter spike, shrink slowly when clean) — `interpolation_controller.gd:206-226`.
   On a clean LAN/localhost it collapses toward ~33 ms (1 tick); under jitter it widens to avoid
   extrapolation/freeze. See [`latency-budget.md`](latency-budget.md).

3. **Interpolates newest-two, not straddle-by-time — RESOLVED (2026-06-12).** The controller now
   drives a continuous `render_timeline` clock in `_process` (see "Continuous render timeline")
   instead of stepping `render_tick` on Snapshot arrival, eliminating the discrete blend-factor
   jumps and the 30 Hz-vs-30 Hz beat judder this item described.

## Planned fixes

| Fix | What | Status |
|---|---|---|
| Seed from `SERVER_TICK_INTERVAL` | Replace hard-coded `0.05`/`50.0` with `GameConstants.SERVER_TICK_INTERVAL` (or the live Snapshot interval) so cold-start is correct | Planned |
| Adaptive Render delay | Size delay from measured jitter, clamp 1–3 ticks, asymmetric grow/shrink (`interpolation_controller.gd:206-226`) | **Done** |
| Larger buffer (8–10) | Raise `BUFFER_SIZE` 5→8–10 to absorb bursts at 30 Hz tick / 20 Hz send | Planned |
| Time-based straddle search | Drive a continuous `client_time − delay` render clock and straddle by timestamp, not integer tick | **Done** (2026-06-12, `render_timeline` in `_process`) |

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
