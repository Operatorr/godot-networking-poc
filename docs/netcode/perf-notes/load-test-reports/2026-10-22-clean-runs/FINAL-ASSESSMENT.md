# Final bounded assessment — stopped incomplete

Remote testing stopped on 2026-10-24, before the 08:35 UTC reporting checkpoint. Both hosts are restored and released. No further automatic attempts are planned. [Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39) remains open: there is no clean campaign or new capacity certificate.

## Outcome and effort

The campaign produced **23 test attempts: 20 launched workloads and three storage blocks before launch**. A separate idle-preservation maintenance task launched zero workloads. These are campaign totals across October 22–24, not a rolling 24-hour count. At the earlier 06:34 UTC checkpoint, the exact preceding 24-hour count was 13 test attempts; see the [scorecard](PROGRESS-SCORECARD.md).

Ten launched workloads earned clean-cell-pass: **50.0% workload yield**, or **43.5% attempt yield**. Ten of the 12 distinct planned scenario/population cells have clean observations: **83.3% clean-cell coverage**. This is neither percentage of bugs fixed nor overall project completion. All 12 cells were attempted, but attempted coverage is not success.

Clean cells: Strategy150, Idle100, Movement50/100/150, Combat50/100, Clustered50, Strategy50/100. Their individual build identities and qualifications remain authoritative; the earliest two use the earlier bot build. The game executable is unchanged across these fixed-build observations.

Two cells remain non-clean:

- **Idle150:** ordinary R2 met offered cadence for every peer, but 113/150 peers failed the 29.7 Hz wire gate on both captures. The cause and application delivery remain unresolved. The approved offered-load-v2 policy separates generator validity from wire delivery without granting a pass or rewriting historical strict-v1 reports. [Evidence](clean-idle150-r2-20261023.md).
- **Strategy200:** the final one-attempt assessment was **aborted-collector-invalid**, with 10/36 predicates true and zero measured-window coverage. Population reached 200 and then fell to 81/80. Abort preceded measurement by 28.702 seconds. Receive-buffer errors occurred on both hosts: 135,913 game and 299 bots. This cannot isolate a clean server-capacity limit. Prefix correctness counters were zero, but final correctness, AoI, cadence and legacy results remain unknown. No new underlying game-code defect was proved. [Evidence](clean-strategy200-r1-20261024.md).

## What improved, and what did not

Real correctness defects were reproduced and fixed: encoded Delta size accounting, exact Baseline ACK gating, cross-channel stale Delta handling, authoritative observer position for received AoI, Baseline decoder-count compatibility, recovery AoI filtering, and the Tick estimator's clock pairing. The [bug ledger](BUG-LEDGER.md) records regression evidence and local-only edge coverage. Subsequent clean cells had zero recorded correctness errors under their tested conditions.

The campaign also repaired its own measurement and recovery machinery: readiness polling, terminal process-disappearance handling, status freshness after blocking operations, drained counter capture, and bounded live-prefix acquisition. Strategy100 R3 validates the prefix fix with original acquired hashes/lengths matching stopped backup bytes. These are concrete reliability gains, not evidence of faster game code.

We measured every run against absolute gates, but did **not** consistently publish matched before/after KPI deltas from the outset. Too much effort went into repeated harness/storage failures without an early stopping budget. That was a campaign-management failure. The final bounded policy corrected it; the final invalid overload result does not trigger another retry.

Matched single-observation changes, calculated as `(later - earlier) / earlier * 100`:

| Comparator | Tick work p99 | Received Snapshot age p95 | Reported bandwidth | Actual Tick rate |
|---|---:|---:|---:|---:|
| Combat100 R1 → R3 | +0.17% worse | +4.36% worse | −0.69% lower | 0%, both 30 Hz |
| Strategy100 R1 → R3 | −3.24% lower | −2.38% lower | +0.74% worse | 0%, both 30 Hz |

[Raw values and comparator qualifications](PROGRESS-SCORECARD.md). Identical runtime binaries and requested load make these useful descriptive comparisons, but single observations with differing controllers do not demonstrate causal performance improvement. **No defensible overall performance-improvement percentage has been established.** Zero-to-zero errors have no defined percentage reduction. Different behaviors/populations and aborted prefixes cannot be pooled into a speedup. Legacy bandwidth targets remain unmet; raw Tick-estimator pass/fail remains recorded independently without changing its threshold.

The tracked measures are per-peer offered and wire cadence, authenticated population, delivery/coverage, Tick rate and work duration, backlog, Snapshot age, bandwidth, replication/decode/send/panic/UDP errors, received AoI completeness and violations, terminal completion, restoration and preservation. These are measurable; passing measurements do not by themselves attribute a change to a fix.

## Evidence limits and historical claims

Original reports/classifications remain unchanged. Original buggy-build observations cannot certify fixed-build capacity. The old 32.9 Hz estimator was invalid; independent Tick timestamps are separate evidence. Mixed-time AoI and emission-only checks cannot substitute for received visibility. Historical misses/unknown entities were observed, but their precise historical packet causes remain unproved. High-entity decoder and manual-recovery edge fixes retain local-only validation where remote runs did not exercise them. Nothing here establishes the 500–1000-player target.

Preservation qualifications are retained: an early replay regenerated two historical private scratch analyses without before-hashes; an early parent verifier replay overwrote raw verifier outputs whose original bytes are unknown; Strategy100 R3's local census failed because parent documentation changed the campaign ledger concurrently, with all prior fields/classifications and the other 13,756 files unchanged. Primary run archives and committed reports remain the evidence of record. Final Strategy200 preserved all 14,340 historical local files, passed automatic restoration and both independent 157-command release audits. Its auxiliary full-window checker failed on absent steady-window data; that failure is retained, with separate aborted-prefix analysis rather than a fabricated complete result.

## Stop rule and smallest future decision

The specific bounded objective was to finish Strategy100 validation, permit at most one Strategy200 attempt, and report pass or incomplete by 2026-10-24 08:35 UTC. Strategy100 passed; Strategy200 did not yield a valid assessment. The attempt budget is exhausted and remote work is stopped. This satisfies the reporting stop rule, not the original campaign success requirements.

A separately reviewed next plan should first isolate the bot-host transport prerequisite for overload measurement and define how to distinguish server saturation from generator loss. It should also state a falsifiable explanation/test for Idle150's offered-to-wire deficit. No further full ladder or blind retry is justified. Any new experiment should name one hypothesis, a matched comparator, unchanged acceptance gates, expected KPI direction, and a fixed attempt/time budget before launch. No such experiment is launched or scheduled here.
