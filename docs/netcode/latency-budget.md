# Netcode latency budget — why it feels sluggish

**Status:** Verified against code (2026-06-04). Evidence base: full read of the netcode stack
(`server_main`, `server_broadcast_service`, `delta_state_cache`, `network_manager`, `prediction`,
`interpolation_controller`, `entity_state_buffer`, config + constants). Numbers below are the
*current* code reality, not targets — for targets see [`performance-budgets.md`](performance-budgets.md).
(Stage 3 now reflects the 30 Hz live Snapshot rate; PvP is now lag-compensated.)

> **Read this first.** It answers "where does it fail?" with a millisecond-by-millisecond
> account of the delay between pressing a key and seeing the world react. The companion doc
> [`smoothness-render.md`](smoothness-render.md) covers a *separate* problem (visual stepping)
> that is often felt at the same time.

## The headline

On **localhost (≈0 ms network latency)**, the time from your input to *seeing another entity
react to it* is **≈115–166 ms** (down from ≈120–180 ms now that #3 raised the live Snapshot rate to
30 Hz). None of that is the network. It is latency **baked into the pipeline.** Add 100 ms real ping
and it becomes ≈245–270 ms.

The two felt problems are distinct and must not be conflated:

| Problem | Doc | Nature |
|---|---|---|
| "Everything trails / I act and the world reacts late" | **this doc** | end-to-end **latency** |
| "Looks like 30 fps even at 100 fps" | [`smoothness-render.md`](smoothness-render.md) | render **smoothness** |

## The budget (localhost, 0 ms network)

Input → visible reaction on a remote entity, worst-case and average:

| # | Stage | Avg | Worst | Evidence | Fixable? |
|---|---|---|---|---|---|
| 1 | Input sampled (once per `_physics_process`, 30 Hz) | ~16 ms | ~33 ms | `prediction.gd:153,189` | **Yes** — sample at render rate / raise tick to 60 Hz (#8, gated) |
| 2 | Server waits for next Tick to apply input (30 Hz) | ~16 ms | ~33 ms | `server_main.gd:178-188` | Partly — raise tick rate (costs CPU; #8 gated) |
| 3 | Server waits to emit next Snapshot (**30 Hz live**, raised from 20 by #3) | ~16 ms | ~33 ms | `data/config/server_config.json` `snapshot_rate_hz:30` | Done (#3) — snapshot rate now matches the tick |
| 4 | Client renders remote entities in the past — **adaptive 1–3 Ticks**, jitter-driven | **~33 ms** (clean LAN) | up to **~100 ms** (high jitter) | `interpolation_controller.gd:206-226` (MIN/MAX 1–3) | **Done** — adaptive delay collapses toward ~33 ms on localhost |
| — | **Total (your action → seen on a remote entity)** | **~80 ms** (clean LAN) | jitter-dependent | — | — |

For **your own** Local player, motion is *predicted* (`prediction.gd`) so it appears without the
round trip — but it is still sampled at 30 Hz (stage 1) and visually steps at 30 Hz (see
[`smoothness-render.md`](smoothness-render.md)), which is why even your own movement feels
"floaty / like steering a boat."

### Note on the cadence authority (now unified)

The tick/input cadence is now driven by a single authority — `GameConstants.SERVER_TICK_RATE`
(still **30 Hz**, `game_constants.gd:22`). `game_manager._ready()` applies it to
`Engine.physics_ticks_per_second` (`game_manager.gd:70`), the input send cadence derives from it
(`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`), and `server_config.gd`'s default tick rate tracks it.
The live Snapshot rate was also raised to **30 Hz** (#3 — `server_config.json snapshot_rate_hz:30`),
so stage 3 now matches the Tick instead of lagging it. A gated 30→60 trial (which would halve stages
1–2) is documented in [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) — default
stays 30, results PENDING.

## The Render delay (now adaptive — DONE, was the dominant lever)

Stage 4 used to be a hard, unconditional **66.7 ms** (a fixed 2 Ticks) that did not shrink on
localhost. **It is now adaptive** (`interpolation_controller.gd:206-226`): the client measures
Snapshot inter-arrival jitter and sets `render_delay_ticks_smooth = clamp(1 interval + 2× jitter,
MIN=1, MAX=3 Ticks)`, then renders at `render_tick = current_server_tick − round(that)`. The
adaptation is **asymmetric** — it adds buffer fast when jitter rises (absorb a spike before it
stutters) and sheds it slowly when the link is clean — so a zero-jitter localhost/LAN link collapses
toward **~33 ms (1 Tick)** while a jittery link grows the buffer to avoid stutter.

This is the Render-delay half of "Option 3 — shrink the offset." It is **per-client and jitter-driven
(not raw-ping-driven)**, which is correct: the interpolation buffer's job is to smooth out
arrival-time *variance*, not absolute latency. A stable 90 ms link needs no more buffer than a stable
10 ms link; only jitter does. The remaining stage-4 floor (1 Tick) is inherent — you need at least one
Tick of buffer to have two Snapshots to interpolate between. Detail in
[`interpolation.md`](interpolation.md).

## What is fixable vs inherent

- **Already done:** stage 4 (adaptive render delay — now jitter-driven, collapses toward ~33 ms on
  LAN) and stage 3 (snapshot rate raised 20→30 Hz, #3). These were the bulk of the localhost feel.
- **Costs CPU/bandwidth:** stage 2 (raising tick rate 30→60). Helps feel, hurts scale — a real
  trade-off, see [`performance-budgets.md`](performance-budgets.md).
- **Inherent to the transport:** under *real* ping and packet loss, TCP head-of-line blocking
  freezes *all* state behind one lost segment. Not visible on localhost; dominant under loss.
  See [`transport-websocket.md`](transport-websocket.md) and [`adr/0001-websocket-tcp-transport.md`](../adr/0001-websocket-tcp-transport.md).

## Under real ping (projection)

At 100 ms RTT, add ~50 ms each way. Local player still predicts (feels fine), but: remote
entities trail by ~50 ms + 66.7 ms render delay. Your shots no longer need to lead targets by ping —
**PvP is now lag-compensated** (rewind + swept test, cap 4 ticks; #7,
`projectile_manager.gd:273-331`, see [`../systems/combat-hits.md`](../systems/combat-hits.md)), so the
server checks where the shooter *saw* the victim. The remaining transport risk: any packet loss
stalls all state (TCP HOL) until the deferred ENet transport lands (#12). The localhost baseline is
the floor everything else stacks on — which is why fixing the baked-in latency comes first.

### Why this offset also distorts *incoming* monster bullets

The same two facts — Local player **predicted-ahead**, remote entities (incl. bullets) rendered
**~66.7 ms behind** — mean a server-authoritative monster-bullet hit, tested on *true* positions,
disagrees with what you see by a vector along your movement: **phantom hits while fleeing**,
**pass-throughs while chasing**, exact at rest. Because dodging is the whole game, monster → player
hits are now **client-detected against the predicted self and server-validated** (2026-06-10), so the
hit matches your screen. This does **not** reduce the latency numbers above — it reconciles *which*
position the hit is judged against (predicted vs. authoritative). Details:
[`../systems/combat-hits.md`](../systems/combat-hits.md).

## The eight questions

- **Client:** samples input (30 Hz), predicts Local player, interpolates Remote entities with a
  fixed 66.7 ms Render delay.
- **Server:** applies input and advances sim at 30 Hz; emits Snapshots at 30 Hz (live, raised by #3).
- **Predicted:** Local player movement only.
- **Replicated:** all entity positions/state via Snapshots; events via `GAME_EVENT`.
- **Persisted:** nothing latency-relevant — gameplay state is in-memory.
- **Validated:** server is authoritative; movement bounds/speed checked server-side.
- **Can fail:** snapshot starvation under load (scheduler defers far entities), TCP HOL under
  loss, render-delay too small under jitter (warp). The 20-vs-30 Hz snapshot config drift is resolved (now 30 Hz).
- **Tested:** load tests in `load_testing/` (baseline/target/stress); **no automated latency
  regression test yet** — see roadmap.

## How to measure (don't trust this doc — verify)

1. Run the headless server locally; connect one real client + watch the HUD `server_status` /
   `debug_overlay`.
2. Confirm the live `snapshot_rate_hz` actually loaded (log it on boot).
3. Add a frame-stamped input→on-screen-reaction probe (e.g. fire, measure ticks until the
   muzzle/impact appears). Compare to the table above.
4. Then change one lever at a time (snapshot rate → render delay → input rate) and re-measure.

## See also

- [`smoothness-render.md`](smoothness-render.md) — the 30 fps-look (separate problem, often felt together)
- [`client-prediction.md`](client-prediction.md) · [`interpolation.md`](interpolation.md) · [`server-tick-broadcast.md`](server-tick-broadcast.md)
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — prioritized fixes
