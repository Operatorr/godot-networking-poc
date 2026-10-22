# One matched Strategy 150 AoI diagnostic

**Outcome: generator-invalid; no valid-load performance reproduction or capacity advance.** Exactly one workload ran in `aoi150-20261022`, with the unchanged send150 config, seed 30, original mix/AoI/LOD/budgets, 30 Hz offered inputs, 100 ms joins, 60-second warmup and full 300-second measurement. Both game buffers were requested at 2 MiB/effective 4 MiB; bot buffers remained native. Diagnostic game/bot builds and AoI collection change overhead, so this is not a pure performance comparison.

Bots **49 and 61** achieved **29.66 and 29.626667 Hz** mapped input on **both** wire captures, below the unchanged 29.7 Hz gate. All offered-input rates passed (minimum 29.996301 Hz). All other capacity gates passed except strict AoI: 150 authenticated throughout; 9,000 Ticks/30 Hz; Tick work p99 30.091373 ms; ending lag, backlog, delivery, UDP, application errors and capture coverage passed. Worst per-peer Snapshot/ActionConfirm age p99 was 54.13/71.89 ms; observed maxima were 63.87/108.47 ms. No second workload or retune was attempted.

**Authoritative emission evidence passed its separate diagnostic check.** All **1,660,210** audit rows reconciled exactly to **9,723 baselines + 1,650,487 deltas**, including every one of 404 cumulative samples against exact Tick UTC timestamps. Final unsampled tail was zero for both types; final population was zero. There were no duplicate keys, missing Tick mappings, full-state requests or exhausted row guard. Maximum wire-position distance was **1100.1205**, with **zero above 1150**. The steady window contained 1,350,000 Snapshots and 166,176,114 remote positional records; lifetime totals were 211,999,863 records and 202,467,700 remote positional records. There is no independent successful-send **record-count** metric; Snapshot-count coverage is reconciled separately. Emission does not prove delivery.

**All 225 retained legacy anomalies** had unique `(observer_id, snapshot_tick, server_ms)` authoritative matches and were mixed-time false positives: **217 during ramp/warmup, 8 steady, none after the window**. The largest legacy distance, **1947.792969**, was **816.216980** against its authoritative center. Attribution uses f32 arithmetic and validates baseline and maximum-distance witnesses. This is the bounded first-16/latest-maximum sample, not a census of legacy anomaly events or a retrospective proof about historical runs.

**Standalone strict AoI remains failed/unknown.** Delivered bot evidence contained 171,890,687 matched and **29,723,783 unknown** positional observations; all 150 bots had unknowns. No matched-distance violators were reported (rounded maximum 1100.1), but omitted same-Snapshot observer positions prevent a pass. `decode_clean` passed; `per_peer_budget` remained skipped as originally configured. Bot exit status was 2, with no watchdog/controller abort. Baseline-reference misses, unknown entities, decode/send failures and panics were zero in both lifetime and steady evidence. Oversized warnings remain findings: **402,565 lifetime; 322,978 steady**. Journal counts cover the complete scan; raw retention was capped at 24 MiB and is incomplete.

Exact application input delivery, receive/send queue residence and causal instrumentation slowdown remain **null/unknown**. No historical result is upgraded.

| Identity | Exact value |
|---|---|
| Candidate revision | `4c33a3e0bdccad352f82bbe00cdabf8e907a84d8` |
| Game SHA-256, identical on both hosts | `cabbaaad37d959150654db870012ea455e995fb049cfbe6a9ff6e88bb0ce8ce2` |
| Bot SHA-256, identical on both hosts | `67b9f18e2c5709413b9cf8a90615fe82a37d2b748ab2d1eb1b1327ef313afbd9` |
| Unchanged config SHA-256 | `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370` |
| Frozen wire collector revision | `994cce8c7cb2f689cd59f4d09e93e270057aba7e` |

Both packages were rebuilt in new clean checkouts with Rust 1.95.0, native `aarch64-unknown-linux-gnu`, locked dependencies and no custom Rust/Cargo build environment. Source bundle/tree, compiler, build commands and binary hashes are archived. Controller adaptation passed 21 checks before launch; the expanded analysis suite passed 25 checks.

Independent read-only cleanup audits passed on both hosts: original binaries/config/service/measurement destination, maintenance and network settings restored; old artifacts/evidence preserved; audit environment removed; zero players and no owned active processes/units. Remote/local game and bot archive SHA-256 values match. Public evidence: [capacity gates and provenance](aoi150-summary.json), [AoI correlation and evidence hashes](aoi150-correlation.json), [controller adaptation](CONTROLLER.md). Detailed per-peer cadence, all 225 attributions and bounded raw artifacts remain in the ignored evidence directory identified by those JSON files.
