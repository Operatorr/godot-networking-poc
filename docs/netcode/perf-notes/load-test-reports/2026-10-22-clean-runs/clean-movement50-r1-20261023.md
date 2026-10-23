# Ordinary Movement50 — round 1

**One workload; clean-cell-pass; 36/36 original gates pass.** Failed gates: none. [Machine summary](clean-movement50-r1-20261023-summary.json) retains all predicates and exact per-peer/full/steady evidence. This is independent of failed Idle150, whose classification remains unchanged. No retry, second cell, capacity advance, issue/map/plan/parent-ledger edit, PR or push. Campaign candidate `fea24dd1ec75eb3a5e832e408489943ced88814f` remains the parent's decision.

Runtime source **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**; controller/helper commit **19655115fd38dda47bce2426503792ff3044dfb5**; executed controller SHA-256 **3b7b976c3f84dcf2422be5a0da6347840da63d782f49924e39d5329ad28a5edc**. All 115 frozen helper identities match. Repaired collector source is frozen at `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; atomic publisher matches `d2dfe73`.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Both hosts use fresh Rust-only cone checkouts, selected before checkout, with every materialized blob and Cargo file verified and clean source pinned. Both executables are real one-link ELF64/AArch64 copies with checked dependencies and hashes. **No game or bot package was compiled**: both locked packages originated natively on bots in R3; subsequent game copies are verified reuse. **Procedural deviation:** the existing controller compiled the frozen standalone wire reader once on each host during staging. I missed that existing step before execution and disclosed it during staging. Its two exact commands, output hashes and source identities are retained in the summary. This does not fully satisfy the no-compilation instruction. No clean-campaign certificate follows.

Condition: Movement50, requested 30 Hz inputs, 100 ms stagger, seed 30, difficulty 1, global 60 s warmup then exact 300 s measure; primary-fire counts are zero. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game Rx/Tx requested 2 MiB/effective 4 MiB; bot native 212,992 B; native unimpaired network. No Rust/game/protocol/sim/input cadence, scheduling, flush, throttle, channel, reliability or budget change.

Actual `/proc/PID/environ` proofs on both hosts confirm **OMEGA_NATIVE_DIAG entirely absent**, AoI audit absent and ordinary OMEGA_MEASURE_DIR enabled. 64 identified bot polls, 368 bot recorder rows / 18243 peer rows and 458 server rows, final report and isolated archives have no native diagnostic fields or traces. Private native counters are **absent/unobserved, not zero**; no native analyzer ran. Ordinary recorder completed sections total **0.663707535 s**, excluding the last sample's own work; this is not total causal overhead. Matched-boundary host execution is **16.900% game / 20.763% bots** of two-core capacity; game process **16.998%** of one core. Bot process/swarm matched-boundary CPU is unavailable after natural teardown, not zero. The separate **299.040662067 s** inner bracket reports **27.304%/27.471%** of one core. Queue residence, outstanding reliable queue and causal slowdown remain unknown.

Offered **29.996481682264–29.999814995041 Hz**, 0/50 failing >=29.7. Mapped game wire **29.970000000000–30.000000000000 Hz**, 0/50 failing; bot wire **29.970000000000–30.000000000000 Hz**, 0/50 failing. Offered denominator is **300.001850061 monotonic seconds**; both wire denominators are exact 300 s UTC. Steady missed schedules **0**. Specified ENet shedding does not relabel any failed wire predicate. Application input delivery and shedding magnitude remain unknown.

Full/steady bot Baseline-reference, unknown-entity, decode/send/panic counts, server decode/send, transport, oversized/panic/suppression, UDP/socket and parser/drop counts are retained exactly in JSON. Full bot counts **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**; steady **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**. Received AoI covers all received Snapshots before stale application discard: **22,152,858 matched / 0 unknown**, **0** actual >1150-unit peer violations, **0** empty-evidence peers; final Snapshot counts reconcile through drained. Full/steady stale counts are **{'full': 0, 'steady': 0}**. Full capture parsers retain **1650000/1649999 packets**, with zero parse errors or kernel capture drops. The one-packet difference is not an application-delivery count. All original errors remain explicit.

Steady Tick **9000 /300 s = 30.0 Hz**; work p99/max **5.564597/8.04287 ms**, **0** over 33.333 ms. Snapshot age p99/max **32.495036/51.182834 ms**; ActionConfirm **32.725317/64.060423 ms**. Deferred wait maximum **0 Ticks**; first/last 30 s pending means **[0, 0]**. All full/steady delivery, Tick work/cadence, backlog, read gaps, socket memory, CPU/observer and capture counters remain in JSON. Journal: **156 records / 256063 B**, complete scan **True**, raw retention **True**. The unobserved-steady journal correction is retained.

Legacy predicates remain separate: bandwidth **10.95 KiB/s**, strict <5 pass **False**; raw Tick estimate **30.000015991038843 Hz**, >=30 pass **True**. Exact arithmetic **544055 ×1000 / 18135157**, **1 ms** clock resolution. Rounding does not alter either result. The generic bot process exits 1 because the legacy bandwidth criterion fails; the watchdog has no failure reason.

Full additive budget before source/binary staging: **8852103168 free − 160893214 allowance**, **101275362 B** above unchanged 8 GiB reserve. Before workload staging: **8832876544 − 144424960**, **98516992 B** above reserve. Resource-only abort caps: 16 MiB live game, 24 MiB journal, 42 MiB role-only archive, 32 MiB margin, plus exact source/bundle/object/real-binary/original-executable/config/manifest/directory costs. Other ordinary paths retain 1 GiB. Zero extra original-payload allowance is backed by realpath/same-device/device/inode/hash/uid/gid/mode proof. The stopped original measurement directory was hashed, atomically renamed with no copy fallback and verified before restart; current owner/group/mode was recreated. No cleanup, package changes, evidence/journal/source/binary removal, resize, purchase or reserve reduction.

Publication lead **39.671225663 s**; fresh queries of both hosts followed publication. Original end is the steady endpoint; drained closes full counters separately and is excluded from measurement clocks. Natural terminal guard observed; missing-guard grace exercised remotely **False**, with no claim beyond actual evidence.

Automatic restoration passed. Two fresh independent audits **111/111 bounded 90 s commands** passed, covering all prior binaries/archives/closed states, candidates/sparse blobs, old backup inodes/hash manifests/markers/frozen recovery, new rename/current paths/ownership, ordinary 524,288 B buffers, maintenance/network/firewall, zero players/quiet queues and no owned/competing workloads. Final free storage **8806330368 B game / 18117705728 B bots**. **Both hosts released.** Fresh census verifies **7368 historical files unchanged**; parent plan/ledger/proposal changes are the explicit new baseline. Remote/local archive SHA and every extracted member are checked in fresh real directories without symlinks/hardlinks.

```text
game.tar.gz 8f5f5d6b627bc22220c1f20c9342c0b34ee2e1c7667dfc60fd99f0b2f77b9d12
bots.tar.gz ac2a1772c37b5d60d030884b52fd827ea519ddcb343c7a18d94932031b10051c
```

**82 applicable Python checks pass**, including failing-before/passing-after Movement50 profile dispatch. Rust unchanged: retained parent 240 pass/3 ignored, Clippy two old warnings, fmt/extension green; no expensive repeat. Historical R5's 423 ambiguous retirements, sampled fingerprints and unproved historical cause/application delivery remain qualified. This independent observation does not upgrade Idle150 or certify the campaign. Stop after this attempt.

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
