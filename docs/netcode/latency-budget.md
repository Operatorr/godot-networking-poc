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
| 4 | Client renders remote entities ~2 Ticks in the past | **66.7 ms** | **66.7 ms** | `game_constants.gd:31-37`, `interpolation_controller.gd:11,221` | **Yes** — Render delay is the dominant lever (see `interpolation.md`) |
| — | **Total (your action → seen on a remote entity)** | **~115 ms** | **~166 ms** | — | — |

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

## The dominant lever: the fixed Render delay

Stage 4 is the single biggest contributor and the most misunderstood. Remote entities are drawn
at `render_tick = current_server_tick − 2` so the client always has a future Snapshot to
interpolate toward (`interpolation_controller.gd:186`). At 30 Hz that is a hard, unconditional
**66.7 ms** — and it is a **fixed tick count**, so it does **not shrink on localhost/LAN** where
there is no jitter to hide. You pay the full jitter-buffer cost on a connection with zero jitter.

→ Fix direction: make the Render delay **adaptive** — size it to measured inter-arrival jitter
(~1 Snapshot interval + a few ms) instead of a constant 2 Ticks. On localhost this collapses
toward ~1 Tick. Detail and trade-offs in [`interpolation.md`](interpolation.md).

## What is fixable vs inherent

- **Fixable now, no architecture change:** stage 4 (adaptive render delay) is the remaining lever;
  stage 3 (the 20 Hz live-config regression) is **already fixed** — snapshot rate is now 30 Hz (#3).
  These are the bulk of the localhost feel.
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
