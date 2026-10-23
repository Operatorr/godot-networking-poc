# Ordinary Movement100 — round 1

**One workload; clean-cell-pass; 36/36 original gates pass.** Failed gates: none. [Machine summary](clean-movement100-r1-20261023-summary.json) retains all predicates and exact per-peer/full/steady evidence. This is independent of failed Idle150, whose classification remains unchanged. No retry, second cell, capacity advance, issue/map/plan/parent-ledger edit, PR or push. Campaign candidate `fea24dd1ec75eb3a5e832e408489943ced88814f` remains the parent's decision.

Runtime source **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**; controller/helper commit **5e27c55b1694e2da818dea9df1b9a68ce286b84a**; executed controller SHA-256 **e029a9b78a98866502b6577aefb982c4f098606e7e79615d31b47c8c0977bb13**. All 116 frozen helper identities match. Repaired collector source is frozen at `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; atomic publisher matches `d2dfe73`.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Both hosts use fresh Rust-only cone checkouts, selected before checkout, with every materialized blob and Cargo file verified and clean source pinned. Both executables are real one-link ELF64/AArch64 copies with checked dependencies and hashes. **No game or bot package was compiled**: both locked packages originated natively on bots in R3; subsequent game copies are verified reuse. **Authorized standalone capture reader:** the frozen reader was compiled once on each host by the existing staging step, from repaired collector `994cce8`. Its two exact commands, output hashes, source identities and shared 16 MiB staging allowance are retained in the summary. Game and bot packages were not rebuilt.

Condition: Movement100, requested 30 Hz inputs, 100 ms stagger, seed 30, difficulty 1, global 60 s warmup then exact 300 s measure; primary-fire counts are zero. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game Rx/Tx requested 2 MiB/effective 4 MiB; bot native 212,992 B; native unimpaired network. No Rust/game/protocol/sim/input cadence, scheduling, flush, throttle, channel, reliability or budget change.

Actual `/proc/PID/environ` proofs on both hosts confirm **OMEGA_NATIVE_DIAG entirely absent**, AoI audit absent and ordinary OMEGA_MEASURE_DIR enabled. 64 identified bot polls, 373 bot recorder rows / 36718 peer rows and 467 server rows, final report and isolated archives have no native diagnostic fields or traces. Private native counters are **absent/unobserved, not zero**; no native analyzer ran. Ordinary recorder completed sections total **1.162519169 s**, excluding the last sample's own work; this is not total causal overhead. Matched-boundary host execution is **23.552% game / 27.723% bots** of two-core capacity; game process **27.674%** of one core. Bot process/swarm matched-boundary CPU is unavailable after natural teardown, not zero. The separate **299.047898429 s** inner bracket reports **39.382%/39.556%** of one core. Queue residence, outstanding reliable queue and causal slowdown remain unknown.

Offered **29.999863137624–29.999863137624 Hz**, 0/100 failing >=29.7. Mapped game wire **29.990000000000–30.000000000000 Hz**, 0/100 failing; bot wire **29.990000000000–30.000000000000 Hz**, 0/100 failing. Offered denominator is **300.001368630 monotonic seconds**; both wire denominators are exact 300 s UTC. Steady missed schedules **0**. Specified ENet shedding does not relabel any failed wire predicate. Application input delivery and shedding magnitude remain unknown.

Full/steady bot Baseline-reference, unknown-entity, decode/send/panic counts, server decode/send, transport, oversized/panic/suppression, UDP/socket and parser/drop counts are retained exactly in JSON. Full bot counts **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**; steady **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**. Received AoI covers all received Snapshots before stale application discard: **61,180,349 matched / 0 unknown**, **0** actual >1150-unit peer violations, **0** empty-evidence peers; final Snapshot counts reconcile through drained. Full/steady stale counts are **{'full': 0, 'steady': 0}**. Full capture parsers retain **3234817/3234816 packets**, with zero parse errors or kernel capture drops. Capture differences are not application-delivery counts. All original errors remain explicit.

Steady Tick **9000 /300 s = 30.0 Hz**; work p99/max **9.53649/15.34049 ms**, **0** over 33.333 ms. Snapshot age p99/max **32.616396/34.190890 ms**; ActionConfirm **45.205303/66.508484 ms**. Deferred wait maximum **0 Ticks**; first/last 30 s pending means **[0, 0.012222222222222223]**. All full/steady delivery, Tick work/cadence, backlog, read gaps, socket memory, CPU/observer and capture counters remain in JSON. Journal: **306 records / 500626 B**, complete scan **True**, raw retention **True**. The unobserved-steady journal correction is retained.

Legacy predicates remain separate: bandwidth **13.58 KiB/s**, strict <5 pass **False**; raw Tick estimate **30.00001395387664 Hz**, >=30 pass **True**. Exact arithmetic **1096470 ×1000 / 36548983**, **1 ms** clock resolution. Rounding does not alter either result. The generic bot process exits 1 when a legacy criterion fails; the watchdog has no failure reason.

Full additive budget before source/binary staging: **8801742848 free − 160938290 allowance**, **50869966 B** above unchanged 8 GiB reserve. Before workload staging: **8782295040 − 144424960**, **47935488 B** above reserve. Resource-only abort caps: 16 MiB live game, 24 MiB journal, 42 MiB role-only archive, 32 MiB margin, plus exact source/bundle/object/real-binary/original-executable/config/manifest/directory costs. Other ordinary paths retain 1 GiB. Zero extra original-payload allowance is backed by realpath/same-device/device/inode/hash/uid/gid/mode proof. The stopped original measurement directory was hashed, atomically renamed with no copy fallback and verified before restart; current owner/group/mode was recreated. No cleanup, package changes, evidence/journal/source/binary removal, resize, purchase or reserve reduction.

Publication lead **39.131315545 s**; fresh queries of both hosts followed publication. Original end is the steady endpoint; drained closes full counters separately and is excluded from measurement clocks. Natural terminal guard observed; missing-guard grace exercised remotely **False**, with no claim beyond actual evidence.

Automatic restoration passed. Two fresh independent audits **115/115 bounded 90 s commands** passed, covering all prior binaries/archives/closed states, candidates/sparse blobs, old backup inodes/hash manifests/markers/frozen recovery, new rename/current paths/ownership, ordinary 524,288 B buffers, maintenance/network/firewall, zero players/quiet queues and no owned/competing workloads. Final free storage **8752738304 B game / 18033442816 B bots**. **Both hosts released.** Fresh census verifies **7855 historical files unchanged**; parent plan/ledger/proposal changes are the explicit new baseline. Remote/local archive SHA and every extracted member are checked in fresh real directories without symlinks/hardlinks.

```text
game.tar.gz cf7c20fd456fdb3c850ddd13392dbfd56c1f012c9151c1b311671cf6c2abafb2
bots.tar.gz 7f09902295f9b75e77836f889ae39d44648f43bce9dda42a88e9d2930de94c07
```

**88 applicable Python checks and 21 independent archive analysis checks pass**, including failing-before/passing-after Movement100 profile dispatch. Rust unchanged: retained parent 240 pass/3 ignored, Clippy two old warnings, fmt/extension green; no expensive repeat. Historical R5's 423 ambiguous retirements, sampled fingerprints and unproved historical cause/application delivery remain qualified. This independent observation does not upgrade Idle150 or certify the campaign. Stop after this attempt.

| Original gate | Strict result |
|---|---|
| all_requested_authenticated | PASS |
| application_errors_zero | PASS |
| autonomous_recovery_succeeded | PASS |
| bot_buffers_unchanged | PASS |
| bots_all_observed_udp_and_socket_errors_zero | PASS |
| bots_full_workload_udp_errors_zero | PASS |
| bots_udp_errors_zero | PASS |
| candidate_bot_runtime_identity | PASS |
| candidate_game_runtime_and_buffers | PASS |
| collectors_clean | PASS |
| complete_300s_common_coverage | PASS |
| delivery | PASS |
| ending_lag | PASS |
| full_replication_counters_cover_final_snapshot | PASS |
| full_transport_errors_zero | PASS |
| full_workload_oversized_panics_suppression_zero | PASS |
| full_workload_replication_and_bot_errors_zero | PASS |
| game_all_observed_udp_and_socket_errors_zero | PASS |
| game_full_workload_udp_errors_zero | PASS |
| game_udp_errors_zero | PASS |
| identity_mapping | PASS |
| independent_final_cleanup_verified | PASS |
| journal_error_counts_complete | PASS |
| mapped_wire_29_7hz | PASS |
| per_identity_offered_29_7hz | PASS |
| received_aoi_all_peers_zero_unknown | PASS |
| received_aoi_default95_policy | PASS |
| received_aoi_no_actual_above1150 | PASS |
| replication_backlog | PASS |
| runtime_identity | PASS |
| server_full_and_steady_errors_zero | PASS |
| steady_window_oversized_panics_suppression_zero | PASS |
| steady_window_replication_and_bot_errors_zero | PASS |
| strict_enabled_assertions | PASS |
| tick_hz | PASS |
| tick_work_p99 | PASS |
