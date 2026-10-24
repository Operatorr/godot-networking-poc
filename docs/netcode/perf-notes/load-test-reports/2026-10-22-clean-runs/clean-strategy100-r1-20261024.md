# Ordinary Strategy100 — round 1

**One attempt; one workload; valid-failure; 35/36 original gates pass.** Failed gates: ['independent_final_cleanup_verified']. [Machine summary](clean-strategy100-r1-20261024-summary.json) retains exact per-peer and full/steady evidence for issue 39. No retry, extra workload, ladder/capacity advance or campaign certificate. Historical results are unchanged. The original composite release audit fails a preflight prefix-metadata condition, so the final existing `independent_final_cleanup_verified` gate is false despite passing workload evidence. Both clean/capacity flags are false and no highest passing population is claimed.

Explicit **offered-load-v2**: offered-load valid **True**, generator valid **True**, wire delivery **True**, clean/capacity pass **False/False**. Strict projection **valid-failure**, strict generator **True**. All 36 numeric predicates and gate names are unchanged, including per-peer offered and both captures' mapped wire >=29.7 Hz. Approved scoring sources remain byte-identical to `22b1a43`. Unknown/incomplete/aborted evidence cannot pass; wire-only deficits remain non-pass with no highest passing population.

Runtime **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**; executed controller/helper commit **4d0e8b495b0abb3fef1ae5c1ab62e2df4d5a074c** and controller SHA **abe8ecc14505fe33a7ad137f23dc5e638f41b77020b9385afd4e02ecd5f4dcb0**; all **129** frozen helper hashes match. The only maintained-code changes are this exact compact profile, explicit policy and release-round mappings. A real dispatch/condition regression fails before and passes afterward. A separate newly exposed append race remains unfixed in the maintained probe under the dispatch-only scope; its actual generated-command reproducer and proposed bounded-read reference are retained. Proc handling `a25b8ce` and delayed-status refresh `a85635c` remain intact, with genuine in-window/stale/runtime/error failures and unchanged 10 s terminal/freshness limits and 550 s bound.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Fresh Rust-only cone sources were selected before checkout; every materialized blob, Cargo file and clean pinned revision was verified. Both hosts use independent real one-link ELF64/AArch64 copies with verified dependencies, reused from `clean-idle150-audit-r3-20261023`; both locked packages originated natively on bots. **Zero game/bot package builds.** Only the expressly authorized frozen standalone capture reader compiled once per host, from collector `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; source/command/output hashes are in the summary. Atomic publisher matches `d2dfe73`. No Rust/game/protocol/sim/input schedule/flush/throttle/channel/reliability/seed/budget tuning occurred.

**Strategy100 Arena**, requested 30 Hz inputs, 100 ms stagger, seed 30, difficulty 1, global 60 s warmup then exact 300 s common measurement. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game RX/TX requested 2 MiB/effective 4 MiB; bots native 212,992 B. Native unimpaired network, without emission AoI or perf. Existing Strategy selects live visible targets, otherwise wanders, and uses its existing orbit/dodge/sprint/dash and class ability rules. Actual input flags: **{'inputs': {'full': 1096913, 'steady': 899999}, 'shoot_inputs': {'full': 765138, 'steady': 638811}, 'ability_inputs': {'full': 74716, 'steady': 61550}}** (full/steady). Every peer's behavior/fire/ability counts are retained, with no other behavior's assertions or fixed random proportions. Action flags do not establish application input delivery.

Actual `/proc` checks on both hosts prove **OMEGA_NATIVE_DIAG entirely absent**, emission AoI absent and ordinary OMEGA_MEASURE_DIR enabled. Identified polls **63**, bot rows **373**, peer rows **36713**, server rows **468**, final report and isolated archives contain no native diagnostic evidence. Private native counters remain **unobserved, not zero**. Ordinary recorder completed sections total **1.12420491 s**; final sample excludes its own current work, and this is not a causal total observer cost.

Offered cadence **29.99664199802822–29.999975328620287 Hz**, failing peers **[]**, monotonic interval **300.000246714 s**. Mapped exact-300 s wire: **{'game': {'min': 29.973333333333333, 'max': 30.0, 'failing': []}, 'bots': {'min': 29.973333333333333, 'max': 30.003333333333334, 'failing': []}}**. Application input delivery, historical shedding cause and ordinary shedding magnitude remain unknown. Exact cadence, capture/parser/drop, UDP/socket, backlog, CPU and observer measurements are retained in machine fields. Native socket read-gap counters are **unobserved**, not zero; separate ordinary input/Snapshot cadence gaps retain full cumulative maxima and steady histogram differences. Steady exact maxima are unknown because maxima cannot be subtracted.

Full bot errors **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**; steady **{'baseline_reference_misses': 0, 'unknown_delta_entities': 0, 'decode_failures': 0, 'send_failures': 0, 'panics': 0}**. Full/steady server/journal/transport/oversized/panic/suppression counters are retained explicitly. Received AoI checks every Snapshot before stale application discard: **114093970 matched / 0 unknown**, actual >1150-unit peer violations **[]**, empty/unknown peer evidence retained in JSON. Full lifecycle zero violations bounds the steady subset; no separate steady matched-position count is fabricated. End is the steady endpoint; drained closes full lifecycle separately, with final Snapshot reconciliation independently checked.

Steady Tick/cadence/work: **{'count': 9000, 'actual_tick_hz': 30.0, 'work_ms': {'n': 9000, 'min': 6.52793, 'median': 10.441164, 'p95': 12.775416, 'p99': 14.619642, 'max': 24.375816}, 'work_over_33_333ms': 0, 'accumulator_lag_ms': {'n': 9000, 'min': 0.00010400000315796687, 'median': 0.6054586666708051, 'p95': 1.1455463333377782, 'p99': 1.6577423333363275, 'max': 5.510495333338978}, 'ending_accumulator_lag_ms': 0.4486610000064284, 'elapsed_tick_lag_end_ms': 0.18630333335067917, 'observer_us': {'n': 9000, 'min': 7.44, 'median': 21.32, 'p95': 47.081, 'p99': 82.722, 'max': 1099.175}, 'authenticated': {'n': 9000, 'min': 100, 'median': 100.0, 'p95': 100, 'p99': 100, 'max': 100}, 'alive': {'n': 9000, 'min': 69, 'median': 86.0, 'p95': 94, 'p99': 96, 'max': 97}, 'monsters': {'n': 9000, 'min': 0, 'median': 0.0, 'p95': 0, 'p99': 1, 'max': 1}, 'projectiles': {'n': 9000, 'min': 110, 'median': 166.0, 'p95': 188, 'p99': 198, 'max': 219}, 'effects': {'n': 9000, 'min': 0, 'median': 0.0, 'p95': 1, 'p99': 1, 'max': 1}, 'pending_replication': {'n': 9000, 'min': 0, 'median': 470.0, 'p95': 1141, 'p99': 1407, 'max': 1814}, 'max_deferred_wait_ticks': {'n': 9000, 'min': 0, 'median': 5.0, 'p95': 7, 'p99': 7, 'max': 10}}**. Delivery **{'snapshot_age_s': {'n': 30000, 'min': 0.000776886, 'median': 0.015185709, 'p95': 0.029180649, 'p99': 0.032322516, 'max': 0.073724589}, 'confirm_age_s': {'n': 30000, 'min': 0.000800007, 'median': 0.015450331500000001, 'p95': 0.029797374, 'p99': 0.043098327, 'max': 0.088740877}}**; first/last 30 s backlog **{'pending_replication': [291.4433333333333, 507.43333333333334], 'max_deferred_wait_ticks': [3.9788888888888887, 5.337777777777778]}**. Complete byte-aware journal: **306 records / 500620 B**, complete scan **True**, raw retained **True**. Matched-boundary host execution: **30.798517520215633% game / 36.13519074442608% bots** of two-core capacity. Game process **40.60187033533088%**, bot process CPU **unavailable** (one-core percentage). Inner-bracket bot process/swarm **55.36903972478729%/55.54200293419887%**, over **299.047989315 s**. Matched-boundary and inner intervals retain distinct denominators; absent process CPU is unknown, never zero-filled. Collector CPU and sample durations are retained in JSON. Queue residence and outstanding reliable queue size remain unknown.

Legacy strict <5 KiB/s is **False**: `1168721311 / 100 / 360.0 /1024 = 31.70359459092882`. Independent raw Tick >=30 is **True**: `1096687 ×1000 / 36556173 = 30.00004951284151 Hz`, paired Tick/server_ms spans at **1 ms** resolution. Rounded display never replaces either actual predicate.

Full additive allowance before any source/binary staging: **8920588288 free − 161652604 allowance**, **169001092 B** above unchanged 8 GiB reserve. Before workload staging: **8900640768 − 144424960**, **166281216 B** above reserve. Resource-only caps remain 16 MiB live game, 24 MiB journal, 42 MiB role archive, 32 MiB margin, plus exact staging/source/bundle/object/real binary/original executable/config/manifest/directory/reader costs. Prior profiles/defaults and reserve are unchanged; no mid-attempt cap change. Original measurement was stopped/hashed and atomically renamed without copy fallback, with realpath/same-device/device/inode/hash/uid/gid/mode proof before restart. Both release audits verify actual new backup inodes and recreated current owner/mode.

Historical preservation is **0 loose / 17 archived original backups, plus this run's new loose backup**. All retained archive/proof/manifest/marker/config/recovery bytes remain verified; former historical loose directories/inodes are intentionally absent and metadata is historical evidence. All old restore units remain inactive; restore a verified measurement tree before deliberately reusing a closed recovery script. Parent compaction deliberately removed 15 duplicate game trees and 17 uploaded staging bundles after exact archive/local-bundle verification. Public Cargo source cache (9,279 files) remains backed up at SHA **4097d75f89a898fcd155474534e6e24b6cd9934376f2fa710fdd169471e5910a**. Frozen sources/Cargo/binaries/evidence remain. No additional cleanup, package change, removal, journal vacuum, resize/purchase or reserve reduction occurred.

Publication lead **38.844879209 s**, with both hosts requeried after publication and >=10 s lead retained. Natural terminal guard observed **True**, **5.517906791 s** after endpoint. Unavailable bot identity polls **1**; missing-guard grace **True**. Actual expired-reply refreshes **0**, roles/times retained. Exact missing-proc ordering is unproved; an absent expiry event is not claimed as a race reproduction. Guard and actual terminal/expiry evidence are retained with the unchanged limits.

The original composite audit stops at command 108: its first pre-staging `server.ndjson` hash covers **46,013,846 B**, while its separately recorded size is **46,012,575 B**. The second probe similarly hashes **115,257,477 B** of `ticks.csv` while recording **115,254,292 B**. These original hashes match the preserved prefixes exactly at the longer lengths (**+1,271 / +3,185 B**). Both complete stopped files match the immutable external manifest and retain their original devices/inodes/ownership/mode. This confirms a live append between stat and the unbounded hash; it does not indicate lost backup bytes. The initial pre-composite 36/36 derivation remains in private evidence; final classification incorporates the actual original failed check through the existing cleanup gate. Scoring sources, all numeric predicates and all other gate flags are unchanged.

The original failed command/audit and both frozen budget files remain byte-identical. Two fresh complete audits run the **unchanged maintained helpers** over a real local evidence input view. Only the first probe's prefix length is reconciled to the exact original SHA-matched length; SHA/device/inode/uid/gid/mode and every resource allowance remain unchanged. No controller is copied or rerun. The two audits verify the actual preserved data, but do **not** erase the original acquisition defect or make this attempt clean. The deterministic real-probe witness reproduces the mismatch; a bounded-prefix reference passes locally, and **the maintained fix is not applied**. Parent follow-up must repair acquisition before a separately authorized matched attempt.

**Automatic restoration succeeded. Both original archive checkpoints completed; no supplemental archive completion was needed. Both hosts released.** Two independent fresh unique bounded-90 s release audits pass with the explicit reconciled read-only evidence view: **147 / 147 commands**. Both verify retained archives/binaries/closed states, frozen sparse blobs/Cargo/recoveries, all 17 archived historical backups against external manifests/proofs/markers, this new loose backup's live inodes/current owner/mode, original service/config and ordinary 524,288 B buffers, maintenance/qdisc/firewall, zero players, quiet queues and no competing/owned workload. Last audit disk sample: **8596819968 game / 17516756992 bots**. Fresh local census verifies **12352 historical files unchanged**, including immediate parent delegation/docs and private archive evidence. All remote/local workload archive SHAs and every member match fresh isolated real extractions without links.

```text
game.tar.gz 8acec8d6bdf1dfb3739f63f131566c6419bca4ba22fb79e02a99fc6d8c7a67d6
bots.tar.gz d7f730a7100e28b3c2f4333622d108aee8a1d0d6ca41b46e2be26dd477e86284
```

A final post-release read-only disk observation records **8593379328 B game / 17516634112 B bots**. Game is only **3444736 B above the unchanged 8 GiB reserve**, so the full additive staging allowance cannot fit at that reading. No cleanup, reserve change or further staging was performed. This observation is additive after private metadata-archive sealing; archived bytes and original classifications remain unchanged.

**145 applicable Python checks and 33 final independent archive-analysis checks pass.** The additional deterministic append-race witness proves the current generated probe fails its release condition and the proposed bounded-read reference passes; this is not counted as a maintained-code fix or an additional workload. Rust unchanged: retained 240 pass/3 ignored, Clippy two old warnings, fmt/extension green; no expensive repeat. No historical analyzer replay, reclassification, issue/map/parent PLAN/BUG-LEDGER/ledger/policy edit, PR or push. Stop after this single attempt.

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
| independent_final_cleanup_verified | FAIL |
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
