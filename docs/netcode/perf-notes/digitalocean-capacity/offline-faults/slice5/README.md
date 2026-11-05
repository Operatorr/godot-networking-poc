# Slice 5 measured-window evidence

Local integration for [issue #68](https://github.com/Operatorr/godot-networking-poc/issues/68). **Not live-host validation and not a capacity finding.** Nothing here says PASS, because no scorer exists until issue #69. No account, Droplet, SSH session, paid workload or CAX11 evidence was involved.

| File | What it is | Reproducible |
| --- | --- | --- |
| [`real-windows.json`](real-windows.json) | Summaries of real `omega-server` and `omega-load-test` processes on one machine in real time, from one exact clean build | No: process ids and timings are real. `SHA256SUMS` only says these are the bytes retained |
| [`synthetic-proofs.json`](synthetic-proofs.json) | The real prover over mocked recorder files. Nothing ran, and each "60 s window" in it is arithmetic | Yes: `test_measurement_evidence` regenerates it and compares the hash |

`measurement_schema.json`, the recorders and the prover are in `scripts/do_session/` and `rust/load_test/src/measured.rs`. See [the slice 5 README section](../../../../../../scripts/do_session/README.md#two-host-measurement-window-and-recorders-slice-5).

## Provenance of the real runs
| | |
| --- | --- |
| Source revision (clean tree) | `bf0e104a5f2e09c7b6e017fcdd0d623a74ff3d1f` |
| Binaries, SHA-256 | `omega-server` `884db120ed9a0d8c06f934f4dcc6a4016a635644a3a46ac6120c1cad5e62435b`, `omega-load-test` `a0fb981e37440f94811d2489d9328cb59a14514c2623372d24984441e67e661d` |
| Fault build, SHA-256 | `omega-load-test` with `fault-injection` `952567507ff8f03d738b1ee99d01a7d2220b0f0c01e00d6695238529b06062d9`. Used only in rows marked injected |
| Build | `cargo build --release --locked -p omega-server -p omega-load-test` |
| `Cargo.lock` | `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b` |
| Server config | `deployment/server_config.loadtest.json` `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6` (with `metrics_port` and `--port` chosen per run) |
| Toolchain | rustc 1.95.0, aarch64-apple-darwin; Python 3.9.6; macOS-26.7.2-arm64-arm-64bit |
| Schema | `omega.measurement/2` `59d3d2b89a6fa356dfdf858e53fdbbcd625821546456d466c3845954afaee67a` |
Later commits on the branch touch only this directory, so the code that ran is the code at that revision.

## Full contract windows, real time

Strategy behavior, difficulty 1.0, seed 1, 30 Hz, four generator shards, 100 ms global stagger, 25 bots. Two host roots on loopback with the production adapter's arguments, the real runner and supervisor, and real clock brackets.

| Window | Status | Length (ns) | Scheduled | Sent | Worst bot | Ticks in interval | Tick numbers contiguous | ENet samples per bot (min) | Largest shard poll gap (ms) | Boundary half-width (ms) | Frames sent while dead in game |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 60 s | complete | 60000000000 | 45000 | 44999 | 0.999444 | 1802 | True | 60 | 2.0 | 34.3 | 6542 |
| 300 s | complete | 300000000000 | 225000 | 224999 | 0.999889 | 9002 | True | 299 | 12.6 | 34.7 | 29191 |

**`complete` here has limits.** Both ran with `require_counters=False`: macOS has no per-socket drop counter, so socket drops are reported as unknown (`null`), and the same proof with counters required is `inconclusive`. Both endpoints share one wall clock, so the half-width is the bracket's width and has seen no real offset between hosts. Nothing was run under load that stresses this machine; 25 bots says nothing about any host's capacity.

The whole controller path ran one more real 60 s window at the same revision, through the real registry, watchdog and executor: `test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path` passed in 74.4 s. The window proved `complete`, and the run was still recorded `INCONCLUSIVE`, with `window proof: complete` among its reasons, because nothing has scored it.

## Fault battery, real time, short holds

Each hold is 6 s, so `contract_hold` is false on every row: this shows the machinery reacting to a real fault, not a contract window. The prover refuses these lengths unless it is explicitly allowed them. Outside faults use the frozen binaries with signals and a datagram relay. Injected faults use the fault build, which names itself in `swarm.json` and so can never prove a window.

| Scenario | Fault | Status | Reasons |
| --- | --- | --- | --- |
| `short_complete` | None | complete | none |
| `short_delayed_authentication` | Relay holds one bot 4 s; the barrier waits | complete | none |
| `short_authentication_never_arrives` | Relay swallows one bot; 4 s readiness limit | invalid | `window_not_established` |
| `short_poll_starvation_in_window` | SIGSTOP swarm 1.5 s in the hold | invalid | `offered_input_below_minimum`, `poll_starvation` |
| `short_poll_starvation_through_barrier` | SIGSTOP swarm 1 s at the barrier | invalid | `poll_starvation` |
| `short_swarm_killed_in_window` | SIGKILL swarm in the hold | inconclusive | `swarm_evidence_missing` |
| `short_game_killed_in_window` | SIGKILL game in the hold | inconclusive | `collector_boundary_missing`, `recorder_truncated` |
| `short_injected_early_shard_exit` | Injected: shard 1 leaves in the hold | invalid | `fault_injection_build`, `counters_not_frozen`, `early_shard_exit`, `missing_acknowledgment`, `window_incomplete` |
| `short_injected_one_shard_starved` | Injected: shard 2 sleeps 1.2 s in the hold | invalid | `fault_injection_build`, `offered_input_below_minimum`, `poll_starvation` |
| `short_injected_shard_starved_through_barrier` | Injected: shard 3 sleeps 0.9 s at the barrier | invalid | `fault_injection_build`, `poll_starvation` |
| `short_injected_dead_but_connected_input` | Injected: bot 3 stays connected and stops sending | invalid | `fault_injection_build`, `offered_input_below_minimum` |
| `short_injected_recorder_truncated` | Injected: shard 1 never writes its footer | inconclusive | `fault_injection_build`, `recorder_truncated` |

`test_measurement_integration` adds, on those same real bytes: recorders truncated, a shard overwritten, a 37 s known wall offset that still maps, unknown offset and clock drift that cannot, a reused pid and inode, and a second real run sharing no identity with the first. Deterministic rules, including exactly-99% input and fringe population ambiguity, are in `test_measurement_window`.

## Mocked proofs

| Scenario | Status | Reasons |
| --- | --- | --- |
| `below_99_percent_input_invalid` | invalid | `offered_input_below_minimum` |
| `clock_bracket_missing` | inconclusive | `clock_mapping_missing`, `collector_boundary_missing` |
| `clock_bracket_too_wide` | inconclusive | `clock_ambiguous`, `population_boundary_ambiguous`, `collector_boundary_missing`, `server_tick_coverage` |
| `clock_drift_is_ambiguous` | inconclusive | `clock_ambiguous`, `population_boundary_ambiguous`, `collector_boundary_missing`, `server_tick_coverage` |
| `complete_300s` | complete | none |
| `complete_60s` | complete | none |
| `connected_but_not_sending_invalid` | invalid | `offered_input_below_minimum` |
| `dead_in_game_still_sending_idle_frames_valid` | complete | none |
| `early_shard_exit` | invalid | `early_shard_exit`, `window_incomplete` |
| `exactly_99_percent_input_valid` | complete | none |
| `game_socket_drop_is_a_fact_not_a_broken_window` | complete | none |
| `generator_socket_drop_invalid` | invalid | `generator_socket_drops` |
| `global_stagger_violated` | invalid | `global_stagger_violated` |
| `large_known_wall_offset_still_maps` | complete | none |
| `missing_end_acknowledgment` | invalid | `missing_acknowledgment` |
| `missing_input_counter_is_not_zero` | inconclusive | `input_record_missing` |
| `pid_reused` | inconclusive | `pid_reused` |
| `poll_starvation` | invalid | `poll_starvation` |
| `population_tick_below_n` | invalid | `population_lost_in_window` |
| `process_identity_reused_from_earlier_run` | inconclusive | `process_identity_reused` |
| `readiness_timeout_has_no_window` | invalid | `window_not_established` |
| `recorder_cut_inside_a_line` | inconclusive | `recorder_truncated` |
| `recorder_lost_its_footer` | inconclusive | `recorder_truncated` |
| `recorder_overwritten` | inconclusive | `recorder_overwritten` |
| `schema_not_the_frozen_one` | inconclusive | `schema_mismatch` |
| `server_never_finished_recorders` | inconclusive | `collector_boundary_missing`, `recorder_truncated` |
| `server_transition_missing` | inconclusive | `server_auth_evidence_missing` |
| `short_hold_refused` | inconclusive | `non_contract_hold` |
| `socket_counter_missing_is_not_zero` | inconclusive | `socket_counters_missing` |
| `socket_counter_moved_backward` | inconclusive | `socket_counter_reset` |
| `socket_inode_changed` | inconclusive | `socket_identity_changed` |
| `socket_inode_reused_from_earlier_run` | inconclusive | `socket_identity_reused` |
| `wall_clock_stepped` | inconclusive | `clock_step` |
| `warmup_violated` | invalid | `warmup_violated` |
| `window_seen_after_it_began` | invalid | `window_observed_late` |

## Commands

```bash
cd rust && cargo build --release --locked -p omega-server -p omega-load-test
cargo build --release --locked -p omega-load-test --features omega-load-test/fault-injection --target-dir <scratch>/fault-target
cd ../scripts/do_session
python3 measurement_evidence.py real --out <scratch>/out --release $PWD/../../rust/target/release --fault-release <scratch>/fault-target/release --long
python3 measurement_evidence.py synthetic --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice5
```
