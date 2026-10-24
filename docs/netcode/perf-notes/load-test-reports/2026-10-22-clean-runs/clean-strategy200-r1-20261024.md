# Ordinary Strategy200 — final bounded attempt

**One reserved attempt, one workload, zero retries: aborted-collector-invalid; strict projection aborted-collector-invalid.** 10/36 original predicates pass. Clean/capacity pass remain false. [Machine summary](clean-strategy200-r1-20261024-summary.json) retains every flag, source/hash, prefix counter and preservation proof. No campaign certificate, issue closure, push, PR or advance.

All 200 bots authenticated, then server population fell to 81 and 80 in consecutive controller polls, crossing the unchanged 65%-of-peak guard. The recorder observes a low of 79 after the 200 peak. The controller decided to abort **28.70194868 seconds before the scheduled measurement start**. The bot process ran **60.10837907891255 seconds**, including ramp and partial warmup, before controller SIGTERM. **Zero seconds of the common 300-second window were observed.** This is an unsustainable observed prefix, not a validated correctness-clean capacity limit. Complete-window offered cadence is unobserved; generator validity fails closed, with real bot-host receive errors. The underlying disconnect cause is not isolated, and no new code bug is established.

Observed-prefix bot errors: {'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}. Observed-prefix missed schedules: **125**. Prefix inputs/fire/ability flags: **290270 / 179461 / 19490**. Every peer's counters and actual authenticated/alive trajectory are retained. Server decode/send counters are zero in retained observations. The complete journal has 606 records / 990609 bytes; 121 disconnect records fall inside the workload bracket (200 across the experiment including shutdown). The last peer sample reaches 33.847332152 s Snapshot age and 26.613145805 s confirmation age. These are prefix observations only. No final bot report or start/end/drained boundary rows exist. Full-lifetime and steady correctness, final received-AoI matched/unknown/empty/above-1150 counts, complete-window per-peer offered/wire rates and failure fractions, and both legacy predicates remain **unknown**, never zero-filled or passed.

**Actual socket/UDP failure:** workload-bracket game `InErrors/RcvbufErrors = 135913`; bots `InErrors/RcvbufErrors = 299` and `NoPorts = 1617`. UDP send-buffer errors are zero. Game sampled receive occupancy reaches 4194288 of 4194304 B; bot receive occupancy reaches 212736 of 212992 B. Both configured buffer sizes remain unchanged in the observed prefix. Prefix Tick work p99 is 37.636797 ms and accumulator lag peaks at 1.314287682 s; these prefix statistics do not replace the missing window. Bot-host receive loss invalidates the generator transport prerequisite; these data cannot isolate a clean server-only capacity limit. Twenty-seven independent aborted-run checks reproduce all 36 fail-closed flags and raw UDP/journal arithmetic.

Both prefix captures have zero parser errors and kernel drops. Six separate retained-prefix packet/CSV accounting/end-time checks pass. The population-adapted R3 full-window checker attempted to read an absent steady count and failed with `KeyError: '40156'`; its failed output is retained without a retry. It does not become a capture-validity or wire-cadence pass. Primary maintained analysis preserves all 36 original predicates and abort precedence.

**LOAD SCALING at twice requested population; not performance improvement from code fixes.** Strategy100 R3 reference values are Tick work p99 **14.146315 ms**, Snapshot age p95 **28.485562 ms**, bandwidth **31.93799319118924 KiB/s**, actual Tick **30 Hz**. All corresponding Strategy200 completed-window values and relative changes are **N/A**. Prefix Tick/population/backlog/error statistics are separate in the summary and cannot replace the missing comparable window.

Pinned runtime source `a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf`; controller `fabce8a3f7ea866086519dcaad5afffb67167af9` / SHA `ace5a96ac2972eba085f81ce0f8d76fc9b9b00bd32a3043fedfd1f81b0b8055a`. Game `de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db`, bot `56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67`, config `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`. Both real independent one-link AArch64 copies and Rust-only cone source/Cargo identities verify. Zero game/bot builds; the frozen standalone capture reader compiled once per host. All 134 helper hashes match. Collector `994cce8c7cb2f689cd59f4d09e93e270057aba7e`, atomic publisher `d2dfe73`; actual ordinary measurement enabled and native/AoI flags absent. Native private counters remain unknown. All 157 applicable Python tests pass; maintained changes are exact dispatch/profile mappings and acceptance/rejection tests only.

Both full additive allowances pass above the unchanged 8 GiB reserve: pre-staging margin **164291102 B**, pre-workload margin **160264192 B**. Caps stay 16 MiB live game, 24 MiB journal, 42 MiB role archive and 32 MiB margin plus actual staging costs. No cleanup, rotation, package operation, resize or tuning occurred.

**Automatic restoration succeeds; both hosts are released.** Two fresh full independent audits pass (157 / 157 commands, each bounded to 90 s), plus independent protected/mirror/original-service endpoint checks. Original binary/config/environment/512 KiB buffers, zero players, quiet queues and no owned units/processes are verified. Both original unmodified acquired-prefix lengths and hashes match the stopped backup; no corrected input view. The 19 archived historical backups, prior loose R3 backup and new loose Strategy200 backup remain preserved. All **14340 historical local files** retain size/hash against the post-marker baseline. Every new role/build/preflight/evidence archive member matches real isolated extraction. Final free bytes: game **8868298752**, bots **17336844288**.

Terminal evidence is controller-stop, exit −15; natural endpoint latency is N/A, unavailable identity polls 0, missing-guard grace false, expiry refreshes 0. Exact proc-read ordering remains unproved. The failed full-window check, missing final evidence and unknowns remain explicit.

| Original predicate | Result |
|---|---|
| all_requested_authenticated | FAIL |
| application_errors_zero | FAIL |
| autonomous_recovery_succeeded | PASS |
| bot_buffers_unchanged | FAIL |
| bots_all_observed_udp_and_socket_errors_zero | FAIL |
| bots_full_workload_udp_errors_zero | FAIL |
| bots_udp_errors_zero | FAIL |
| candidate_bot_runtime_identity | PASS |
| candidate_game_runtime_and_buffers | PASS |
| collectors_clean | PASS |
| complete_300s_common_coverage | FAIL |
| delivery | FAIL |
| ending_lag | FAIL |
| full_replication_counters_cover_final_snapshot | FAIL |
| full_transport_errors_zero | PASS |
| full_workload_oversized_panics_suppression_zero | PASS |
| full_workload_replication_and_bot_errors_zero | FAIL |
| game_all_observed_udp_and_socket_errors_zero | FAIL |
| game_full_workload_udp_errors_zero | FAIL |
| game_udp_errors_zero | FAIL |
| identity_mapping | PASS |
| independent_final_cleanup_verified | PASS |
| journal_error_counts_complete | PASS |
| mapped_wire_29_7hz | FAIL |
| per_identity_offered_29_7hz | FAIL |
| received_aoi_all_peers_zero_unknown | FAIL |
| received_aoi_default95_policy | FAIL |
| received_aoi_no_actual_above1150 | FAIL |
| replication_backlog | FAIL |
| runtime_identity | PASS |
| server_full_and_steady_errors_zero | FAIL |
| steady_window_oversized_panics_suppression_zero | FAIL |
| steady_window_replication_and_bot_errors_zero | FAIL |
| strict_enabled_assertions | FAIL |
| tick_hz | FAIL |
| tick_work_p99 | FAIL |

Role archive SHA-256:

```text
game 1cdb1cb755cd628929b90f842b0ee62693ce7bc0010f8e286073f8bffbe42938
bots f489e8e3e34accae52d3f79e3f421c6d406339f7ec595adc5061a08f6c9f3733
```
