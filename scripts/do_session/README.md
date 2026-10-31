# do_session — DigitalOcean test-session planner (handoff slice 1)

Offline planning/preflight for the disposable DigitalOcean capacity sessions planned in
[issue #57](https://github.com/Operatorr/godot-networking-poc/issues/57). It implements slice 1
of the [accepted controller handoff](https://github.com/Operatorr/godot-networking-poc/issues/61):
explicit conditions and limits in, an **immutable hashed manifest**, the **legal next run** and an
**explainable time/spend admission** out. Nothing in this package talks to a provider, SSH or the
network; the session directory is its only side effect and every file is create-only or
append-only. A rejected freeze or admission therefore creates no provider resource by construction.

Terminology follows `docs/CONTEXT.md` and issues #59/#60: a *test session* owns one game/bot
Droplet pair with one fixed hardware condition; its *test batch* is the frozen search; a *test
run* is one fresh workload execution. These are infrastructure terms, not the gameplay Instance.

## Modules

| File | Owns |
| --- | --- |
| `manifest.py` | `freeze_manifest(conditions, preflight, frozen_at)` → `(manifest, sha256)`. Rejects (listing every reason) missing limits, absent timing basis, moving/dirty source, unsupported or silently substituted hardware/image/region/route, deviations from the frozen workload schema, credential *values*, conditional RAM tiers without memory-pressure evidence + explicit admission, world-open allowlists. Prices come from the preflight, never a table. |
| `search.py` | The accepted finite search as a branch graph: coarse 25→500 by 25; refinement by 5 inside the failing bracket (from 5 after a first-rung failure); three fresh 300 s confirmations of the highest passing candidate. `derive(state)` gives the single legal next trial and the result label; `legal_paths(state)` enumerates every remaining PASS/FAIL path. |
| `admission.py` | `admit(...)` recomputes the manifest hash, requires healthy registry/watchdog acknowledgment of that hash, and checks `elapsed + pre-workload + max over legal paths + collection/export + recovery grace ≤ cap − teardown reserve`, plus both-host cost for the full cap with billing minimums and prorated transfer. Management-host cost is disclosed separately. |
| `do_session.py` | CLI: `freeze`, `admit`, `next-run`, `record`, `mark-t0`, `mark-ready`, `stop`, `paths`. Exit 0 admitted, 2 rejected, 3 no remaining work. |

## Search semantics as implemented

- Outcomes: `PASS`, `FAIL` (attributable game-host capacity failure) advance the search;
  `INVALID_LOAD`, `INFRASTRUCTURE_FAILURE`, `INCONCLUSIVE` stop the batch and establish nothing;
  `INCOMPLETE` (interrupted) makes the dependent coarse/refinement branch **undecidable** and stops it.
  Confirmation repetitions are independently eligible after an incomplete sibling, but the set is
  then `unconfirmed_partial`, never a confirmed capacity.
- A selected confirmation with no recorded outcome blocks subsequent selection, including ordinary
  `next-run` calls. Finalize it before selecting a sibling; pending differs from recorded `INCOMPLETE`.
- `PASS` and `FAIL` require a nonempty `--evidence-ref`. Replay refuses legacy advancing outcomes
  without evidence; an outcome label alone cannot establish a predecessor or confirmed capacity.
- A failed confirmation ends the batch as `unconfirmed_variable` with no replacement trial.
- Three passes at 500 → `confirmed_search_cap_reached` ("at least 500"). Failure at 5 →
  `no_passing_target` (not proof that nothing smaller works).
- Ceilings hold by construction: ≤20 coarse + ≤4 refine + ≤3 confirm = 27 per condition,
  401 legal paths from an empty state. The maximal-count path (fail at 500, pass 480/485/490/495,
  confirm 495 ×3) has **24 × 60 s + 3 × 300 s = 39 minutes of scored holds alone**; the all-coarse-pass
  path is 23 trials / 35 minutes. Neither a 27-count cap nor a 30-minute example proves fit.

## Time and cost model

Per trial: `readiness_bound(N) = max(60, 0.1·N + 30)` (the nominal ramp lives inside it and is not
added again) + 2 s post-auth warmup + hold + process reset + recorder finalization + per-trial
export. Session: create/bootstrap + readiness/access, then collection/export and the full recovery
grace; workloads must end by `C = cap − teardown_reserve`. Re-admission
before each dispatch and before an explicit resume uses the same formula with the real elapsed
time since `t0` and the shrinking set of legal remaining paths.

`mark-t0` starts the immutable lifetime immediately before the first create request. It enters
`provisioning`; admission conservatively retains the full setup bound plus elapsed time until
`mark-ready --evidence-ref REF` records verified pair readiness. Only then is setup removed from
the remaining budget. Readiness must not precede `t0`, and it never resets that original clock.

Timing terms carry a `basis` (`calibrated` with evidence hash, or `declared_conservative`) and
provenance. A `capacity` session rejects declared bootstrap/readiness/collection bounds (Gate C
needs calibration); `calibration`/`lifecycle_smoke` manifests may capture declared bounds for
their later, separately gated planners.

Cost: both hosts for the **full cap**, hourly price × billable units with the stated billing
increment/minimum, plus outbound transfer at the overage price after prorating the allowance by
`cap / allowance_hours_per_month` (or not at all). The estimate is an admission control, not an
invoice or a provider billing ceiling.

## Running

```bash
cd scripts/do_session
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q  # 95 offline tests, no network
python3 do_session.py freeze --conditions fixtures/conditions_capacity_1vcpu_1g.json \
    --preflight fixtures/preflight_sgp1_fake.json --session-root /tmp/do --now 2026-10-30T12:00:00Z
python3 do_session.py paths --session-dir /tmp/do/do-cap-1v1g-20261030a
```

`fixtures/preflight_sgp1_fake.json` mirrors the redacted 2026-10-30 preflight shape from issue #62
(slugs, prices, image IDs, registered key). It is a fake: live facts must be re-read at remote
admission. The conditions fixture uses placeholder SHAs and fake calibration hashes; a real
session supplies reviewed revisions and real calibration evidence (Gate A).

## Boundaries

Required manifest sections must be JSON objects. Builds require the `release` profile and an
explicit Rust `major.minor.patch` toolchain (optionally with a host triple); effective features
belong in the explicit `build_flags` argument list. Credential fields are limited to the two
supported token references. Hash verification also checks these rules on older schema-1 manifests.

If selection-file publication succeeds but its journal append fails, retry `next-run` after fixing
the local I/O fault. It re-admits against the current clock/health/limits and reconciles only the
exact original manifest/trial/predecessor selection, preserving its bytes and selection timestamp.
Conflicting or corrupt selections are refused. A journaled pending trial is never selected again.

`calibration` and `lifecycle_smoke` manifests may capture declared timing bounds, but this capacity
planner rejects their `admit`, `next-run` and `paths` requests. Their separately bounded workload
plans and execution gates belong to later slices; these kinds cannot implicitly start the ladder.

This slice does not create registries, watchdogs, Droplets, firewalls or runs (slices 2–4), does
not score evidence (slices 5–6) and does not export or publish (slice 7). The historical CAX11
gate ([issue #53](https://github.com/Operatorr/godot-networking-poc/issues/53)) is unchanged.
