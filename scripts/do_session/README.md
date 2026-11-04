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
| `admission.py` | `admit(...)` recomputes the manifest hash, requires healthy registry/watchdog acknowledgment of that hash, and checks `elapsed + pre-workload + max over legal paths (each trial plus its launch window) + collection/export + recovery grace + delete margin ≤ cap − teardown reserve`, plus both-host cost for the full cap with billing minimums and prorated transfer. Management-host cost is disclosed separately. |
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
export. That is the trial's `total_s`, the value `dispatch_run` takes as `estimated_duration_s`. Each
remaining trial on a path also reserves its 30 s launch window (`reserved_s`), because each future
grant may be used at its very end. Session: create/bootstrap + readiness/access, then collection/export
and the full recovery grace. All of it must end by `C = cap − teardown_reserve`, less the 0.5 s margin
that lets a delete be issued by C. An exact fit stays admitted when every grant is used to its end; a
window not used comes back as slack. Re-admission before each dispatch and before an explicit resume
uses the same formula with the real elapsed time since `t0` and the shrinking set of legal remaining paths.

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
| `create_evidence.py` | The typed evidence that can settle a create request, and the fail-closed parser for it. |
| `deadline_capacity.py` | The reservation arithmetic that decides how many sessions can be promised a first delete by C. |
| `cleanup_provider.py` | The read/delete-only provider seam, error taxonomy and redaction. |
| `registry_client.py` | Controller side: retried requests, acknowledgement checks, `guarded_create`, the SSH/subprocess transports. |
| `registry_cli.py` | Management-host CLI: `init`, `rpc`, `watchdog`, `status`, `health`, `incidents`, `journal`, `verify-journal`, `abort`, `disown`, `dispose-create`. |
| `fake_provider.py`, `fault_harness.py`, `registry_fixtures.py`, `fault_evidence.py` | Offline fixtures only. |

### Contract as implemented

- **Before any create:** `register_session` → `acquire_control` → watchdog acknowledges the manifest →
  `arm_session` checks deadline capacity and sets t0/D/C once from the registry's clock → watchdog acknowledges the armed deadline →
  `begin_create` persists the intent and authorizes one request. The grant must be sent within 10 s and the
  request must finish within 35 s without client retries; `guarded_create` refuses to send a stale grant. A missing step, an unreachable or
  failing registry, or a stale watchdog heartbeat means no create. Names and tags come from the
  manifest: Droplets are `<session>-game` and `<session>-bot`, the firewall is `<session>-fw`.
- **Lost acknowledgements:** retries reuse the request id and get the original answer, so t0 cannot
  move. Replays of `dispatch_run` and `begin_create` re-run their gates first. A replayed
  `begin_create` always answers `must_reconcile`, because the earlier grant may have reached the provider.
- **Uncertain creates:** a timeout or lost grant leaves the outcome unknown, and elapsed time never changes that.
  The client's 10 s start window and 35 s timeout bound how long this client waits, not when the provider finishes
  or shows the result. A retry and a clean closure both need one of the settlements under
  [Create settlement](#create-settlement). Without one, `guarded_create` raises `CreateUnresolved` and sends nothing,
  and the batch should stop and clean up. A resource found by tag and name is adopted at any time.
- **Fencing:** each `acquire_control` issues the next token, and taking a live lease needs explicit
  `takeover`. Dispatch needs the current token, a live lease, a fresh watchdog heartbeat, a ready pair,
  no active run, an unused run id and a run that fits before the deadline tick even when launched at the very
  end of its grant (`launch_by + estimated_duration_s ≤ C − 0.5 s`). Preparation does not cut dispatch short. A lapsed lease cannot be
  renewed. Re-acquiring pauses the session and marks any active run interrupted; only `record_resume`
  makes it dispatchable again, and it refuses unclassified interrupted runs and terminal failures.
- **Cleanup has two halves.** *Preparation* is read-only: from 40 s before C the watchdog reads known Droplets and
  records their ownership. It changes no session state, so a workload or evidence recovery keeps running, and it
  issues no delete. `start_attempt` refuses a delete without durable cleanup intent, so this holds by construction.
  *Deletion* starts on the tick 0.5 s before C (the service wakes for it) or at an earlier cleanup request. Cleanup
  intent is persisted first, then Droplets with fresh ownership go straight to their delete, regardless of the
  controller. Without a successful ownership read no delete is issued. Order is Droplets, firewall, tags. Droplets
  are never held back. Firewalls and tags wait until every create is settled, and each layer waits until the one it
  protects is verified gone. A resource found or reported later makes tags re-verify, because it can recreate them,
  and a tag read that began before it proves nothing. Closure needs authenticated absence of every resource, every
  create settled, and a successful empty listing started after the last verification and the last settlement. An
  accepted DELETE, a failed read, a failed listing or a stopped guest never closes a session.
- **Deadline capacity:** each armed session reserves one provider-request slot from `C − 40 s` to `C + 37 s`, enough
  for one ownership read and a first delete held to its bound. Ordinary work never uses reserved slots, and each session
  has one deadline request at a time, earliest C first. So if reservations fit, a due request has a slot however many
  others are hung. The default watchdog has 12 slots: 8 reserved, 4 ordinary. `arm_session` refuses a session that
  would need more reservations at once with `deadline_capacity_exceeded`, before t0 exists and before any create can be
  authorized. The refusal names the overlapping sessions and `retry_after_s`, after which arming again fits. Only
  overlapping windows count: sessions whose C values are 77 s apart never compete, and a closed session gives its slot back.
- **Retries:** at most six requests per resource per sweep, backoff 2, 4, 8, 16, 30 s, spread across
  ticks. A resource has one active burst; later sweeps and restarts continue it. Sweeps never stop
  retrying. `Retry-After` holds all requests (capped at one hour) and survives restarts. Auth failures
  open an incident and retry on later sweeps. Round-robin dispatch with a per-session in-flight limit
  keeps one session from starving another. Within a session a due Droplet delete goes first, then whatever waited
  longest, so repeating listings cannot starve firewall and tag work.
- **Overdue:** at D any unverified session gets a durable `cleanup-overdue` incident, a journal error
  and `incidents/incident-*.json` with exact ids, unresolved create requests, attempts, the last error and remediation commands.
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
- **Evidence recovery:** a failed-download episode ends at exactly `min(first_failure + grace, C)`, in any substate.
  Returning to `collecting` does not extend it. Preparation runs alongside it without shortening it. When the
  episode ends at C, deletion begins on the tick 0.5 s before C, so a controller's local timeouts must stop by then, as
  the contract's "stop evidence recovery before C" already requires.
- **Independent outcomes:** `measurement`, `evidence` and `cleanup` are separate fields. `overall` only
  summarizes them and reads `clean` only with verified absence, complete evidence and no overdue incident.

### Create settlement

| What the registry accepts | Reported through | Meaning |
| --- | --- | --- |
| The resource itself | `record_resource`, or watchdog listing or tag read | It landed. Adopted by exact id at any time. |
| `rejected` with `request_number` | `record_create_result` | The provider definitively refused this request. |
| `not_sent` with `request_number` and fencing token | `record_create_result` | No byte of this request left the grant's holder. |
| A `create_settlement` receipt | `record_create_settlement`, or watchdog `get_request_settlement` | The provider says this exact request reached a terminal state. |

An empty listing, a 404 on a tag, a client timeout and any amount of elapsed time are not on this list. While a
request is unresolved: no retry is granted, a pair cannot become ready, firewalls and tags stay in place, known
Droplets are still deleted at once, reconciliation keeps listing every sweep, an `unresolved-create` incident stays
open and D still produces `cleanup-overdue`. A late landing is found and deleted because the session is still open.

**The shipped registry trusts no receipt basis** (`DEFAULT_TRUSTED_BASES` is empty) and `CleanupProvider.get_request_settlement`
returns None, so with no adapter guarantee a lost create response leaves the session open until the resource appears
or the operator decides. This is deliberate: nothing here assumes a DigitalOcean completion guarantee, and none has
been researched. `offline_fixture_receipt` is trusted only by fixtures and by the watchdog when it runs against the fake.

The operator's exit is `registry_cli.py dispose-create --session S --intent ID --note WHY`, allowed only during
cleanup, so it can never permit a retry. The session then closes as `verified_absent_with_operator_disposition`, never
clean. A landing after that closure is outside reconciliation unless someone reports it; `record_resource` reopens
cleanup. Check the account by unique tag before disposing.

**What a future adapter (#66) must do:**

1. Create callbacks: start only inside the grant's `create_start_window_s`, use `create_request_timeout_s` as a client
   timeout, never retry inside the HTTP client, and return the exact id.
2. Raise `create_evidence.CreateNotSent` only when no byte of the request can have left the process, and
   `CreateRejected` only for a provider response that definitively refuses the request. A timeout, reset or 5xx is
   neither: let it propagate, and the outcome stays unknown.
3. Keep `find_fn` an authenticated lookup by unique tag and exact name that follows pagination. A hit is proof of
   landing; a miss proves nothing.
4. Return a receipt from `get_request_settlement` only for a documented provider guarantee that the request named by
   `create_request_ref` is terminal and no resource can appear from it later. Bind that ref to the provider's own
   operation record, and read that record rather than infer from timing. Otherwise return None. Use
   `create_evidence.receipt(ref, terminal, basis, provider_reference, resource_id)` with a non-secret reference.
5. Add a named basis to the registry's trusted set in reviewed code, citing that guarantee, and only then. Registry
   deployments must not pass a basis at runtime: `registry_cli.py` has no option for it.

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
- **Live sessions get deadline checks, not inventory reads.** Before cleanup the watchdog reads only known Droplets,
  and only in the preparation window. A create no controller reported is found once cleanup starts, by unique tag.
- **Without a provider guarantee, a lost create response needs an operator.** Until an adapter meets the obligations
  above, such a session stays open and overdue until the resource appears or the operator runs `dispose-create`. That
  is the accepted cost of never reporting clean over a create that may still land. A landing after a disposition is
  caught only if reported.
- **The first delete by C has limits.** It holds for ownership reads that succeed within 35 s and for sessions admitted
  under the deadline capacity. A provider outage, a failed read or a `Retry-After` hold can still delay it, because
  ownership is never skipped and rate limits are honored. Those cases stay visible and overdue at D, never a false success.
  Reads may be up to about 55 s old when their delete is issued; an older one is read again.
- **Reservations cost ordinary throughput.** Reserved slots stay idle when no deadline is near, so ordinary work runs
  on 4 slots. With normal provider latency this is invisible. With requests near their 35 s bound, verifying absence
  after the first deletes can outlast the teardown reserve, which shows up as overdue. Lowering the slots of a watchdog
  with armed sessions opens a `deadline-capacity-overcommitted` incident rather than unarming anyone.
- **The 0.5 s delete margin comes out of the last moment before C.** An episode or workload allowed until C loses at most
  that much host availability, so a controller's local timeouts must stop before it.
- **Time verification is unproven on a real host.** `adjtimex` was exercised with stubs on macOS only. Issue #72
  must confirm on the Linux management host that a synced clock reads as verified and that a boot before
  sync fails closed. A boot whose time daemon has not synced when the watchdog starts cleans up its armed
  sessions: the safe direction, but a reason to let sync finish on boot. Do not order the unit on
  `systemd-time-wait-sync` without a timeout, since a watchdog that never starts protects nothing.
- **Dispatch grants still need process enforcement.** The registry only proves that a run launched by `launch_by`
  with its stated estimate ends before deletion starts. Issue #67 must stop the process at that estimate, and must
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
