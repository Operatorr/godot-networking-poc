# omega-load-test — ENet bot swarm

Rust port of the retired Python harness (`load_testing/`, removed with the WebSocket server;
full history in git before the port). It lives in the workspace **on purpose**: the bots link
[`protocol`](../protocol/) for the wire format and [`sim_core`](../sim_core/) for movement
prediction, so codec drift and sim drift against the server are impossible by construction.

## Running

```bash
./scripts/run_server.sh                                  # terminal 1: the server under test
./scripts/run_load_test.sh --scenario baseline           # terminal 2: the swarm (run the test on local 127.0.0.1:8081)
./scripts/run_load_test.sh --scenario baseline --live    # terminal 2: the swarm (runs the test on live server)
OMEGA_LOAD_TEST_SECRET=… ./scripts/run_load_test.sh --scenario baseline --live   # the live arena (signed)
./scripts/run_load_test.sh --bots 75 --duration 120 --server 10.0.0.1:8081
./scripts/run_load_test.sh --bots 3 --scenario strategy --live # live server testing
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

### Running against the live server

Two one-time setups (server, then laptop), then run the swarm. See also
[`deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md) §4.

**1. Enable the ticket endpoint on the live API** (once). `POST /api/loadtest/ticket` is dormant
(503) until `LOAD_TEST_TICKET_SECRET` is set. On the droplet:

```bash
ssh deploy@<droplet-ip>
SECRET=$(openssl rand -hex 32)
echo "LOAD_TEST_TICKET_SECRET=$SECRET" | sudo tee -a /etc/omega-realm/api.env
sudo systemctl restart omega-api
echo "$SECRET"   # copy to your laptop (step 2)
```

The endpoint only mints synthetic `character_id`s (>= 1,000,000), so a leaked secret can't touch a
real character — but it does let the holder spawn bots on the live server, so treat it as a secret.

**2. Put the secret on your laptop.** Save the value from step 1 to a file the run command reads
(kept out of the repo and your shell history):

```bash
echo '<SECRET from step 1>' > ~/.omega_loadtest_secret && chmod 600 ~/.omega_loadtest_secret
```

Optionally persist it as an env var so you don't prefix every run. This appends a line that
_re-reads the file_ on each new shell — the secret value itself stays only in the file, not in
`.zshrc` or your history:

```bash
echo 'export OMEGA_LOAD_TEST_SECRET="$(cat ~/.omega_loadtest_secret)"' >> ~/.zshrc
```

**3. Run the swarm** (`--live` targets the live Arena and the live API automatically):

```bash
# if you did NOT add the .zshrc line, pass the secret inline (reads the file for that one command):
OMEGA_LOAD_TEST_SECRET="$(cat ~/.omega_loadtest_secret)" ./scripts/run_load_test.sh --bots 3 --scenario strategy --live
# if you DID add the .zshrc line (and opened a new shell), the env var is already set:
./scripts/run_load_test.sh --bots 3 --scenario strategy --live
```

To disable the endpoint again, remove the `LOAD_TEST_TICKET_SECRET=…` line from
`/etc/omega-realm/api.env` and `sudo systemctl restart omega-api`.

## What each bot is

A real client as far as the server can tell: its own UDP socket + ENet host (3 channels),
the ENet-connect `data` protocol-version check, `ConnectAuth` → `AuthResult` handshake,
inputs on ch2 at 30 Hz (`--input-hz` to change; the old Python bots sent 10 Hz),
`BaselineAck` per baseline, `LocalHitReport` for monster-shot overlaps (once per projectile,
≤ 20/s — the server quota), and `RespawnRequest` 3.2 s after death. Movement prediction runs
`sim_core::step_movement` — the same integration the server applies — so the positions bots
report in `PlayerInput` survive server validation exactly like a real client's.

## The one-minute loop (`scripts/quick_stress.sh`)

For iterating on server performance, don't drive the swarm by hand. `./scripts/quick_stress.sh`
builds, starts a local Arena with telemetry on, runs the swarm, stops everything and renders a
report — one command, about 90 s, no human in the loop. See
[`docs/netcode/perf-notes/hill-climb/README.md`](../../docs/netcode/perf-notes/hill-climb/README.md).

### Threads (`--threads N`, default 1)

The swarm can shard its bots over N OS threads (round-robin by bot id). Each shard owns its
bots end to end — socket, ENet host, sim state are created and dropped on the shard thread;
only the plain-data per-bot metrics come back — so nothing is shared between threads during the
run. The global join cadence is unchanged: bot *i* connects at *i × --stagger* from swarm start
whichever shard owns it. Shards share one Phase-2 clock: `--duration` starts when the last shard
finishes its ramp, and every 5 s sample in the report sits on that clock, with RTT percentiles
computed over the pooled samples. Use this on any multi-core bot host so the generator never saturates one
core (the old single-threaded swarm peaked at ~85 % of a core around 190 strategy bots, which
confounded every capacity reading). `OMEGA_MEASURE_DIR` per-bot observations are only recorded
on single-threaded swarms; per-shard evidence is what `--measured-window` is for.

### Measured window (`--measured-window`)

One common scored interval for the DigitalOcean capacity contract. It needs every workload control stated (`--bots --threads --stagger --behavior
--difficulty --input-hz --seed --hold-s --evidence-dir --output`), refuses `--scenario`, `--duration`, `--no-report` and tickets (a ticket fetch would block a shard), and takes the
readiness bound from `--readiness-timeout-s` or the accepted `max(60 s, ramp + 30 s)`.

Each generator shard owns its bots end to end and never blocks. Generator shard here means one swarm thread, not the glossary's server **Shard**.

```text
bot i connects at i x stagger, with no settling  ->  all N authenticated  ->  2 s warmup  ->  a future start and end published 1 s ahead
  ->  every shard acknowledges start  ->  hold  ->  every shard acknowledges end and freezes  ->  2 s guard, still connected  ->  drain  ->  footer + fsync
```

- **Readiness.** `--readiness-timeout-s` bounds authentication only. Once all N have authenticated on time it is finished, so the warmup can run past it, and lost bots and shards are still watched through the warmup.
- **Input.** A fixed 30 Hz grid from the moment of authentication. A slot that was missed is counted and never burst-sent. A window's scheduled count comes from the grid, so it does not trust the polls, and a frame scores only if its slot is inside the window and its enqueue came before the end, by that enqueue's own timestamp. RTT samples are stamped when read, and connect, auth and disconnect when observed, all on the swarm's monotonic clock; a poll's reading only picks the due slot. A bot that is dead in the game still sends idle frames, and those count; `dead_frames` shows how many.
- **Files** in `--evidence-dir`, all create-only, so an existing file makes the run exit 4 instead of being replaced: `swarm.json` (identity, nonce, effective controls), `coordinator.ndjson` (barrier, publication, stalls, wall/monotonic pairs), `shard-<k>.ndjson` (numbered rows with header and footer: joins, auths, 1 Hz per-bot samples with timestamped ENet RTT and loss, acknowledgments, frozen window counters) and `window.json` (the outcome). Monotonic times are this process's own, counted from its start.
- **Exit status** says whether the evidence is finished, and never judges the server: 0 window recorded, 1 window not established or incomplete, 2 usage, 4 a recorder failed. `report.json` is the old whole-run summary, labelled `legacy_whole_run_diagnostic`; it includes ramp and drain and decides nothing.
- **Judging it** is `scripts/do_session/measurement_window.py`, and scoring it is issue #69. Nothing in this mode says PASS.
- **Faults.** `--fault` exists only with `--features fault-injection`. Every binary states `build.fault_injection` in `swarm.json`, so a fault build names itself even with no `--fault` and can never prove a window. Frozen benchmark builds do not have it.

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
| `quick`     | 100  | 60 s         | strategy  | The fast hill-climb loop (`scripts/quick_stress.sh`) |

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

For diagnostic builds, `OMEGA_MEASURE_DIR` enables cumulative per-bot observations
in `bots.ndjson`. Observations are flushed approximately once per second during
both join settling and the join stagger, so an aborted ramp retains offered-input
counts/gaps, delivery and error evidence. Ramp rows have `phase: "ramp"` and
`phase_s: null`; they never start the post-join warmup/measurement clock. Existing
post-join rows have `phase: "run"` and retain their original `phase_s` and boundary
semantics. `completed_observer_ns` and `completed_samples` describe all completed
observations **before** the current row, including serialization and flush time;
they do not measure the causal performance perturbation of instrumentation.

## Regression assertions (`--assertions strict|warn|off`, default warn)

- `aoi_cull` — no bot observes entities beyond `aoi_exit_radius` (+50 u tolerance, 95 % of
  bots must pass). `--aoi-exit-radius` if the server config differs from the 1100 default.
  Distances use explicit observer/entity positions from the same Snapshot. A delta
  without the observer's position is **unknown**, and any unknown (or no observations)
  prevents a strict pass. Cached positions and ActionConfirms are not contemporaneous
  substitutes. Reports retain matched/unknown counts and a diagnostic legacy maximum.
  These are lifetime metrics, including warmup. Opt-in server `OMEGA_AOI_AUDIT=1`
  alongside `OMEGA_MEASURE_DIR` supplies separate authoritative emission evidence in
  `aoi.csv`; it does not make the standalone bot assertion complete or prove delivery.
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
