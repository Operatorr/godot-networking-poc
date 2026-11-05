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
| Source revision (clean tree) | `f1f6188f87b7787fbe3cb196b81cc554b8eb92de`, tree `6fc25bbb48ae03d745813321050632e5b804516b` |
| Binaries, SHA-256 | `omega-server` `d574418be9edfec3f3a34e7bd363bcd5e4f80e146a4fc03056db35760a85ef19`, `omega-load-test` `12f1b36c75963fbda790a99218977c2b97210835069c95c9ff840a4ba8352e81` |
| Fault build, SHA-256 | `omega-load-test` with `fault-injection` `a5ba66d9ed3d19feabb90e80a1319229ebccf1bc31a705af204fe2166e27cb3a`. Used only in rows marked injected and in `short_fault_build_with_nothing_injected` |
| Build | `cargo build --release --locked -p omega-server -p omega-load-test` |
| `Cargo.lock` | `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b` |
| Server config | `deployment/server_config.loadtest.json` `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6` (with `metrics_port` and `--port` chosen per run) |
| Toolchain | rustc 1.95.0 (59807616e 2026-04-14), aarch64-apple-darwin; Python 3.9.6; macOS-26.7.2-arm64-arm-64bit |
| Schema | `omega.measurement/3` `dac9395161b89090cf71315e52250cd22efba19f5680beed47fc6ca70a32e0be` |
| Sandbox | All of it under `scripts/do_session/measurement_offline.sb`: non-loopback sends and the resolver refused, `/bin/ps` allowed |

Commits after that revision change only documentation, this evidence and one test, so the code that ran is the code at that revision.

**What these replace.** The summaries retained at `60806b6` came from `bf0e104`, with `omega.measurement/2` binaries. Their recorders stamped events at poll entry and read socket counters inside an unbracketed interval, so their proofs do not stand for this source. They remain in Git history and nothing here relies on them.

## Full contract windows, real time

Strategy behavior, difficulty 1.0, seed 1, 30 Hz, four generator shards, 100 ms global stagger, 25 bots. Two host roots on loopback with the production adapter's arguments, the real runner and supervisor, and real clock brackets.

| Window | Status | Length (ns) | Scheduled | Sent | Worst bot | Ticks in interval | Tick numbers contiguous | ENet samples per bot (min) | Largest shard poll gap (ms) | Boundary half-width (ms) | Frames sent while dead in game |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 60 s | complete | 60000000000 | 45000 | 45000 | 1.000000 | 1802 | True | 60 | 2.0 | 35.0 | 5456 |
| 300 s | complete | 300000000000 | 225000 | 224998 | 0.999889 | 9002 | True | 299 | 2.8 | 35.0 | 28347 |

**`complete` here has limits.** Both ran with `require_counters=False`: macOS has no per-socket drop counter, so socket drops are reported as unknown (`null`), and the same proof with counters required is `inconclusive`. That setting is local only; the production executor requires counters, and on a host without them its proof stays `inconclusive`. Both endpoints share one wall clock, so the half-width is the bracket's width and has seen no real offset between hosts. Nothing was run under load that stresses this machine; 25 bots says nothing about any host's capacity.

The whole controller path ran one more real 60 s window at the same revision and binaries, through the real registry, watchdog and executor: `test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path` passed in 73.3 s. The run was still recorded `INCONCLUSIVE`, because nothing has scored it.

## Fault battery, real time, short holds

Each hold is 6 s, so `contract_hold` is false on every row: this shows the machinery reacting to a real fault, not a contract window. The prover refuses these lengths unless it is explicitly allowed them. Outside faults use the frozen binaries with signals and a datagram relay. Injected faults use the fault build, which states so in `swarm.json` with or without a `--fault`, and so can never prove a window.

| Scenario | Fault | Status | Reasons |
| --- | --- | --- | --- |
| `short_complete` | None | complete | none |
| `short_delayed_authentication` | Relay holds one bot 4 s; the barrier waits | complete | none |
| `short_warmup_runs_past_the_readiness_bound` | All 8 in early against a 2 s bound; the warmup runs past it | complete | none |
| `short_final_authentication_near_the_readiness_bound` | Relay holds one bot 3 s against a 4 s bound; the warmup runs past it | complete | none |
| `short_authentication_never_arrives` | Relay swallows one bot; 4 s readiness limit | invalid | `window_not_established` |
| `short_poll_starvation_in_window` | SIGSTOP swarm 1.5 s in the hold | invalid | `offered_input_below_minimum`, `poll_starvation` |
| `short_poll_starvation_through_barrier` | SIGSTOP swarm 1 s at the barrier | invalid | `poll_starvation` |
| `short_swarm_killed_in_window` | SIGKILL swarm in the hold | inconclusive | `swarm_evidence_missing` |
| `short_game_killed_in_window` | SIGKILL game in the hold | inconclusive | `collector_boundary_missing`, `recorder_truncated` |
| `short_fault_build_with_nothing_injected` | Fault build, no `--fault`: the window ran clean and the binary alone is refused | inconclusive | `fault_injection_build` |
| `short_injected_early_shard_exit` | Injected: shard 1 leaves in the hold | invalid | `counters_not_frozen`, `early_shard_exit`, `fault_injection_build`, `missing_acknowledgment`, `window_incomplete` |
| `short_injected_one_shard_starved` | Injected: shard 2 sleeps 1.2 s in the hold | invalid | `fault_injection_build`, `offered_input_below_minimum`, `poll_starvation` |
| `short_injected_shard_starved_through_barrier` | Injected: shard 3 sleeps 0.9 s at the barrier | invalid | `fault_injection_build`, `poll_starvation` |
| `short_injected_dead_but_connected_input` | Injected: bot 3 stays connected and stops sending | invalid | `fault_injection_build`, `offered_input_below_minimum` |
| `short_injected_recorder_truncated` | Injected: shard 1 never writes its footer | inconclusive | `fault_injection_build`, `recorder_truncated` |

`test_measurement_integration` adds, on those same real bytes: recorders truncated, a shard overwritten, a 37 s known wall offset that still maps, unknown offset and clock drift that cannot, a reused pid and inode, a second real run sharing no identity with the first, every real recorder stating its schema and role, and every real collector row bracketing its counter read. It passed at this revision with 29 tests run and 2 skipped, the two skips being the long windows retained above. Deterministic rules, including exactly-99% input, reads straddling each boundary on both roles, and fringe population ambiguity, are in `test_measurement_window`.

## Mocked proofs

| Scenario | Status | Reasons |
| --- | --- | --- |
| `below_99_percent_input_invalid` | invalid | `offered_input_below_minimum` |
| `build_not_stated` | inconclusive | `build_unstated` |
| `clock_bracket_missing` | inconclusive | `clock_mapping_missing`, `collector_boundary_missing` |
| `clock_bracket_too_wide` | inconclusive | `clock_ambiguous`, `collector_boundary_missing`, `population_boundary_ambiguous`, `server_tick_coverage` |
| `clock_drift_is_ambiguous` | inconclusive | `clock_ambiguous`, `collector_boundary_missing`, `population_boundary_ambiguous`, `server_tick_coverage` |
| `complete_300s` | complete | none |
| `complete_60s` | complete | none |
| `connected_but_not_sending_invalid` | invalid | `offered_input_below_minimum` |
| `counter_read_straddling_end_is_not_a_final_read` | inconclusive | `collector_boundary_missing` |
| `counter_read_straddling_start_counts_its_drop` | invalid | `generator_socket_drops` |
| `counter_rows_without_a_read_bracket` | inconclusive | `collector_boundary_missing` |
| `dead_in_game_still_sending_idle_frames_valid` | complete | none |
| `early_shard_exit` | invalid | `early_shard_exit`, `window_incomplete` |
| `exactly_99_percent_input_valid` | complete | none |
| `fault_build_with_nothing_injected` | inconclusive | `fault_injection_build` |
| `foreign_process_schema` | inconclusive | `collector_boundary_missing`, `schema_mismatch` |
| `foreign_shard_schema` | inconclusive | `schema_mismatch` |
| `foreign_swarm_schema` | inconclusive | `schema_mismatch` |
| `frames_missing_only_after_a_disconnect` | invalid | `population_lost_in_window` |
| `freeze_with_no_time` | inconclusive | `freeze_time_missing` |
| `frozen_before_the_end` | inconclusive | `frozen_before_end`, `frozen_before_end_acknowledgment` |
| `game_counter_read_straddling_start_counts_its_drop` | complete | none |
| `game_socket_drop_is_a_fact_not_a_broken_window` | complete | none |
| `generator_socket_drop_invalid` | invalid | `generator_socket_drops` |
| `global_stagger_violated` | invalid | `global_stagger_violated` |
| `large_known_wall_offset_still_maps` | complete | none |
| `missing_end_acknowledgment` | invalid | `missing_acknowledgment` |
| `missing_error_counters_are_not_zero` | inconclusive | `input_record_missing` |
| `missing_final_schema` | inconclusive | `collector_boundary_missing`, `schema_mismatch` |
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
| `zero_input_before_a_server_disconnect_stays_visible` | invalid | `offered_input_below_minimum`, `population_lost_in_window` |

## Commands

```bash
cd rust && cargo build --release --locked -p omega-server -p omega-load-test
cargo build --release --locked -p omega-load-test --features omega-load-test/fault-injection --target-dir <scratch>/fault-target
cd ../scripts/do_session
sandbox-exec -f measurement_offline.sb python3 measurement_evidence.py real --out <scratch>/out --release $PWD/../../rust/target/release --fault-release <scratch>/fault-target/release --long
python3 measurement_evidence.py synthetic --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice5
```
