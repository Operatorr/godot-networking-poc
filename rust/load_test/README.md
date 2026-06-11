# omega-load-test — ENet bot swarm

Rust port of the retired Python harness (`load_testing/`, removed with the WebSocket server;
full history in git before the port). It lives in the workspace **on purpose**: the bots link
[`protocol`](../protocol/) for the wire format and [`sim_core`](../sim_core/) for movement
prediction, so codec drift and sim drift against the server are impossible by construction.

## Running

```bash
./scripts/run_server.sh                                  # terminal 1: the server under test
./scripts/run_load_test.sh --scenario baseline           # terminal 2: the swarm
./scripts/run_load_test.sh --bots 75 --duration 120 --server 10.0.0.1:8081
```

Bots authenticate **ticket-less** (dev mode), so the server must run with
`allow_unsigned_tickets` (the default). The `stress` scenario needs a server config with
`max_players >= 200` (default is 100; excess bots are kicked at connect and show up as
crash-rate failures, which is itself a valid full-server test).

## What each bot is

A real client as far as the server can tell: its own UDP socket + ENet host (3 channels),
the ENet-connect `data` protocol-version check, `ConnectAuth` → `AuthResult` handshake,
inputs on ch2 at 30 Hz (`--input-hz` to change; the old Python bots sent 10 Hz),
`BaselineAck` per baseline, `LocalHitReport` for monster-shot overlaps (once per projectile,
≤ 20/s — the server quota), and `RespawnRequest` 3.2 s after death. Movement prediction runs
`sim_core::step_movement` — the same integration the server applies — so the positions bots
report in `PlayerInput` survive server validation exactly like a real client's.

## Scenarios (same table as the Python harness)

| Scenario | Bots | Duration | Behavior | Purpose |
|---|---|---|---|---|
| `baseline` | 50 | 120 s | default | Basic functionality under load |
| `target` | 100 | 300 s | default | The POC success-metric validation run |
| `stress` | 200 | 300 s | default | Find the breaking point |
| `idle` | 100 | 120 s | idle | Connection-only baseline |
| `movement` | 100 | 120 s | movement | Movement/snapshot throughput |
| `combat` | 100 | 120 s | combat | Constant shooting / projectile load |
| `clustered` | 100 | 120 s | clustered | AoI worst case (everyone converges on origin) |
| `strategy` | 10 | until Ctrl-C | strategy | Gameplay-like bots |

Behaviors `default/idle/movement/combat/clustered` keep the Python constants (re-pick
probabilities, shoot chances, converge-on-origin). `strategy` is a **simplified** port:
target selection, orbit-at-preferred-range, intercept aim with difficulty-scaled gaussian
error, projectile dodging, stamina-gated sprint, and cooldown dash are kept; the old A*
waypoint hunt and flank planner are not.

## Metrics & success criteria

Success criteria are unchanged (avg latency < 100 ms, P95 < 150 ms, bandwidth < 5 KB/s per
player, packet loss < 2 %, crash rate < 5 %, tick rate ≥ 30 Hz). Two measurements moved to
ENet-native sources because their old carriers died with the WebSocket protocol:

- **Latency** is the ENet round-trip time (the HEARTBEAT echo no longer exists; clock sync
  rides `Snapshot.server_ms`). Sampled 1 Hz per bot after a 2 s warm-up.
- **Packet loss** is ENet's measured mean loss ratio, not the snapshot-tick-gap estimate.

Reports: console summary + `report_<timestamp>.json` in the CWD (`--output` to choose),
with config, aggregates, server-reported `SERVER_METRICS`, 5 s time series, and per-bot
summaries — the same shape as the Python report.

## Regression assertions (`--assertions strict|warn|off`, default warn)

- `aoi_cull` — no bot observes entities beyond `aoi_exit_radius` (+50 u tolerance, 95 % of
  bots must pass). `--aoi-exit-radius` if the server config differs from the 1100 default.
- `decode_clean` — every received server packet must decode strictly (successor of
  `batch_decode_clean`; any failure means codec drift). 
- `per_peer_budget` — received bytes/s per bot ≤ `--rate-budget` (0 skips). Pair with
  `--bandwidth-budget` to advertise a budget in `ConnectAuth` and then assert it.

`lod_cadence` from the Python suite was **not** ported: the Rust server replaced fixed
MID/FAR send intervals with a byte-budget priority scheduler (LOD is a distance penalty —
`server/src/broadcast.rs`), so per-band cadence is emergent and has no configured expectation
to assert. Scheduler health is visible in the `sched_*` fields of `SERVER_METRICS` instead.

Exit codes: `0` all success criteria met · `1` criteria failed (or nothing connected) ·
`2` strict assertions failed.
