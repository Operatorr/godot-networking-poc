# do_session — DigitalOcean test-session planner, registry and watchdog (handoff slices 1–2)

Control code for the disposable DigitalOcean capacity sessions planned in
[issue #57](https://github.com/Operatorr/godot-networking-poc/issues/57), following the
[accepted controller handoff](https://github.com/Operatorr/godot-networking-poc/issues/61).

- **Slice 1, the planner:** explicit conditions and limits in, an **immutable hashed manifest**, the
  **legal next run** and an **explainable time/spend admission** out. It talks to no provider, SSH or
  network; the session directory is its only side effect and every file is create-only or
  append-only. A rejected freeze or admission therefore creates no provider resource by construction.
- **Slice 2, the registry and watchdog:** see [below](#session-registry-fencing-and-cleanup-watchdog-slice-2).
  It runs only against the offline fake provider until slice 3 supplies the real adapter.

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
grace; workloads must end by `C = cap − teardown_reserve`, less 40 s because cleanup starts that early
so its first delete is issued by C, and less one 30 s dispatch grant, which may be used at its very end.
Later grants are charged through real elapsed time at re-admission. Re-admission
before each dispatch and before an explicit resume uses the same formula with the real elapsed
time since `t0` and the shrinking set of legal remaining paths.

`mark-t0` starts the immutable lifetime immediately before the first create request. With a registry,
pass `--arm-ack` so the planner adopts the registry's durable t0 rather than a local clock. It enters
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
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q  # all offline, no network; about a minute with the process crash matrix
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

The planner does not create Droplets, firewalls or runs (slices 3–4), does not score evidence
(slices 5–6) and does not export or publish (slice 7). The historical CAX11 gate
([issue #53](https://github.com/Operatorr/godot-networking-poc/issues/53)) is unchanged.

## Session registry, fencing and cleanup watchdog (slice 2)

Runs on the trusted management host, outside the disposable pair. Deadlines and cleanup intent live
there, so deletion needs no controller, laptop, SSH key or lease.

| File | Owns |
| --- | --- |
| `registry.py` | SQLite store and control-plane API: manifest, ownership, creation intents, t0/D/C, fencing, run and cleanup transitions, incidents, hash-chained journal. Every write is one durable transaction that also stores its response under the request id. |
| `cleanup_ledger.py` | Durable cleanup state machine: C/D evaluation, per-resource bursts, attempt history, ownership checks, closure rules and receipts. |
| `watchdog.py` | The service loop: 1 s ticks, 15 s sweeps, fair off-thread provider requests, incident files. |
| `session_clock.py` | The forward-only effective clock built from the wall clock, the boot-scoped monotonic clock and a persisted anchor. |
| `cleanup_provider.py` | The read/delete-only provider seam, error taxonomy and redaction. |
| `registry_client.py` | Controller side: retried requests, acknowledgement checks, `guarded_create`, the SSH/subprocess transports. |
| `registry_cli.py` | Management-host CLI: `init`, `rpc`, `watchdog`, `status`, `health`, `incidents`, `journal`, `verify-journal`, `abort`, `disown`. |
| `fake_provider.py`, `fault_harness.py`, `registry_fixtures.py`, `fault_evidence.py` | Offline fixtures only. |

### Contract as implemented

- **Before any create:** `register_session` → `acquire_control` → watchdog acknowledges the manifest →
  `arm_session` sets t0/D/C once from the registry's clock → watchdog acknowledges the armed deadline →
  `begin_create` persists the intent and authorizes one request. The grant must be sent within 10 s and the
  request must finish within 35 s without client retries; `guarded_create` refuses to send a stale grant. A missing step, an unreachable or
  failing registry, or a stale watchdog heartbeat means no create. Names and tags come from the
  manifest: Droplets are `<session>-game` and `<session>-bot`, the firewall is `<session>-fw`.
- **Lost acknowledgements:** retries reuse the request id and get the original answer, so t0 cannot
  move. Replays of `dispatch_run` and `begin_create` re-run their gates first. A replayed
  `begin_create` always answers `must_reconcile`, because the earlier grant may have reached the provider.
- **Uncertain creates:** a create stays uncertain after a timeout or lost grant. A resource found by tag and
  name is adopted at any time, but absence only counts after the 60 s bound (10 s start window + 35 s request + 15 s
  visibility, on the monotonic clock when the boot is unchanged, so a wall step cannot shorten it).
  `begin_reconcile` refuses until then; after it the caller lists and reports `reconciled_absent` with the
  returned `reconcile_id`. Only that re-enables `begin_create`. `guarded_create` raises `CreateStillSettling`
  with `retry_after_s` meanwhile and sends nothing. A `rejected` report must name the request it answers.
- **Fencing:** each `acquire_control` issues the next token, and taking a live lease needs explicit
  `takeover`. Dispatch needs the current token, a live lease, a fresh watchdog heartbeat, a ready pair,
  no active run, an unused run id and a run that fits before cleanup starts even when launched at the very
  end of its grant (`launch_by + estimated_duration_s`). A lapsed lease cannot be
  renewed. Re-acquiring pauses the session and marks any active run interrupted; only `record_resume`
  makes it dispatchable again, and it refuses unclassified interrupted runs and terminal failures.
- **Cleanup:** the watchdog persists cleanup intent and starts 40 s before `C`, regardless of the controller:
  one ownership read (35 s bound) plus tick delay, so the first delete is issued by C after any read that
  succeeds within its bound. `Watchdog` refuses a lead too short for that. Sessions awaiting a first delete near
  their C go first and ordinary work leaves one session's share of in-flight capacity free. This is scheduling,
  never a bypass: without a successful ownership read no delete is issued. Order is Droplets, firewall, tags.
  Droplets are never held back. Firewalls and tags wait until every outstanding create has settled, and each
  layer waits until the one it protects is verified gone. A Droplet or firewall create settles after its 60 s
  bound (from both its request and the cleanup start) plus two empty listings, the last started after the bound.
  A tag create settles through the tag's own read after its bound. A resource found or reported later makes tags
  re-verify, because it can recreate them, and a tag read that began before it proves nothing. Closure needs
  authenticated absence of every resource, every create settled, and a successful empty listing started after the
  last verification. An accepted DELETE, a failed read, a failed listing or a stopped guest never closes a session.
- **Retries:** at most six requests per resource per sweep, backoff 2, 4, 8, 16, 30 s, spread across
  ticks. A resource has one active burst; later sweeps and restarts continue it. Sweeps never stop
  retrying. `Retry-After` holds all requests (capped at one hour) and survives restarts. Auth failures
  open an incident and retry on later sweeps. Round-robin dispatch with a per-session in-flight limit
  keeps one session from starving another.
- **Overdue:** at D any unverified session gets a durable `cleanup-overdue` incident, a journal error
  and `incidents/incident-*.json` with exact ids, attempts, the last error and remediation commands.
  Reconciliation continues, and the actual overrun is recorded when absence is finally verified.
- **Ownership:** deletion needs the exact id plus matching session tag, role tag and expected name, or
  for firewalls the expected name and targets. Project membership is never consulted. A mismatch, a
  protected `omega-management` tag or a manifest-retained id is an incident, never a delete. The
  operator resolves it with `disown`, and the session then closes labelled as a disposition, not clean.
- **Clocks:** effective time never moves backward. A backward wall step cannot delay C or D because
  monotonic time keeps counting. A forward step may start cleanup early, and correcting it cannot revive
  the session. Either one is an incident and blocks arming new sessions until it clears.
- **Reboots:** a reboot loses the monotonic origin, and timestamps that merely move forward do not bound
  the downtime. A new boot is trusted only if the kernel reports a synchronized clock (`adjtimex`) and the wall
  is not behind the persisted floor. Otherwise the registry opens a `clock-unverifiable` incident and, in the
  same transaction, every armed open session starts cleanup (`clock_unverifiable`), loses its lease and gets a
  `cleanup-overdue` incident marked `deadline_uncertain`, because D may have passed. Renewal, dispatch and create are refused
  while time stays unverified, new sessions stay refused too, and verified time later never revives a session. Its
  status and receipt carry `deadline_uncertain` and `overrun_is_lower_bound`.
- **Evidence recovery:** a started episode ends at its recorded deadline in any substate. Returning to
  `collecting` does not extend it, and the deadline ends no later than cleanup starts for C, 40 s before C.
- **Independent outcomes:** `measurement`, `evidence` and `cleanup` are separate fields. `overall` only
  summarizes them and reads `clean` only with verified absence, complete evidence and no overdue incident.

### Operating notes

- The registry has no daemon. Controllers run `registry_cli.py rpc` per request over key-only SSH
  (`registry_client.ssh_argv`), so only the watchdog is supervised:
  `deployment/do-watchdog/omega-do-watchdog.service`. Installing it belongs to issue #72.
- To move hosts: stop the service, copy the one state directory, start it elsewhere. Do not copy it
  while the service runs. The new host counts as a reboot, so its clock must already be synchronized or
  armed sessions start cleanup. `registry_cli.py init` refuses an existing registry, and a missing state
  directory is an error rather than a fresh start.
- `registry_cli.py health --session S` prints the JSON that `do_session.py --infra-health` expects.
- Retained fixture timelines: `docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice2/`.
  Regenerate with `fault_evidence.py`. They are not capacity or live-provider results.

### Limitations

- **No real provider yet.** `watchdog` refuses to start without an explicit provider, and refuses the
  fake without `--allow-offline-fake`. The DigitalOcean adapter, its pagination, request timeouts and
  `Retry-After` mapping belong to slice 3. No live account has exercised this code.
- **Live sessions get deadline checks, not inventory reads.** Provider reconciliation starts when cleanup
  starts. A create no controller reported is found then, by unique tag.
- **The settle window is a bound, not a proof.** A create landing more than 60 s after its request can
  duplicate a retry, or be an orphan after closure unless someone reports it (`record_resource` reopens
  cleanup and re-verifies tags). The adapter in #66 must honor the grant's `create_request_timeout_s`, must not
  retry in the HTTP client, and should confirm the 15 s visibility margin against the real API.
- **The first delete by C has limits.** It holds for ownership reads that succeed within 35 s and for up to four
  sessions reaching cleanup together under the default limits (eight in flight, two per session). Behind hung
  sessions, the reserved capacity covers one such session. Beyond that, a session waits for a slot, and
  provider outages or a `Retry-After` hold can also delay the first delete. These cases stay visible and overdue at D, never a false success.
- **Time verification is unproven on a real host.** `adjtimex` was exercised with stubs on macOS only. Issue #72
  must confirm on the Linux management host that a synced clock reads as verified and that a boot before
  sync fails closed. A boot whose time daemon has not synced when the watchdog starts cleans up its armed
  sessions: the safe direction, but a reason to let sync finish on boot. Do not order the unit on
  `systemd-time-wait-sync` without a timeout, since a watchdog that never starts protects nothing.
- **Dispatch grants still need process enforcement.** The registry only proves that a run launched by `launch_by`
  with its stated estimate ends before cleanup starts. Issue #67 must stop the process at that estimate, and must
  use `estimated_duration_s` that includes every part of the trial it starts.
- **A dispatch grant cannot reach into a launched process.** `launch_by` bounds when a controller may
  launch; stopping a workload that started just before a takeover needs slice 4's run identity checks.
- **Storage failures hold back deletion.** Intent must be durable before a delete, so a full disk stalls
  cleanup and makes the host unhealthy. Losing the single-disk host entirely falls back to manual tag
  cleanup, the residual risk the operator accepted in issue #63.
- **A far-future clock step is sticky.** The ratchet expires every session (the safe direction) and
  refuses new ones while wall and effective time disagree. Recover with a fresh state directory once
  everything is closed.
- **Monotonic protection needs Linux.** Without `/proc/sys/kernel/random/boot_id` (for example on macOS)
  a reboot cannot be detected and only the persisted floor applies. A wall clock behind that floor fails closed
  there, but a smaller backward step can still delay C.
