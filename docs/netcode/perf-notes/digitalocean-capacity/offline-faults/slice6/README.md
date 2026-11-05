# Slice 6 scoring evidence

Offline evidence for [issue #69](https://github.com/Operatorr/godot-networking-poc/issues/69). **Not live-host validation and not a capacity finding.** No account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and no real run has ever passed this scorer. Scorer, policy and fixtures are in `scripts/do_session/`: see [the slice 6 README section](../../../../../../scripts/do_session/README.md#strict-scoring-and-search-outcomes-slice-6).

| File | What it is | Reproducible |
| --- | --- | --- |
| [`synthetic-scores.json`](synthetic-scores.json) | The real prover and scorer over 134 mocked recorder trees, each with one thing changed. Nothing ran, and each "60 s window" is arithmetic | Yes: `test_scoring_evidence` regenerates it and compares the hash |
| [`synthetic-searches.json`](synthetic-searches.json) | 44 whole searches through the real executor, registry, prover and scorer over a fake guest that exports those trees. No outcome is scripted: each comes from the bytes | Yes, likewise |
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
| A SIGKILL beside an earlier or later host OOM increment, a reset counter, or an RTT gate proven failed | `inconclusive_evidence`: the host's count is a diagnostic, and no producer names a victim |
| A Tick overrun beside a host OOM increment | `capacity_failure`, from the Ticks alone |
| Each of 21 kinds of missing generator evidence, beside a Tick overrun and beside a demonstrated panic: poll liveness, freeze and drain times, join times, frozen rows, publication, final authentication, a cut or missing coordinator or shard, the bot collector, one socket read, a socket counter | `inconclusive_evidence`, 42 scenarios |
| A ramp: timeout alone, or transport timeout alone; generator counters unproven | `inconclusive_evidence` |
| A ramp: timeout beside a proven overrun, or a kick of an authenticated bot | `capacity_failure` |
| A ramp: a kick of a bot never authenticated, which the server sends to a refused join too | `inconclusive_evidence` |
| A ramp beside a proven overrun, in each of 28 ways that are not the supervised processes or do not cover what they did: foreign swarm, game or collector pid, start or boot; a changed inode, a wrong endpoint, an unclaimed socket; a socket absent from a read or never read; no join row, port or counters for a started bot; no abort row or one that disagrees; a last read long before the abort; broken ownership | `inconclusive_evidence`, 28 scenarios |
| A ramp: poll starvation alone | `invalid_offered_load` |
| A local counter bypass; a prover never given the schema; the historical `/2` placeholder manifest; a short hold the prover was allowed; a foreign schema; a fault build | `inconclusive_evidence`, whatever the gates say |
| A host rebooted | `infrastructure_failure` |

## What the synthetic searches show

| Ending | Scenarios | Claim |
| --- | ---: | --- |
| `confirmed` | 9, and a 10th whose report withholds the claim below | The candidate on this pair, three valid passes, not provider-wide |
| `confirmed_search_cap_reached` | 1 | At least 500; not a discovered ceiling |
| `no_passing_target` | 3 | No passing target at 5-player resolution; not zero, `players` and `lower_bound` null |
| `unconfirmed_variable` | 3 | Failed at repetition 1, 2 or 3; no replacement, nothing after it |
| `unconfirmed_partial` | 1 | An interrupted confirmation; its untouched siblings ran; never confirmed |
| `stopped_*` | 20 | Invalid load, inconclusive evidence or infrastructure, across coarse, refinement and confirmation; earlier passes named as exploratory only |
| `undecidable_incomplete_predecessor` | 2 | A cut trial or one an unfrozen controller could not score, neither inferred nor replayed |
| `partial_time_exhausted` | 1 | Results kept; nothing dispatched that cannot fit |
| `in_progress` | 3 | A session collected after one decided trial, with nothing more run |

Every scenario records `no_hidden_retry`: one game start per trial. The search also covers crashes at `after_execution_record`, `after_score_retained`, `before_outcome_commit` and `after_outcome_commit`. `test_capacity_search.EveryLegalPath` walks all 401 leaves of the graph with no files.

These also pin what a search may not do with evidence it cannot trust, with each outcome coming from the real path:

| Scenario | Trials | Claim |
| --- | --- | --- |
| A Tick overrun or a panic with no poll liveness or freeze time | `INCONCLUSIVE`, no successor | Stopped |
| A panic with the generator independently proven | `FAIL`, then refinement | The search goes on, with no whole window demanded of it |
| A ramp overrun over a foreign swarm, game or collector, or a socket never read | `INCONCLUSIVE`, no refinement | Stopped |
| A foreign or edited retained score, or a foreign classification, on return | `INCONCLUSIVE`, the file left as found | `evidence_disagreement` |
| An unchanged retained score, collected with the hosts as they are | The retained outcome, not recomputed | As the journal says |
| A retained score replaced after a search had confirmed | Unchanged in the journal | `evidence_disagreement`, with `confirmed_observation` kept as `journal_claim` |
| Collect from the frozen controller, a natural end | `PASS` | As the journal says |
| Collect from an unfrozen controller, a natural end | `INCOMPLETE`, and no proof or score written | Undecidable; cleanup still requested |
| Collect from an unfrozen controller, with a retained score that holds up, or one that does not | The retained outcome, or `INCONCLUSIVE` | As the journal says, or `evidence_disagreement` |

## Real binaries, one machine

| | |
| --- | --- |
| Source revision (clean tree) | `673e17a1adcef151cafaab970dc7d17bba02fc56`, tree `429e4ec194e3838bbb6e38d88b1297e2d355321b`. These replace the summaries from `e0d9b29`, which are in this file's history and tested the scorer before these fixes |
| Binaries, SHA-256 | `omega-server` `d574418be9edfec3f3a34e7bd363bcd5e4f80e146a4fc03056db35760a85ef19`, `omega-load-test` `12f1b36c75963fbda790a99218977c2b97210835069c95c9ff840a4ba8352e81` |
| Binary origin | **Not rebuilt.** The same hashes retained in [slice 5](../slice5/README.md), built from `f1f6188`. This slice changes no `rust/` file and `a4265a1` changed none after `f1f6188` |
| `Cargo.lock` | `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b` |
| Server config | `deployment/server_config.loadtest.json` `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6` |
| Platform | macOS-26.7.2-arm64-arm-64bit, Python 3.9.6 |
| Schema | `omega.measurement/3` `dac9395161b89090cf71315e52250cd22efba19f5680beed47fc6ca70a32e0be`, unchanged |
| Scorer policy | `omega.do-session.capacity-scorer/1` `29c024c22e2478cce0f65a77cd9f3e40a54827d35b68f471680f0018acc897fa` |
| Sandbox | All of it under `scripts/do_session/measurement_offline.sb`. That profile was probed for the earlier summaries: a sent UDP datagram and a TCP connect to `192.0.2.1` and a resolver lookup were refused, and loopback UDP and `/bin/ps` worked. The probe was not repeated for this rerun |

Commits after that revision change only this directory. The prover ran with `require_counters=False`, because macOS has no per-socket drop counter, and the scorer refuses that. **So every row is `inconclusive_evidence` by construction.** These runs check the producers' real units and reasons. They cannot show a pass.

| Scenario | Proof | Continuity | Errors | Ticks over / narrow..wide | RTT p95 (samples) | ENet loss peak | Sent / scheduled, worst bot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `contract_60s_25_bots` | complete | pass | pass | 0 / 1798..1802 | 3.0 ms (1499) | 0/1, 1 borrowed | 45000 / 45000, 1/1 |
| `short_complete_8_bots`, 6 s | complete | pass | pass | 0 / 178..182 | 3.0 ms (48) | 0/1, 0 borrowed | 1438 / 1440, 179/180 |
| `one_bot_path_blocked_mid_window`, 20 s | invalid | **fail** | fail, 1 error that is the disconnect itself | 0 / 598..602 | 4.0 ms (148) | 101/262144 | 4438 / 4800, 239/600 |
| `game_killed_mid_window`, 20 s | invalid | **fail** | fail, 8 errors that are the disconnects themselves | unknown | 3.0 ms (60) | 1757/524288, 6 borrowed, later seconds unknown | 1873 / 4800, 73/200 |
| `swarm_paused_mid_window`, 6 s | invalid | pass | pass | 0 / 178..182 | 3.0 ms (36) | 0/1, 12 borrowed | 1087 / 1440, 3/4 |
| `authentication_never_arrives`, 4 s bound | invalid | unknown | unknown | 0 of 134 ramp Ticks | none | none | none |

What these confirm on real bytes:

- **RTT is whole milliseconds** (3.0), and real ENet loss is non-zero once something goes wrong, on the 65536 scale.
- **A blocked path records reason 0 on both the bot and the server.** In this run the bot saw it between 484 and 554 ms after the mapped server event, so the order is `server_first`. In the earlier run the same interval straddled zero and the order was `unresolved`. Either way, the cause stays `transport_timeout_unattributed`. Its input floor still held, at 239/600 of the whole window, because frames after the disconnect are not owed.
- **A real SIGKILL leaves `killed_with_no_cause_on_record`.** Every bot timed out with reason 0, and the exit says nothing. This platform has no OOM count, and on any platform that host-wide count would stay a diagnostic. The server's missing data left the generator's own evidence unaffected: of its reasons, `recorder_truncated` and `collector_boundary_missing` are the game's, and only the absent socket counters leave the generator unproven.
- **A real stalled swarm is the generator's:** `poll_starvation` and `offered_input_below_minimum`, in `independent_failures`.
- **A real readiness timeout stays no capacity limit,** with a generator that cannot be proven here anyway. The ramp's identity and coverage checks read real bytes for it: the swarm, the game and both collectors were recognized as the supervised processes, the coordinator's abort row was read, all 8 started bots were found with their sockets, and the only reason is `window_not_established`.

The real controller path also runs one 60 s window through `test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path`, with the same refusal in its `score.json`. It is not retained here.

## Not shown anywhere here

A real pass; Linux `/proc` socket and OOM counters; any process-attributed OOM evidence, which no producer writes yet; independent-host clocks; public routes; SSH or systemd; generator headroom under real load; a real server kick, since nothing in the real workload triggers one, so that case rests on the traced source and the mocked trees; and any host's capacity.
