# CAX11 run checklist — one run per test

Amended by the user on 2026-10-14: **one five-minute run per test**, replacing the three-repeat
requirement. The [canonical matrix](https://github.com/Operatorr/godot-networking-poc/issues/30#issuecomment-6145030523)
and controller/coverage checker now use one pass. Earlier runs and their source revisions
remain historical evidence. The full campaign has not restarted.

## Workloads and population ladder

| Workload | What bots do | What it exercises |
| --- | --- | --- |
| movement | Move without primary fire | Movement/input and state replication |
| combat | Move and continuously attempt primary fire | Combat, projectiles and event traffic |
| clustered | Converge near the centre and shoot probabilistically | Dense groups and replication fan-out |
| strategy | Target, dodge, sprint/dash and use Class abilities | More complete client behavior and ability/event traffic |

The agreed core ladder is **50 → 100 → 150 → 200 → 250 → 500 → 750 → 999**.
Run all four workloads at 50/100/150, and **Strategy only at 200 and above**.
That is **17 core cases: 12 at the lower populations + 5 Strategy cases above 150**,
for **85 measured minutes + 17 minutes of global warmup**, before ramp/setup/evidence.
A movement/combat/clustered stop at 150 is a planned limit, not a measured capacity ceiling.
Failure boundaries are refined only when a tested case actually fails. The executable
ceiling remains 999; 1000 is a financial extrapolation from a valid Strategy 999 observation.

The first 50/100 checkpoint has **8 cases: 4 workloads × 2 populations**, with one run each.
That is **40 minutes of measurement + 8 minutes of global warmup**, before ramps, setup
and evidence processing. The existing matching corrected 50-bot clustered pilot is a
candidate for explicit reuse; preserve its diagnostic provenance and verify the binding
before scheduling that same condition again.

| Workload | 50 | 100 | 150 | 200 | 250 | 500 | 750 | 999 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| movement | [ ] | [ ] | [ ] | — | — | — | — | — |
| combat | [ ] | [ ] | [ ] | — | — | — | — | — |
| clustered | matching pilot available | [ ] | [ ] | — | — | — | — | — |
| strategy | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

## Measurement gates

- [x] Corrected 50-bot clustered pilot: all joins/stays, valid generation/collection,
  zero kernel/codec/entity-reference errors including warmup, 30 Ticks/s and Tick-work
  p99 7.951 ms. [Validation](single-run-validation.json). Game b1266c1, bot 642c147.
- [x] Independent provider graph comparison: about 1.1 MBps at the requested window,
  consistent with the guest traffic observation. [Comparison](provider-network-comparison.json).
- [x] Fail-fast controller with both endpoint archives preserved: eight Python tests and
  the completed pilot's read-only status probe pass. [Validation](controller-failure-validation.json).
- [ ] Pin game/bot commits, binary/config/toolchain/collector hashes and use a fresh
  corrected-campaign namespace/state. The generic runner defaults to the older measured
  game revision; configure it explicitly. Preserve all original builds and raw failures.
- [ ] Measure collection on/off once each on the corrected revision; report matched
  mean Tick work, CPU and observer time, with world/shared-host variability. These are
  different instrumentation conditions, not three repeated pairs. Validate selective
  impairment and cleanup at small load before the robustness phase.
- [ ] Record the known sent-versus-ACKed Baseline behavior under impairment using
  reference-miss and recovery counters; the map defers its doc/code drift.
- [ ] Check evidence storage at each checkpoint. The last 50-bot pair used about 343 MB
  archived. Larger populations are unmeasured; the 8 GiB guard is an emergency stop,
  not a campaign storage estimate. Verify off-host checksums before removing duplicates.

Every scored case restarts the isolated no-API game service, ramps at 100 ms stagger,
excludes 60 seconds of global warmup and measures 300 seconds. Stop a workload's core
ladder after its first failed observation; classify generator/collector faults separately
from server limits. Preserve failed and invalid evidence. Do not rerun passing cells for
statistical repetition. A changed build or invalid-collection repair is separately identified.

## Remaining phases

| Phase | Conditions, one run each | Maximum five-minute windows |
| --- | --- | ---: |
| Core | Four workloads at 50/100/150; Strategy alone at 200/250/500/750/999; truncate tested ladders at failure | 17 |
| Boundary | Bisect each actually failed workload to <=25 players; at most one new probe for each lower-only workload and five for Strategy | 8 |
| Idle | 100 and highest passing tested population capped at 150, deduplicated | 2 |
| Network | combat/strategy × 100 and own highest stable (deduplicate/omit unstable 100) × nine profiles, with one before/after native control per group | 44 |
| Transfer | combat/clustered/strategy × 100 and highest common stable × Snapshot15 and AoI600/660, with one before/after native control per group | 24 |
| External | 3–10 genuinely external clients; game-flow/interface accounting and delayed provider reading | 1 |
| Admission | Only if Strategy 999 passes: 999 established + one extra join, using Strategy; short separate check | unscored |

All 200+ conditions, including native controls and the admission check, use Strategy.
Combat network probes and multi-workload transfer comparisons therefore stay at 150 or below.
The existing native-before/native-after positions remain explicit control checks for
impairment/transfer groups. The former three repeated passes are removed from every phase.
Idle/transfer retain the specified 100-player observations even if their native controls
fail; those observations cannot establish valid savings claims.

Network profiles, each applied separately per direction:

- [ ] 25 ms delay
- [ ] 50 ms delay
- [ ] 100 ms delay
- [ ] 50 ms delay +/-5 ms normal jitter
- [ ] 50 ms delay +/-20 ms normal jitter
- [ ] 0.1% independent loss
- [ ] 1% independent loss
- [ ] 3% independent loss
- [ ] 50 ms delay +/-20 ms normal jitter plus 1% independent loss

Transfer comparisons change one setting at a time:

- [ ] Snapshot15, preserving Tick/input30 and original AoI
- [ ] AoI600/660 with LOD near400/mid600, preserving Snapshot30 and Tick/input30
- [ ] Retain the explicit native-before and native-after controls for comparison/cleanup

## Updated time estimate

The 50/100 core checkpoint contains **8 runs, not 24**. At the latest observed 50-player
controller time of 637.81 seconds, eight complete runs would take about **85 minutes**,
including setup, ramp, archiving, downloads and analysis. Add corrected-build preflight
and the still-unmeasured 100-player processing costs. This is an estimate, not extra
measurement duration; each scored window remains five minutes. Reusing the matching
corrected pilot would leave seven new scored cases and reduce the remaining time.

If all core ladders pass at 999, the complete amended matrix contains up to **88 scored
windows**, including its explicit control positions. With the conservative boundary
allowance, the ceiling is **96**. Early failures/deduplication reduce the actual count.

| Component | 88-window case | 96-window ceiling |
| --- | ---: | ---: |
| Measurement only | 7 h 20 min | 8 h |
| Measurement + one-minute warmup, before ramp/setup/evidence | 8 h 48 min | 9 h 36 min |
| At the latest observed 50-bot controller throughput | about 15 h 35 min | about 17 h |

Higher populations may take longer to ramp and generate larger evidence. Update the
estimate and storage budget after 50/100 before the larger ladder and comparison groups.
The old 24-run checkpoint and 283/343-window three-repeat estimates are superseded.

## Final report

- [ ] Keep source-window counters, authenticated/alive player-seconds, app/IP/interface
  bytes, retransmissions, suppressed sends, delivery/loss and generator validity.
- [ ] Separate source revisions and failures. Label each cell a single observation;
  do not claim measured repeat variability or three-repeat confirmation.
- [ ] Lead summaries with outbound bytes/s and bytes/player-second, then conditional
  monthly/yearly external-transfer costs. Use measured 100-player cells for 100 CCU;
  use a valid Strategy 999-player cell scaled 1000/999 for Strategy 1000 CCU. Higher-population
  costs for the other workloads remain [MEASURE] sensitivity because their tests stop at 150.
- [ ] Show decimal/TiB assumptions, calendar month lengths for 2027, monthly allowance
  renewal and the separate bot-host compute cost. Invoice precision remains conditional.
- [ ] Audit coverage and raw checksums before resolving
  [Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31).
  Historical retrieval and CCX13 remain deferred.
