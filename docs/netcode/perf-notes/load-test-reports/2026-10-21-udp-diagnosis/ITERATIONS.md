# CAX11 UDP diagnosis and capacity iterations

Task: [Diagnose UDP receive-buffer errors and increase validated CAX11 capacity](https://github.com/Operatorr/godot-networking-poc/issues/38).
Parent: [Article: load testing Omega Realm & why realtime games cap at ~64 players](https://github.com/Operatorr/godot-networking-poc/issues/23).

## Scope and baseline

This investigation preserves the closed one-pass campaign. It diagnoses the UDP
receive-buffer failures, compares justified changes, and measures sustained capacity.
Each remote experiment has a separate agent; experiments on the shared pair run
sequentially, with cleanup verified before the next dispatch.

- Frozen game: `b1266c1`, SHA-256 `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`.
- Frozen bots: `642c147`, SHA-256 `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`.
- Historical highest passing Strategy population: **100**. The 176–191 peaks
  in later overload ramps are not sustained capacity observations.
- Private evidence namespace: `deployment/hetzner/results/udp-diagnosis-20261021/`.
- Capacity conditions: original Strategy/Class mix/AoI/Snapshot/budgets, 30 Hz
  input and Tick, 100 ms join stagger, 60 s global warmup, 300 s measurement.
  Instrumentation, buffer changes and timing changes are separate conditions.
- Missing observations remain unknown; a short diagnostic is never a capacity pass.

## Iteration ledger

| Experiment | Question/intervention | Build and condition | Outcome | Evidence and cleanup |
| --- | --- | --- | --- | --- |
| Baseline Strategy 200 reproduction | Reproduce the reported failure and identify which process/socket drops datagrams; no performance tuning | Frozen game/bots; native settings; bounded diagnostic; socket observations added | Failed ramp after 38.05 s; peak 189 authenticated; all 172,927 game receive-buffer errors attributed to its socket; 4,178 bot-host errors, at least 3,745 on bot sockets; input cadence unknown | [Full evidence and verified restoration](baseline-reproduction.md) |
| Frozen-build profile reproduction | Identify dominant CPU work during queue overflow; prediction: transport/replication, logging or generator hot paths distinguish the competing explanations | Same frozen builds/settings; bounded 99 Hz CPU profiling added; diagnostic only | Failed ramp after 43.05 s, peak 185 authenticated. Reliable-command removal self CPU rose 1.73% → 11.95% → 52.63% before/after onset/final ten seconds. Broadcast remained substantial. | [Profile evidence and verified restoration](profile-reproduction.md) |
| Instrumented Strategy 200 control | Align actual read gaps, loop phases and bot ramp cadence with overflow before changing processing or buffers | Exact `cc86869`; original settings/buffers; no optimization | Failed ramp, 43.06 s, peak 182 authenticated. Initial read gaps about 26 ms, late maximum 443 ms; retry/ACK traffic and service work rose sharply. Collector state guard truncated wire evidence at 27.57 s. | [Control evidence and verified restoration](instrumented-control.md) |
| Bitmap replication candidate, Strategy 200 | Reduce pre-overflow replication cost; predict shorter read gaps and less subsequent retry amplification | Candidate `1d15d84` game; identical `cc86869` bot and control collectors/settings/buffers | Failed ramp at 37.56 s; peak 181 authenticated. No consistent World Tick benefit or later onset; 161,782 game receive drops. | [Comparison and verified restoration](bitmap-comparison.md); old collector again truncated late wire evidence |

Local candidate preparation: [linear stale-cache membership](REPLICATION-CANDIDATE.md)
replaces repeated slice scans with a u16 bitmap. A HashSet trial was rejected for
small-set regressions. The candidate improves the bounded local helper timing;
remote comparison did not demonstrate a capacity benefit. It remains a local
algorithmic improvement, not an established cause/fix for CAX11 overflow.

The first profiling preflight found no installed sampler and launched **zero**
experiments. The replacement agent installed `linux-perf 7.0.0-38.38` and two
debuginfod dependencies, validated recording, and completed exactly one workload.
Kernel and perf policy were unchanged. The bot ramp recorder fix `3b910cd` was
excluded from the frozen-build experiment.

Server timing/socket instrumentation passes the workspace tests, Clippy (existing
warnings remain), and formatting check. The next control will distinguish its
observations from the frozen profile; instrumentation itself is not an improvement.

## Ranked hypotheses after reproduction

1. **Serial processing delays reads.** If ENet servicing or replication dominates,
   CPU profiles and read gaps should locate that work while receive queues fill;
   reducing the identified work should reduce gaps and drops at matched load.
2. **Reliable traffic amplifies initial loss.** Retries and transport CPU should rise
   after the first drops; an intervention reducing the initial pressure should also
   prevent the feedback, rather than merely postpone it.
3. **Generator polling falls behind or bunches inputs.** Per-bot scheduling gaps
   should deteriorate during the ramp. Missing ramp observations currently prevent
   this test; recording during join is a separate instrumentation change.
4. **Warnings or measurement I/O contribute to stalls.** Profiles should expose
   logging/collector work; any suppression experiment must retain independent
   error counters and be labelled separately from an optimized capacity build.

The reproduced immediate mechanism is game-socket receive-queue overflow. Its
processing cause is unresolved. Interface/qdisc/checksum deltas were zero in the
baseline; that does not establish the causal order within each one-second sample.

## Required evidence per comparison

Record executable/configuration hashes, compiler/kernel and effective buffers;
authenticated/living population and per-peer offered/wire cadence throughout the
ramp and steady state; first drop and socket attribution; game/bot CPU and steal;
Tick work/deadlines; queue/delivery/retry behavior; exact errors and missing values;
collector overhead; classification; and highest passing sustained population.

Rank falsifiable hypotheses after reproduction. State the prediction and the
single-factor intervention before each experiment. Distinguish a proven mechanism
from a correlated symptom, and a generator limit from a game-server limit.

## Collector prerequisite for sustained validation

The instrumented control also exposed a collector history guard failure.
[The bounded-history repair](COLLECTOR-REPAIR.md) reproduces and fixes that local
failure, preserving prefix evidence and versioning changed retry semantics.
The completed bitmap comparison froze the old collector at `04faa97`. The next
observation keeps its exact game/bot binaries and native settings, changing only
the collector to `30ec792`: predict complete late coverage without command-count
exhaustion, with measured collector CPU/RSS. It also checks whether collector
pressure materially perturbed the earlier failure; any performance change is
first attributed to this instrumentation condition, not game optimization.

## Prepared next intervention

[Receive-buffer control](BUFFER-CANDIDATE.md) adds an opt-in game receive request
without changing the default. Workspace checks and real socket initialization
coverage pass. It prepares a later 2 MiB-request condition to distinguish burst
absorption from throughput/backlog; no remote improvement is claimed.
[Existing reliable-event counters](RELIABLE-PRESSURE.md) show substantial fan-out
already before overflow, so baseline fragmentation alone cannot explain the
application-enqueued reliable volume. Event reliability/recipients are unchanged.

## Completion state

Investigation in progress. No new capacity claim or root-cause conclusion yet.
Correctness defects discovered here must also be recorded for
[Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39).
