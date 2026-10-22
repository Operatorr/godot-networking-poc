# Unprofiled Strategy 150 dodge-search candidate — 2026-10-21

**Exactly one workload completed. Generator valid; capacity result `valid-failure`.**
The candidate restored every bot to **29.993376–30.000042 Hz offered** and
**29.843333–29.996667 Hz exact mapped wire input** at both hosts. All 150 remained
authenticated through the full 300-second window, and every per-peer delivery gate
passed. **Game send-buffer errors and the strict AoI assertion still failed.**
Historical **Strategy 100 remains the highest validated capacity**; no new capacity
pass or correctness certificate is claimed.

The direct comparator is the earlier **unprofiled** [capacity150](capacity150.md),
not the subsequent profiled observation. The single factor was candidate bot
`2c25af7d5ab4cba81de1777437e2df2cfe735ebc`. The search implementation, local validation,
and prediction are in [DODGE-CANDIDATE.md](DODGE-CANDIDATE.md); all
[capacity gates](CAPACITY-150-PLAN.md) remain unchanged. No profiler/tracer, second
workload, tuning, gameplay change, additional agent, commit/push, parent-ledger edit,
or provisioning occurred. The unrelated worktree was untouched.

[Compact exact summary](dodge150-summary.json) includes window endpoints, all gates,
failing identities, counters, trajectories, hashes and cleanup. Full per-peer rows,
per-second timelines, commands and connection details remain private.

## Matched condition and provenance

Both hosts independently built **only `omega-load-test`** in the same isolated path:
`/home/deploy/omega-udp-dodge-2c25af7/rust/target/release/omega-load-test`.
Both clean checkouts are the exact candidate revision and produced identical SHA-256:

```text
73b957c7cb090ac8c433aa66dfba983ec8ad62305f527cab83be596dce524b1e
```

Build: `cargo build --release --locked -p omega-load-test`; Rust **1.95.0**
(`59807616e1fa2540724bfbac14d7976d7e4a3860`), Cargo **1.95.0** (`f2d3ce0bd`), LLVM
**22.1.2**, native `aarch64-unknown-linux-gnu`, existing **thin LTO** release profile.
Both kernels: **7.0.0-30-generic**, Ubuntu build `#30`, aarch64. No custom Rust/Cargo
flags or user Cargo configuration were present. Exact commands/environment/toolchain
and bundle hash are retained in the separate private build evidence directory.
The dependency/source comparison against `cc86869` contains only `behavior.rs` and
a protocol diagnostic integration test that does not enter the release binary.

Game remained exact `f1cc5d645217ddc14a4069c3fe40992d496270ae`, executable
`/home/deploy/omega-udp-buffer-f1cc5d6/rust/target/release/omega-server`, SHA
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`.
Private configuration SHA
`642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183` requested
2,097,152 receive bytes; actual game receive/send stayed **4,194,304 / 524,288**,
bot buffers **212,992 / 212,992**. No game build or deployment occurred.

Strategy 150, seed 30, difficulty 1, Warrior/Rogue/Mage rotation, 30 Hz requested
input/Tick/Snapshot, 100 ms stagger, original AoI/LOD/budgets and strict assertions
were preserved. World randomness remains entropy-seeded; identical World trajectories
are not asserted. Original/control artifacts were preserved independently, including
control bot SHA `831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`.

## Window and runtime proof

Workload: **15:24:23.838084–15:30:41.096155 UTC**, about **377.258 s**.
Actual Phase 2: **15:24:40.962688 UTC**, after a **17.124604 s** ramp.
Measurement: **15:25:40.962688–15:30:40.962688 UTC**, exactly **300 s** after
60 s global warmup. Exact nanoseconds are in the summary. Natural exit code **2**
reflects strict assertion failure; no controller abort, runtime error or rerun.

Schedules were atomically published with **53.270481 s** lead and no dummy window.
Fresh game PID **594312**, invocation `fae919a37a3240a1841d5d93dffe13ef`, executable
hash and socket ownership/buffers matched immediately before traffic and all **125**
polls. Bot PID **632158**, start ticks **70622595**, candidate path/hash matched all
**124** polls while present; the final poll followed natural exit. No missing live
identity or restart. Candidate/control path/hash rejection tests and the actual
remote validation mode ran before the swarm. No old control bot was launched.

## Offered load, population and delivery

- **Generator gates pass.** Every one of 150 identities exceeds 29.7 Hz for both
  offered and exact wire input. Offered total **1,349,938** across a measured bot
  boundary span of **299.999575149 s**; exact 300-second wire totals **1,347,875 game /
  1,347,876 bots**. The one-command endpoint difference is retained. Missed schedules
  were **53**, both full-workload and steady, versus **397,350 steady** previously.
- **Wire coverage is complete.** Both mappings contain the same 150 unique identities.
  Across **44,850 active bot-seconds** (150 × 299 complete UTC seconds), input counts
  range **23–31**, median **30**, with **zero zero-input bot-seconds**. Exact partial
  seconds enter the scored rates; complete seconds describe trajectories.
- **Ramp observations are qualified.** First/last Running observations give rates
  **29.834028–30.834389 Hz** for 142 bots over their differing staggered intervals.
  Bots **143–150** lack two Running samples before Phase 2, so their ramp rates are
  unknown. The 1,102 bracketed active ramp bot-seconds have median 30 inputs, range
  23–31, and no zero-input seconds. Unjoined identities are not zero-filled.
- **Population passes:** all 150 authenticated throughout **9,000 Ticks**. Living
  population **101–144**, median 120; projectiles 153–259, monsters 0–1, effects 0.
- **Delivery passes for every peer:** Snapshot and ActionConfirm counts increase;
  no missing measured delivery observations. Aggregate Snapshot-age p99/max
  **43.435 / 61.554 ms**; ActionConfirm-age p99/max **56.747 / 84.054 ms**. Every
  peer passes its own 250/500 ms p99 and observed-one-second guards. Prior unprofiled
  confirm-age maximum was **1,716.931 ms**, with peers 97 and 129 failing. These are
  sampled message ages, not one-way latency or exact queue residence.

Generator process CPU was **78.302151% of one logical CPU** over the strict inner
**299.046702 s** bracket, versus the prior reported **97.71%**, while offered load rose
from **18.34025 Hz** to essentially 30 Hz. The outer bot CPU bracket is **null**,
because its ending sample follows process exit; it is not replaced with another
interval. Steal was zero. The retained trajectory rises from roughly 62–68% early
warmup to roughly 78–80% later, while wire medians remain 30 inputs/s. Adjacent
observation rates and grouped medians are descriptive; the exact counters score gates.

This supports the predicted generator-pressure improvement from the dodge-search
change. Actual owner occupancy, tie frequency, hit-report scan cost and serial
poll-cycle duration remain unmeasured. One entropy-varying observation does not
establish a general capacity multiplier or eliminate all generator costs.

## Game gates, errors and correctness

Actual Tick rate **30.0 Hz**, work p99 **29.667207 ms**, maximum **46.426357 ms**;
**35 Ticks** reached/exceeded 33.333 ms. Ending elapsed-Tick lag **0.103892 ms**;
ending accumulator lag **1.038835 ms**. These gates pass. Deferred-wait first/last
30-second means **6.250 / 6.236667 Ticks**, maximum 10; pending replication means
**4,878.54 / 4,554.182**, maximum 8,092. The unchanged campaign backlog rule passes.
Game CPU was **71.038213%** over the strict inner **299.064391 s** bracket (outer
bracket 70.941581%); prior reported game CPU was 70.38%. Steal was zero.

**UDP-error gate fails:** game `SndbufErrors` **2,295 full workload / 2,290 steady**,
versus **637 / 637** previously. Both hosts have zero receive-buffer, checksum,
memory and input errors; bot send-buffer errors and observed socket drops are zero.
The game adapter independently counted **2,295 zero-byte sends total** and **2,290**
across the inner transport bracket, while reported send errors remain zero. Transport
fields are null on exact boundary records; the inner bracket is explicitly
**15:25:41.924783–15:30:40.558504 UTC**, not silently relabelled exact-window telemetry.
Matching totals support game-send attribution, without kernel send tracing.

First send-buffer-error bracket: workload **+75.461411 to +76.461524 s**, delta **5**,
just before measurement. No first receive-error event exists because observed deltas
are zero. Maximum sampled receive memory was **708,320 bytes game full workload**
(**674,624 steady**) and **10,864 bytes bots**. Socket ownership was available in all
retained rows; the analyzer still preserves null ownership when missing. Interface
and qdisc drop/overlimit deltas are zero. Cumulative maximum game read gap was
**53.631855 ms**, compared with 41.601 ms previously. Neither these samples nor
interface captures measure application input delivery or queue residence.

Across **299 complete UTC measurement seconds**, game-side reliable retry-command
bytes total **23,875,200**, versus **109,484,645** previously; incoming ACK commands
**30,740,384**, versus 36,811,073. Peak incoming datagrams/ACK commands per retained
10 ms bin were **323 / 8,931**. Bounded v2 retry-history semantics are unchanged;
these are repeated-command observations, not exact outstanding reliable queues.
Captured input precedes socket/application delivery. Endpoint count agreement is
not an application-delivery guarantee.

**Strict `aoi_cull` fails:** **131/150** bots within 1,150 units, below 95% required.
Violating IDs: **54, 58, 92, 95, 96, 100, 101, 104, 110, 112, 123, 128, 130, 131,
138, 142, 143, 145, 148**. `decode_clean` passes. `per_peer_budget` remains skipped
under the original zero rate-budget command. There are **6 baseline-reference misses
and 8 unknown delta-entity observations**, both full-workload and steady; exact peer
IDs **91 and 123** are affected; detailed counts remain in the private rows. Bot/game decode errors, reported
application send errors, panics and unexpected bot disconnects are zero.

The byte-aware journal fully scanned **429,798 records**. Oversized-unreliable
warnings: **429,342 full workload / 349,181 steady**; no panic or suppression notices.
The retained raw prefix is **25,165,518 bytes**, below 24 MiB; it is incomplete,
while compact counts cover the full bounded experiment. Full payload-size extrema
remain unknown. The journal's single `send` substring hit is the startup buffer
message, not a send failure; 150 disconnect records belong to normal end-of-run
shutdown. These correctness findings remain relevant to issue 39 even though
cadence and delivery improved.

## Collectors, restoration and evidence

Collector source stayed **994cce8c7cb2f689cd59f4d09e93e270057aba7e**; only its standalone
recorder was compiled, identically on both hosts, SHA
`d49fcf7ef4995150e47789f564f8147cbf1491d1615e9abc5d6e44ca2fb27300`.
All five frozen collector source files, the capture wrapper and atomic helper are
byte-identical to the unprofiled comparator; the recorder is a fresh namespace build,
not a claim of an unchanged collector executable hash. Existing 600-second wrapper,
180/550/600/720-second ramp/workload/capture/restoration bounds, 48 MiB capture,
64 MiB files and 512 MiB capture cgroups remained. Both readers ended at EOF with
**7,767,340 game / 7,767,341 bot packets**, zero parse errors and zero capture drops.
All boundaries/maps/coverage pass. Bot boundary lateness start/end was
**3.774029 / 3.349178 ms**; game **1.478722 / 1.613539 ms**.

Capture child CPU **19.366064 / 30.123291 s**, max RSS **38,944 / 39,004 KiB**
(game/bots); retained sizes about **5.46 MB** each. Host collector self/child CPU
**1.098%/2.882% game**, **1.298%/2.713% bots** of one core. Bot observation work
**1.438760 s** over 377 completed observations is elapsed instrumentation work,
not causal overhead. No profiler or full pcap was retained. Fourteen local
controller/publication/analysis checks passed. An independent local recomputation
confirms offered/wire extrema, counts and Tick p99; its initial attempt to read
null boundary transport was corrected to retain unknown exact-boundary transport.
No remote recovery or additional workload was used.

Restoration was armed before the original service stopped. Original measurement
files were preserved and hash-verified before restart. Cleanup verified bot exit,
kept the five-second quiet tail, stopped game then captures, restored the original
service, and canceled the restoration timer. Independent read-only verification
checks original executable/config/drop-ins/measurement destination, ordinary
**524,288/524,288** game buffers, zero players, no owned bots/collectors/timers or
profilers, unchanged network/maintenance, all prior archives and closed campaign
state. The separate prebuild audit also checks all **9 game-host / 4 bot-host**
old executable artifacts. Candidate builds and all remote originals are retained. A final post-analysis remote
state/archive audit also passes; exact audit times and hashes are in the summary.

Original game SHA `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`;
original bot SHA `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`;
original configuration SHA
`bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`.

Private run evidence: `deployment/hetzner/results/udp-dodge150-20261021/`.
Build evidence: `deployment/hetzner/results/udp-dodge150-20261021-build/`.
Remote originals: `/home/deploy/omega-results/udp-dodge150-20261021/` on both hosts.
Primary archives independently match retained remote checksums:

```text
game.tar.gz  61cff08ea4326953ce6cd2b34fd28dc262839ea68c64f0c594415bfbc301a885
bots.tar.gz  aab2bf27aa69f6921e0270407fcedd81745d69d1c936c510ad45912690441211
```

The candidate resolves the previously observed generator underload in this cell,
but exposes a still-failing game send-error condition at the required load.
Remaining questions for the parent are the source of game send backpressure,
AoI/baseline correctness, and whether the behavior holds in future independently
owned observations. No follow-up experiment was launched here.
