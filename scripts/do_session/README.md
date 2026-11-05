# do_session — DigitalOcean test-session planner, registry, watchdog, provisioning, fresh test runs, the measured window and its scorer (handoff slices 1–6)

Control code for the disposable DigitalOcean capacity sessions planned in
[issue #57](https://github.com/Operatorr/godot-networking-poc/issues/57), following the
[accepted controller handoff](https://github.com/Operatorr/godot-networking-poc/issues/61).

- **Slice 1, the planner:** explicit conditions and limits in, an **immutable hashed manifest**, the
  **legal next run** and an **explainable time/spend admission** out. It talks to no provider, SSH or
  network; the session directory is its only side effect and every file is create-only or
  append-only. A rejected freeze or admission therefore creates no provider resource by construction.
- **Slice 2, the registry and watchdog:** see [below](#session-registry-fencing-and-cleanup-watchdog-slice-2).
- **Slice 3, provisioning, access and cold bootstrap:** see [below](#provider-adapter-access-and-cold-bootstrap-slice-3).
  It has only ever run against offline fakes. No live account has exercised this code.
- **Slice 4, fresh-process runs and explicit resume:** see [below](#fresh-process-runs-and-explicit-resume-slice-4). It has run against a fake
  remote and as real processes on one machine, never over SSH or on a Droplet.
- **Slice 5, the two-host window and recorders:** see [below](#two-host-measurement-window-and-recorders-slice-5). The real binaries and recorders have run on loopback on one
  macOS machine, including real 60 s and 300 s windows, never on a Droplet or on Linux. It proves or refuses a window and scores nothing.
- **Slice 6, the strict scorer and search outcomes:** see [below](#strict-scoring-and-search-outcomes-slice-6). It has scored mocked recorder files and short real loopback runs. **No run can pass on this path outside Linux,**
  because it needs per-socket kernel counters, and no real pass has ever been scored. It makes no capacity claim.

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
(slices 5–6) and does not export or publish (slice 7). With a registry, `run_executor` derives the search from the registry and
mirrors it into this journal, so `paths` and `admit` keep working on the same session directory. The historical CAX11 gate
([issue #53](https://github.com/Operatorr/godot-networking-poc/issues/53)) is unchanged.

## Session registry, fencing and cleanup watchdog (slice 2)

Runs on the trusted management host, outside the disposable pair. Deadlines and cleanup intent live
there, so deletion needs no controller, laptop, SSH key or lease.

| File | Owns |
| --- | --- |
| `registry.py` | SQLite store and control-plane API: manifest, ownership, creation intents, t0/D/C, fencing, run and cleanup transitions, incidents (including `report_ownership_conflict` from a controller), hash-chained journal. Every write is one durable transaction that also stores its response under the request id. |
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
  *Deletion* normally starts on the tick 0.5 s before C, but never shortens active recovery. Explicit cleanup requests can start it earlier. Cleanup
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
  episode ends at C, prepared deletion is dispatched on the C boundary. The ordinary 0.5 s scheduling margin
  does not shorten recovery. Host or provider delays can still delay dispatch; this is not a hard-real-time service.
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
returns None, so a lost create response leaves the session open until the resource appears or the operator decides.
The DigitalOcean adapter keeps it that way. The published API reference documents no idempotency key and no lookup for
a create whose response was lost. Its 202 "does not indicate the success or failure of the operation", and action links
arrive only inside the response that was lost. None of that gives a request-specific terminal record, so no basis is
named, and no bound is derived from HTTP timeouts or paid experiments. `offline_fixture_receipt` is trusted only by
fixtures and by the watchdog when it runs against the fake.

The operator's exit is `registry_cli.py dispose-create --session S --intent ID --note WHY`, allowed only during
cleanup, so it can never permit a retry. The session then closes as `verified_absent_with_operator_disposition`, never
clean. A landing after that closure is outside reconciliation unless someone reports it; `record_resource` reopens
cleanup. Check the account by unique tag before disposing.

**What an adapter must do.** `do_api.py` does items 1 to 3 and declines 4 and 5, because the required guarantee does not exist:

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

- **Never run live yet.** `watchdog` refuses to start without an explicit provider, and refuses a fake without
  `--allow-offline-fake`. `do_api:from_token_file` is the real adapter, but only fakes have exercised it.
- **Live sessions get deadline checks, not inventory reads.** Before cleanup the watchdog reads only known Droplets,
  and only in the preparation window. A create no controller reported is found once cleanup starts, by unique tag.
- **A lost create response that never appears needs an operator.** The session stays open and overdue until the
  resource appears or the operator runs `dispose-create`. That is the accepted cost of never reporting clean over a create that may still land. A landing after a disposition is
  caught only if reported.
- **The first delete by C has limits.** It holds for ownership reads that succeed within 35 s and for sessions admitted
  under the deadline capacity. A provider outage, a failed read or a `Retry-After` hold can still delay it, because
  ownership is never skipped and rate limits are honored. Those cases stay visible and overdue at D, never a false success.
  Reads may be up to about 55 s old when their delete is issued; an older one is read again.
- **Reservations cost ordinary throughput.** Reserved slots stay idle when no deadline is near, so ordinary work runs
  on 4 slots. With normal provider latency this is invisible. With requests near their 35 s bound, verifying absence
  after the first deletes can outlast the teardown reserve, which shows up as overdue. Lowering the slots of a watchdog
  with armed sessions opens a `deadline-capacity-overcommitted` incident rather than unarming anyone.
- **The 0.5 s delete margin applies outside active recovery.** Workload admission reserves this margin.
  Recovery keeps its accepted deadline, including C; deletion at that boundary has no early scheduling margin.
- **Time verification is unproven on a real host.** `adjtimex` was exercised with stubs on macOS only. Issue #72
  must confirm on the Linux management host that a synced clock reads as verified and that a boot before
  sync fails closed. A boot whose time daemon has not synced when the watchdog starts cleans up its armed
  sessions: the safe direction, but a reason to let sync finish on boot. Do not order the unit on
  `systemd-time-wait-sync` without a timeout, since a watchdog that never starts protects nothing.
- **Dispatch grants are enforced on the guest, and only there once launched.** See [slice 4](#fresh-process-runs-and-explicit-resume-slice-4). A controller that
  is gone can no longer stop anything, so the supervisor's bound and the host fence do that work.
- **Storage failures hold back deletion.** Intent must be durable before a delete, so a full disk stalls
  cleanup and makes the host unhealthy. Losing the single-disk host entirely falls back to manual tag
  cleanup, the residual risk the operator accepted in issue #63.
- **A far-future clock step is sticky.** The ratchet expires every session (the safe direction) and
  refuses new ones while wall and effective time disagree. Recover with a fresh state directory once
  everything is closed.
- **Monotonic protection needs Linux.** Without `/proc/sys/kernel/random/boot_id` (for example on macOS)
  a reboot cannot be detected and only the persisted floor applies. A wall clock behind that floor fails closed
  there, but a smaller backward step can still delay C.

## Provider adapter, access and cold bootstrap (slice 3)

Turns an admitted manifest into a verified ready game/bot pair, or into ownership-safe cleanup with explicit incident
state. All of it has been verified only against offline fakes. No provider mutation has ever been sent.

| File | Owns |
| --- | --- |
| `do_api.py` | The real adapter over `http.client`. `DigitalOceanProvider` holds the watchdog's reads and exact deletes. `DigitalOceanProvisioningProvider` adds facts, creates, firewall updates and project assignment behind a gate. One route allowlist covers every request, and each call makes one attempt with an absolute bound over resolver, connect, TLS and exchange. |
| `remote_authorization.py` | The separately bounded packet every mutation needs, and `MutationGate`, which re-checks it and the frozen payload just before sending, holds the registry's recorded ids as the only authority to change an existing resource, and re-checks the window after connecting. |
| `resource_ownership.py` | The one ownership policy: exact tags and names, protected tags, retained ids. The watchdog applies it before a delete and the controller before any operation. |
| `provider_preflight.py` | Fresh project, account, quota, region, size, price, image, key and collision facts, judged by the manifest's own rules. |
| `session_access.py` | Exact firewall requests, the exact read-back comparison over every schema selector, and what a replacement may overwrite. Refuses any source that is not one routable host. |
| `guest_bootstrap.py` | Cloud-init user data: public key, sshd policy, limits, the host-key binding. Validated on every rendering. |
| `ssh_access.py` | Key-only, strictly host-verified SSH and scp, and the first-contact pinning decision. |
| `guest_agent.py` | Stdlib-only program uploaded to guests. It reports facts as JSON and decides nothing. |
| `readiness.py` | Pure rules over retained observations. A missing value always fails. |
| `provisioner.py` | The whole path, and `refresh_access`. |
| `provision_cli.py` | Operator CLI: `source-digests`, `preflight`, `provision`, `refresh-access`. |
| `fake_do_http.py`, `fake_guest.py`, `provision_fixtures.py`, `provision_fault_evidence.py` | Offline only. The fake account sits at the HTTP boundary, so tests run the real adapter. |

### The path

```text
authorization -> fresh facts -> register -> watchdog ack -> fresh facts -> admission -> arm (t0/D/C frozen)
  -> 3 tags -> firewall (read back) -> game -> bot
  -> active + ownership + exact plan -> project assignment (ownership first, read back)
  -> firewall with the bot's exact address (ownership first, read back, applied)
  -> exact inventory -> pin both host keys -> cloud-init done
  -> clean locked build on the bot host -> release relayed to the game host (hashes compared)
  -> probes (package inventories retained), clock bracket, sampler -> bot's SSH attempt must time out -> cross-host ENet smoke -> ports released
  -> exact inventory -> firewall unchanged -> mark_ready
```

Every failure stops the batch and requests cleanup. Nothing is repaired in place and no pair is replaced. The watchdog
deletes what the session owns, and if the request cannot be delivered, C still arrives on the management host.

### Choices worth knowing

- **Unknown creates.** The controller observes for 120 s, adopting the resource if it appears, and sends nothing while
  it watches. After that the batch stops with the request unresolved. Observation is a local wait, not a provider
  bound. Closure then follows [Create settlement](#create-settlement): a late landing is found by tag and deleted, and
  otherwise only `dispose-create` closes the session, labelled as a disposition rather than clean.
- **What a create response proves.** A 2xx with an exact id means it landed. 400, 401, 403, 404, 422 or 429 is
  `CreateRejected`. A connection that failed or did not open within its limits is `CreateNotSent`. Everything else stays
  unknown, including any 5xx, 408, 409, a redirect, a timeout once the request was being written, and a 2xx without an
  id. A rejection stops the batch and is not retried.
- **One absolute request bound.** `request_bound_s` covers the resolver, every address, TLS and the exchange, and the
  caller returns at the bound. No socket timeout reaches the system resolver, so connecting runs on a worker the caller
  can abandon. Only the calling thread writes a request, after connecting and after every send limit is checked again,
  so an abandoned worker can never send one. It closes what it opened. At most `MAX_CONNECT_WORKERS` (32, above the
  watchdog's 12 slots) can be unfinished. Past that a request fails at once as not sent instead of adding a thread. A
  resolver stuck for good holds those 32 and every request fails, visibly, until the process restarts.
- **Authorization covers one exact session and manifest, one pair and a time window.** It is re-validated at every
  mutation and again after the connection opens, immediately before the first request byte, and connecting cannot wait
  past the window. So the window bounds when a request may begin to leave the controller. It cannot bound when the
  provider finishes one sent just inside it. Write scopes and token expiry are operator attestations in the packet, because DigitalOcean has no endpoint
  that reports a token's scopes, and proving a write scope would itself be a mutation. Read scopes are proven by the
  preflight reads succeeding. The packet does not gate deletion: cleanup must work when no controller is left. Exact
  ids and ownership authorize deletes, and the watchdog's adapter cannot create anything.
- **Ownership before every operation.** Convergence, each project assignment, the firewall replacement, both inventories
  and refresh use `resource_ownership.py`, the watchdog's own policy, so provisioning cannot certify or operate on a
  Droplet that cleanup would refuse to delete. A conflict stops the work and is reported through
  `report_ownership_conflict`, which opens the same `ownership-mismatch` incident the watchdog would, before anything else
  happens. Owned resources are still cleaned up. The refused one stays with its incident, and protection is never
  stripped. The watchdog's next read clears the incident if the resource turns out to be owned after all, as with a
  firewall whose targets are right but whose rules someone edited. During a refresh a conflict refuses the refresh and
  opens the incident, and does not itself start cleanup: the operator decides, and C still arrives.
- **Replacing a firewall.** PUT overwrites everything, so before every attempt, retries included, the firewall is read
  and must still have the recorded id, the exact name, exactly its two role tags, no direct Droplet, and only rules this
  session could have written: its own outbound set, and SSH and game rules whose sources are exact hosts. Only those
  addresses may differ. Anything else is refused with nothing sent, and the gate refuses an id the registry does not
  record. A firewall already as desired, as after a lost response, gets no second PUT. **DigitalOcean documents no
  conditional update, so a read-then-write race remains:** a change landing between the read and the PUT is overwritten,
  and the read-back then sees our own replacement. The window is one request, not zero.
- **Control before each mutation.** `require_control` renews the lease and checks fence, cleanup state and C with no
  throttling. It runs after every wait, after the ownership read and immediately before each PUT and assignment. It too
  answers only for the moment it was asked. Cleanup, an abort, an expired lease, a takeover or C stops a refresh with
  `applied=false` and `stopped` naming the reason, and the rules in force stay as they are.
- **Exact selectors.** Comparison covers every selector in the
  [firewall schema](https://raw.githubusercontent.com/digitalocean/openapi/main/specification/resources/firewalls/models/firewall_rule.yml)
  (`addresses`, `droplet_ids`, `kubernetes_ids`, `load_balancer_uids`, `tags`), ingress and egress alike. An unknown
  populated field is refused rather than ignored. Empty selectors count as absent. Drift stops before any Droplet is
  bought, stops readiness, and refuses a refresh.
- **A success without a record is not absence.** Only an authenticated 404 means gone. A 200 with a null, scalar or array
  where a record belongs is a failed read, so cleanup stays open and retries it.
- **Package provenance.** The agent reports every package and version with the command's status and a hash, and the
  controller keeps the list in `provisioning/packages-<role>.json`, because teardown destroys the only other copy.
  `readiness.json` keeps each role's status, count, hashes and artifact path, and `required_artifacts` names the files an
  exporter must carry. Its own hash, in `mark_ready`'s evidence reference, binds them. A failed, incomplete, malformed or
  self-contradicting list stops readiness, and one that parsed is still retained to explain why. Real inventories stay in
  the private session directory. Committed timelines hold only the synthetic fixture.
- **Subprocess output.** SSH stdout and stderr go to private temporary files while the controller polls and
  services lease callbacks, avoiding pipe backpressure from full package inventories. Each stream is checked
  against a 4 MiB limit on every poll and after exit; oversized output fails rather than becoming a truncated
  success. Temporary storage can grow between polls and needs local disk space; files close on every exit path.
- **Refresh completion.** The final firewall read-back must still have live controller authority before it
  reports success, including when the requested rules already match and no PUT was necessary.
- **First contact.** No private key goes into user data. Each Droplet gets a random nonce through the authenticated API,
  and at first boot it publishes `HMAC(nonce, host key)` and deletes the nonce file. The controller scans the key, reads
  the proof over a connection pinned to that key, and pins it only if the proof matches. The nonce exists only in
  controller memory and user data (still readable from the provider's metadata service on the guest). It authorizes
  nothing, and evidence writes refuse it. Pinning makes a host key change a failure.
- **A restarted controller cleans up.** Nonces are not persisted, so it cannot verify first contact, and an armed
  session id is never provisioned again. Cold bootstrap has nothing partial worth saving, and a live lease refuses a
  second controller outright.
- **The bot host builds both binaries.** A 1 GiB game host cannot be trusted to link a release build, and compiling
  there would leave page cache and memory history behind before measurement. The relay goes through the controller,
  since guests hold no key for each other. Each role's provenance records what it runs, and the build report records
  where it was made.
- **Binary hashes.** A calibration session cannot know its build's hash in advance, so it records the observed hash,
  and the report says `observed_for_calibration`. The relayed copy must still equal the builder's. Lifecycle smoke and
  capacity sessions enforce the frozen hash, so a build that does not reproduce stops them.
- **One firewall for both roles,** as the frozen intents define. UDP 8081 therefore also applies to the bot host, where
  nothing listens. Metrics has no rule, and the server binds it to loopback, which the smoke verifies.
- **Admission.** Capacity sessions pass the full planner admission. Calibration and lifecycle smoke have no search yet,
  so they must fit setup, collection, recovery and teardown inside the cap, plus the cost and transfer limits. Their
  workload plans belong to their own gates.
- **After `mark_ready`.** This slice leaves a verified pair with no workload process running. It renews its lease only
  while running. `run_cli.py execute` continues under the token it printed; if that lease lapses, only `resume` gets back in.

### Running it

```bash
cd scripts/do_session
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q      # all offline
python3 provision_cli.py source-digests --repo ../.. --sha <full-sha>   # local: digests to freeze
```

`preflight`, `provision` and `refresh-access` contact the provider, and none of them has ever been run. `provision`
and `refresh-access` need an authorization packet and refuse before reading a token without one. Watchdog deployment is
issue #72: `OMEGA_DO_PROVIDER=do_api:from_token_file`, `OMEGA_DO_PROVIDER_ARG=<restricted token file>`. The token is
read once at service start, so rotating it means restarting the service.

Retained timelines: `docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice3/` (23 scenarios). Regenerate with
`provision_fault_evidence.py`. They are not capacity or live-provider results.

### What only a live run can show

These are stated so Gate A checks them instead of assuming them. Each failure direction is safe: the session stops and
cleans up, or stays open and visible.

- Real response shapes for everything in `do_api.py`. They come from the public API reference, and a few points it
  leaves open are handled conservatively: `POST /v2/tags` on an existing name, a tag listing for a deleted tag, and
  `ports` spelling on read-back. If listing a deleted tag returned 404, sessions would stay open rather than close. If a
  real firewall response carried a populated rule field the published schema does not list, readiness would refuse it.
- That no real read-then-write interleaving ever hits the firewall race above. It is disclosed, not excluded.
- `cloud-init status --format json` semantics, sshd policy ordering and `nofile` limits on the pinned image, and the
  time taken to publish the host binding. The 600 s contact wait is a guess until calibrated.
- Whether a release build reproduces byte for byte between two cold sessions. If it does not, Gate B stops at the hash.
- Real ENet smoke behaviour across the public route. `guest_agent.py` was exercised with stub binaries.
- Linux itself: the agent's `ss`, `timedatectl`, `sshd -T` and `dpkg-query` paths ran only behind mocks on macOS. A
  package list cut exactly at a line boundary is caught by required entries (`base-files`, `dpkg`, `libc6`,
  `openssh-server`, `python3`) only if it lost one of them.
- Automatic detection of the operator's current address. Allowlists are exact values supplied at freeze and refresh, and
  this code cannot prove such a value is current. That stays an operational gate.

## Fresh-process runs and explicit resume (slice 4)

Reuses the verified pair for every run. Each run gets new processes, a new socket and its own sealed directory, and an interruption never turns into a replay.

| File | Owns |
| --- | --- |
| `guest_runner.py` | Stdlib program uploaded to both hosts under a content-addressed name: the host fence, launch checks, the supervisor with its absolute bound, identity and socket facts, stop and seal. |
| `run_plan.py` | What a trial means on one host, as pure data. `ReleaseAdapter` holds the measured binary arguments of slice 5, and `swarm_bound_s` the time a healthy swarm needs. |
| `run_checks.py` | Pure rules over host and run facts. It sorts execution failures and holds the scorer boundary. A missing fact fails. |
| `run_executor.py` | The controller: one run, reconciliation of an unfinished run, explicit resume, collection and the cleanup request. |
| `run_cli.py` | Operator CLI: `execute`, `resume`, `collect`. It has no provider mutation and no scorer option. |
| `fake_run_guest.py`, `run_fixtures.py`, `run_fault_harness.py`, `run_fault_evidence.py`, `fixtures/local_standins/` | Offline only. |

### One run

```text
admit legal remaining paths -> publish selection -> preflight both hosts      a dirty host stops here, with the run untouched
  -> dispatch_run: durable intent, grant                                      from here the run id is spent for good
  -> launching -> authorize, game, recheck -> wait for its new socket -> authorize, bot, recheck -> running
  -> watch, renewing the lease -> stop -> seal both hosts -> export through .partial -> execution.json -> sealed
  -> classification.json -> record_run_outcome -> planner journal mirror
```

- **The registry decides what comes next.** For a capacity session `dispatch_run` takes only the single legal next trial, replayed from its own `runs` table, with an
  estimate covering the whole trial. Nothing else can be dispatched, and the search cannot advance past a run with no outcome. Calibration and lifecycle smoke are refused
  with `no_workload_plan`; their plans belong to their own gates. An outcome that advances the search needs the run in phase `sealed`. `typed_runs=False` exists only for slice 2's
  lifecycle fixtures, and `registry_cli.py` cannot set it.
- **Fencing reaches the host.** Every guest operation that starts or stops a process carries the token: `guest_runner`'s `start`, `stop` and `seal`, and `guest_agent`'s `fetch_source`, `build`,
  `install_release`, `sampler`, `smoke_game_start`, `smoke_bot` and `smoke_game_stop`. All of them check, under one lock, one fence file that only rises. A new controller raises it first, so a
  replaced controller's late start is refused, and anything started just before is in the inventory the new controller then stops.
- **A process start is a durable, single-use grant, and revocation has a defined order against it.** The registry cannot reach a guest and a guest cannot reach the registry, so no check spans the two.
  What exists instead is a lease on each start. The invariant: *a start commits only before the revocation that covers it takes effect, and that effect is recorded.*

  ```text
  controller                       registry (SQLite, one transaction)                guest (host lock)
  grant_prepare --------------------------------------------------------------------> fence open at this token? mint id, start its elapsed clock
  authorize_guest_action(id) ----> token, lease, cleanup, C, run phase, no revocation pending
                                   INSERT grant (outstanding) + journal: INTENT COMMIT
                                   ttl_s; conclusive_at = commit + ttl_s + 1 s, never past lease or C - 0.5 s
  start(plan, id, ttl_s) ---------------------------------------------------------> token == fence, not closed? burn id once (create-exclusive): GUEST COMMIT
                                                                                    elapsed <= ttl_s and wall within tolerance, on arrival, after slow checks,
                                                                                    from the process about to spawn, and once it exists (then fence and slack)
  resolve_guest_grant(started) --> settled. A lost reply settles nothing.
  ```

  - **Identity and state.** Each intent is one row in `guest_grants`, keyed by the id the guest minted: `outstanding`, then `started`, `refused`, `fenced` or `expired`. The registry journals every change.
  - **Serialization.** Registry writes are one `BEGIN IMMEDIATE`, so a revocation commits either before the intent, which is then refused, or after it, which then finds it outstanding. On the guest, the flock orders a start against a fence: the fence refuses it, or the fence's answer names it.
  - **Revocation.** `operator_abort`, `request_cleanup`, the deadline and `acquire_control` commit at once and refuse new grants from that moment. If they find an outstanding grant, the session reads `revocation-pending`, with `revocation.target_state`, `effective_at` and the grants, and the watchdog issues no destructive request. It takes effect when every such grant is resolved, its guest has acknowledged a fence (`report_guest_fence`), or it is conclusively expired, whichever is first. `revocation_effective` is journaled. A new controller can stop, seal and raise fences meanwhile, but gets no grant and cannot resume.
    Cleanup acknowledgements, RPC session listings, CLI listings and status use the same pending/effective projection. Acceptance of an abort durably records intent and immediately blocks new authority; it does not acknowledge completed revocation while outstanding grants remain. A start committed before effective completion may subsequently execute and must remain accounted for; no new start may commit afterward.
  - **Expiry and C need no step.** A grant is never conclusive past the lease it was issued under or `C − 0.5 s`, so a lapsed lease leaves nothing usable, and the hold cannot reach the deadline tick. The longest hold is 11 s from the revocation, with or without a controller.
  - **Clocks.** `ttl_s` runs on the guest's own boot-time clock, from a mint that happened before the commit, so a guest whose wall clock is wrong cannot stretch it. A reboot voids it. The wall limit stays as a second reason to refuse, never as a reason to accept.
  - **Replay.** A second delivery finds the id burned, even after the first run finished. The burn comes first, so a refusal cannot leave the grant usable. A lost reply leaves the id burned on the guest, and the next `fence` or `inspect` reports it as `grants_consumed`.
    A `refused` result such as `launch_unconfirmed` does not prove that no start committed: the grant may already be burned. Retained process inventory and reconciliation still account for any resulting process.

  **What this does not do.** A start already granted when an abort commits can still land during those seconds. No check can refuse it without a channel to the guest, and the contract keeps credentials off guests and gives the watchdog no SSH key. It lands before the revocation takes effect, the record says so, and no delete has been issued. A live controller stops it at once through the recheck and the inventory. With none left, it ends at its process bound or at the deletion that follows. After the revocation takes effect, no start can commit, on the assumption that a guest's elapsed clock runs at about the right rate: 1 s of slack per 10 s, not measured. A guest paused between its last look and the fork can create a process late, and it is stopped as soon as it runs again, by the check after the spawn.

  A controller that sees cleanup still closes the fence on both hosts. A closed fence never reopens under any token, refuses every start and still allows stop and seal.
- **The readiness smoke ends by itself.** Each process it starts runs under `guest_agent bounded`, a helper that stops it at `--lifetime-s` (120 s for the server) with or without a controller. The start
  is inside the controller's `try`, so a lost reply still reaches the stop. The stop leaves a mark, so a start for that smoke arriving later is refused. It settles the process by boot id, pid and start
  time. The next controller retires any smoke left running, on both `resume` and `collect`.
- **Bounds hold with no controller.** The supervisor stops the game by `launch_by + estimate − finalization − export − grace`, and the swarm one grace earlier, by its monotonic clock or the
  absolute wall time, whichever comes first: SIGTERM, then SIGKILL after the grace. The `systemd-run` unit (`RuntimeMaxSec`, `KillMode=control-group`, `Restart=no`, `OOMPolicy=continue`, so a kill reaches the supervisor to record and not the whole unit, and `Delegate=memory`, so the game can have a cgroup leaf of its own) is the second bound, for a
  supervisor that dies. `KillMode` and `RuntimeMaxSec` cover the delegated subtree too. The relative bound counts from the actual launch and is cut to what the absolute limit leaves. Since `launch_by + estimate ≤ C − 0.5 s`, those limits end before the deadline tick.
  The game's startup wait and both stops come out of `process_reset_s`, and a smaller value is refused. If too little of the grant is left for the whole workload when a start reaches the guest, or when
  the swarm is due, nothing starts and the run is INCOMPLETE. No guest command starts past `C − 0.5 s`, and each one's timeout is cut to what is left. Inside an evidence recovery episode the same
  applies to its own cutoff of `min(first failure + grace, C)`, for every command, file and role, and lease renewal during the episode gets only the time left too.
- **Identity is boot id, pid and kernel start time,** plus the unit's `InvocationID` on systemd. A reused pid is not our process, and start ticks can repeat after a reboot, so a mismatch on any of them is never signalled. Each new process and socket is compared
  against the host's ledger of every identity used before. The game socket comes from `/proc/net/udp` joined with `/proc/<pid>/fd`, so its drop counter is that socket's and no other.
  Counter rows belong to one pid, start time and inode, and a change of owner or a counter moving backward is refused.
- **Between runs** each host must show: the frozen binary, config, sampler and runner hashes; clean frozen source on the builder; the boot id from readiness; free ports; no process from those
  paths; no `omega-*` unit; no run active; a new run directory; the fence naming this controller; enough disk; and only `noqueue`, `mq`, `fq_codel`, `fq`, `pfifo_fast` or `pfifo` qdiscs with no
  filters. Unknown is a failure: no `tc` means the impairment state could not be read. A failure stops the batch through `record_batch_stop`, so it survives this controller.
- **Directories are immutable.** The run directory is created exclusively. Sealing hashes every file and makes the tree read-only, for interrupted runs too. Exports go through `.partial` and SHA256,
  and they are promoted with a hard link, because a rename would overwrite. A file that fails stays partial and is never promoted.
- **Each run has its own sampler,** a separate process writing its own file. One that dies during a run stops that run as infrastructure.

### What a run can say

| Execution facts | Recorded | Effect |
| --- | --- | --- |
| Host, identity, sampler, seal or export failure; lost contact for 45 s; a game that ended during startup | `INFRASTRUCTURE_FAILURE` | Terminal |
| The swarm crashed (a signal or any status but 0 or 1), and the game did not fail | `INVALID_LOAD` | Terminal; no scorer is asked |
| The swarm overran its bound | `INCONCLUSIVE` | Terminal; a timeout is never called capacity |
| Controller lost, grant unused, cleanup during the run | `INCOMPLETE` | The dependent coarse or refinement path stops; an untouched confirmation sibling stays eligible |
| The processes finished, or the game failed by itself | Whatever the scorer says, within the rules below | `PASS` and `FAIL` advance the frozen search; others stop the batch |

The swarm exits 1, with its report written, when the server misses the binary's own success criteria. `ReleaseAdapter.completed_exit_codes` therefore counts that as completing: it is a verdict on the server, which must stay available to the scorer, and this slice ignores the verdict itself. A 1 with no report is missing evidence.

**Evidence boundary.** `execution.json` is the line between running and scoring. It binds identities, exits, socket rows, seal hashes and export results, and it is what `evidence_ref` chains back to. A scorer is
a function of `dict(run_id, trial, root, execution, execution_sha256, execution_ref)`: verified local files and sealed facts, nothing live. It returns `dict(outcome, evidence_ref, scorer, reasons)`. It cannot
PASS a run whose processes failed, or call FAIL with a failed generator unless it sets `generator_failure_attributed_to_server`. Anything malformed becomes `INCONCLUSIVE`. The executor's default scorer is
[`capacity_scorer.score`](#strict-scoring-and-search-outcomes-slice-6), and `run_cli.py` has no option to replace it. Fixtures in this slice script outcomes through `run_fixtures.scripted_scorer`; those outcomes are not measurements.

Since slice 5 the adapter runs the measured swarm, and each finished run keeps a `window-proof.json`. A scorer receives it as `window_proof`, and `apply_scorer` refuses a PASS unless its status is `complete`. See [below](#two-host-measurement-window-and-recorders-slice-5).

### Coming back

A crash leaves whatever the registry last committed. Returning under a new token pauses the session and marks an active run interrupted. Nothing resumes by itself.

| Died | The run | Next |
| --- | --- | --- |
| After selection, before `dispatch_run` committed | Untouched | Explicit resume dispatches that same trial |
| After `dispatch_run`, through launch and watch | Touched for good; stopped, sealed, `INCOMPLETE` | Its dependent path stops, and resume refuses with `no_eligible_untouched_work` |
| After seal, with the swarm having ended by itself | Scored from retained evidence by the frozen revision, or read back if `score.json` was already retained and holds up. `INCOMPLETE` from any other controller, or for a fixture with no scorer | Follows that outcome |
| After `classification.json`, before the commit | The recorded verdict stands if it holds up and no stop fact is on record, is not scored again, and a terminal one stays terminal. A refused one is `INCONCLUSIVE`, short of a terminal fact | Follows that outcome |
| After the commit | Outcome stands; only the local mirror is repaired | Next untouched trial is eligible, unless a stop fact is found for a committed run, which stops the session and leaves the outcome |

An interruption does not hide a failure the evidence shows: a rebooted host or a sampler that died gives `INFRASTRUCTURE_FAILURE`, and a swarm that crashed by itself gives `INVALID_LOAD`.

Nor does a crash change a verdict already determined. If the controller that watched the run wrote `execution.json` and died before classifying, the next one reaches the verdict that controller would
have reached from its record, carries those problems into `execution-reconciled-<token>-<n>.json`, and cannot have them unsaid by a transfer that now works. Every generation counts: a returner that dies after writing its own record leaves `demonstrated_problems` and `demonstrated_outcome` for the next one, each carried fact names its source record and hash under `carried_from`, and what it only failed to reach stays in `uncertain`, which is not carried and cannot become a terminal failure. So a corrupt export in one confirmation stays terminal, and
its untouched siblings refuse resume, with or without a scorer. `INCOMPLETE` is kept for what really is unknown: a run cut short, a host that could not be reached, or a transfer that could not run during
the return. Corrupt bytes found during a return are a demonstrated failure, and they outrank a score or classification retained before the crash: see [stop facts](#through-the-executor). A swarm that exited 1 with its report is still not invalid load: that is a verdict for the scorer, or `INCOMPLETE` without one.

`run_cli.py resume --operator-request REF` runs in this order, and any failure leaves the session paused with the attempt recorded in `execution/journal.ndjson`:

1. Exclusive control. A live lease needs `--takeover`, which makes the other controller stale.
2. Not in cleanup, past C or terminal, and the manifest hash unchanged.
3. This controller's checkout at the frozen `controller_sha`, with no edits under `scripts/do_session`.
4. The pair as the provider reports it: exact ids, plan, ownership, address, firewall target, rules and applied state, and nothing extra under the session tag. Host pins are inherited, never made.
5. Fence raised, any smoke left running retired, then every unfinished run stopped, sealed, exported and classified. A run directory the registry never dispatched refuses the resume.
6. Admission on the legal remaining paths against the original deadline and spend, and a legal next trial.
7. Full readiness again: probe, clock, sampler, SSH enforcement and a real ENet smoke, each process start freshly authorized, plus the same boot id, kernel and package list as at `mark_ready`.
8. Both hosts reset, as between runs, then admission once more, because revalidation took time.
9. `record_resume`, which refuses unless every check is true and names the exact next run.

`run_cli.py execute` makes check 3 as well, before touching any guest. The wrong checkout changes nothing and requests no cleanup: C still arrives, and the right checkout can run or `collect`.

`run_cli.py collect --reason WHY` is the other exit. It stops and seals whatever is left and requests cleanup, from any checkout: only a new decision needs the frozen revision. Slice 7 owns the session export, so no session can read `clean` yet. C arrives regardless.

### Collecting before the delete

A seal names what should have arrived, and does not prove it did. At the end of a batch every file of every planned role is checked against its seal and retained in `execution/evidence-inventory-token<N>-<i>.json`
as `verified`, `missing`, `corrupt` or `unreadable`. A role whose start was refused before any directory existed is `never_created`, and is not waited for. Anything unverified gets one bounded recovery
episode before the delete, then the registry's evidence status says `corrupt` or `missing`, or `partial` when all run files are verified. A retained `.partial` is never promoted, and an existing file with other
bytes is never overwritten. Recovering the bytes does not undo a failure already recorded.

No local failure stands between a finished batch and its cleanup request. A full disk or a permission error while collecting is kept on `wrap_up_error`, journaled and printed, the CLI exits 2, and the request still
goes out. A controller that has lost its token cannot request cleanup, because the registry refuses it. The watchdog still deletes by C.

### Running it

```bash
cd scripts/do_session
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q                                  # about 5 minutes with the real-process suites
OMEGA_LOCAL_RELEASE_DIR=<dir with omega-server and omega-load-test> python3 -m unittest test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path
```

`test_guest_runner` and `test_run_local_integration` are real processes on one machine: real signals, sockets and crashes through a real registry CLI and watchdog. Retained timelines:
`docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice4/` (38 scenarios, regenerated by `run_fault_evidence.py`). They use the fake remote, so they are reproducible and claim nothing about a host.
Slice 3's generator records `RETAINED_AGENT_SHA256` as the uploaded agent's hash, a label in a timeline where no agent ran, so fencing the agent's process steps did not rewrite that retained evidence.

### What only a live run can show

These are stated so Gates A and B check them instead of assuming them. Each failure direction is safe: the batch stops, or the session stays open and visible.

- **Linux and systemd.** `/proc` start ticks and socket rows ran against text fixtures only. `systemd-run`, `InvocationID`, `RuntimeMaxSec`, `KillMode` and `OOMPolicy` ran through shims that start the real supervisor. `sudo -n
  systemd-run --uid` from an SSH session, cgroup kill and `--collect` behaviour are unverified. Python 3.12 is unverified: everything ran on macOS with Python 3.9.
- **Real SSH.** Only `SshAccess` argument building and pin restoration are tested. Polling logs in over SSH every 10 s on the host being measured. Its cost is unmeasured, and slice 5 should decide whether to keep it during a hold.
- **`tc`.** The real output format is untested, and the local fixture's `tc` is scripted. If a stock image reports a qdisc outside the allowed list, every run stops before dispatch; Gate A must read the real list.
- **Socket identity on macOS** is development-only and has no drop counters, so `require_counters` is off in the local harness. Real drop counters have never been read.
- **Grace values and the 45 s contact tolerance** are declared, not measured. Export time and size are bounded per file only, and a hold's real log volume is unknown.
- **A process-group supervisor killed with -9 leaves its workload running,** as the local tests show, until a controller stops it by identity. On a Droplet the systemd unit is what bounds that case, and that is unverified.
- **Fence and ledger live on the guest.** A guest rebuilt or tampered with loses them, which the boot id, package and hash checks are meant to catch, not prevent. A guest is not a trusted party.
- **Authorization is against delay and staleness, not malice.** The token and window travel from the controller, unsigned. A controller holding the SSH key could lie to a guest in any case, and the registry
  has no channel of its own to one.
- **The 10 s window and 1 s slack are declared, not measured.** The mint round trip, a registry commit, an SSH login and the guest's own checks must fit in 10 s on a real host. If they do not, the start is refused and the run is `INCOMPLETE`, which
  is the safe direction but stops the search. A start now costs one more SSH login, before any workload exists.
- **A smoke helper killed with -9** takes its server with it on Linux through `PR_SET_PDEATHSIG`, which has not run here. On macOS the server survives until a stop settles it by identity, as the local tests show.
- **Readiness smoke during resume** overwrites the earlier readiness logs on the guest. Readiness evidence kept by the controller is unaffected.

## Two-host measurement window and recorders (slice 5)

Turns a fresh run into attributable per-role observations over one common scored interval, or an explicit refusal. It scores nothing: [slice 6](#strict-scoring-and-search-outcomes-slice-6) does, over this proof and the same files. Terms: a *generator shard* is one swarm thread that owns its bots, and is not the glossary's server **Shard**. A *window* is the common scored interval.

| File | Owns |
| --- | --- |
| `rust/load_test/src/measured.rs` | `omega-load-test --measured-window`: the barrier, future window, acknowledgments, per-bot input grid and per-shard create-only recorders. [Its README section](../../rust/load_test/README.md#measured-window---measured-window) has the details. |
| `rust/server/src/measurement.rs` | With `OMEGA_MEASURE_WINDOW_EVIDENCE=1`: `process.json`, `population.ndjson` (auth and disconnect transitions, wall/monotonic pairs) and `final.json`, all create-only, including `ticks.csv` and `server.ndjson`. Unset, it behaves as before, so historical campaign units keep restarting in place. |
| `scripts/quick_stress/sample_host.py --identity` | The role collector: a header naming the schema, then per row this sampler's clock pairs on either side of every counter read, boot id, each process's kernel start identity and per-thread CPU, every UDP socket that exact process owns (inode, endpoint, drops, queues), raw memory, OOM and interface counters, and what each sample cost. Host-wide kernel counters stay in `udp.snmp`. |
| `measurement_schema.json` | The frozen schema: `omega.measurement/3`, the producers and their roles, the limits below and the file lists. A manifest freezes its id and SHA-256 as `telemetry_schema`; `provision_cli.py source-digests` prints both. |
| `measurement_window.py` | `prove(...)`: pure over verified local files. `complete`, `invalid` or `inconclusive`, with coded reasons and facts. |
| `measurement_fixtures.py`, `measurement_local.py`, `measurement_evidence.py`, `measurement_offline.sb` | Offline only: mocked recorder files, one real local run, the retained evidence, and the sandbox profile for running the real battery with the external network refused. |

### Reconciling the checkout with the historical harness

The handoff inspected a single-threaded `bb583d4` and the Change A reference `98a6304`. The checkout this slice started from has neither shape, so nothing here assumes them:

| | Inspected earlier | This checkout before slice 5 (PR 52's swarm) | Slice 5 measured mode |
| --- | --- | --- | --- |
| Threads | One thread | `--threads N`, round-robin, geometry on each thread | Kept, with 4 explicit threads and refused if fewer bots than threads |
| Join cadence | Sequential settle | Slot by global stagger, but each shard waits for a bot to settle, so a slow handshake delays that shard's later slots | No settling. A slow handshake never moves another bot's slot, and each actual time is recorded |
| Start of measurement | Timer | `RunClock` fires when the last shard's ramp ends, including a shard that failed. No authentication barrier and no warmup | All N authenticated, 2 s warmup, one published future start and end |
| Barrier | None | Other shards keep polling, because `RunClock` never blocked them | Kept: readiness is a value the coordinator reads, and shards read a window. Nothing waits |
| End of measurement | Timer | Each shard times out by itself | One published end, an end acknowledgment and frozen counters from each shard, then a 2 s guard before drain |
| Per-bot observations | Single-thread `bots.ndjson` | Disabled when threaded, and overwriting on restart | One create-only file per shard |
| Input accounting | Cumulative, re-anchored after a stall | The same | A fixed grid from authentication. What a window was owed is arithmetic |
| Server population | Tick rows only | Tick rows only | Tick rows, auth and disconnect transitions, and a final count |

The legacy path is unchanged: `quick_stress`, the campaign harness and `--threads` runs without `--measured-window` take the same code, apart from the counting socket wrapper, which adds counters and no behavior.

### One measured run

```text
controller  clock-before.json (raw readings, narrowest of 3 per role), then dispatch
game        ENet socket open, recorders on
swarm       bot i connects at i x 100 ms -> N authenticated -> 2 s warmup -> window published 1 s ahead, durable first
  shards    each records window_observed, ack_start, ack_end, freeze
  hold      60 or 300 s, all shards polling, all recorders flushing 1/s
  guard     2 s still connected and polling, so the server's population is provable past the end
  drain     up to 1.5 s, outside the window by construction; footer, fsync, window.json
controller  stop (SIGINT first, so recorders finish), clock-after.json, seal, export
            window-proof.json over the verified files -> execution/classification as in slice 4
```

The 4.5 s of lead, guard and drain live inside the admitted `process_reset_s`, and the controller refuses a manifest whose value cannot also hold the game start wait and two stop graces (29.5 s with default policy). The bound also covers a final authentication at the readiness limit, so the search's time model and its 401 legal paths are unchanged.

### What the proof holds a run to

Limits live in `measurement_schema.json`, which the manifest freezes.

| Evidence | Rule | Reason code |
| --- | --- | --- |
| Producers | `swarm.json`, `window.json`, the coordinator and every shard header, `process.json` and `final.json` state the frozen schema id and the role the schema gives them; each collector's header states the id. Checked before anything else in that recorder is read, and independently of the manifest's hash, which proves only that bytes arrived. `population.ndjson` and `ticks.csv` carry no header and are bound by `final.json`'s row counts. Clock brackets must be their known schema too | `schema_mismatch`, `clock_mapping_missing` |
| Build | Every swarm binary states `build.fault_injection`, whether or not a `--fault` was given. A fault build can never prove a window, even with nothing injected; a swarm that states no build cannot either | `fault_injection_build`, `build_unstated` |
| Controls | Exactly the trial's N and hold, and the manifest's strategy, difficulty, seed, 30 Hz, 4 threads, 100 ms, round-robin, and a stated empty fault list | `workload_mismatch`, `fault_injection_build`, `ownership_mismatch`, `geometry_not_initialized` |
| Recorders | Numbered from zero, one process nonce, header first, footer last, a footer that states no recorder failure. Server rows match `final.json` | `recorder_truncated`, `recorder_overwritten`, `recorder_failed` |
| Join | Each bot within 100 ms of its global slot, and authenticated | `global_stagger_violated`, `bot_never_authenticated` |
| Liveness | No shard gap over 500 ms, from first poll to drain, measured by the shard and reported separately by the coordinator | `poll_starvation`, `poll_liveness_missing` |
| Window | Published before its start, final authentication inside the readiness bound and start at least 2 s after it, seen by every shard first, length exactly the hold, each acknowledgment within 500 ms. Each boundary row appears once, in the order observed, start, end, freeze, drain, footer | `window_not_established`, `readiness_bound_exceeded`, `window_not_future`, `warmup_violated`, `window_observed_late`, `missing_acknowledgment`, `boundary_contradiction`, `early_shard_exit` |
| Freeze | Has its own real time, at or after the end and the shard's end acknowledgment, and before a drain that is itself present and timed. A snapshot proves only what came before it | `counters_not_frozen`, `freeze_time_missing`, `frozen_before_end`, `frozen_before_end_acknowledgment`, `drained_before_freeze`, `drained_before_end`, `drain_missing`, `drain_time_missing` |
| Input | Per bot, integers only: `sent x 100 >= scheduled x 99`, so exactly 99% is valid. Bots dead in the game still send idle frames and still count. A frame scores if its slot is inside and the enqueue itself came before the end, by that enqueue's own timestamp. Every required count must be a real non-negative integer before its value means anything: absent, null, text, a boolean or a negative is missing, never zero. A pooled average cannot hide one bot | `offered_input_below_minimum`, `input_record_missing`, `bot_errors`, `generator_socket_errors`, `peer_sample_coverage` |
| Clocks | Below | `clock_mapping_missing`, `clock_ambiguous`, `clock_step`, `host_rebooted` |
| Population | Every Tick in the mapped interval holds exactly N with contiguous numbers, every bot has a server auth before the interval, no disconnect in it, and entity ids agree. A disconnected bot owes nothing after the disconnect, which is judged by itself. It still owes the floor over the part it was connected for, less the one slot the disconnect can interrupt, because starvation before a disconnect is not explained by it | `population_lost_in_window`, `population_boundary_ambiguous`, `server_tick_gap`, `server_tick_coverage`, `server_auth_evidence_missing`, `server_refused_a_join` |
| Identity | Supervisor pid, kernel start and boot id match every recorder and collector row, and nothing was used by an earlier run on that host | `pid_reused`, `process_identity_reused`, `process_identity_changed`, `process_lost_in_window`, `recorder_overwritten` |
| Sockets | Per bot and for the game: one inode from baseline to final row, a real counter in every row, never backward. A generator drop is invalid load; a game drop stays a fact for the scorer. Host kernel counters are reported beside them and attribute nothing | `socket_identity_changed`, `socket_identity_reused`, `socket_counter_reset`, `socket_counters_missing`, `socket_evidence_missing`, `generator_socket_drops` |
| Collectors | A baseline whose counter read finished before the earliest possible start, a final read that began after the latest possible end, rows in order, and no silence over 5 s. A read's span runs from `clock` to `clock_after`, widened by the row's `collector_ns`, which must contain it. A read that straddles a boundary is neither baseline nor final, so what happened during it is counted by the rows around it, or the boundary is `inconclusive`, and never a false zero | `collector_boundary_missing`, `collector_gap` |

A reason's category sets the status: `generator` or `server` evidence means `invalid`; `evidence` or `clock` means `inconclusive`. Generator and server facts decide over missing evidence, and all reasons stay listed, because attribution is the scorer's.

`facts` keeps the counts the scorer needs (per-bot scheduled, sent and what was owed before any disconnect, sample coverage, socket drops, kernel deltas), and the raw per-bot ENet samples stay timestamped in the shard files. A disconnected bot's `scheduled_before_disconnect`, `sent` and `disconnected.at_ns` let the scorer tell starvation before a disconnect from frames missing after it. This proof reports both and names no cause: a below-minimum reason here does not say the server or the generator was to blame, and establishing a server-caused disconnect is still the scorer's. RTT, loss, Tick time and game-socket drops are not judged here. **The proof never says PASS, and `establishes_capacity` is always false.**

### How clocks are handled

Each process counts from its own start, and the two roles are never compared directly. A boundary moves only through intervals:

```text
swarm mono -> bot wall      nearest tight pair from the coordinator, plus 200 ppm per second of distance
bot wall -> game wall       hull of the before and after brackets, for both hosts
game wall -> game mono      nearest tight pair from the server, the same way
```

The result is an interval around each boundary, and the server must prove N across the outer one. A loss in the certain middle is `population_lost_in_window`; a loss only at the uncertain edge is `population_boundary_ambiguous`. A half-width over 2 s, the size of the swarm's end guard, is `clock_ambiguous`. Neighbouring pairs jumping more than 100 ms is `clock_step`. A missing bracket is `clock_mapping_missing`. None of these can reach `complete`.

**Local integration keeps these separate from a live clock.** On loopback both roles read one wall clock, so the real brackets are small and the before/after hull is honest but cannot have seen real offset between hosts. Offsets and drift are exercised by editing real recorder bytes and brackets, and by mocked files.

### Limits

- **The readiness bound ends with authentication.** It bounds how long all N may take to authenticate, by each authentication's own timestamp; exactly on the bound is on time. The coordinator listens 500 ms past it, because a shard surfaces an authentication on its next poll, then gives up. Warmup, lead, hold, guard and drain all come after it and may run past it, watched for lost bots and shards the whole time. The accepted default of `max(60 s, ramp + 30 s)` is unchanged.
- **Event times are this process's clock at the event.** An enqueue, a failed send, an RTT reading, a connect, an authentication and a disconnect each read the swarm's monotonic clock when they happen. A poll's own reading picks the due grid slot and nothing else. An enqueue is `Peer::send` returning, so it is the accepted "enqueue/send" and not the moment a datagram left the socket.
- **Never on Linux, a Droplet, a public route or systemd.** `/proc` parsing has only fixture coverage, so inode joins, kernel start ticks and drop counters on a real kernel are Gate A's first job.
- **macOS has no per-socket drop counter.** Its collector reports `counter_source: unavailable_on_platform`. A proof with counters required is `inconclusive` there, so real local runs pass `require_counters=False`, say so in `socket_counters_required`, and report the total as unknown, not zero. The executor requires counters by default.
- **Limits are declared, not calibrated.** 500 ms, 100 ms, 200 ppm and 2 s come from the contract's frames and margins. A real generator may need different values, and changing them means a new schema hash. Whether SSH brackets stay inside 2 s on a real pair is unmeasured.
- **One poll gap is not one lost frame.** A shard that recovers quickly can stay above 99%; the proof still refuses a gap over 500 ms, on purpose, because it would hide RTT and acknowledgment evidence.
- **Observer effect is measured, not excluded.** Each shard records `observer_ns` and each collector `collector_ns`. Those are costs of the recorders' own work, and they do not prove the recorders changed nothing.
- **A start can be seen late only if a loop takes longer than the 1 s publication lead.** Frames in that gap are not counted, and `window_observed_late` refuses the window.
- **Disconnect reasons on the server are ENet's `data`.** A timeout reads 0. Telling a server-caused timeout from a generator's is the scorer's work, with `poll_starvation` beside it.
- **`evidence.required_artifacts` in existing conditions fixtures is still a placeholder list.** Slice 7 owns the exporter that checks it; a real manifest should list the recorder files from `measurement_schema.json`.

### Running it

```bash
cd scripts/do_session
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_measurement_window test_measurement_collector test_measurement_executor test_measurement_local test_measurement_evidence   # deterministic and offline

# Real binaries in real time. Needs builds of the exact revision under test:
(cd ../../rust && cargo build --release --locked -p omega-server -p omega-load-test)
(cd ../../rust && cargo build --release --locked -p omega-load-test --features omega-load-test/fault-injection --target-dir /tmp/omega-fault)
OMEGA_LOCAL_RELEASE_DIR=$PWD/../../rust/target/release OMEGA_FAULT_RELEASE_DIR=/tmp/omega-fault/release python3 -m unittest test_measurement_integration
OMEGA_LOCAL_RELEASE_DIR=$PWD/../../rust/target/release OMEGA_MEASURE_LONG=1 python3 -m unittest test_measurement_integration.ContractWindows   # about 6 minutes
OMEGA_LOCAL_RELEASE_DIR=$PWD/../../rust/target/release python3 -m unittest test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path   # 60 s through the whole controller

python3 measurement_local.py --release ../../rust/target/release --target 8 --hold-s 6     # one run, by hand
```

**To run the real battery with the external network refused,** prefix any of those with `sandbox-exec -f measurement_offline.sb`. It denies every non-loopback send and the system resolver, keeps loopback, and lets the setuid `/bin/ps` run outside the sandbox: a sandboxed process may not exec a setuid binary, and without `ps` the macOS collector reports every process as gone. Under a profile without that allowance the real proofs are correctly `inconclusive`, with `process_lost_in_window`. That is the environment, and the proof should not be weakened for it. A profile written `(deny network*)` then `(allow network* (local ip "localhost:*") ...)` does not refuse external sends, because an unbound socket matches the local filter; check any other profile before relying on it.

`measurement_local` always tries every role's stop and the relay, whatever failed before or among them, and a setup failure after the relay exists is covered too. A cleanup failure on a clean run raises `CleanupFailed` naming every failure; after an execution failure that failure stays the one raised, carrying `cleanup_failures`. A process whose stop failed is still ended by its own supervisor bound.

Retained results: [`offline-faults/slice5/`](../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice5/README.md). These are local integration results, not live-host validation or capacity findings.

## Strict scoring and search outcomes (slice 6)

Turns one run's common-window evidence into separate validity and gate decisions, and a session's runs into one bounded claim. It reads retained files and nothing live. It has scored only mocked recorder files and short loopback runs of the real binaries. Retained evidence: [`offline-faults/slice6`](../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice6/README.md).

| File | Owns |
| --- | --- |
| `capacity_scorer.py` | The production scorer and its pinned policy. Pure over verified files, the sealed execution record and the window proof. The executor's default scorer. |
| `capacity_report.py` | Renders a run's `score-report.md` and a session's search report, adding no judgement, and audits what it renders against the retained files. `capacity_report.py --session-dir D --out DIR` regenerates the same bytes offline. |
| `search.py` | `observations` and `capacity_claim`: the facts that outlive a search's status, and the one sentence each ending may say. |
| `scoring_fixtures.py`, `scoring_evidence.py` | Mocked trees with one thing changed, the tables of generator and ramp evidence each must refuse, and `ScoredSim`, which runs the real executor, prover and scorer over a fake guest that exports those trees. |

### What each number really is

Traced to the producer, not the field name. See the docstring of `capacity_scorer.py` for each.

| Value | What it is |
| --- | --- |
| Tick work | `work_ns` in `ticks.csv`: nanoseconds across `world.tick`, its outbox flush and `host.flush`. ENet service between Ticks is not in it. Its `mono_ns` is the Tick's start, on the server's own origin. |
| RTT | `peer.round_trip_time()`: ENet's smoothed mean in whole ms, read about once a second per bot and stamped when read. It starts at 500 ms. It is not a raw ping. |
| ENet loss | `peer.packet_loss()`: a smoothed (7/8 old, 1/8 new) estimate of **reliable commands retransmitted per command sent**, on scale 65536, moved at most once per 10 s epoch. It is not a measured fraction of datagrams dropped, and every report labels it an estimate. |
| Disconnect reason | On the bot, the data of a server's disconnect command, or 0 when ENet gave up. A bot learns a non-zero reason only from the server. `USER_QUIT` is also 0, so a server row with reason 0 may be a bot leaving or a server-side timeout. A real blocked path records 0 on both sides (`test_capacity_real`). |
| Disconnect time | `at_ns` is when the bot's poll saw it. The server's row has its own time on its own clock, which is moved across through the clock intervals. Both are kept, with the lag bounds and which came first. |
| Bot `errors` | `Bot::fail` raises it once, so a disconnect the bot did not ask for counts one error. That error **is** the disconnect, and the prover's generator-labelled `bot_errors` cannot tell the difference, so the scorer re-derives it per bot. |

### Gates and validity

Every comparison is on exact integers or fractions. Floats appear only as labelled approximations of a retained `n/d`.

| Gate | Passes when | Exact boundary |
| --- | --- | --- |
| N/N continuity | The proof shows N in every Tick across the interval, with no unexpected disconnect | |
| Zero bot errors | Every frozen counter is a real 0, the disconnect's own error excepted and counted | A missing counter is no reading |
| Tick budget | Fewer than 1% of Ticks have `work_ns > 33_300_000` | A Tick of exactly 33.3 ms is not above it; exactly 1% fails |
| Game socket | The identified socket's counter did not move between reads bracketing the widest interval | |
| RTT p95 | The nearest-rank p95 of every in-window sample of every bot, in one pool, is below 150 ms: value at 1-based rank `ceil(95 n / 100)` | Exactly 150 fails; no interpolation; never an average of per-bot p95s |
| ENet loss | Every one-second bin's mean over the bots owed there is below 2/100 | Exactly 2/100 fails; a window average cannot hide one bad second |

**Bins.** One per second from the window start. A bot counts once per bin: the mean of its readings there, or its nearest in-window reading within 2 s, counted as `borrowed`. The estimator moves at most every 10 s and readings drift later with each poll, so one bin can honestly lack a reading, and a bin must not be counted as lower for it. A longer gap leaves that bin `seconds_without_coverage` and the gate unknown. A failure in a bin that can be evaluated still stands.

**Boundaries.** The clock mapping gives a narrow and a wide interval on the server's clock. A verdict must hold across all of it. The worst possible Tick ratio is the wide interval's slow Ticks over the narrow interval's Ticks, and the least is the narrow's slow Ticks over the wide's Ticks. Pass needs the first under 1%, failure needs the second at 1% or more, and anything between is unknown. A socket drop proves a failure only when both counter reads around it fall inside the narrow interval. A drop that might be just outside proves neither. A stepped wall clock makes both unknown, because the mapping is no longer conservative. RTT and loss are on the swarm's own clock, so they are untouched.

**Offered load** is its own axis: `valid`, `invalid` or `not_proven`. Each bot needs `sent x 100 >= scheduled x 99`, so exactly 99% is valid. A disconnected bot is held to the part it was connected for, less the one interrupted slot. If it misses that floor only because it saw the disconnect late, the floor is recomputed up to the latest time the server's event could have happened, and `input_missing_only_after_the_server_event` records that this happened. If the clocks cannot place the server's event, nothing is excused. Generator socket drops are read per bot socket, never from a host counter. A missing counter, a missing frozen row, too few ENet samples or a decode failure (the server or the bot could have caused it) leave it `not_proven`.

**Generator evidence is checked by whose it is, not by category.** The prover names every reason it draws from the swarm's own files (`facts.swarm_problems`). Poll liveness, freeze and drain times, join times, publication, a cut coordinator or shard: each is labelled `evidence`, and each leaves offered load `not_proven`, beside a failed gate or a crash just the same. None of it can be the server's doing. A server's missing data can be, so a demonstrated crash that cut off the server's own recorders still stands on a generator whose evidence is independently whole. No failure is required to have a whole window behind it. A wall clock step on the bot host also leaves it `not_proven`, because its counter reads can no longer be placed.

### Classification

Decided in this order. Every gate is still computed, so a refused run shows what it measured.

1. **Refused evidence → inconclusive.** No retained proof of the frozen schema, a proof made without the manifest's schema, `require_counters=False`, a hold that is not 60 or 300 s, a proof of another trial, an unverified export, or integrity reasons (foreign schema, fault build, overwritten recorder, reused identity, counter reset, and so on). A failure on foreign bytes is no failure.
2. **Host rebooted, or an execution infrastructure problem → infrastructure failure.**
3. **Independent generator failure.** Alone it is **invalid offered load**. Beside any server failure or unexplained loss it is **inconclusive**, because nothing separates them, and both stay visible. Generator trouble never produces a capacity failure.
4. **Not a capacity signal → inconclusive.** A game exit with no cause on record, a `SERVER_SHUTDOWN` reason, a refused session.
5. **Offered load not proven → inconclusive.** A server failure cannot stand on it.
6. **Demonstrated server failure → capacity failure.** A panic or crash signal, a kick, a Tick or game-socket gate proven failed, a failed RTT or loss gate, or a transport timeout beside proven server distress.
7. **A transport timeout alone → inconclusive.** A server, a path and a stalled bot can each cause one, and nothing here says which.
8. **Anything unknown, or a proof that is not `complete` → inconclusive.** Otherwise **valid pass**.

**RTT and loss are measured on the path from the generator.** A failed one with a valid generator is a capacity failure, as the accepted gates say, but it does not isolate the server from the network. Reports show which gate failed.

**A SIGKILL proves nothing about memory, short of the kernel's own count for the game's own cgroup.** `/proc/vmstat`'s `oom_kill` is host-wide, so an increment says neither who was killed nor when, and it stays a diagnostic (`host_oom_kill_delta`). A count for the whole unit names nobody either: `__oom_kill_process` raises `MEMCG_OOM_KILL` and only then sends SIGKILL, so the unit can have counted the sampler while the sampler is still alive and listed at every read, and no second membership sample or later signal can undo that. So the supervisor gives the game a leaf cgroup that nothing else is ever in (`guest_runner.OomWatch`, `game/process-oom.json`, schema `/2`). The kernel raises its count on the memory cgroup of the victim's mm owner, and `memory.events.local` of a leaf holding one process therefore names that process. The sequence runs inside the unit's own `Delegate=memory` subtree, as the uid the unit already runs as: before any child exists the supervisor makes `supervision/` and moves itself there, writes `+memory` to the now process-free unit's `cgroup.subtree_control` (the kernel's no-internal-process rule requires that order), and makes `workload/`. The game enters `workload/` in the forked child before `exec`; the sampler stays with the supervisor. `process_oom` calls a SIGKILL `out_of_memory` only when all of this holds: the file is the sealed run's, of the plan's own systemd unit, naming that unit's two leaves; game, sampler and supervisor match the sealed pid, kernel start and boot, and the invocation matches; `/proc` showed the game in `workload/` and the others in `supervision/`; `workload/` started empty at a count of zero, held only the game while it lived, and is empty after the reap; the count rose by exactly one by the read right after the reap, and stayed there; with no group kill and no counter that restarted. Anything less stays `killed_with_no_cause_on_record`, inconclusive, and `attribution.game_exit.process_oom` says why, with `unit_oom_kill_at_reap` beside it as a diagnostic of a kill elsewhere in the unit. What happened to the sampler no longer matters to this, so a sampler the kernel took too leaves the game's kill named. A gate proven failed before it stays on record beside it, and decides nothing, because the two cannot be separated. A named kill still advances only over a generator proven valid. If the unit gave no delegation, or any step is refused, the run goes on, the file says unavailable or names where the game really was, and the SIGKILL stays unexplained. `OOMPolicy=continue` keeps systemd from stopping the supervisor when one process is killed. No new privilege or `sudo` command is involved: `Delegate=` makes systemd hand this subtree to the unit's `User=`, only that subtree is written to, and systemd trims it recursively when the unit ends.

**A ramp that never held N** has no window, so it can never pass, and the prover labels it a generator reason. `prove_ramp` then holds it to the same evidence, on the same reason codes:

- **The supervised processes.** `swarm.json`, `process.json` and the rows of both collectors must match the pid, kernel start and boot the supervisors sealed, and nothing an earlier run on that host used. A sealed hash says nothing here: it shows which bytes arrived, not whose they are.
- **Every socket opened.** A shard holds its sockets until it exits, so each one must be in every collector read made between its opening and the first read certainly after the abort, with one inode, on the endpoint its join row claims. A socket no bot claims is refused. Its counter counts from creation, so a drop before the first read still counts, and a read that does show a drop is on record whatever else is missing.
- **Every bot started.** Each slot well before the coordinator's abort needs a join row with a port, and each started bot needs error counters. Ownership is round-robin. A slot after the abort was never owed.
- **The end of the ramp.** A counter proves zero for what came before its read and nothing after it. So a read must begin certainly after the abort, on the conservative placement of both clocks, and see every opened socket (`reads_certainly_after_abort`, `first_read_after_abort_ns`). A last read before the abort, however close, one the clocks allow on either side of it, and a socket no such read saw all leave the generator `not_proven`, with no drop count: a counter that was not read is never zero. The swarm makes this possible by holding every socket open and read for 2.5 s past its drain (`COUNTER_HOLD_NS`, `rust/load_test/src/measured.rs`), except when it was stopped from outside. Full 60 s of hold is not asked for. The two-second borrow for ENet loss samples is a different estimate of a different metric, and it excuses nothing here.

Then it needs something on the server's record: a crash, a kick, or at least 1% of Ticks above 33.3 ms among those with an authenticated player, read on the server's own clock. The server sends the same reason to a join it refuses, so a kick only counts for a bot both sides recorded as authenticated. A timeout alone is inconclusive. A refused join is a limit or a ticket, and no capacity signal.

The whole-run `report.json` is carried as a labelled diagnostic and never read for a decision. CPU, memory, gaps, bandwidth and host kernel counters are diagnostics and add no gate.

### Through the executor

`RunExecutor`'s default scorer is `capacity_scorer.score`, beside the strict prover and `require_counters=True`, and `run_cli.py` takes no option that changes any of them.

- **Retained once.** `score.json` and `score-report.md` are create-only and the verdict's `evidence_ref` is `score.json`'s hash. A returning controller reads a retained score and never recomputes it, even with a host unreachable.
- **Only this run's own decision is read back.** A score must carry the expected run, trial, session, manifest, frozen controller revision and policy, the exact retained proof and execution digests, and the sealed identities, and its own gates and offered load must support its outcome. A classification must name this run, and a PASS or FAIL must rest on a bound score by the hash it recorded when written. Anything else is refused and left exactly as found, nothing is recomputed, the refused file's hash goes on record, and the run is `INCONCLUSIVE`. A refused classification gets a `classification-reconciled-<token>-<n>.json` beside it, and the registry outcome names that file. A terminal fact from the execution record still takes precedence, so a refusal cannot mask one. No expected hash is ever replaced by the hash of whatever is there now.
- **Whole or absent.** `score.json`, `classification.json`, `window-proof.json` and each execution record reach the disk under a `.writing-*` name and take their final name only when flushed and whole, without overwriting. An interrupted write leaves that file in place, and nothing reads or promotes it.
- **Only the frozen revision makes a new decision.** `_score` enforces this for every path, so `collect` and a checkout that changes during a batch are both covered. A controller that cannot show it is the frozen revision, including one whose check fails or was never supplied, still stops, seals, exports and requests cleanup, and it keeps every terminal fact. It writes no new proof or score: a naturally finished run stays `INCOMPLETE`. It can only read back a retained score or classification that holds up.
- **A scorer that fails is inconclusive,** like a prover that fails, and the outcome still commits. A credential value is refused before retention.
- **`apply_scorer` still holds the answer** against the execution facts and the proof: no PASS over a failed process or an incomplete window.
- **Stop facts outrank a retained decision.** `capacity_scorer.stop_records` reads what every generation wrote down: `demonstrated_problems.infrastructure` and `demonstrated_outcome` of each execution record, and each `terminal-fact-*.json`. A return settles any uncommitted outcome from those and from what it found itself, before it reuses a retained score or classification, however intact. The verdict is the stop, its file names what it `supersedes` by hash, and the earlier files stay as they were, as history. A retained verdict that already stops stays what it is, with the fact beside it. What a host only failed to answer stays in `uncertain`, which is no such fact, so an unreachable host or a transfer that cannot run costs a healthy decision nothing.
- **A failure found after the commit stops the session.** An outcome is immutable, so the run keeps it. A return also rechecks every committed run: a fact on record, or bytes for a PASS or FAIL that are gone and come back failing their hash on a fresh transfer, are written to `terminal-fact-<token>-<n>.json` and sent to the registry as `record_batch_stop`. The same goes for corrupt bytes that recovery finds at wrap-up. Written first, so a crash before the registry hears of it leaves the next return to finish the job. Then `resume` refuses, as it refuses any terminal failure, and cleanup still goes out.
- **A stop the registry did not take is still a stop.** `record_batch_stop` can fail, be refused, or commit and lose its answer. None of that is permission. A fact stays in `stops_unheard` until the registry acknowledges it, and both `resume` and the next dispatch (`_require_no_open_stop`) ask once more with the same request id and refuse with `terminal_fact_unacknowledged` if it still has not been heard, with no `record_resume` and no process start. A lost answer is replayed by the registry rather than applied twice, and reads as what it is: the status shows the terminal failure. The file stays for the next controller, whose first look replays it before any work. Nothing here stands between a batch and its wrap-up or cleanup, which list the unheard fact in `wrap_up_errors` and go on.
- **A seal that fails its hash is corrupt bytes like any other.** A transfer that could not run, a status with no seal hash, or a claimed success with no file say nothing about the host, and stay recoverable. A seal or other file that arrived with the wrong hash is a demonstrated failure on a committed run or at wrap-up. `_corrupt_receipt` keeps the receipt (`expected_sha256`, `actual_sha256`) and the bytes themselves under `corrupt-evidence/<role>/<file>.<actual hash>`, durably, under a name no later transfer writes to, and `terminal-fact-*.json` names them, all before anything is forgotten. A working transfer later can restore the good file, and cannot unsay the fact.
- **Corrupt bytes are written down in an order a crash cannot get around.** Each step is finished, by the durable writer's own definition (bytes fsynced, name linked, directory fsynced), before the next begins: a `seal-receipt-<token>-<role>-<key>.json` before any file of that role is transferred, then `corrupt-observation-<token>-<key>.json`, with both hashes and this run's identity, then the bytes, then the outcome or `terminal-fact-*.json`, then the registry. `stop_records` reads what each crash leaves, before any recovery, admission or dispatch. An interrupted write of a stop record (a `.writing` file with no identical copy under its final name), an observation short of its bytes, and bytes under `corrupt-evidence/` that no record of this run accounts for are all `unverified`: `stop_record_unverified`, nothing said to the registry, and no claim. An observation with its bytes is a fact like a terminal fact and is replayed as one, unless a fact already names the same bytes, so one failure stays one stop. On a run with no outcome yet, it becomes the outcome. None of these disappear when a later transfer brings good bytes. An observation is held to the same safeguards as a terminal fact, and its file name and its retained name must also follow from what it says, so a file's name never makes it this session's. A record that cannot be reconciled stays refused until an operator looks at it. Cleanup goes ahead whatever is left. A transfer that could not run writes none of this.
- **An expected hash has to come from something older than the observation.** Correct names and a matching actual hash only prove which bytes it kept. The seal receipt is what a guest's own `seal` or `status` reply said this role sealed, identity-bound and written before any byte of it is judged, so a genuine observation finds it after any crash. A raw file's observation needs its path listed at that hash, and a seal's needs that hash to be the receipt's digest. Nothing recomputes or replaces an expected hash. No receipt from this or an earlier controller of this run, a receipt that cannot be held to this run, receipts that disagree, a sealed execution record that names another seal, or a retained `seal.json` that is unreadable, changed, of another role or does not list the path, each leave the observation `unverified`, never a fact, and removing the stray file restores the session. The seal is the last file a transfer brings, so its absence only counts once an execution record says it arrived. A receipt that could not be written costs this replay: the observation then refuses instead of stopping for good, and the controller that saw the mismatch still stops.
- **Names are durable before anything depends on them.** Creating a name does not persist it: that takes an fsync of the directory holding it, and a child's fsync says nothing of the child's own name ([fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)). The durable root of a session is its directory. `make_session_durable` puts the directory's name on disk at freeze and again when each controller starts, up one path on one filesystem, as far as this account can open. Below it, `make_directory_durable` creates and syncs each level from the root, on every call, because a directory that is merely there may be what a failed fsync or a dead process left. The run directory is made durable before its dispatch, and every stop record, execution record, proof, score, classification and grant is written through that same path. A sync that fails stops a dispatch as `directory_not_durable`, which says nothing about any host, and on a write it still writes the file, for a process crash to find, and reports the write as not retained. Raw files, plans and clock brackets are not written this way: losing them refuses or recovers from the guest, and decides nothing. A dispatched run whose directory is gone refuses as `run_directory_lost`, and is not quietly made again. `collect` carries on past all of this to the rest of the runs and to cleanup.
- **The reader answers whatever a file holds.** `stop_records` checks a field's type before anything is looked up with it, in terminal facts, observations and every execution record, foreign or not, and any file it still cannot judge goes under `unverified`. So a list where an outcome belongs refuses as `stop_record_unverified` from `resume`, dispatch and the report, and cannot turn into `controller_failure` and an irreversible infrastructure stop. Removing the stray file restores the session. An execution record of no known shape is carried nowhere by a return, and a `demonstrated_outcome` that is not a stop, which its writer never writes, is refused rather than committed. Retained scores, proofs and classifications get the same: every nested field anyone reads back out of them is checked before it is looked up or iterated, a score's digest only says it was not changed afterwards, and what cannot be read is refused rather than raised. The refused file stays as it was, the run takes `INCONCLUSIVE` without a word of infrastructure failure, a genuine stop fact beside it still wins, and the report renders the disagreement.
- **A stop fact is believed only as this run's own.** A `terminal-fact-*.json` must name this session, manifest and run, a role of it, a stopping outcome, at least one reason and when it was found. Its fencing token must match its file name, be no older than the token the run was dispatched under and, to a controller, no newer than its own. Any receipt in it must hold two different hashes and name bytes that really have the hash it recorded, inside the run directory. An execution record carrying a stop must name the same three identities. Anything else goes under `unverified_stop_records`: `resume` and dispatch refuse with `stop_record_unverified`, nothing irreversible is said to the registry because this is not a demonstrated failure of this session, and the report withholds its claim as `evidence_disagreement`. A real fact beside a foreign one is still final. A report has no current token, so a fact naming a token newer than any controller reaches its `hard_facts`, and its claim is withheld all the same.
- **Terminal facts survive.** Every existing rule stands: nothing dispatched twice, no successor from an incomplete trial, no resume past a terminal failure, cleanup requested whatever happens. Failing to write a report never delays cleanup.

### What a search may say

`search.capacity_claim` is the only sentence. `capacity_report` renders it above every retained trial.

| Ending | Claim |
| --- | --- |
| `confirmed` | Three valid five-minute passes at that target: an observed candidate on this rented pair, not provider-wide capacity |
| `confirmed_search_cap_reached` | At least 500 under this condition; search cap reached, not a discovered ceiling. `players` is null and `lower_bound` is 500 |
| `no_passing_target` | No passing target at the five-player resolution. Not proof that no smaller population could work, and not a capacity of zero. `players` and `lower_bound` are null |
| `unconfirmed_variable` | A valid confirmation failed. The bracket and every result are kept, with no replacement |
| `unconfirmed_partial` | Part of the confirmation set is incomplete, and the rest may pass. Not a confirmed capacity |
| `stopped_*`, `undecidable_incomplete_predecessor`, `partial_*` | No capacity established. The highest one-minute pass is named as an exploratory observation only |

**A report checks what it renders.** Each trial's journal outcome is followed through the classification and score it names, by the hashes recorded when they were written, to the run's own proof and execution record. If any of that disagrees or cannot be verified, the row lists it under `evidence_problems`, its score's content is not rendered as this run's, `claim` becomes `evidence_disagreement` and `establishes` is false. The journal's own outcomes stay in the rows and in `journal_claim`, labelled history. A report still renders whatever is there, and it stays deterministic over contradictory bytes. Each row also lists its `hard_facts`. A stop fact beside an outcome that does not stop is one of those disagreements, even though the outcome is immutable and intact. Where a stop fact outranked a retained decision, the row carries `superseded_decisions` by hash, its `classification` is null, its gates read as history, and `evidence.verified` is false over the whole session even though the stop in `claim` is exactly what happened. `evidence.trials_with_stop_facts` and `evidence.superseded_trials` name them.

The search graph and admission are unchanged from slice 1. `test_capacity_search.EveryLegalPath` walks all 401 leaves and checks each claim against its history. `Trial`s that were selected but never dispatched are not trials of the report.

### Running it

```bash
cd scripts/do_session
python3 -m unittest test_capacity_scorer test_capacity_search test_capacity_integrity test_stop_record_lifecycle test_scoring_evidence
OMEGA_LOCAL_RELEASE_DIR=<dir with omega-server and omega-load-test> sandbox-exec -f measurement_offline.sb python3 -m unittest test_capacity_real
python3 scoring_evidence.py synthetic --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice6
python3 capacity_report.py --session-dir loadtest-runs/digitalocean/<session_id> --out <new dir>
```

### Limits

- **No real pass exists.** macOS has no per-socket counters, so a real local run is refused at step 1. Linux `/proc` counters, independent-host clocks, public routes and generator headroom remain unverified, and the fixtures' mocked sampler rows stand in for all of them.
- **Process-attributed OOM evidence has run against no kernel.** The producer and consumer are real and their seam is tested: the real supervisor with real SIGKILLed children, over directories standing where cgroupfs would be and refusing what it refuses, then the real scorer. Every real file format, `memory.events.local` in a real global OOM, `Delegate=memory` under `systemd-run --uid` on the pinned image, the move of the supervisor and the `+memory` write, a transient unit's trim of its subtree, `OOMPolicy=continue` and the real Droplet's cgroup v2 mount are unverified, and only an operational check on a real host can say otherwise. They rest on reading the kernel's `oom_kill.c`, `memcontrol.c` and `cgroup-v2.rst` and systemd's `CGROUP_DELEGATION.md`, `systemd.resource-control` and `cg_trim`. Tests that read real cgroup files run only on a Linux host on cgroup v2. Where any of it does not hold, the file says unavailable or the proof fails, and a SIGKILL stays inconclusive and stops the batch. What the count proves is that the kernel's OOM killer chose this process during this life. It cannot exclude an independent SIGKILL landing at the same moment, and nothing records that it was the cause of the exit rather than a race with one; there is no such case in the unit, because nothing but the supervisor signals the game. Membership is sampled at each read, and the game's leaf is writable by the unit's uid, so a process of that uid deliberately migrated into it between reads would not be seen: nothing here does, and the game and the sampler spawn nothing. A kill by `systemd-oomd` or anyone else is not in this count, and stays unexplained. Only the game's kill decides anything: a swarm's or a sampler's stays what it was.
- **A retained file's digest and bindings catch wrong, stale, cut or edited files. They do not stop someone deliberately rewriting a session directory and recomputing the digest.** Nothing here claims to.
- **A report can only check policy against its own checkout.** The manifest pins the controller revision and not a policy hash, so a report regenerated from another revision with a different policy withholds its claim rather than vouch for it.
- **A real failed ramp is conclusive only if the collector actually reads inside the swarm's 2.5 s hold.** That hold is chosen, not calibrated. A collector stalled across all of it, a swarm killed before it, or any old binary with no hold leaves the generator `not_proven`, and the search stops rather than advancing. Its drops are read on real Linux counters that no test here has seen.
- **Durability stops where the disk does.** A crash between comparing a hash and finishing the first write, or a disk that refuses every file and a registry that does not answer, leaves only this controller's memory: it refuses for as long as it lives, and a later controller over good bytes has nothing to find. A `.partial` is not treated as an observation, because a cut transfer also leaves one and proves nothing. A process crash takes no names, and a power cut can take any name no fsync covered. The crash points here are simulated interruptions and injected failures of the writer's system calls in one process, and `test_durable_namespace` models a power cut by removing exactly the names no sync reached, which is what is permitted and not what any disk does. No real power cut, and no filesystem's actual behaviour after one, has been tested. A sync of the run directory that fails while an observation is written is reported as not retained, and a power cut straight after it can still take that observation, with nothing left to say a sibling should not run: two faults, and nothing was reported durable. `fsync` on macOS is not a flush to stable media: by its own manual page the drive may still lose or reorder what it was given, and only the `F_FULLFSYNC` fcntl asks it to empty its cache, which nothing here does. So a controller on a Mac has this ordering, and not this durability against a power cut.
- **Declared limits are declarations.** The 2 s borrow bound and the prover's clock limits are chosen, not calibrated.
- **Distress is coarse.** A transport timeout is attributed only beside a proven Tick or game-socket failure or a lost process. Server stalls that show up in neither stay inconclusive. A long stall outside `world.tick` counts as one Tick at most, and the accepted gate has no cadence term, so it is a diagnostic.
- **Compact findings, cost and full run reports are slice 7.** `score-report.md` covers the decision only.
