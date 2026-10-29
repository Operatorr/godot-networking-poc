# Hill-climb: the one-minute stress loop and the climb to 1000 players

**Status:** Active (started 2026-10-29). This directory is the **single place** to look for
"where are we, what is the bottleneck, what do we try next". The ledger next to it
([`ledger.md`](ledger.md)) gets one row per run, appended automatically.

## Why this exists

The 2026-10-13/14 Hetzner campaign (`../load-test-reports/2026-10-14-one-pass/`) took 20–30
minutes per run (5-minute measured window, two remote hosts, archive + audit pipeline) and ended
with Strategy ramps breaking at **176–191 authenticated players** and a conclusion of *"the CPU
hot path and the role of retransmissions are not measured"*. Every later "bounded diagnostic"
(2026-10-21, -22, -29) spent its budget on measurement validity and never answered **why**.

The fix is a loop that is cheap enough to run after every change: **one command, ~90 seconds,
full telemetry, a report an agent can read in one screen.** Only with that loop in place does
iterating (hill-climbing) on the server make sense.

## The loop

```bash
./scripts/quick_stress.sh                        # 100 strategy bots × 60 s, local Arena
./scripts/quick_stress.sh --bots 200 --label x   # a rung of the ladder, tagged
cat loadtest-runs/latest/REPORT.md               # the report (also printed to stdout)
```

What one run does (no human in the loop, ~90 s for 100 bots):

1. `cargo build --release` (incremental: seconds when nothing changed).
2. Starts a **local Arena** (`deployment/server_config.loadtest.json`: `max_players 999`, no API,
   unsigned tickets) with `OMEGA_MEASURE_DIR` on → per-tick `ticks.csv` + 1 Hz `server.ndjson`
   (loop-phase timings, bytes by packet type/channel, reliable events by type, procfs CPU/RSS,
   socket read gaps).
3. Starts a 1 Hz **host sampler** (`scripts/quick_stress/sample_host.py`): server + swarm process
   CPU/RSS, system CPU/steal, host-wide UDP `InErrors/RcvbufErrors/SndbufErrors`, the server
   socket's rx/tx queue + drops.
4. Runs the swarm: `--scenario quick` = **strategy** (gameplay-like) bots, **one join per 100 ms**,
   sharded over `--threads` OS threads (default `min(4, nproc-1)`) so the generator is never the
   bottleneck on a multi-core box.
5. Stops everything, renders `REPORT.md` + `summary.json` (`scripts/quick_stress/report.py`),
   prints the verdict block + key numbers, appends a row to [`ledger.md`](ledger.md).

Everything lands in `loadtest-runs/<utc-timestamp>-<label>/` (gitignored; `loadtest-runs/latest`
is a symlink). Typical sizes for 100 bots × 60 s: `ticks.csv` ~300 KB, `server.ndjson` ~400 KB,
logs < 100 KB. The server logs at `info` (two lines per join, nothing per hit/projectile);
the report's *Log hygiene* section flags any file over 20 MB — fix the source, don't sample it.

Wall-clock budget: ramp (bots × stagger) + duration + ~10 s. 100 bots × 60 s ≈ 85 s; 200 bots ≈ 95 s.

### Reading a report

The first screen is the whole answer:

- **PASS/FAIL** and *Why not a pass* — connected/requested, bot errors, failed success criteria,
  ticks over 33 ms, kernel receive-buffer drops.
- **Bottleneck read** — in the order each one invalidates the next: *GENERATOR-BOUND* (swarm CPU
  per thread > 85 %: the server numbers are suspect, add threads/hosts), *SERVER CPU-BOUND*
  (> 85 % of a core, with the two biggest loop phases named), *UDP RECEIVE OVERFLOW*,
  *TICK OVERRUN* (p95 > 33.3 ms), *NETWORK* (loss > 2 % / RTT p95 > 150 ms), or
  *NO BOTTLENECK HIT* with a naive linear headroom estimate.
- One line each: server CPU, bots CPU, tick p95/max, % ticks over 33 ms, RcvbufErrors, RTT p95,
  loss, KB/s per bot, **reliable events per peer per second**, server bytes out.

Then the tables, in the order you need them when the verdict says CPU-bound: tick work
distribution → **CPU by loop phase** (`service_and_route` = ENet receive + packet handlers,
`simulation` = movement/projectiles/AI/collisions, `snapshot_build` = AoI + delta scheduling +
encoding, `outbox_flush` = encode + `peer.send` for every queued packet, `enet_flush` = ENet
command/ack processing + UDP sends) → traffic by packet type and channel → **reliable
GameEvent packets per second by type** (the N² term) → host → bots → criteria → log hygiene.

### Success criteria (what "flawless" means)

From `rust/load_test/src/metrics.rs`, asserted by the swarm: RTT avg < 100 ms, RTT p95 < 150 ms,
bandwidth < 5 KB/s per player, ENet loss < 2 %, crash rate < 5 %, tick rate ≥ 30 Hz. The report
adds: every requested bot connected, zero bot errors, < 1 % of ticks over 33.3 ms, zero kernel
UDP receive drops.

Two of these need a decision before they can gate anything (see *Open questions*): the
**5 KB/s** bandwidth gate is already failed at 20 strategy bots (10 KB/s) and the swarm's
**tick-rate** estimate reads 29.9997 Hz on a perfect server (truncated u32 `server_ms` spans);
the report uses the server's own tick clock for that criterion.

## The ladder (checklist)

Climb one rung at a time. A rung is **done** when a 60 s quick run passes every criterion at
that population on the reference box. Record the rung's run in the ledger and link it here.
Each `[ ]` is a decision or a measured fact; tick it with the ledger row that proves it.

- [x] **Loop exists**: one command, < 2 min, report readable in one screen. (2026-10-29, this doc)
- [x] **Generator is not the bottleneck**: swarm sharded over threads (`--threads`),
      swarm CPU reported per run.
- [x] **Server loop phases measured** (service/route, simulation, snapshot build, outbox flush,
      ENet flush) + process CPU + reliable-event rates by type. No more "hot path not measured".
- [ ] **Rung 50** strategy: PASS at 60 s. (Bandwidth gate decision pending — see below.)
- [ ] **Rung 100** strategy: PASS at 60 s.
- [ ] **Rung 150** strategy: PASS at 60 s.
- [ ] **Rung 200** strategy: PASS at 60 s. *(The old wall: 176–191 on CAX11.)*
- [ ] **Rung 300**
- [ ] **Rung 500** — POC target floor.
- [ ] **Rung 1000** — POC target ceiling.
- [ ] **Same rung on the live host class** (Hetzner CAX11 / CCX13 / DO droplet): the local box is
      a 4-vCPU shared VM; the ladder here measures the *code*, the live run measures the *box*.
- [ ] **5-minute confirmation** of the highest passing rung (the quick loop is 60 s by design;
      memory growth, leaderboard cadence and respawn cycles need the longer run once).

Optimization candidates are listed under *Hypotheses* with their status; when one is applied,
re-run the rung that failed, append the ledger row, and move the hypothesis to *Confirmed* or
*Refuted* with the before/after numbers.

## Hypotheses for the 190 wall

Written from the first local ladder (see *Findings* below) and the Hetzner evidence
(`../load-test-reports/2026-10-14-one-pass/CAX11-CONCLUSION.md`). Status: **untested / testing /
confirmed / refuted**. Each one names the measurement that decides it.

| # | Hypothesis | Decides it | Status |
|---|---|---|---|
| H1 | **Reliable broadcast storm.** Every `PROJECTILE_FIRED` (player *and* monster), `DAMAGE`, `EXP_GAIN`, `ABILITY_EFFECT`, … is a reliable ch1 packet **broadcast to every connected peer with no AoI filter** (`rust/server/src/sim/world.rs`, `outbox.broadcast`). Packets/s = players × events/s, events/s ∝ players ⇒ **N²**. Each one is an ENet reliable command (allocation, ack bookkeeping, retransmit timer) on the server and an ack datagram from every client back to the server. | `event_sends_per_s` total vs players in the report; `outbox_flush` + `enet_flush` phase share; datagrams in/s. | see Findings |
| H2 | **Snapshot build is O(peers × visible entities)** per tick (`broadcast_state_updates`: per peer a grid query, a HashSet of previously-visible ids, a delta-mask check per visible entity, a sort, encoding). With everyone in one 2000-unit arena and AoI 1000 u, most peers see most entities. | `snapshot_build` % of core vs players (expect ~N² in a clustered arena). | see Findings |
| H3 | **Kernel receive-buffer overflow is a symptom of (H1/H2) stalls**, not a cause: a 20–30 ms tick leaves the 512 KB socket buffer to absorb a full tick of inbound inputs + acks from N clients; past ~150 clients at ~100 B × 30 Hz + acks that is > 512 KB per stall. | `RcvbufErrors` appearing only when `tick p95` or `read-gap max` crosses ~20 ms. If drops appear with low tick times, buffer size/drain cadence is the cause instead. | untested |
| H4 | **Generator saturation** on the Hetzner bot host (single-threaded swarm at 81–87 % of a core) distorted the 190 reading. | Bots CPU per thread in the report; the sharded swarm removes it. | fixed in harness; re-measure on Hetzner |
| H5 | **Host class**: CAX11 is 2 shared Ampere vCPUs; a dedicated x86 core (CCX13) moves the wall but does not change the N² shape. | Same rung on both hosts; compare `ms per tick` per phase. | untested |
| H6 | **Bandwidth gate**: 5 KB/s per player is unreachable with the current snapshot size (~15 KB/s per player of ch0 deltas at 50 bots) — either the gate or the wire format has to change. | Snapshot bytes per peer per tick vs the 1200 B/snap budget; what the peer budget scheduler defers. | see Findings |

## Open questions (decisions the user owns)

1. **Bandwidth gate**: keep 5 KB/s per player (then snapshot and event volume must drop ~4×) or
   set the gate to the measured 30 Hz-full-AoI reality and budget egress cost instead?
2. **AoI for events**: should `PROJECTILE_FIRED` / `DAMAGE` / `EXP_GAIN` be AoI-scoped (only peers
   that can see the shooter/victim) and should `PROJECTILE_FIRED` be unreliable (the snapshot
   already carries the projectile entity)? This is the single largest lever H1 points at.
3. **Target host**: which box is the reference for the ladder rungs above 200?

## Findings

_Filled in per ladder run; newest at the bottom. Each entry links its ledger row and run label._
