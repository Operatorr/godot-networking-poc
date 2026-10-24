# Ordinary Strategy50 — round 1

**One workload; clean-cell-pass; 36/36 original gates pass.** Failed gates: none. [Machine summary](clean-strategy50-r1-20261024-summary.json) retains all predicates, exact per-peer measurements and full/steady counters. This is one matched observation for [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), with no retry or further workload. Combat100 R1/R2 remain sealed non-passes; R3 remains its separate 36/36 passing observation. All historical classifications remain unchanged. This report does not certify the campaign or advance another workload.

Explicit **offered-load-v2**: offered-load valid **True**, generator valid **True**, wire delivery **True**, clean-cell pass **True**, capacity pass **True**. Strict projection: generator valid **True**, classification **clean-cell-pass**. All original 36 gate names and numeric predicates remain unchanged; both scoring sources are byte-identical to approved `22b1a43`. Unknown wire or a wire deficit never produces a passing population.

Runtime source **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**; controller/helper commit **0d1895f5c587ad6b3fb9d508a65dadff3ed4cfd5**; executed controller SHA-256 **f57e8f27fa916a03b2fa03d43b7a09bb15be1e5cf4063c31b024bb43bb89edc9**. All 127 frozen helper hashes match. Only the exact Strategy50 ordinary profile/policy and release-round dispatch were added, with a regression that failed before and passed afterward. Both parent corrections **a25b8ce** (missing proc identity) and **a85635c** (delayed paired status refresh) remain in the executed controller. Frozen repaired collector source is `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; atomic publisher matches `d2dfe73`.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Both hosts received fresh Rust-only cone sources selected before checkout, every materialized blob and Cargo file verified, with clean pinned source. Both reused R3 binaries are real one-link ELF64/AArch64 copies with verified dependencies. Both locked packages originated natively on bots. **Zero game/bot package builds** occurred; the dependency-source cache may remain absent. The explicitly authorized frozen standalone capture reader compiled **once per host**, under the existing shared 16 MiB staging allowance. Exact commands, source bytes/hashes and output hashes are retained in the summary. No Rust/game/protocol/sim/input scheduling, flush, throttle, channel, reliability, seed or budget changed.

Condition: **Strategy50 Arena**, requested 30 Hz input, 100 ms stagger, seed 30, difficulty 1, global 60 s warmup then an exact 300 s common measured window. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game RX/TX requested 2 MiB/effective 4 MiB; bots native 212,992 B. Native unimpaired network, with no emission AoI audit or perf workload. Primary-fire flags total **384,083 full / 320,465 steady**; every peer's fire/ability counts are retained. Existing Strategy selects visible live targets, otherwise wanders; it orbits targets, shoots in range, dodges, sprints and dashes with its existing reaction cache. Class-specific abilities are layered each frame and have a six-second self-cooldown plus probability gate; Warrior holds charge. Actual full/steady fire and ability flags are checked between zero and total inputs; no other behavior's action assertion is inherited. Ability flags and all per-peer action counts are retained in JSON. Observed ability flags total **37206 full / 30640 steady**; input flags total **544,151 full / 449,999 steady**. These action flags do not prove application input delivery.

Actual `/proc/PID/environ` checks on **both hosts** prove **OMEGA_NATIVE_DIAG entirely absent**, AoI audit absent and ordinary OMEGA_MEASURE_DIR enabled. 38 identified bot status polls, 368 bot recorder rows / 18244 peer rows, 575 server rows, final report and isolated archives retain no native diagnostic fields/traces. Private native counters are **unobserved, not zero**; no native analyzer ran. Ordinary recorder completed sections total **0.659415435 s**; its final row excludes that sample's own work. This is not a causal estimate of total observer cost.

Offered cadence **29.996534922285–29.999868240979 Hz**, 0/50 peers failing >=29.7; monotonic denominator **300.001317596 s**. Both mapped captures use exact 300 s UTC: game **29.996666666667–30.003333333333 Hz**, 0/50 failing; bots **29.996666666667–30.003333333333 Hz**, 0/50 failing. Missed steady schedules **0**. Admission, wire and application delivery are different observations; application input delivery and ordinary shedding magnitude remain unknown.

Full bot correctness/error counts: **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**; steady: **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**. All full/steady server, UDP/socket, parser/drop, transport, oversized/panic/suppression and stale-Snapshot counters remain explicit in JSON, including the full/steady journal counts. Received AoI checks all received Snapshots **before** stale application discard: **35,364,905 matched / 0 unknown**, **0** actual >1150-unit violations, **0** empty-evidence peers, with no unknown peers. These AoI counts cover the full lifecycle; matched-position steady totals are not separately recorded. Full-lifecycle zero unknowns/violations also bounds the steady subset to zero. Snapshot counters reconcile through drained; stale counts **{'full': 0, 'steady': 0}**. Full capture parsers retain **1,821,440/1,821,440 packets**. Capture differences do not measure application delivery.

Steady Tick **9000 /300 s = 30.0 Hz**; work p99/max **6.880135/10.979992 ms**, **0** over 33.333 ms. Snapshot age p99/max **32.511813/38.253384 ms**; ActionConfirm **42.192179/70.235112 ms**. Deferred wait maximum **6 Ticks**; first/last 30 s pending means **[0.0033333333333333335, 0.3333333333333333]**. Exact full/steady delivery, read gaps, Tick cadence/work, backlog, capture, socket memory, CPU and observer measurements remain in the summary. Queue residence and outstanding reliable queue size remain unknown.

Matched-boundary host execution **17.890% game / 19.887% bots** of two-core capacity; game process **20.452%** of one core. Bot process/swarm matched-boundary CPU may be unavailable after natural teardown, never zero-filled; the separate **299.041305806 s** inner bracket reports process/swarm **27.605%/27.777%** of one core. Complete byte-aware journal scan: **156 records / 256060 B**, complete scan **True**, raw retention **True**.

Legacy targets retain their actual results: **19.57 KiB/s**, strict <5 pass **False**; raw Tick estimate **30.000039150720514 Hz**, >=30 pass **True**. Bandwidth raw arithmetic **360779190 / 50 / 360.0 / 1024 = 19.573523763020834 KiB/s**. Tick exact arithmetic **544052 ×1000 / 18135043**, **1 ms** clock resolution. Rounded displays cannot change either predicate; these remain separate from the matrix's 29.7 Hz Tick gate. Generic bot exit/legacy status is retained in the guard proof.

Full additive allowance before source/binary staging: **8967102464 free − 161452630 allowance**, **215715242 B** above unchanged 8 GiB reserve. Before workload staging: **8946024448 − 144424960**, **211664896 B** above reserve. Resource-only caps remain 16 MiB live game, 24 MiB journal, 42 MiB role archive and 32 MiB margin, plus exact source/bundle/object/real binary/original executable/config/manifest/directory/reader costs; all prior profiles retain their limits and the ordinary default remains 1 GiB. No cap changed mid-attempt. The stopped original measurement directory was hashed and atomically renamed into `original/measurement-current`, without copy fallback, after realpath/device/inode/hash/uid/gid/mode proof. Hashes were verified before restart and current owner/mode recreated. Original payload additional allowance was zero only under that proof.

The parent's [prior compaction](storage-compaction-20261023.md) intentionally removed eleven redundant remote loose `game/` trees after exact archive comparison; their archives and local extractions remain. A [second verified compaction](storage-compaction-r2-20261023.md) removed 76 duplicate loose files from Combat50 and Combat100 R1/R2/R3 and 17 redundant uploaded bundles, preserving their archive/local copies and all 248 protected hashes. These duplicate paths remain deliberately absent and were not recreated. The parent also [recovered 174,473,216 B](storage-recovery-r4-20261023.md) of public dependency-source cache only after verifying all 9,279 files in off-host backup **4097d75f89a898fcd155474534e6e24b6cd9934376f2fa710fdd169471e5910a**. Frozen repository sources, Cargo files, executables and prior evidence remain. The parent also archived two closed original measurement backups (Strategy150 R1 and native Idle150 R2), retaining all raw bytes in exact verified remote/local archives and frozen manifests. Their former loose directories/inodes are deliberately absent; old restore timers/services are inactive and those old scripts require restoring the archived tree first. Historical representation is **14 loose / 2 archived**, plus this run's **new loose** backup. See [closed-backup proof](storage-closed-backup-archives-20261024.md). This attempt performed no further cleanup, package change, source/binary/evidence removal, journal vacuum, resize, purchase or reserve reduction.

Publication lead **27.065644942 s**, with both hosts freshly queried afterward and >=10 s required lead retained. **Successful terminal guard observed by status: True**. Expired-reply refresh observed: **False**, refresh count **0**; exact roles/times are retained. Unavailable bot identity was reported in **1** post-phase polls. These observations do not prove the specific proc-read race or ordering. A successful run does not establish that the expiry race occurred when no expired replies were logged. The unchanged 10 s recorder threshold, 10 s terminal deadline and 550 s overall bound remain enforced; genuine stale/runtime/resource/collector failures still fail. Archived terminal guard is retained; missing-guard bounded grace observed remotely **False**. End remains the steady endpoint, while drained closes full lifecycle separately. The fixed status reader completed successfully through terminal collection. This validates that observed flow; disappearance at a particular proc read is **not known to have occurred remotely**. The four parent regression tests cover actual stat/hash/readlink/environment readers, permission/error rejection and in-window failure; the ten-second terminal wait remains bounded. Combat100 R1's exact disappearance ordering remains unknown.

The original post-restoration game and bot archive checkpoints were interrupted by SSH connection timeouts; the original cleanup file and failed command records remain byte-identical. Both missing archives were completed through a separate supplemental proof after fresh restore/idle/quiet-queue/resource-cap verification, without another workload. Analysis receives only the additive archive identity fields through an explicit read-only input view; both approved scoring sources and all predicates remain unchanged. A first supplemental precheck refused its own embedded process-audit command before mutation; the retained local red/green regression corrects only that self-match and continues to reject a real collector. Offline publication proofs were prepared after both release audits.

**Automatic restoration passed**, without manual intervention. Two independent fresh unique release audits passed: **143 / 143 bounded commands**, each command capped at 90 s. They cover retained binaries/archives/closed states, frozen sparse source blobs/Cargo files/recovery scripts, 14 loose historical backups and 2 closed archives in their declared representations, frozen manifests/markers, this new loose rename/current owner/mode, original service/config and ordinary 524,288 B buffers, maintenance/qdisc/firewall, zero players/quiet queues and no competing/owned workload. **Both hosts released.** Final free storage **8758243328 B game / 17595469824 B bots**. Fresh local census verifies **11657 historical files unchanged**, including the parent's immediate delegation/docs and private cache/regression proof. Remote/local workload archive SHA values and **every member** match fresh isolated real extractions with no links.

```text
game.tar.gz 5459f64f3fc4f0867d80c0e00221d2ff17f342414cb9d37040c1d2e12170cf80
bots.tar.gz 60da6baba38380c03b1219603b7b5bb08fcdb3d8343a3b91388e2cec30262d99
```

**143 applicable Python checks and 33 independent archive-analysis checks pass.** Rust is unchanged: retained 240 pass/3 ignored, Clippy two old warnings, fmt/extension green; no expensive repeat. Historical R5's 423 ambiguous retirements and sampled fingerprints retain their limitations; historical shedding cause, ordinary shedding magnitude and application delivery remain unknown. No history rescore, campaign certificate, parent PLAN/BUG-LEDGER/campaign-ledger/policy edit, issue comment, PR or push. Stop after this one attempt.

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
