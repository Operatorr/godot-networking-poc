# Fixes and open checks, separate from baseline measurements

The user authorized bug fixes for one smooth pilot before reviewing a full-run checklist.
No CPU, AoI or bandwidth optimization has been applied. Original and measurement builds,
raw failures and earlier classifications remain preserved; the corrected build is distinct.

| Change | Evidence | Revision |
| --- | --- | --- |
| Apply ENet-requested UDP buffers | Original adapter ignored both sizes. Two tests fail before and pass after. Remote effective limits rise from 212,992 to 524,288 bytes; post-fix pilot has zero UDP errors throughout collection. | `77a8af5` |
| Match cache to replacement Baseline | Two tests reproduce omitted/truncated cached entities re-entering with partial records for an absent receiver entity. Cache reset fixes both. Remote scored unknown deltas fall to zero, while warmup faults remain visible. | `a8fb109` |
| Recover new entities after first unreliable FULL loss | Test drops first Snapshot; old next record is position-only, corrected next record remains FULL. Normal masks resume after a reliable Baseline includes the entity. Adds correctness traffic rather than optimizing bandwidth. | `b1266c1` |
| Bound local packet-analysis memory | Exact matching/quantiles move to scratch SQLite; retry cache has its classification lifetime. Same archived inputs preserve metrics except four unsupported mirror outstanding fields. RSS drops from 2.919 GB to 0.543 GB on replay; five regression tests pass. | `30ad91f` |
| Qualify mirror ACK scope | Egress-only mirrors cannot see returning ACKs. Their outstanding fields are unavailable rather than growing fictitious queues. Bidirectional endpoint ACK accounting remains. | `30ad91f` |
| Preserve warmup faults | Cumulative bot/server diagnostics and full collected-interval kernel errors are published beside scored metrics. Replay retains 2,425 cumulative unknown-entity observations from the transport-only pilot. | `323a83b` |
| Reuse SSH and archive endpoints concurrently | Independent cleanup attempts and per-endpoint timings preserve failure evidence. Unique run IDs, finite capture/trace lifetimes and the full-matrix hold prevent overwrites and accidental restarts. | `77a8af5` / `30ad91f` |

Remote first-record recovery validation passed the whole-run checks: zero unknown-entity
or reference errors, including warmup. Passing one pilot does not establish a complete matrix. The user
now requires one five-minute observation per test rather than three repetitions. See [validation](single-run-validation.json).

## Checks before full execution

- The [map](https://github.com/Operatorr/godot-networking-poc/issues/23) already records
  the sent-versus-ACKed Baseline doc/code drift as deferred. `reset_baseline` sets the
  reference at send time and broadcast emission has no pending-ACK guard. Report reference
  misses/recovery under impairment as observed behavior; do not silently change protocol
  ordering during this baseline campaign. No native reference misses were observed in
  the completed pilots. A future ordering correction needs its own revision/comparison.
- Controller/ramp failure handling is now corrected: inspect the full ramp log for the
  first start/connect/ticket failure, stop further joins, retain `ramp-failure.json` as
  unscored evidence and archive both endpoints. A finite swarm lifetime covers controller
  disappearance. [Local integration fixtures and read-only remote probe](controller-failure-validation.json)
  verify the implemented path; no remote failed-join benchmark was executed. Successful
  run input rate, stagger, warmup and measurement duration remain unchanged.
- Measure full versus light collection overhead on the final selected revision, including
  the clustered workload that exposed socket pressure. Existing movement controls from
  the prior revision do not establish corrected-build overhead or exclude observer effects.
- Verify larger-population collector/generator resource use and evidence storage. The
  analyzer is now bounded more carefully, but higher-population processing time and RSS
  remain unmeasured. Stop invalid collection rather than announcing a server ceiling.
- The old <5 KiB/s combined-bandwidth target still fails at 50 players. It is an aspirational
  target, not a socket error or invoice limit. Record it beside measured transfer; do not
  optimize the baseline during this task.
- Scheduled/enqueued Snapshots missing from first observed wire transmission remain a
  separate ENet/source delivery observation. Exact endpoint packet matching cannot call
  them network loss. Verify recovery, and retain their count even when the pilot is stable.

Historical retrieval and CCX13 remain deferred behind their existing gates.

## Merge preparation review, 2026-10-14

The specification review reproduced a false-complete coverage audit using 88 mislabeled
copies of the pilot and corrupted archives. The verifier now binds every required condition
to its population, workload, impairment profile and transfer variant, including replacement
attempts, and recomputes both retained archive digests. A separate reporting fix prevents
collector-invalid or non-Strategy 999-player observations from producing the forecast columns
labelled as derived from valid 999-player evidence. Seven regression tests cover these cases
and the actual scheduler's complete 88-cell fixture; all 22 local campaign tests pass.
These are local audit/reporting fixes; no new benchmark was executed and historical reports
were not regenerated.

The standards review found no hard invariant violations or configured private endpoints,
private-key blocks or GitHub-token patterns in the tracked evidence. One maintenance follow-up
remains: consolidate campaign paths/build selections into one configuration rather than
rebinding globals across modules. The fresh execution handoff already requires coordinated
initialization and a separate audit of source revisions and binary provenance before resolution.
