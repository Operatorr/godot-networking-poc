# Slice 8 integrated offline fault battery

Offline evidence for [issue #71](https://github.com/Operatorr/godot-networking-poc/issues/71), the offline part of handoff slice 8. **Not live-host validation and not a capacity finding.** No account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and nothing was published. The battery is `scripts/do_session/fault_battery.py`: see [its README section](../../../../../../scripts/do_session/README.md#integrated-offline-fault-battery-slice-8).

| File | What it is | How it was made | Reproducible |
| --- | --- | --- | --- |
| [`synthetic-battery.json`](synthetic-battery.json) | 28 scenarios, 29 sessions, 130 named checks and 8 invariants per session. Each session goes through the real planner admission, registry, watchdog, provisioner and DigitalOcean adapter, run executor, window prover, scorer and exporter, with faults at several of those boundaries at once. Each keeps its registry timeline, every provider mutation and a count of reads, resource inventories at named moments, guest starts and transfers, run records, cleanup attempts and incidents, and its three results | **Synthetic**: a fake DigitalOcean account at the HTTP boundary, fake guests behind the SSH seam, fixture recorder files and one scripted clock, in one process. Crashes are `SimulatedCrash` at the production code's own failpoints | Yes: `test_fault_battery` regenerates it and compares the hash |
| [`real-process.json`](real-process.json) | Two sessions with real processes killed and restarted: a controller `kill -9`'d mid-run and the watchdog service `kill -9`'d and restarted, then refused resume, collect and real cleanup; and a controller exiting at a named boundary between trials, the watchdog restarted, and explicit resume to the end of the scripted search | **Real local processes** on one macOS machine on real clocks: registry CLI, watchdog service, controllers, role runners and **stand-in** workloads on loopback. The provider and the pair's view are JSON files, `tc` is a stub, and outcomes come from a **scripted scorer**. Only facts that do not depend on timing are kept | Yes, as normalized facts: `test_fault_battery_process` compares them |
| [`SHA256SUMS`](SHA256SUMS) | Hashes of both | | |

No raw recorder file, run tree, log or session directory is retained. Each scenario's trees are deleted with its temporary directories. No real `omega-server` or `omega-load-test` binary ran in this battery; the earlier real-binary local runs are slice 5 and slice 6 evidence, and they are compatibility checks, not capacity.

## Provenance

Both files were generated from the clean code commit `8f1a93cd9062741afd4c9e44636703de0361828f`, with nothing else in the working tree, on one macOS machine under `scripts/do_session/measurement_offline.sb` (external network and name lookup denied, loopback allowed):

```bash
cd scripts/do_session
OMEGA_FAULT_BATTERY_RECORD=DIR sandbox-exec -f measurement_offline.sb python3 -m unittest -v test_fault_battery_process   # 3 tests, OK; writes DIR/real-process.json
sandbox-exec -f measurement_offline.sb python3 fault_battery.py --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice8 --real-process DIR/real-process.json
```

`synthetic-battery.json` came out byte-identical to the copy committed with that code. `real-process.json` was refreshed there because the code commit's copy predated two fields that commit added (`provider_held_at_start`); no other fact changed. The commit that adds this section changes only these two evidence files, `SHA256SUMS` and this README. No source, test or fixture changes after `8f1a93c`, so later revisions regenerate the same bytes while the code does; `test_fault_battery` checks that by hash.

## Requirements and where each is shown

Every session also satisfies the same eight invariants: nothing unrelated mutated, one request per created resource, each run id started once, the trial ceiling, deadlines unchanged from what was armed, `clean` only with complete evidence and nothing owned left, `closed` only with nothing owned left, and a claim only from complete evidence of a confirmed search.

| Issue #71 asks for | Scenarios |
| --- | --- |
| Partial, ambiguous and late creates | `partial_pair_stops_before_any_run`, `lost_acknowledgement_and_lost_create_then_confirmed`, `late_create_found_after_the_stop`, `unknown_create_overdue_then_operator_disposition`, `create_landing_with_a_foreign_tag_is_not_adopted` |
| Wrong ownership | `create_landing_with_a_foreign_tag_is_not_adopted`, `ownership_conflict_after_the_batch_is_not_deleted` |
| Controller and laptop disappearance; independent cleanup without a runner | `controller_and_laptop_vanish_mid_run`, `changed_checkout_returns_and_c_still_arrives`, `failed_transfer_crash_and_late_return_end_the_episode`, and both real-process sessions |
| Watchdog restart and reboot | `watchdog_restart_and_reboot_keep_the_deadline`, `reboot_with_untrusted_clock_fails_closed`, `failed_transfer_crash_and_late_return_end_the_episode`, and both real-process sessions |
| Stale fencing; revocation pending until the handoff takes effect | `stale_controller_after_takeover_then_eligible_resume`, `takeover_with_an_outstanding_grant_is_pending` |
| Retry fairness, rate limits, deletion outages, persistent overdue cleanup | `fairness_rate_limits_and_a_deletion_outage`, `unknown_create_overdue_then_operator_disposition` |
| Deadline exhaustion | `deadline_exhaustion_is_a_partial_search` |
| Interrupted, eligible and ineligible resume; dependent-path uncertainty | `interrupted_coarse_run_stops_the_dependent_path`, `interrupted_confirmation_leaves_siblings_eligible`, `stale_controller_after_takeover_then_eligible_resume`, `terminal_invalid_load_survives_two_crashes`, `deadline_exhaustion_is_a_partial_search`, `changed_checkout_returns_and_c_still_arrives` |
| Genuine server failure versus invalid generator load | `server_failure_advances_generator_failure_stops`, `terminal_invalid_load_survives_two_crashes` |
| Clock and socket gaps | `socket_gap_is_inconclusive`, `guest_reboot_clock_gap_is_infrastructure`, `reboot_with_untrusted_clock_fails_closed`, `failed_transfer_crash_and_late_return_end_the_episode` |
| Failed confirmations | `failed_confirmation_has_no_replacement` |
| Corrupt and incomplete evidence | `accepted_delete_lingers_beside_corrupt_evidence`, `storage_faults_on_both_sides_hold_every_result`, `failed_transfer_crash_and_late_return_end_the_episode`, the interrupted-run scenarios |
| Rejected admission creates nothing | `admission_rejected_creates_nothing`, `unacknowledged_watchdog_creates_nothing` |
| No hidden retry or deadline extension; clean only after owned absence | The invariants, in every session |

The full map, with the contract points the parent also asked to see together (operator disposition, accepted delete versus absence, terminal facts through recovery, the frozen source, publication truth, independent results and no claim on anything unknown), is the `requirements` list at the top of `synthetic-battery.json`.

## What the sessions show

| Scenario | Measurement | Evidence | Overall | Establishes |
| --- | --- | --- | --- | --- |
| No fault (the control) | `confirmed` | `complete` | `clean` | The fixture's candidate. Its published text is prepared locally only: `verified_local`, three text files, no raw file |
| A lost arm acknowledgement and a lost create answer | `confirmed` | `complete` | `clean` | The same candidate: t0 is when the registry acted, and the create was adopted with no second request |
| Two sessions: the sibling's deletes fail with 503 and its reads with 429 + 45 s guidance | Main `confirmed` | Main `complete` | Main `clean`; sibling overdue, then `resources_verified_evidence_incomplete` with the incident kept | Main's candidate. Main closed exactly as fast as the control; every 429 was waited out; no burst passed six attempts |
| Watchdog restarted, then the management host rebooted, mid-batch | `confirmed` | `complete` | `clean` | The candidate, with t0, C and D as armed |
| Controller A crashed, B took over and resumed, A woke up | `confirmed` | `complete` | `clean` | The candidate. A was refused before dispatching anything |
| A foreign firewall retarget and a foreign tag after the batch | `confirmed` | `complete` | `cleanup_not_verified` | The candidate from the earlier export, while the session stays open on an ownership incident and nothing foreign is deleted |
| Admission refused; watchdog never acknowledged | none | `unknown` | `closed_never_armed` | Nothing. Zero provider mutations |
| Partial pair; late create; unknown create; foreign-tagged landing | none | `unknown` | verified incomplete, operator disposition, or open | Nothing. The late create is found by tag and deleted; the unknown one stays overdue past D until an operator disposition, which never reads clean |
| Controller and laptop gone mid-run; a changed checkout returns | none | `unknown` | `resources_verified_evidence_incomplete` | Nothing. The watchdog alone deleted by C |
| Interrupted coarse run; interrupted confirmation; outstanding grant at takeover | `operator_collect` or `unconfirmed_partial` | `partial` or `missing` | `resources_verified_evidence_incomplete` | Nothing. No interrupted run was replayed |
| Starved generator after a server kick; generator starved through two crashes | `stopped_invalid_load` | `complete` | `clean` | Nothing. The kick advanced the search as a capacity failure first |
| Socket counter gap; guest reboot in the window; source changed mid-run | stopped inconclusive or infrastructure | `complete` | `clean` | Nothing |
| Second confirmation fails | `unconfirmed_variable` | `complete` | `clean` | Nothing, and no third or replacement confirmation |
| Operator back 25 minutes before C | `operator_collect` | `complete` | `clean` | Nothing: resume refused on the original headroom |
| Management host rebooted with its clock an hour behind and unsynchronized | `clock_unverifiable` | `complete` | `resources_verified_after_overdue` | Nothing. No run dispatched after the reboot |
| Corrupt transfer beside deletes the provider accepts but keeps listing | `stopped_infrastructure_failure` | `corrupt` | `resources_verified_evidence_incomplete` | Nothing. No Droplet was recorded absent while still listed |
| Registry disk error on one outcome; controller disk full promoting one file | `stopped_infrastructure_failure` | `complete` | `clean` | Nothing. The outcome was recorded once; the later verified bytes changed no decision |
| Failed transfer, crash, watchdog restart, controller back after the grace with its wall clock 2 min behind | `operator_collect` | `missing` | `resources_verified_evidence_incomplete` | Nothing. No transfer after the episode, which ends at the first failure plus the grace |

`clean` beside a failed or stopped search means every file arrived and every resource is gone, not that anything was measured.

## The checks fail on broken code

`test_fault_battery.ChecksFailOnBrokenCode` breaks one production behaviour at its real seam and asserts the battery's own checks notice: an adapter that hides a Droplet once its delete was accepted, a registry that forgets unresolved creates, a controller that skips its frozen-source check, and a run verdict that passes a counter gap. Breaking only the scorer's socket gate, or only the scorer, was tried and changed nothing, because the window prover and the executor's check of the scorer each refuse the gap on their own; so that control replaces the verdict as a whole. Nothing from these runs is retained.

## Limits

- Every number in `synthetic-battery.json` is fixture arithmetic on a scripted clock, and says nothing about any host, capacity, price or cost.
- Both real-process sessions share one machine, one fake provider file and stand-in workloads. They show that real processes die and come back as the synthetic sessions say; they are not SSH, systemd, Linux or a Droplet.
- Real SSH and provider lifecycle and bills, Linux counters, cgroup OOM attribution, systemd supervision and controller boot identity on Linux, independent hosts and clocks, public routes, generator headroom, actual publication and physical power loss remain unverified. Gates A, B and C keep their separate authorization.
- Combinations are bounded and chosen by risk from the contracts, not exhaustive.
- The historical CAX11 gate is unchanged.
