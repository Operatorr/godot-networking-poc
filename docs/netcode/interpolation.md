# Entity interpolation & render delay

**Status:** Active (verified 2026-06-14 against code). Interpolation runs on a continuous,
wall-clock render timeline straddling `render_timeline = newest_tick − adaptive_delay`, seeded from
the real **30 Hz** tick rate. The stale 20 Hz seed constants that caused cold-start micro-stutter are
gone (both controller and buffer now seed from `GameConstants.SERVER_TICK_INTERVAL`).

> This doc is about how **Remote entities** are *drawn* — the smoothing between Snapshots and the
> deliberate [Render delay](../CONTEXT.md). It is **not** the "looks like 30 fps" complaint: that is
> a separate render-pacing concern owned by [`smoothness-render.md`](smoothness-render.md). The two
> are felt together but fixed independently.

This is a **client-only** concern. The authoritative Rust `omega-server`
(`rust/server/src/net/broadcast.rs`) emits `Snapshot` packets (type 65) and never interpolates; the Godot
client buffers them and blends. The retired GDScript headless server played no part in this path and
is being deleted — do not cite `client/scripts/server/*.gd`.

## What this covers

The Local player is **predicted** (see [`client-prediction.md`](client-prediction.md)) and is
explicitly skipped here (`interpolation_controller.gd` `_process_state_update`, the
`entity_id == local_entity_id` continue). Everything else — other players, monsters, projectiles, and
v4 world-effect entities (ids 40000–49999) — is a **Remote entity**: never predicted, drawn purely by
blending buffered Snapshots a fixed amount of server time in the past.

## Where the Snapshots come from

The server builds per-peer delta Snapshots each 30 Hz tick (`rust/server/src/net/broadcast.rs`: AoI grid
+ hysteresis, DeltaStateCache, per-peer byte budget) and sends them on **ch0**
(unreliable-sequenced); periodic full-state **baselines** ride **ch1** (reliable-ordered). Wire format
is the hand-rolled bit-packed `Snapshot` (`rust/protocol/src/snapshot.rs`, PROTOCOL_VERSION=4) — see
[`../server/contract.md`](../server/contract.md) §Snapshot for the byte layout. Positions are
quantized ×10 (truncate toward zero, clamp i16); the codec lives in the `ProtocolCodec` GDExtension and
the client receives one decoded `Dictionary` per packet.

Every Snapshot carries `server_tick` and `server_ms` (server monotonic ms). `server_ms` is the
relocated clock-sync signal (the old app heartbeat is gone; ENet-native RTT supplies the half-trip
estimate) — it feeds the network clock, not this interpolator. The interpolator works purely off
`server_tick` plus local wall-clock arrival times.

## The two roles

| Role | File | Responsibility |
|---|---|---|
| **InterpolationController** | `interpolation_controller.gd` | Owns the render-delay clock and per-entity blend. Receives `STATE_UPDATE`, reconstructs deltas into full state, drives the continuous `render_timeline`, and writes `node.position` **every render frame**. Spawns/despawns Remote entities (signals to `ClientEntityManager`). |
| **EntityStateBuffer** | `entity_state_buffer.gd` | Per-entity 5-slot ring of `EntitySnapshot`s. Answers `get_interpolation_data(render_tick) → [before, after, factor]`, extrapolates on underrun, and drops duplicate ticks. Pure data, no clock. |

The controller drives the clock; the buffer answers point queries against it. `ClientEntityManager`
owns the visual node and registers it back into the controller via `register_entity_node`; registered
nodes run `physics_interpolation_mode = OFF` because the controller writes their rendered position
directly each frame (Godot's physics interpolation would fight those writes — it re-interpolates from
stale physics-tick transforms). Animation/flags are **not** interpolated — they snap to the latest
Snapshot.

## The pipeline

```
STATE_UPDATE ─► InterpolationController._on_server_message → _process_state_update  (per Snapshot, 30 Hz)
                  ├─ reconstruct delta → full state          (_reconstruct_entity_state)
                  ├─ calibrate estimated_tick_interval + adaptive render delay (from inter-arrival jitter)
                  ├─ new id?  → entity_spawned ─► ClientEntityManager
                  └─ known id → EntityStateBuffer.add_snapshot

_process (every render frame) ─► advance render_timeline (wall-clock) → _interpolate_all_entities(frac)
                  ├─ render_timeline += delta / estimated_tick_interval
                  │    pulled toward (current_server_tick + since-arrival/interval − render_delay_ticks_smooth)
                  └─ per entity: _calculate_interpolated_position
                        └─ buffer.get_interpolation_data(render_tick) → bracketing lerp
                        └─ node.position = blended
```

## Render delay (adaptive)

| Property | Value | Source |
|---|---|---|
| Seed render delay | `REMOTE_ENTITY_RENDER_DELAY_TICKS = 2` (~66 ms @30 Hz) | `game_constants.gd` · `interpolation_controller.gd` `RENDER_DELAY_TICKS` |
| Effective delay | **adaptive 1–3 ticks** (≈33–100 ms @30 Hz), smoothed | `interpolation_controller.gd` `render_delay_ticks_smooth`, `MIN/MAX_RENDER_DELAY_TICKS` |
| Adaptive? | **Yes** — target = `1 interval + 2× jitter`, clamped 1–3 ticks, **asymmetric** (grow fast 0.5, shrink slow 0.05) | `_process_state_update` jitter block |
| Driven by | inter-arrival **jitter**, not raw ping (a stable 90 ms link buffers no more than a stable 10 ms one) | same |

On a jitter-free LAN/localhost the effective delay collapses toward 1 tick (~33 ms) instead of a fixed
~66 ms; under jitter it widens toward 3 ticks to avoid extrapolation/freeze. `current_server_tick`
advances only when a newer Snapshot arrives; `render_timeline` advances continuously off wall-clock and
is pulled toward `current_server_tick + since-arrival − render_delay_ticks_smooth`, so the controller
almost always has a *newer* Snapshot to interpolate *toward*. See
[`latency-budget.md`](latency-budget.md) for where this delay sits end-to-end.

## EntityStateBuffer — 5-slot ring

| Property | Value | Source |
|---|---|---|
| `BUFFER_SIZE` | **5** snapshots, pre-allocated, no realloc | `entity_state_buffer.gd` `BUFFER_SIZE`, `_init` |
| Depth @30 Hz | ~166 ms (5 × 33.3 ms) | `entity_state_buffer.gd` header |
| `TICK_INTERVAL_SEC` | `GameConstants.SERVER_TICK_INTERVAL` (= 1/30) — **no longer hardcoded 0.05** | `entity_state_buffer.gd` |
| Duplicate ticks | dropped (`server_tick == last_tick_added`) | `add_snapshot` |
| Bracket search | scans all 5 slots for `before ≤ render_tick < after` | `get_interpolation_data` |

`get_interpolation_data(render_tick)` returns `[before, after, factor]` where
`factor = (render_tick − before.tick) / (after.tick − before.tick)`, clamped 0..1. With effective delay
1–3 ticks and a 5-slot buffer, ~2 slots cover the delay and ~3 give jitter headroom.

## Continuous render timeline

Snapshots are integer-tick; rendering happens at arbitrary wall-clock times. The controller keeps
`render_timeline` (fractional server ticks): it advances by `delta / estimated_tick_interval` every
render frame and is pulled toward the snapshot-derived target — snap when drift exceeds
`RENDER_TIMELINE_SNAP_TICKS = 3`, exponential pull (`RENDER_TIMELINE_PULL_RATE = 4/s`) otherwise. Each
frame: `render_tick = floor(render_timeline)`, `frac = render_timeline − render_tick`. The controller
then blends `pos(render_tick)` toward `pos(render_tick + 1)` by `frac` (each `pos(t)` is the buffer's
bracketing lerp) — exactly piecewise-linear interpolation along the snapshot polyline, advancing with
wall-clock time instead of stepping on snapshot arrival. This eliminates the discrete blend-factor
jumps and the 30 Hz-vs-30 Hz beat judder of the old arrival-stepped design.

`estimated_tick_interval` seeds from `GameConstants.SERVER_TICK_INTERVAL` (correct from the first
frame) and is recalibrated by EMA (alpha 0.1) from measured inter-arrival times, so it tracks the live
Snapshot spacing.

## Underrun: extrapolate 2 ticks, then freeze

When `render_tick` is past the newest Snapshot (`after == null`, `factor ≥ 1.0`):

| Case | Behaviour | Source |
|---|---|---|
| `ticks_past ≤ 2` | linear **extrapolate** from last two snapshots' velocity | `_calculate_interpolated_position` → `entity_state_buffer.gd` `extrapolate_position` |
| `ticks_past > 2` | **freeze** at `before.position` | `_calculate_interpolated_position` |
| `< 2` snapshots | hold latest position (cannot derive velocity) | `extrapolate_position` early-out |

`MAX_EXTRAPOLATION_TICKS = 2` (≈66.7 ms @30 Hz). This same cap also bounds `since_update` so a stall
can't drag `render_timeline` into deep extrapolation.

## Despawn after 3 missing updates

In **full** (non-delta) Snapshots, an entity absent from the update increments its missing counter; at
`DESPAWN_THRESHOLD = 3` it despawns (`_check_for_despawns`). In **delta** Snapshots, unchanged entities
are simply not sent, so this path is skipped (`if not is_delta:` guard) and removal relies on an
explicit `DELTA_MASK_REMOVED` marker (`_handle_explicit_despawn`). A position jump over
`TELEPORT_THRESHOLD = 150` (`GameConstants.TELEPORT_THRESHOLD`, shared with server validation) clears
the buffer and snaps the node instead of interpolating across (`_handle_entity_update`).

## Delta-chain integrity

The controller validates the delta chain against the last received baseline: a `baseline_tick`
mismatch (`baseline_tick != last_baseline_tick`) triggers `REQUEST_FULL_STATE` (ch1), retried up to
`FULL_STATE_MAX_RETRIES = 3` every `FULL_STATE_REQUEST_TIMEOUT_MS = 2000`; on exhaustion it clears all
buffers to recover. Baselines are acked back to the server with `BaselineAck{server_tick}` on ch1 so
the server can clear its resend timer (server cadence: 100-tick baseline interval, 30-tick resend — see
[`../server/contract.md`](../server/contract.md)).

## The eight questions

- **Client:** all of it — buffering, Render delay, continuous-timeline blend, extrapolate/freeze, despawn.
- **Server:** none here; `rust/server/src/net/broadcast.rs` only emits `Snapshot`s (ch0 deltas / ch1 baselines) that feed the buffers.
- **Predicted:** nothing — Remote entities are never predicted (Local player is, via the shared `sim_core` crate through `PredictionSim`, elsewhere).
- **Replicated:** position (interpolated), animation/flags (snapped to latest), via Snapshots.
- **Persisted:** nothing — buffers are in-memory `RefCounted` rings, cleared on disconnect. Durable state lives in the Go API (Postgres/Redis), not here.
- **Validated:** teleport guard (>150 units clears buffer) and delta-chain baseline checks (full-state resync on mismatch).
- **Can fail:** underrun past 2 ticks → freeze; sustained jitter → wider delay (more latency, no stutter); broken delta chain → full-state resync.
- **Tested:** no automated interpolation test today; verified visually against bot-swarm motion (`./scripts/run_load_test.sh`).

## See also

- [`smoothness-render.md`](smoothness-render.md) — **different problem**: render pacing / physics interpolation, not Render delay
- [`latency-budget.md`](latency-budget.md) — where the adaptive Render delay sits in the end-to-end budget
- [`client-prediction.md`](client-prediction.md) — the Local player path this doc deliberately skips
- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the 30 Hz tick + AoI broadcast that produces the Snapshots
- [`../server/contract.md`](../server/contract.md) — authoritative `Snapshot` wire format, channels, quantization
