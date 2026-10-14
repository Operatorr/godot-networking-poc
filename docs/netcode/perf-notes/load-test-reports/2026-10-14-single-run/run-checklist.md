# CAX11 run checklist and execution estimate

Status: corrected single-run pilot passed operational checks. Full matrix restart is held
for the user's review of this checklist and estimate. This checklist does not authorize execution.

The canonical [agreed matrix](https://github.com/Operatorr/godot-networking-poc/issues/30#issuecomment-6145030523)
remains the specification. Correctness fixes establish a new, separately identified
baseline. Earlier original/measurement builds and failed runs remain evidence; never
merge their repeats into a stable rung for the corrected revision.

## Before the full rundown

- [x] One 50-bot clustered pilot: all joins/stays, valid per-bot offered input, clean
  captures, no kernel/socket/codec errors throughout warmup and measurement, 30 Hz
  Tick cadence, p99 7.951 ms, no growing lag/backlog, valid entity recovery.
  [Validation](single-run-validation.json); game b1266c1, unchanged bot 642c147.
  Actual end-to-end controller time 637.81 s (10 min 38 s); peak local RSS 580.65 MB.
- [x] Independent provider graph comparison: same-zone traffic appears around
  1.1 MBps (roughly 1.0–1.2). Archive screenshot, comparison window and guest IP/interface counters.
- [ ] Pin game/bot commits, binary hashes, toolchain/config/collector versions and
  original-build preservation. Keep the corrected revision unchanged for scored runs.
  Use a fresh corrected-campaign namespace/state; the existing controller defaults to
  measurement revision 642c147 and reuses earlier cells, so it must be configured explicitly.
  Diagnostic pilots do not substitute for corrected-build three-repeat core cells.
- [ ] Report the known sent-versus-ACKed Baseline behavior under delay/loss using
  reference-miss and recovery counters. The map already defers this doc-versus-code drift;
  do not silently change protocol ordering or hide it inside capacity classification.
- [ ] Repeat collection on/off controls on the corrected revision, alternating order
  across three pairs. Report exporter matched mean/CPU and observer time with world/shared
  CPU variability. Validate selective impairment at small load and cleanup afterward.
- [ ] Verify bounded ramp/controller lifetimes, fail-fast reporting, unique run IDs,
  interrupted-run recovery and archive-error preservation. No automatic replacement of
  valid failing workloads. Collector-invalid replacements require retained originals.
- [ ] Reserve evidence storage before committing to the campaign. Mac currently has
  about 53 GiB free; game host about 27 GiB. A 50-bot clustered pair is about 345 MB
  archived, and larger-population captures are unmeasured. The 8 GiB emergency guard
  prevents another start but is not a full-campaign storage plan. Never delete the only
  raw copy; verify off-host checksums before removing remote duplicates.
- [ ] Review this concrete checklist and estimate with the user before lifting the hold.

## Scored cells

Every cell restarts the isolated game service, ramps with 100 ms stagger, excludes
60 seconds of global warmup and measures 300 seconds. Three repeats per cell/group;
reverse workload/profile/variant order in repeat 2. Every failure and invalid collection
is retained. Classifications separate generator, collector, server and delivery.

| Phase | Checklist | Maximum five-minute runs |
| --- | --- | ---: |
| Core | movement, combat, clustered, strategy at 50, 100, 250, 500, 750, 999; three repeats each rung | 72 |
| Boundary | Each failed workload: bisect last stable/first failed to <=25 players; three repeats at each new probe; both final sides already repeated | 60 |
| Idle | 100 and highest stable population, deduplicated; three repeats each | 6 |
| Network | combat and strategy at 100 (only if native stable) and own highest stable, deduplicated; nine profiles plus native before/after, three repeats | 132 |
| Transfer | combat, clustered, strategy at 100 and highest common stable, deduplicated; native-before, Snapshot15, AoI600/660, native-after; three repeats | 72 |
| External | 3–10 genuinely external clients, representative workload, no artificial impairment; matched game-port and interface counters, delayed provider reading | 1 |
| Admission | Only if movement 999 passes all repeats: 999 established plus one extra join; separate short rejection check | unscored |

Core checklist (each box includes repeats 1/2/3):

| Workload | 50 | 100 | 250 | 500 | 750 | 999 |
| --- | --- | --- | --- | --- | --- | --- |
| movement | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| combat | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| clustered | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| strategy | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

Stop each workload ladder after completing all three repeats at its first failed rung.
Generator saturation does not establish a server ceiling. Boundary populations are
chosen from those results; the existing 25-player rounding algorithm can require five
probes in the 750–999 interval (not four), so 60 is the conservative boundary allowance.
Idle and transfer retain the agreed 100-player observations even when native stability
at 100 is not established; failed controls cannot support valid savings claims.

Network profile checklist (each box covers eligible combat/strategy populations and
three repeats, with native-control brackets per group):

- [ ] 25 ms delay each direction (+50 ms RTT)
- [ ] 50 ms delay each direction (+100 ms RTT)
- [ ] 100 ms delay each direction (+200 ms RTT)
- [ ] 50 ms delay +/-5 ms normal jitter each direction
- [ ] 50 ms delay +/-20 ms normal jitter each direction
- [ ] 0.1% independent loss each direction
- [ ] 1% independent loss each direction
- [ ] 3% independent loss each direction
- [ ] 50 ms delay +/-20 ms normal jitter and 1% loss each direction

Transfer comparison checklist (each box covers combat/clustered/strategy, both required
populations and three repeats):

- [ ] Native Snapshot30, AoI1000/1100 control before
- [ ] Snapshot15 alone; Tick/input30, original AoI
- [ ] AoI600/660 alone; Snapshot30, LOD near400/mid600
- [ ] Native control after, with reversed variant order in repeat 2

## Time estimate

If all ladders reach 999 and pass, no boundary refinement is needed: 283 scored runs.
A conservative fully populated ceiling including boundary probes is 343 runs. These are
conditional maxima; early failures and deduplicated populations shorten the actual list.

| Component | 283-run case | 343-run ceiling |
| --- | ---: | ---: |
| Five-minute scored windows alone | 23 h 35 min | 28 h 35 min |
| Windows plus one-minute warmup, before ramps/setup/evidence | 28 h 18 min | 34 h 18 min |
| At the observed 50-bot pilot throughput (676.45 s/run) | 53 h 11 min | 64 h 27 min |

The last row includes setup, ramp, archiving, checksummed downloads and analysis at the
measured 50-bot workload. Higher populations add ramp time and can produce much larger
captures; it is not a measured upper bound. Use roughly 3–4 days as a provisional planning
reservation when many high rungs pass, then revise after the 100/250-player stages. Do not
promise a five-hour complete rundown. Preflight/build/debug time and interruptions are
additional. With early failures the campaign can be considerably shorter.

A first 50/100 core checkpoint contains up to 24 scored runs: about 4.5 hours at the
observed 50-player end-to-end throughput, plus corrected-build preflight and larger
100-player ramp/evidence costs. Reserve roughly 5–6 hours provisionally, stop each
failed ladder as agreed, and recalculate before going further.

Use explicit stage checkpoints: corrected preflight; complete 50-player core; 100-player
core; remaining ladders/boundaries/idle; network; transfer; external/admission; audit/report.
Recompute remaining count, disk headroom and time from completed cells at each checkpoint.
A saturated generator/collector stops the dependent phase for diagnosis. Keep offered
load explicit and do not report a server capacity result from invalid observations.

## Final evidence and economic report

- [ ] Exact source-window counters, authenticated/alive player-seconds, app/IP/interface
  bytes, retransmissions, suppressed sends, delivery gaps/loss and generator validity.
- [ ] Failed/invalid runs and corrections separated by revision; all repeats and spread.
- [ ] Lead summary with outbound bytes/s, bytes/player-second, conditional monthly/yearly
  transfer and costs; measured 100 only, valid 999 scaled 1000/999 only. Otherwise label
  unmeasured 1000-CCU sensitivity; never extrapolate 50-player fan-out as demonstrated.
- [ ] Decimal/TiB allowance/rate sensitivity, actual calendar month lengths for 2027,
  renewed monthly allowance and separate test-bot compute. Account invoice units remain
  conditional until confirmed; provider network graph independently validates traffic.
- [ ] Verify required matrix coverage and all raw archive checksums before resolving
  [Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31).
  Historical reports stay deferred; CCX13 stays behind CAX11 stabilization/readiness.
