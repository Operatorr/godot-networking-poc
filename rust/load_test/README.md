# omega-load-test — ENet bot swarm

Rust port of the retired Python harness (`load_testing/`, removed with the WebSocket server;
full history in git before the port). It lives in the workspace **on purpose**: the bots link
[`protocol`](../protocol/) for the wire format and [`sim_core`](../sim_core/) for movement
prediction, so codec drift and sim drift against the server are impossible by construction.

## Running

```bash
./scripts/run_server.sh                                  # terminal 1: the server under test
./scripts/run_load_test.sh --scenario baseline           # terminal 2: the swarm (local 127.0.0.1:8081)
OMEGA_LOAD_TEST_SECRET=… ./scripts/run_load_test.sh --scenario baseline --live   # the live arena (signed)
./scripts/run_load_test.sh --bots 75 --duration 120 --server 10.0.0.1:8081
```

Target precedence: explicit `--server <host:port>` wins, then `--live` (the live arena — the same
address the client's LIVE switch uses; override with `OMEGA_LIVE_SERVER`), then `OMEGA_SERVER`, then
the `127.0.0.1:8081` default. `--live` is handled by the wrapper script, not the binary.

### Auth

Two paths, by how the target server is configured:

- **Local / dev (unsigned).** Against a server run with `--allow-unsigned-tickets` (the
  `dev_local.sh` default), bots join **ticket-less** — nothing extra to set.
- **Live / fail-closed (signed).** A server with `allow_unsigned_tickets=false` rejects
  ticket-less joins with `BAD_TICKET`. Pass `--ticket-api-url <origin>` + `--ticket-secret <tok>`
  (or env `OMEGA_TICKET_API` / `OMEGA_LOAD_TEST_SECRET`) and each bot fetches a real signed
  Ed25519 ticket from the Go API's `POST /api/loadtest/ticket` for a **synthetic** `character_id`
  (`1_000_000 + bot_id`). The server keeps synthetic ids out of all DB I/O, so the swarm
  authenticates for real without touching any character row. `--live` wires this up automatically
  (it sets `OMEGA_TICKET_API` to the live API and requires `OMEGA_LOAD_TEST_SECRET`); the secret
  must match the API's `LOAD_TEST_TICKET_SECRET`, and `--region` (default `asia`) must match the
  target instance or the join is `WRONG_REGION`.

The `stress` scenario needs a server config with `max_players >= 200` (default is 100; excess bots
are kicked at connect and show up as crash-rate failures, which is itself a valid full-server test).

## What each bot is

A real client as far as the server can tell: its own UDP socket + ENet host (3 channels),
the ENet-connect `data` protocol-version check, `ConnectAuth` → `AuthResult` handshake,
inputs on ch2 at 30 Hz (`--input-hz` to change; the old Python bots sent 10 Hz),
`BaselineAck` per baseline, `LocalHitReport` for monster-shot overlaps (once per projectile,
≤ 20/s — the server quota), and `RespawnRequest` 3.2 s after death. Movement prediction runs
`sim_core::step_movement` — the same integration the server applies — so the positions bots
report in `PlayerInput` survive server validation exactly like a real client's.

## Scenarios (same table as the Python harness)

| Scenario    | Bots | Duration     | Behavior  | Purpose                                       |
| ----------- | ---- | ------------ | --------- | --------------------------------------------- |
| `baseline`  | 50   | 120 s        | default   | Basic functionality under load                |
| `target`    | 100  | 300 s        | default   | The POC success-metric validation run         |
| `stress`    | 200  | 300 s        | default   | Find the breaking point                       |
| `idle`      | 100  | 120 s        | idle      | Connection-only baseline                      |
| `movement`  | 100  | 120 s        | movement  | Movement/snapshot throughput                  |
| `combat`    | 100  | 120 s        | combat    | Constant shooting / projectile load           |
| `clustered` | 100  | 120 s        | clustered | AoI worst case (everyone converges on origin) |
| `strategy`  | 10   | until Ctrl-C | strategy  | Gameplay-like bots                            |

Behaviors `default/idle/movement/combat/clustered` keep the Python constants (re-pick
probabilities, shoot chances, converge-on-origin). `strategy` is a **simplified** port:
target selection, orbit-at-preferred-range, intercept aim with difficulty-scaled gaussian
error, projectile dodging, stamina-gated sprint, and cooldown dash are kept; the old A\*
waypoint hunt and flank planner are not.

Two survival overlays layer on top of the `strategy` movement (both purely geometric — they
add no RNG draws, so bot runs stay reproducible):

- **Defensive orb-seek** — below **60% HP**, a bot detours to the nearest **Healthorb** within
  800 u while it keeps fighting: aim + fire stay on the engaged target and the dodge overlay
  still wins on movement, so the bot grabs the heal _while_ shooting and dodging. HP comes from
  `ActionConfirm.health` (the only HP on the wire); orbs are already in the AoI entity map.
- **Daze-aware braking** — an incoming shot inside 100 u and still closing is a near-certain hit,
  so the bot drops **sprint** for that frame. A hit taken while sprinting Dazes (sprint/dash
  lock + 30% slow, 1.5 s); taken while walking it does not — so braking mirrors a real player.

Projectile dodging and the braking above react to **every** incoming shot the bot didn't fire —
monster, enemy player, _and_ other bots — learned from `PROJECTILE_FIRED` (which carries each
shot's id + owner). The bot's own shots are excluded so it never dodges its own fire. (Earlier the
swarm only dodged monster bullets, so a human attacker found bots easy to hit in PvP.)

## Player classes & RMB abilities

Bots only spawn as the three **playable** classes — **Warrior (4)**, **Rogue (5)**, **Mage
(6)** — never the disabled ones. The class is assigned **round-robin by bot id** so a swarm
splits evenly (3 bots → 1 Warrior, 1 Rogue, 1 Mage), which keeps test runs reproducible.
Assignment is in `Bot::connect` (`bot.rs`).

Only `strategy` bots use the **RMB ability** (the other behaviors have no target to aim it
at). When a strategy bot is engaging a target in shoot range, it occasionally fires its
ability (`behavior.rs` `apply_ability`):

- **Warrior — Charge**: aims at the target, clears the strafe so the charge launches toward
  it, and **holds** the ABILITY input for ~1.35 s so the steerable charge runs its course and
  homes on the target. (Releasing after one tick — the old behavior — ended the charge
  immediately, so the Warrior barely moved.)
- **Rogue / Mage — instant cast**: a single-frame cast with the input `cursor` set to the
  **target's** world position, so the Shadowstep / Mageblast lands on the target instead of
  the bot's own feet.

## Tuning bot difficulty (`--difficulty 0..1`, default 1.0)

One knob scales how "expert" the strategy bots play; everything it touches lives in
`behavior.rs`:

- **Reaction time** — re-decide interval, 40 ms (1.0) → 500 ms (0.0).
- **Aim accuracy** — gaussian aim error, 0 (1.0) → up to ~0.34 rad (0.0), also widening with
  range.
- **Preferred engagement range** — higher difficulty closes in tighter.
- **Dash & RMB-ability frequency** — higher difficulty dashes and casts more often.

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
