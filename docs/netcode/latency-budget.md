# Netcode latency budget — where the input→reaction delay goes

**Status:** Verified against the Rust port (2026-06-14). Evidence base: the authoritative server
(`rust/server/src/{world,broadcast,config}.rs`), the shared sim (`rust/sim_core/`), the wire spec
([`../server/contract.md`](../server/contract.md)), and the Godot client glue
(`client/scripts/network/{prediction,interpolation_controller}.gd`). Numbers below are the *current*
code reality, not targets — for targets see [`performance-budgets.md`](performance-budgets.md) and the
load-test success criteria in `rust/load_test/src/metrics.rs`.

> **Read this first.** It answers "where does it fail?" with a millisecond-by-millisecond
> account of the delay between pressing a key and seeing the world react. The companion doc
> [`smoothness-render.md`](smoothness-render.md) covers a *separate* problem (visual stepping)
> that is often felt at the same time.

## The headline

On **localhost (≈0 ms network latency)**, the time from your input to *seeing another entity
react to it* is **≈80–130 ms**, and **none of it is the network.** It is latency **baked into the
pipeline** — input sampling, the 30 Hz tick, the snapshot cadence, and the interpolation buffer the
client deliberately renders behind. Add 100 ms real RTT and remote entities additionally trail by
~50 ms each way on top of the render buffer.

The two felt problems are distinct and must not be conflated:

| Problem | Doc | Nature |
|---|---|---|
| "Everything trails / I act and the world reacts late" | **this doc** | end-to-end **latency** |
| "Looks like 30 fps even at 100 fps" | [`smoothness-render.md`](smoothness-render.md) | render **smoothness** |

## The budget (localhost, 0 ms network)

Input → visible reaction on a remote entity, worst-case and average. All stages run at **30 Hz**
(`tick_rate: 30` in `deployment/server_config.{arena,sanctuary}.json`; `rust/server/src/config.rs`
defaults to 30 and rejects 0):

| # | Stage | Avg | Worst | Where (rust/ + client) | Fixable? |
|---|---|---|---|---|---|
| 1 | Input captured each frame, **sent once per tick (30 Hz)** | ~16 ms | ~33 ms | `prediction.gd` (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`, tap-latched so a fast tap between sends is never dropped) | **Yes** — raise tick to 60 Hz (costs CPU; gated trial) |
| 2 | Server waits for next tick to apply input (30 Hz) | ~16 ms | ~33 ms | `rust/server/src/sim/world.rs` (`step`: drain `host.service()` → apply inputs → `sim_core::step_player`) | Partly — raise tick rate |
| 3 | Server waits to emit next snapshot (**30 Hz**) | ~16 ms | ~33 ms | `rust/server/src/config.rs` `snapshot_rate_hz()` (raw 0 ⇒ tick rate; config sets 30); built in `rust/server/src/net/broadcast.rs` | Done — snapshot rate matches the tick |
| 4 | Client renders remote entities in the past — **adaptive 1–3 ticks**, jitter-driven | **~33 ms** (clean LAN) | up to **~100 ms** (high jitter) | `interpolation_controller.gd` (`MIN_RENDER_DELAY_TICKS=1`, `MAX=3`) | **Done** — collapses toward ~33 ms on localhost |
| — | **Total (your action → seen on a remote entity)** | **~80 ms** (clean LAN) | jitter-dependent | — | — |

For **your own** Local player, motion is *predicted* through the shared sim
([`client-prediction.md`](client-prediction.md)) so it appears without the round trip — but input is
still sent at 30 Hz (stage 1) and the body still visually steps at 30 Hz (see
[`smoothness-render.md`](smoothness-render.md)), which is why even your own movement can feel
"floaty / like steering a boat."

### Note on the cadence authority

The tick is the single cadence authority. The server runs one synchronous **30 Hz** tick loop on a
dedicated thread (`rust/server/src/sim/world.rs`; [`design.md` §"The tick"](../server/design.md)); the
client mirrors it — `Engine.physics_ticks_per_second` and `GameConstants.SERVER_TICK_INTERVAL` drive
both the prediction step and the input-send cadence. The **snapshot rate equals the tick rate**:
`snapshot_rate_hz()` returns the tick rate when the raw config value is 0, and otherwise clamps to
`min(raw, tick_rate)` (`rust/server/src/config.rs`); both live configs set it to 30 explicitly. A
gated 30→60 trial (which would halve stages 1–2) is documented in
[`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) — default stays 30, results
PENDING.

## The render delay (adaptive — the dominant lever, now resolved)

Stage 4 is **per-client and jitter-driven** (`interpolation_controller.gd`): the client measures
snapshot inter-arrival jitter and sets `render_delay_ticks_smooth = clamp(1 interval + 2× jitter,
MIN=1, MAX=3 ticks)`, then renders at `render_tick = current_server_tick − round(that)`. The
adaptation is **asymmetric** — it adds buffer fast when jitter rises (absorb a spike before it
stutters, `adapt_rate ≈ 0.5`) and sheds it slowly when the link is clean (`adapt_rate ≈ 0.05`) — so a
zero-jitter localhost/LAN link collapses toward **~33 ms (1 tick)** while a jittery link grows the
buffer to avoid stutter.

This is correct by design: the interpolation buffer's job is to smooth out arrival-time *variance*,
not absolute latency. A stable 90 ms link needs no more buffer than a stable 10 ms link; only jitter
does. The remaining stage-4 floor (1 tick) is inherent — you need at least one tick of buffer to
have two snapshots to interpolate between. The clock the buffer runs against is
`Snapshot.server_ms` (the relocated clock-sync that rides every snapshot — see
[`../server/contract.md` §Snapshot](../server/contract.md)) combined with ENet-native RTT for the
half-trip estimate. Detail in [`interpolation.md`](interpolation.md).

## What is fixable vs inherent

- **Already resolved:** stage 4 (adaptive render delay, collapses toward ~33 ms on LAN) and stage 3
  (snapshot rate equals the 30 Hz tick). These were the bulk of the localhost feel.
- **Costs CPU/bandwidth:** stages 1–2 (raising tick rate 30→60). Helps feel, hurts scale — a real
  trade-off, see [`performance-budgets.md`](performance-budgets.md).
- **Inherent to the transport — but cheap now:** under *real* RTT and packet loss, the transport no
  longer head-of-line-blocks. ENet/UDP runs three independent channels
  ([`design.md` §Transport](../server/design.md), [`../server/contract.md` §Channels](../server/contract.md)):
  snapshots on **ch0 unreliable-sequenced** (a dropped snapshot is superseded by the next, never
  retransmitted), input on **ch2 unreliable-sequenced** (the client replays unacked inputs anyway, so
  loss self-heals), and only must-arrive discrete messages on **ch1 reliable-ordered**. A lost
  datagram on ch0/ch2 costs at most one tick of staleness, not a stall of all state.

## Under real ping (projection)

At 100 ms RTT, add ~50 ms each way. The Local player still predicts through the shared `sim_core`
(feels fine), but remote entities trail by ~50 ms + the 1–3-tick render delay. Your shots no longer
need to lead targets by ping: **PvP and player→monster hits are server-authoritative and
lag-compensated** — the server rewinds against an 8-tick position-history ring
(`POSITION_HISTORY_TICKS = 8` in `rust/server/src/{monster,player}.rs`) and swept-tests, capped at
**6 ticks PvE / 4 ticks PvP** (`MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6`,
`MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4` in `rust/sim_core/src/constants.rs`; derivation in
`rust/server/src/sim/world.rs::pve_compensation`), so the server checks where the shooter *saw* the
victim. See [`../systems/combat-hits.md`](../systems/combat-hits.md). Because the transport is
per-channel UDP, packet loss no longer stalls all state — the localhost baseline is the floor
everything else stacks on, which is why fixing the baked-in latency comes first.

### Why this offset also distorts *incoming* monster bullets

The same two facts — Local player **predicted-ahead**, remote entities (incl. bullets) rendered
**~33–100 ms behind** — mean a hit tested on *true* server positions would disagree with what you
see by a vector along your movement: **phantom hits while fleeing**, **pass-throughs while chasing**,
exact at rest. Because dodging is the whole game, monster→player hits use the **client-authoritative +
server-validated** half of the two-netcode model: the client detects the hit against the **rendered**
self and reports it (`LocalHitReport` on ch1), so the hit matches your screen. A **lenient backstop**
(true 24 u overlap only, grace ≥ 15 ticks) applies a hit only when an authoritative monster-bullet
path *blatantly* overlaps a player and no report arrives — it never re-decides borderline hits on
authoritative positions, which is what would reintroduce the phantom-hit feel. This does **not**
reduce the latency numbers above; it reconciles *which* position the hit is judged against (rendered
vs. authoritative). Predicates are shared via `sim_core::hit` so client and server agree exactly.
Details: [`hit-authority-model.md`](hit-authority-model.md) and
[`../systems/combat-hits.md`](../systems/combat-hits.md).

## The eight questions

- **Client (Godot):** captures input each frame and sends at the 30 Hz tick cadence; predicts the
  Local player through the shared `sim_core` (via the `PredictionSim` GDExtension); interpolates
  remote entities with an adaptive 1–3-tick render delay.
- **Server (Rust):** single-threaded 30 Hz authoritative tick; applies input and steps the sim via
  `sim_core::step_player`; emits per-peer delta snapshots at 30 Hz (ch0), baselines on ch1.
- **Predicted:** Local player movement only (and the client's own monster-hit decision, pending
  server validation). Only Warrior Charge and Rogue Shadowstep's blink are *predicted* abilities.
- **Replicated:** all entity state via delta `Snapshot`s vs. an acked baseline (ch0/ch1); discrete
  `GameEvent`s on ch1 — all through the shared `protocol` crate.
- **Persisted:** nothing latency-relevant — gameplay state is server-authoritative and in-memory;
  the Go API owns only durable account/character/leaderboard state.
- **Validated:** server is authoritative; movement re-simulated and bounds/speed checked server-side;
  PvP/player→monster hits lag-compensated; monster→player reports plausibility-gated.
- **Can fail:** snapshot starvation under load (per-peer byte budget + AoI defers far entities), a
  dropped ch0/ch2 datagram (superseded/replayed, ≤ 1 tick stale — by design), render delay too small
  under sudden jitter (brief warp until the buffer grows).
- **Tested:** the ENet bot swarm (`rust/load_test/`); its success criteria
  (`rust/load_test/src/metrics.rs`: avg latency < 100 ms, P95 < 150 ms, where "latency" is the
  ENet-native RTT, the HEARTBEAT echo having retired with the WebSocket protocol). **No automated
  end-to-end input→reaction regression test yet** — see roadmap.

## How to measure (don't trust this doc — verify)

1. Run the Rust server locally (`./scripts/run_server.sh --mode arena --port 8081`); connect one
   real client and watch the HUD `server_status` / `debug_overlay`.
2. Confirm the effective `snapshot_rate_hz` actually loaded (it logs the config on boot; default
   equals the tick rate).
3. Add a frame-stamped input→on-screen-reaction probe (e.g. fire, measure ticks until the
   muzzle/impact appears). Compare to the table above.
4. Then change one lever at a time (snapshot rate → render delay → input rate) and re-measure.
5. Cross-check aggregate latency under load with the bot swarm
   ([`../../rust/load_test/README.md`](../../rust/load_test/README.md)).

## See also

- [`smoothness-render.md`](smoothness-render.md) — the 30 fps-look (separate problem, often felt together)
- [`client-prediction.md`](client-prediction.md) · [`interpolation.md`](interpolation.md) · [`server-tick-broadcast.md`](server-tick-broadcast.md)
- [`hit-authority-model.md`](hit-authority-model.md) · [`../systems/combat-hits.md`](../systems/combat-hits.md)
- [`../server/design.md`](../server/design.md) · [`../server/contract.md`](../server/contract.md) — the authoritative server (architecture + wire spec)
- [`../adr/0003-enet-udp-transport.md`](../adr/0003-enet-udp-transport.md) — the UDP/ENet transport decision
