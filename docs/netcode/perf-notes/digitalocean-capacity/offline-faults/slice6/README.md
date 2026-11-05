# Slice 6 scoring evidence

Offline evidence for [issue #69](https://github.com/Operatorr/godot-networking-poc/issues/69). **Not live-host validation and not a capacity finding.** No account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and no real run has ever passed this scorer. Scorer, policy and fixtures are in `scripts/do_session/`: see [the slice 6 README section](../../../../../../scripts/do_session/README.md#strict-scoring-and-search-outcomes-slice-6).

| File | What it is | Reproducible |
| --- | --- | --- |
| [`synthetic-scores.json`](synthetic-scores.json) | The real prover and scorer over 179 mocked recorder trees, each with one thing changed. Nothing ran, and each "60 s window" is arithmetic | Yes: `test_scoring_evidence` regenerates it and compares the hash |
| [`synthetic-searches.json`](synthetic-searches.json) | 88 whole searches through the real executor, registry, prover and scorer over a fake guest that exports those trees. No outcome is scripted: each comes from the bytes | Yes, likewise |
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
| A SIGKILL beside an earlier or later host OOM increment, a reset counter, or an RTT gate proven failed | `inconclusive_evidence`: the host's count is a diagnostic |
| A SIGKILL with one kill counted local to the game's own cgroup leaf, bound to the sealed processes. Whatever became of the sampler: dead too, or counted at the same read (`game_oom_the_sampler_died_too`, `game_oom_the_sampler_was_counted_at_the_same_read`) | `capacity_failure`, `out_of_memory`, mid-window or in a proven ramp |
| The same kill, in each of 36 ways it is less than that: another process, pid or boot; another supervisor, invocation or unit; a shared cgroup; a member elsewhere; the sampler or supervisor in the game's leaf, or the game left in the unit; a leaf not of the unit, or not fresh; a stranger in the leaf at any read; a kill counted only elsewhere in the unit, which is the one the sampler leaves; no kill, two kills, a kill only after the reap, or another after it; a group kill; a counter that restarted or went back; a read that failed; reads out of order; another exit; no unit of its own; another schema, or the old unit-wide one | `inconclusive_evidence`, `killed_with_no_cause_on_record`, 36 scenarios |
| A matched OOM kill in a ramp whose last read came before the abort | `inconclusive_evidence`: the generator stays unproven |
| A ramp overflow on a read after the abort, beside an overrun | `inconclusive_evidence`, with both failures still listed |
| A Tick overrun beside a host OOM increment | `capacity_failure`, from the Ticks alone |
| Each of 21 kinds of missing generator evidence, beside a Tick overrun and beside a demonstrated panic: poll liveness, freeze and drain times, join times, frozen rows, publication, final authentication, a cut or missing coordinator or shard, the bot collector, one socket read, a socket counter | `inconclusive_evidence`, 42 scenarios |
| A ramp: timeout alone, or transport timeout alone; generator counters unproven | `inconclusive_evidence` |
| A ramp: timeout beside a proven overrun, or a kick of an authenticated bot | `capacity_failure` |
| A ramp: a kick of a bot never authenticated, which the server sends to a refused join too | `inconclusive_evidence` |
| A ramp beside a proven overrun, in each of 31 ways that are not the supervised processes or do not cover what they did: foreign swarm, game or collector pid, start or boot; a changed inode, a wrong endpoint, an unclaimed socket; a socket absent from a read or never read, or gone by the read after the abort; no join row, port or counters for a started bot; no abort row or one that disagrees; a last read before the abort, however close, or one the clocks allow on either side of it; broken ownership | `inconclusive_evidence`, 31 scenarios |
| A ramp: poll starvation alone | `invalid_offered_load` |
| A local counter bypass; a prover never given the schema; the historical `/2` placeholder manifest; a short hold the prover was allowed; a foreign schema; a fault build | `inconclusive_evidence`, whatever the gates say |
| A host rebooted | `infrastructure_failure` |

## What the synthetic searches show

| Ending | Scenarios | Claim |
| --- | ---: | --- |
| `confirmed` | 9, and 2 more whose reports withhold the claim below | The candidate on this pair, three valid passes, not provider-wide |
| `confirmed_search_cap_reached` | 1 | At least 500; not a discovered ceiling |
| `no_passing_target` | 5 | No passing target at 5-player resolution; not zero, `players` and `lower_bound` null |
| `unconfirmed_variable` | 3 | Failed at repetition 1, 2 or 3; no replacement, nothing after it |
| `unconfirmed_partial` | 1 | An interrupted confirmation; its untouched siblings ran; never confirmed |
| `stopped_*` | 36 | Invalid load, inconclusive evidence or infrastructure, across coarse, refinement and confirmation; earlier passes named as exploratory only |
| `undecidable_incomplete_predecessor` | 5 | A cut trial or one an unfrozen controller could not score, neither inferred nor replayed |
| `partial_time_exhausted` | 1 | Results kept; nothing dispatched that cannot fit |
| `in_progress` | 23 | A session collected or resumed after one decided trial, with nothing more run |
| `awaiting_confirmation_outcome` | 2 | A first confirmation left undecided by a comparison that never said how it ended; its siblings never start |

Every scenario records `no_hidden_retry`: one game start per trial. The search also covers crashes at `after_execution_record`, `after_score_retained`, `before_outcome_commit` and `after_outcome_commit`. `test_capacity_search.EveryLegalPath` walks all 401 leaves of the graph with no files.

These also pin what a search may not do with evidence it cannot trust, with each outcome coming from the real path:

| Scenario | Trials | Claim |
| --- | --- | --- |
| A Tick overrun or a panic with no poll liveness or freeze time | `INCONCLUSIVE`, no successor | Stopped |
| A panic with the generator independently proven | `FAIL`, then refinement | The search goes on, with no whole window demanded of it |
| A ramp overrun over a foreign swarm, game or collector, or a socket never read | `INCONCLUSIVE`, no refinement | Stopped |
| A ramp overrun, a kick or a server crash with the last read just before the abort, or a Tick overrun with it possibly before, or a socket gone by the read after it | `INCONCLUSIVE`, no refinement | Stopped |
| Corrupt bytes on a return, beside an intact retained score or classification, with or without a second crash and a transfer that works again; in a confirmation too | `INFRASTRUCTURE_FAILURE`, resume refused, the siblings never dispatched. The earlier files stay as written and the verdict names them | The stop, with `evidence.verified` false, `hard_facts` and `superseded_decisions` in the row |
| Corrupt bytes found after the outcome was committed, on a return or by recovery at wrap-up | The outcome stays; the session is terminal, and resume refuses | `evidence_disagreement`, with what the journal claimed kept apart |
| A transfer that cannot run, beside an intact retained score or a committed outcome | The decision stands | As the journal says, and no terminal failure |
| An OOM kill counted in the game's own leaf, with or without the sampler's beside it | `FAIL`, then refinement | The search goes on |
| An OOM kill of a reused pid, or in a shared cgroup, or counted only elsewhere in the unit | `INCONCLUSIVE`, no refinement | Stopped |
| A seal that comes back with the wrong hash after the commit, with or without a crash after the fact is written and a transfer that works again | The outcome stays; the session is terminal, resume refused, one game start, receipt and bytes kept | `evidence_disagreement` |
| A `record_batch_stop` that fails beside that fact | `terminal_fact_unacknowledged` from both resume and dispatch, one game start, registry not terminal, and the next controller replays it first | `evidence_disagreement` |
| A terminal fact naming another session, manifest and run | `stop_record_unverified`, resume refused, one game start, registry **not** terminal | `evidence_disagreement`, listed under `unverified_stop_records` and not `hard_facts` |
| A seal or raw file that failed its hash, with a crash after the observation and before its bytes, and a transfer that works again | `stop_record_unverified` from both resume and dispatch, one game start, registry **not** terminal, and the outcome stays | `evidence_disagreement` |
| The same with a crash after the bytes and before any fact, or a fact whose own fsync failed beside a registry that did not answer | Resume and dispatch refuse with `terminal_failure`: the observation is replayed first, one game start, and the outcome stays | `evidence_disagreement`, with the observation in `hard_facts` |
| The same bytes before any outcome was committed, with a crash after they were kept | `INFRASTRUCTURE_FAILURE`, one game start, whatever the working transfer later brings | The stop |
| The same before any outcome, with a crash before they were kept | The run stays undecided behind the comparison that never ended, and `stop_record_unverified` stops anything after it | `evidence_disagreement` |
| A first confirmation whose run-directory `os.fsync` fails while corrupt bytes are written down, then a crash and the loss of only the two new names that sync did not cover, then a transfer that works again | `stop_record_unverified` from both resume and dispatch, four game starts, siblings never started, registry **not** terminal, and the run undecided: the guard outside the run directory is still there | `evidence_disagreement` |
| A crash inside a comparison, with good bytes | The same refusal, one game start: nothing can tell it from the case above | `evidence_disagreement` |
| No validation guard can be established, with corrupt bytes on the way | `directory_not_durable`, nothing compared or kept, no fact, registry **not** terminal, cleanup requested | Undecidable |
| A status reply naming another seal digest or another session, with the good seal still on the guest and the older receipt still true | No comparison, no receipt, no fact: resume goes on, one game start, registry **not** terminal | As the journal says |
| A good seal called corrupt under a digest the older receipt contradicts, told as a terminal fact or a reconciled execution generation | `stop_record_unverified`, one game start, registry **not** terminal, and the outcome stays | `evidence_disagreement` |
| A retained score holding a JSON integer too large for a float | Refused and rendered with no exception, `INCONCLUSIVE`, one game start, the file left as found, and no false infrastructure stop | `evidence_disagreement` |
| A terminal fact or execution record of no known shape, such as a list for an outcome, on a return or at an already running dispatch | `stop_record_unverified`, one game start, registry **not** terminal: no exception and no false infrastructure stop | `evidence_disagreement`, rendered, and listed under `unverified_stop_records` |
| A foreign or edited retained score, or a foreign classification, on return | `INCONCLUSIVE`, the file left as found | `evidence_disagreement` |
| An unchanged retained score, collected with the hosts as they are | The retained outcome, not recomputed | As the journal says |
| A retained score replaced after a search had confirmed | Unchanged in the journal | `evidence_disagreement`, with `confirmed_observation` kept as `journal_claim` |
| Collect from the frozen controller, a natural end | `PASS` | As the journal says |
| Collect from an unfrozen controller, a natural end | `INCOMPLETE`, and no proof or score written | Undecidable; cleanup still requested |
| Collect from an unfrozen controller, with a retained score that holds up, or one that does not | The retained outcome, or `INCONCLUSIVE` | As the journal says, or `evidence_disagreement` |

## Real binaries, one machine

| | |
| --- | --- |
| Source revision (clean tree) | `0d99d4eedc96fba51e479c8f3c69e2bf76d90f7c`, tree `acbc0a78b790d4a5056619cadd2d10b93e745916`. These replace the summaries from `673e17a` and `e0d9b29`, which are in this file's history and tested the scorer and the swarm before these fixes |
| Binaries, SHA-256 | `omega-server` `d574418be9edfec3f3a34e7bd363bcd5e4f80e146a4fc03056db35760a85ef19`, `omega-load-test` `599a735d6253b077863573486dc11cf7f38b12c7b6a2d6dd503512e323f7c82a` |
| Binary origin | **Rebuilt** from the revision above with `cargo build --release --offline`, because a swarm that gives up now holds its sockets for a last counter read. `omega-server` came out with the hash [slice 5](../slice5/README.md) retains from `f1f6188`, and no server code changed. Slice 5's `omega-load-test` is the older one, and its summaries stay what they were: a held window never reaches the new path |
| `Cargo.lock` | `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b` |
| Server config | `deployment/server_config.loadtest.json` `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6` |
| Platform | macOS-26.7.2-arm64-arm-64bit, Python 3.9.6 |
| Schema | `omega.measurement/3` `dac9395161b89090cf71315e52250cd22efba19f5680beed47fc6ca70a32e0be`, unchanged |
| Scorer policy | `omega.do-session.capacity-scorer/1` `042bdbbd8a2ca1639c694750abc33f70a286273d864d5623a26ecf476edbadbb` |
| Sandbox | All of it under `scripts/do_session/measurement_offline.sb`. That profile was probed for the earlier summaries: a sent UDP datagram and a TCP connect to `192.0.2.1` and a resolver lookup were refused, and loopback UDP and `/bin/ps` worked. The probe was not repeated for this rerun |

**These summaries are historical for the scorer and controller that followed them.** They were made at that revision, under policy `042bdbb…`, and were not rerun for the later fixes to recovery and OOM attribution. No Rust changed, so the binaries are still these. The later fixes do not reach them: these runs use a process group and no unit, so they have no leaf and no OOM evidence at all, and none is a committed-run recovery. Their `scorer` and `policy_sha256` say what made them. The current policy is in `synthetic-scores.json`.

Commits straight after that revision changed only this directory. Every row is a real run again, so each number moved from the last refresh. **This refresh ran while unrelated work loaded the machine, at a load average of about 40.** That is why the clock intervals are wider and RTT is higher than before, and none of it is a measurement of anything. No classification moved. The prover ran with `require_counters=False`, because macOS has no per-socket drop counter, and the scorer refuses that. **So every row is `inconclusive_evidence` by construction.** These runs check the producers' real units and reasons. They cannot show a pass.

| Scenario | Proof | Continuity | Errors | Ticks over / narrow..wide | RTT p95 (samples) | ENet loss peak | Sent / scheduled, worst bot |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `contract_60s_25_bots` | complete | pass | pass | 0 / 1788..1812 | 4.0 ms (1498) | 353/1638400, 2 borrowed | 44999 / 45000, 1799/1800 |
| `short_complete_8_bots`, 6 s | complete | pass | pass | 0 / 174..186 | 4.0 ms (47) | 0/1, 1 borrowed | 1440 / 1440, 1/1 |
| `one_bot_path_blocked_mid_window`, 20 s | invalid | **fail** | fail, 1 error that is the disconnect itself | 0 / 595..605 | 8.0 ms (147) | 113/262144, 2 borrowed | 4454 / 4800, 127/300 |
| `game_killed_mid_window`, 20 s | invalid | **fail** | fail, 8 errors that are the disconnects themselves | unknown | 3.0 ms (62) | 277/81920, 7 borrowed, later seconds unknown | 1938 / 4800, 73/200 |
| `swarm_paused_mid_window`, 6 s | invalid | pass | pass | 0 / 172..188 | 3.0 ms (35) | 0/1, 13 borrowed | 1087 / 1440, 3/4 |
| `authentication_never_arrives`, 4 s bound | invalid | unknown | unknown | 0 of 134 ramp Ticks | none | none | none |

What these confirm on real bytes:

- **RTT is whole milliseconds** (3.0 to 8.0 here), and real ENet loss moves on the 65536 scale, in the healthy 60 s run too on this loaded machine, where its peak of 353/1638400 stayed far under the gate.
- **A blocked path records reason 0 on both the bot and the server.** In this run the order is `server_first`, with the bot seeing it between 1118 and 1282 ms after the mapped server event. The same path has given every order across runs, so nothing rests on it. Whichever it is, the cause stays `transport_timeout_unattributed`. Its input floor still held, at 127/300 of the whole window, because frames after the disconnect are not owed.
- **A real SIGKILL leaves `killed_with_no_cause_on_record`.** Every bot timed out with reason 0, and the exit says nothing. This platform has no OOM count, and on any platform that host-wide count would stay a diagnostic. Attribution needs the supervisor's file from a unit of the run's own, and these runs have neither. The server's missing data left the generator's own evidence unaffected: of its reasons, `recorder_truncated` and `collector_boundary_missing` are the game's, and only the absent socket counters leave the generator unproven.
- **A real stalled swarm is the generator's:** `poll_starvation` and `offered_input_below_minimum`, in `independent_failures`.
- **A real readiness timeout stays no capacity limit,** with a generator that cannot be proven here anyway. The ramp's identity and coverage checks read real bytes for it: the swarm, the game and both collectors were recognized as the supervised processes, the coordinator's abort row was read, all 8 started bots were found with their sockets, and the only reason is `window_not_established`. `test_capacity_real` also holds this path to the new swarm's behaviour on real bytes: its collector made a read certainly after the abort. This platform has no counter for that read to prove anything with, so what it shows is the timing of the hold and nothing about a drop.

The real controller path also runs one 60 s window through `test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path`, with the same refusal in its `score.json`. It is not retained here.

## Not shown anywhere here

A real pass; Linux `/proc` socket and OOM counters; real cgroup files, a real kernel's OOM kill or real `systemd-run` properties, since every process-attributed OOM row here is a mocked file of the shape the real supervisor writes, and a test drives that supervisor over a stand-in directory; independent-host clocks; public routes; SSH or systemd; generator headroom under real load; a real server kick, since nothing in the real workload triggers one, so that case rests on the traced source and the mocked trees; and any host's capacity.

## What changed when corrupt bytes got a lifecycle

Regenerating added 12 search scenarios, 67 to 79. No scenario was removed and no classification, status, claim or trial outcome moved. `synthetic-scores.json` and `real-local-scores.json` are byte for byte what they were, so the real summaries above stay historical and were not rerun: no real run exercises this path.

- The five existing scenarios whose return finds corrupt bytes (`corrupt_bytes_on_return_*`, `corrupt_bytes_survive_*`, `corrupt_bytes_in_a_confirmation_*`) gain the new observation in `hard_facts`, because a return now writes one. Those with a second crash also list that crash's own record once more, as the reason it carried. Nothing else in them changed.
- The new scenarios are the rows above. In the two `fsync` scenarios the temporary name's process id is fixed by the generator, so that the file regenerates.

Everything here is a simulated interruption or an injected failure in one process, over a fake guest.

## What changed when OOM evidence moved to a leaf

Earlier versions of these files accepted one kill counted for the whole unit, with the other members seen alive after the reap. That could not name a victim: the kernel counts before it signals, so a sampler chosen and not yet dead looks exactly like a survivor. Regenerating moved these, and nothing else. No scenario was removed.

- `game_oom_the_sampler_died_too` went from `inconclusive_evidence` to `capacity_failure`, `out_of_memory`. It used to mean a kill the unit count could not place. In this file the count is local to the game's leaf, so the sampler's death no longer casts doubt on it.
- `game_oom_kill_matched_to_the_game`, `ramp_oom_kill_matched_to_the_game` and `oom_kill_matched_to_the_game_opens_the_bracket` keep their classification, over evidence of schema `/2`.
- New score scenarios: `game_oom_a_kill_counted_only_elsewhere_in_the_unit`, which is the case that used to be accepted, `game_oom_the_unit_wide_schema_that_could_not_name_a_victim` and nine others. New search scenarios cover the leaf, the corrupt seal, the failed stop request and the foreign fact.

All of this is synthetic. No kernel counted anything, and a real kill has never produced one of these files.
