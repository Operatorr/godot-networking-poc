# Slice 6 scoring evidence

Offline evidence for [issue #69](https://github.com/Operatorr/godot-networking-poc/issues/69). **Not live-host validation and not a capacity finding.** No account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and no real run has ever passed this scorer. Scorer, policy and fixtures are in `scripts/do_session/`: see [the slice 6 README section](../../../../../../scripts/do_session/README.md#strict-scoring-and-search-outcomes-slice-6).

| File | What it is | Reproducible |
| --- | --- | --- |
| [`synthetic-scores.json`](synthetic-scores.json) | The real prover and scorer over 58 mocked recorder trees, each with one thing changed. Nothing ran, and each "60 s window" is arithmetic | Yes: `test_scoring_evidence` regenerates it and compares the hash |
| [`synthetic-searches.json`](synthetic-searches.json) | 26 whole searches through the real executor, registry, prover and scorer over a fake guest that exports those trees. No outcome is scripted: each comes from the bytes | Yes, likewise |
| [`real-local-scores.json`](real-local-scores.json) | The real scorer over real `omega-server` and `omega-load-test` bytes on one machine | No: timings are real. `SHA256SUMS` only says these are the bytes retained |

Raw recorder files are not retained here. The real generator deletes its temporary run directories, so its rows are summaries that cannot be replayed from this directory.

## What the synthetic scores show

Each boundary is tested on both sides, and every comparison keeps its exact count or fraction.

| Scenario | Classification |
| --- | --- |
| A Tick of exactly 33.3 ms; 17 of 1800 Ticks over; RTT 149.999 ms; 24 of 480 samples high; loss just under 2%; input exactly 99% | `valid_pass` |
| Exactly 18 of 1800 Ticks over; RTT exactly 150 ms; 25 of 480 samples high; loss exactly 1/50 in one second; a one-second excursion in a fine average; a game-socket drop proven inside | `capacity_failure` |
| One frame below 99%; a generator socket drop; a bot panic; a poll stall alone | `invalid_offered_load` |
| Tick ratio that depends on where the clocks put the window; a drop that may be just outside; missing RTT, loss or socket counters; a decode failure | `inconclusive_evidence` |
| Three slow bots: an average of per-bot p95s would pass, and the pool fails | `capacity_failure` |
| Two briefly slow bots: an average of per-bot p95s would fail, and the pool passes | `valid_pass` |
| A kick with a healthy generator; a kick seen late with frames missing only after it; a transport timeout beside a Tick overrun; a panic or segfault | `capacity_failure` |
| A kick after independent starvation, or starvation before a late-seen kick; a stall beside an overrun | `inconclusive_evidence`, with both failures still listed |
| A transport timeout alone; a server row the bot never saw; N lost with no account of who; SIGKILL or exit 0 with no cause on record; a `SERVER_SHUTDOWN` or duplicate-session reason | `inconclusive_evidence` |
| A ramp: timeout alone, or transport timeout alone; generator counters unproven | `inconclusive_evidence` |
| A ramp: timeout beside a proven overrun, or a kick | `capacity_failure` |
| A ramp: poll starvation alone | `invalid_offered_load` |
| A local counter bypass; a prover never given the schema; the historical `/2` placeholder manifest; a short hold the prover was allowed; a foreign schema; a fault build | `inconclusive_evidence`, whatever the gates say |
| A host rebooted | `infrastructure_failure` |

## What the synthetic searches show

| Ending | Scenarios | Claim |
| --- | ---: | --- |
| `confirmed` | 8 | The candidate on this pair, three valid passes, not provider-wide |
| `confirmed_search_cap_reached` | 1 | At least 500; not a discovered ceiling |
| `no_passing_target` | 2 | No passing target at 5-player resolution; not zero, `players` and `lower_bound` null |
| `unconfirmed_variable` | 3 | Failed at repetition 1, 2 or 3; no replacement, nothing after it |
| `unconfirmed_partial` | 1 | An interrupted confirmation; its untouched siblings ran; never confirmed |
| `stopped_*` | 9 | Invalid load, inconclusive evidence or infrastructure, across coarse, refinement and confirmation; earlier passes named as exploratory only |
| `undecidable_incomplete_predecessor` | 1 | A cut trial, neither inferred nor replayed; resume refused |
| `partial_time_exhausted` | 1 | Results kept; nothing dispatched that cannot fit |

Every scenario records `no_hidden_retry`: one game start per trial. The search also covers crashes at `after_execution_record`, `after_score_retained`, `before_outcome_commit` and `after_outcome_commit`. `test_capacity_search.EveryLegalPath` walks all 401 leaves of the graph with no files.

## Real binaries, one machine

| | |
| --- | --- |
| Source revision (clean tree) | `e0d9b29dde12394db63221548b5b4c1f92328d04`, tree `a595426d82555e29ad0362ce56a25820c6cd44e5` |
| Binaries, SHA-256 | `omega-server` `d574418be9edfec3f3a34e7bd363bcd5e4f80e146a4fc03056db35760a85ef19`, `omega-load-test` `12f1b36c75963fbda790a99218977c2b97210835069c95c9ff840a4ba8352e81` |
| Binary origin | **Not rebuilt.** The same hashes retained in [slice 5](../slice5/README.md), built from `f1f6188`. This slice changes no `rust/` file and `a4265a1` changed none after `f1f6188` |
| `Cargo.lock` | `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b` |
| Server config | `deployment/server_config.loadtest.json` `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6` |
| Platform | macOS-26.7.2-arm64-arm-64bit, Python 3.9.6 |
| Schema | `omega.measurement/3` `dac9395161b89090cf71315e52250cd22efba19f5680beed47fc6ca70a32e0be`, unchanged |
| Scorer policy | `omega.do-session.capacity-scorer/1` `c7466422b1175b96fde5844ee703742926f9588efb2f8bf6a177dcc5c559817f` |
| Sandbox | All of it under `scripts/do_session/measurement_offline.sb`. Probed before use: a sent UDP datagram and a TCP connect to `192.0.2.1` and a resolver lookup were refused, and loopback UDP and `/bin/ps` worked |

Commits after that revision change only this directory. The prover ran with `require_counters=False`, because macOS has no per-socket drop counter, and the scorer refuses that. **So every row is `inconclusive_evidence` by construction.** These runs check the producers' real units and reasons. They cannot show a pass.

| Scenario | Proof | Continuity | Errors | Ticks over / narrow..wide | RTT p95 (samples) | ENet loss peak | Sent / scheduled, worst bot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `contract_60s_25_bots` | complete | pass | pass | 0 / 1798..1802 | 3.0 ms (1500) | 0/1, 0 borrowed | 44991 / 45000, 1799/1800 |
| `short_complete_8_bots`, 6 s | complete | pass | pass | 0 / 178..182 | 3.0 ms (48) | 0/1, 0 borrowed | 1439 / 1440, 179/180 |
| `one_bot_path_blocked_mid_window`, 20 s | invalid | **fail** | fail, 1 error that is the disconnect itself | 0 / 598..602 | 3.0 ms (148) | 101/262144 | 4440 / 4800, 2/5 |
| `game_killed_mid_window`, 20 s | invalid | **fail** | fail, 8 errors that are the disconnects themselves | unknown | 3.0 ms (60) | 1715/524288, later seconds unknown | 1831 / 4800, 109/300 |
| `swarm_paused_mid_window`, 6 s | invalid | pass | pass | 0 / 178..182 | 3.0 ms (36) | 0/1, 12 borrowed | 1081 / 1440, 67/90 |
| `authentication_never_arrives`, 4 s bound | invalid | unknown | unknown | 0 of 134 ramp Ticks | none | none | none |

What these confirm on real bytes:

- **RTT is whole milliseconds** (3.0), and real ENet loss is non-zero once something goes wrong, on the 65536 scale.
- **A blocked path records reason 0 on both the bot and the server.** The bot saw it between 20.8 ms before and 50.9 ms after the mapped server event, so the order is `unresolved` and the cause stays `transport_timeout_unattributed`. Its input floor still held, at 2/5 of the whole window, because frames after the disconnect are not owed.
- **A real SIGKILL leaves `killed_with_no_cause_on_record`.** Every bot timed out with reason 0, and with no OOM count on record the exit says nothing.
- **A real stalled swarm is the generator's:** `poll_starvation` and `offered_input_below_minimum`, in `independent_failures`.
- **A real readiness timeout stays no capacity limit,** with a generator that cannot be proven here anyway.

The real controller path also ran one 60 s window through `test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path`, whose `score.json` showed the same refusal. It is not retained here.

## Not shown anywhere here

A real pass; Linux `/proc` socket and OOM counters; independent-host clocks; public routes; SSH or systemd; generator headroom under real load; a real server kick, since nothing in the real workload triggers one, so that case rests on the traced source and the mocked trees; and any host's capacity.
