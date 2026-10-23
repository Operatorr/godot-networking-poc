# Ordinary Clustered50 — round 1

**One workload; clean-cell-pass; 36/36 original gates pass.** Failed gates: none. [Machine summary](clean-clustered50-r1-20261023-summary.json) retains all predicates, exact per-peer measurements and full/steady counters. This is one matched observation for [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), with no retry or further workload. Combat100 R1/R2 remain sealed non-passes; R3 remains its separate 36/36 passing observation. All historical classifications remain unchanged. This report does not certify the campaign or advance another workload.

Explicit **offered-load-v2**: offered-load valid **True**, generator valid **True**, wire delivery **True**, clean-cell pass **True**, capacity pass **True**. Strict projection: generator valid **True**, classification **clean-cell-pass**. All original 36 gate names and numeric predicates remain unchanged; both scoring sources are byte-identical to approved `22b1a43`. Unknown wire or a wire deficit never produces a passing population.

Runtime source **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**; controller/helper commit **17618b6ed677ce018899d4bf3c8c425afe95815c**; executed controller SHA-256 **c293845e56250a1bdd530d5003bde1598d39e173aafb87a435ece6253ef6b582**. All 124 frozen helper hashes match. Only the exact Clustered50 ordinary profile/policy and release-round dispatch were added, with a regression that failed before and passed afterward. Both parent corrections **a25b8ce** (missing proc identity) and **a85635c** (delayed paired status refresh) remain in the executed controller. Frozen repaired collector source is `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; atomic publisher matches `d2dfe73`.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Both hosts received fresh Rust-only cone sources selected before checkout, every materialized blob and Cargo file verified, with clean pinned source. Both reused R3 binaries are real one-link ELF64/AArch64 copies with verified dependencies. Both locked packages originated natively on bots. **Zero game/bot package builds** occurred; the dependency-source cache may remain absent. The explicitly authorized frozen standalone capture reader compiled **once per host**, under the existing shared 16 MiB staging allowance. Exact commands, source bytes/hashes and output hashes are retained in the summary. No Rust/game/protocol/sim/input scheduling, flush, throttle, channel, reliability, seed or budget changed.

Condition: **Clustered50 Arena**, requested 30 Hz input, 100 ms stagger, seed 30, difficulty 1, global 60 s warmup then an exact 300 s common measured window. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game RX/TX requested 2 MiB/effective 4 MiB; bots native 212,992 B. Native unimpaired network, with no emission AoI audit or perf workload. Primary-fire flags total **142,010 full / 117,275 steady**; every peer's fire/ability counts are retained. Existing Clustered behavior converges on the origin, stops within 5 units and sets primary fire with probability 0.30 per decision. Every peer has observed full/steady fire flags between zero and total input counts; no fixed 30% result is asserted. Ability flags and all per-peer action counts are retained in JSON. Observed ability flags total **0 full / 0 steady**; input flags total **544,161 full / 450,000 steady**. These action flags do not prove application input delivery.

Actual `/proc/PID/environ` checks on **both hosts** prove **OMEGA_NATIVE_DIAG entirely absent**, AoI audit absent and ordinary OMEGA_MEASURE_DIR enabled. 61 identified bot status polls, 368 bot recorder rows / 18244 peer rows, 468 server rows, final report and isolated archives retain no native diagnostic fields/traces. Private native counters are **unobserved, not zero**; no native analyzer ran. Ordinary recorder completed sections total **0.666851928 s**; its final row excludes that sample's own work. This is not a causal estimate of total observer cost.

Offered cadence **29.999939724321–29.999939724321 Hz**, 0/50 peers failing >=29.7; monotonic denominator **300.000602758 s**. Both mapped captures use exact 300 s UTC: game **29.980000000000–30.000000000000 Hz**, 0/50 failing; bots **29.980000000000–30.003333333333 Hz**, 0/50 failing. Missed steady schedules **0**. Admission, wire and application delivery are different observations; application input delivery and ordinary shedding magnitude remain unknown.

Full bot correctness/error counts: **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**; steady: **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**. All full/steady server, UDP/socket, parser/drop, transport, oversized/panic/suppression and stale-Snapshot counters remain explicit in JSON, including the full/steady journal counts. Received AoI checks all received Snapshots **before** stale application discard: **37,034,221 matched / 0 unknown**, **0** actual >1150-unit violations, **0** empty-evidence peers, with no unknown peers. These AoI counts cover the full lifecycle; matched-position steady totals are not separately recorded. Full-lifecycle zero unknowns/violations also bounds the steady subset to zero. Snapshot counters reconcile through drained; stale counts **{'full': 0, 'steady': 0}**. Full capture parsers retain **1,891,949/1,891,947 packets**. Capture differences do not measure application delivery.

Steady Tick **9000 /300 s = 30.0 Hz**; work p99/max **7.185906/15.900346 ms**, **0** over 33.333 ms. Snapshot age p99/max **32.121914/41.519314 ms**; ActionConfirm **48.774815/64.690392 ms**. Deferred wait maximum **0 Ticks**; first/last 30 s pending means **[0, 0]**. Exact full/steady delivery, read gaps, Tick cadence/work, backlog, capture, socket memory, CPU and observer measurements remain in the summary. Queue residence and outstanding reliable queue size remain unknown.

Matched-boundary host execution **18.763% game / 20.736% bots** of two-core capacity; game process **20.492%** of one core. Bot process/swarm matched-boundary CPU may be unavailable after natural teardown, never zero-filled; the separate **299.040857896 s** inner bracket reports process/swarm **27.401%/27.565%** of one core. Complete byte-aware journal scan: **156 records / 256534 B**, complete scan **True**, raw retention **True**.

Legacy targets retain their actual results: **22.01 KiB/s**, strict <5 pass **False**; raw Tick estimate **29.9999906261402 Hz**, >=30 pass **False**. Bandwidth raw arithmetic **405745536 / 50 / 360.0 / 1024 = 22.013104166666665 KiB/s**. Tick exact arithmetic **544066 ×1000 / 18135539**, **1 ms** clock resolution. Rounded displays cannot change either predicate; these remain separate from the matrix's 29.7 Hz Tick gate. Generic bot exit/legacy status is retained in the guard proof.

Full additive allowance before source/binary staging: **8779632640 free − 161384334 allowance**, **28313714 B** above unchanged 8 GiB reserve. Before workload staging: **8759906304 − 144424960**, **25546752 B** above reserve. Resource-only caps remain 16 MiB live game, 24 MiB journal, 42 MiB role archive and 32 MiB margin, plus exact source/bundle/object/real binary/original executable/config/manifest/directory/reader costs; all prior profiles retain their limits and the ordinary default remains 1 GiB. No cap changed mid-attempt. The stopped original measurement directory was hashed and atomically renamed into `original/measurement-current`, without copy fallback, after realpath/device/inode/hash/uid/gid/mode proof. Hashes were verified before restart and current owner/mode recreated. Original payload additional allowance was zero only under that proof.

The parent's [prior compaction](storage-compaction-20261023.md) intentionally removed eleven redundant remote loose `game/` trees after exact archive comparison; their archives and local extractions remain. A [second verified compaction](storage-compaction-r2-20261023.md) removed 76 duplicate loose files from Combat50 and Combat100 R1/R2/R3 and 17 redundant uploaded bundles, preserving their archive/local copies and all 248 protected hashes. These duplicate paths remain deliberately absent and were not recreated. The parent also [recovered 174,473,216 B](storage-recovery-r4-20261023.md) of public dependency-source cache only after verifying all 9,279 files in off-host backup **4097d75f89a898fcd155474534e6e24b6cd9934376f2fa710fdd169471e5910a**. Frozen repository sources, Cargo files, executables and prior evidence remain. This attempt performed no further cleanup, package change, source/binary/evidence removal, journal vacuum, resize, purchase or reserve reduction.

Publication lead **36.078026727 s**, with both hosts freshly queried afterward and >=10 s required lead retained. **Successful terminal guard observed by status: True**. Expired-reply refresh observed: **False**, refresh count **0**; exact roles/times are retained. Unavailable bot identity was reported in **1** post-phase polls. These observations do not prove the specific proc-read race or ordering. A successful run does not establish that the expiry race occurred when no expired replies were logged. The unchanged 10 s recorder threshold, 10 s terminal deadline and 550 s overall bound remain enforced; genuine stale/runtime/resource/collector failures still fail. Archived terminal guard is retained; missing-guard bounded grace observed remotely **False**. End remains the steady endpoint, while drained closes full lifecycle separately. The fixed status reader completed successfully through terminal collection. This validates that observed flow; disappearance at a particular proc read is **not known to have occurred remotely**. The four parent regression tests cover actual stat/hash/readlink/environment readers, permission/error rejection and in-window failure; the ten-second terminal wait remains bounded. Combat100 R1's exact disappearance ordering remains unknown.

An early local publication-preparation invocation refused the missing completed-audit files and created no publication proof or host mutation. Its original error log is retained; the offline publication step completed only after both audits.

**Automatic restoration passed**, without manual intervention. Two independent fresh unique release audits passed: **139 / 139 bounded commands**, each command capped at 90 s. They cover retained binaries/archives/closed states, frozen sparse source blobs/Cargo files/recovery scripts, old backup inodes/manifests/markers, this rename/current owner/mode, original service/config and ordinary 524,288 B buffers, maintenance/qdisc/firewall, zero players/quiet queues and no competing/owned workload. **Both hosts released.** Final free storage **8732471296 B game / 17644703744 B bots**. Fresh local census verifies **11105 historical files unchanged**, including the parent's immediate delegation/docs and private cache/regression proof. Remote/local workload archive SHA values and **every member** match fresh isolated real extractions with no links.

```text
game.tar.gz 5972ce9fadf969d78814ba2a60d136a8a3451cb4e31700f80d7d3b7735e8e49f
bots.tar.gz 407adc23d452ed6d0f20f2427b0f022947063f556035568b588b4d254c248a89
```

**134 applicable Python checks and 33 independent archive-analysis checks pass.** Rust is unchanged: retained 240 pass/3 ignored, Clippy two old warnings, fmt/extension green; no expensive repeat. Historical R5's 423 ambiguous retirements and sampled fingerprints retain their limitations; historical shedding cause, ordinary shedding magnitude and application delivery remain unknown. No history rescore, campaign certificate, parent PLAN/BUG-LEDGER/campaign-ledger/policy edit, issue comment, PR or push. Stop after this one attempt.

| Original gate | Result |
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
