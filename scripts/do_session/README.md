# do_session — DigitalOcean test-session planner, registry, watchdog, provisioning and fresh test runs (handoff slices 1–4)

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
  remote and as real processes on one machine, never over SSH or on a Droplet. It cannot produce PASS or FAIL yet, because no scorer exists.

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
| `run_plan.py` | What a trial means on one host, as pure data. `ReleaseAdapter` is slice 5's seam: it holds today's binary arguments. |
| `run_checks.py` | Pure rules over host and run facts. It sorts execution failures and holds the scorer boundary. A missing fact fails. |
| `run_executor.py` | The controller: one run, reconciliation of an unfinished run, explicit resume, collection and the cleanup request. |
| `run_cli.py` | Operator CLI: `execute`, `resume`, `collect`. It has no provider mutation and no scorer option. |
| `fake_run_guest.py`, `run_fixtures.py`, `run_fault_harness.py`, `run_fault_evidence.py`, `fixtures/local_standins/` | Offline only. |

### One run

```text
admit legal remaining paths -> publish selection -> preflight both hosts      a dirty host stops here, with the run untouched
  -> dispatch_run: durable intent, grant                                      from here the run id is spent for good
  -> launching: last fenced check -> game, wait for its new socket -> bot -> running
  -> watch, renewing the lease -> stop -> seal both hosts -> export through .partial -> execution.json -> sealed
  -> classification.json -> record_run_outcome -> planner journal mirror
```

- **The registry decides what comes next.** For a capacity session `dispatch_run` takes only the single legal next trial, replayed from its own `runs` table, with an
  estimate covering the whole trial. Nothing else can be dispatched, and the search cannot advance past a run with no outcome. Calibration and lifecycle smoke are refused
  with `no_workload_plan`; their plans belong to their own gates. An outcome that advances the search needs the run in phase `sealed`. `typed_runs=False` exists only for slice 2's
  lifecycle fixtures, and `registry_cli.py` cannot set it.
- **Fencing reaches the host.** `start`, `stop` and `seal` carry the token, checked under one lock with the launch against a fence file that only rises. A new controller raises it
  first, so a replaced controller's late start is refused, and anything started just before is in the inventory the new controller then stops. A start request also carries its
  `launch_by` and is refused on the guest if it arrives late, with one second allowed for clock error.
- **Bounds hold with no controller.** The supervisor stops the game by `launch_by + estimate − finalization − export − grace`, and the swarm one grace earlier, by its monotonic clock or the
  absolute wall time, whichever comes first: SIGTERM, then SIGKILL after the grace. The `systemd-run` unit (`RuntimeMaxSec`, `KillMode=control-group`, `Restart=no`) is the second bound, for a
  supervisor that dies. Since `launch_by + estimate ≤ C − 0.5 s`, those limits end before the deadline tick. The game's startup wait and both stops come out of `process_reset_s`, and a
  smaller value is refused. If too little of the grant is left for the whole workload, the swarm does not start and the run is INCOMPLETE. No guest command starts past `C − 0.5 s`,
  except inside an evidence recovery episode, which has its own deadline of `min(first failure + grace, C)`.
- **Identity is pid plus kernel start time,** plus the unit's `InvocationID` on systemd. A reused pid is not our process, and it is never signalled. Each new process and socket is compared
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
PASS a run whose processes failed, or call FAIL with a failed generator unless it sets `generator_failure_attributed_to_server`. Anything malformed becomes `INCONCLUSIVE`. **No scorer ships.** Slices 5 and 6
(issues #68 and #69) own the measurement schema and gates, `run_cli.py` has no option to supply one, and until then every finished trial is `INCONCLUSIVE`, which stops the batch. Fixtures script outcomes
through `run_fixtures.scripted_scorer`; those outcomes are not measurements.

The current swarm does not meet the measurement contract either: threaded runs skip per-bot observations, and there is no common window. So nothing here should be scored until slice 5 changes the adapter.

### Coming back

A crash leaves whatever the registry last committed. Returning under a new token pauses the session and marks an active run interrupted. Nothing resumes by itself.

| Died | The run | Next |
| --- | --- | --- |
| After selection, before `dispatch_run` committed | Untouched | Explicit resume dispatches that same trial |
| After `dispatch_run`, through launch and watch | Touched for good; stopped, sealed, `INCOMPLETE` | Its dependent path stops, and resume refuses with `no_eligible_untouched_work` |
| After seal, with the swarm having ended by itself | Scored from retained evidence if a scorer exists, otherwise `INCOMPLETE` | Follows that outcome |
| After `classification.json`, before the commit | The recorded verdict stands, is not scored again, and a terminal one stays terminal | Follows that outcome |
| After the commit | Outcome stands; only the local mirror is repaired | Next untouched trial is eligible |

An interruption does not hide a failure the evidence shows: a rebooted host or a sampler that died gives `INFRASTRUCTURE_FAILURE`, and a swarm that crashed by itself gives `INVALID_LOAD`.

`run_cli.py resume --operator-request REF` runs in this order, and any failure leaves the session paused with the attempt recorded in `execution/journal.ndjson`:

1. Exclusive control. A live lease needs `--takeover`, which makes the other controller stale.
2. Not in cleanup, past C or terminal, and the manifest hash unchanged.
3. This controller's checkout at the frozen `controller_sha`, with no edits under `scripts/do_session`.
4. The pair as the provider reports it: exact ids, plan, ownership, address, firewall target, rules and applied state, and nothing extra under the session tag. Host pins are inherited, never made.
5. Fence raised, then every unfinished run stopped, sealed, exported and classified. A run directory the registry never dispatched refuses the resume.
6. Admission on the legal remaining paths against the original deadline and spend, and a legal next trial.
7. Full readiness again: probe, clock, sampler, SSH enforcement and a real ENet smoke, plus the same boot id, kernel and package list as at `mark_ready`.
8. Both hosts reset, as between runs, then admission once more, because revalidation took time.
9. `record_resume`, which refuses unless every check is true and names the exact next run.

`run_cli.py collect --reason WHY` is the other exit. It stops and seals whatever is left, records run evidence as `partial` and requests cleanup. Slice 7 owns the session export, so no session can read `clean` yet. C
arrives regardless.

### Running it

```bash
cd scripts/do_session
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q                                  # about 5 minutes with the real-process suites
OMEGA_LOCAL_RELEASE_DIR=<dir with omega-server and omega-load-test> python3 -m unittest test_run_local_integration.WholeRuns.test_real_binaries_run_through_the_same_path
```

`test_guest_runner` and `test_run_local_integration` are real processes on one machine: real signals, sockets and crashes through a real registry CLI and watchdog. Retained timelines:
`docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice4/` (26 scenarios, regenerated by `run_fault_evidence.py`). They use the fake remote, so they are reproducible and claim nothing about a host.

### What only a live run can show

These are stated so Gates A and B check them instead of assuming them. Each failure direction is safe: the batch stops, or the session stays open and visible.

- **Linux and systemd.** `/proc` start ticks and socket rows ran against text fixtures only. `systemd-run`, `InvocationID`, `RuntimeMaxSec` and `KillMode` ran through shims that start the real supervisor. `sudo -n
  systemd-run --uid` from an SSH session, cgroup kill and `--collect` behaviour are unverified. Python 3.12 is unverified: everything ran on macOS with Python 3.9.
- **Real SSH.** Only `SshAccess` argument building and pin restoration are tested. Polling logs in over SSH every 10 s on the host being measured. Its cost is unmeasured, and slice 5 should decide whether to keep it during a hold.
- **`tc`.** The real output format is untested, and the local fixture's `tc` is scripted. If a stock image reports a qdisc outside the allowed list, every run stops before dispatch; Gate A must read the real list.
- **Socket identity on macOS** is development-only and has no drop counters, so `require_counters` is off in the local harness. Real drop counters have never been read.
- **Grace values and the 45 s contact tolerance** are declared, not measured. Export time and size are bounded per file only, and a hold's real log volume is unknown.
- **A process-group supervisor killed with -9 leaves its workload running,** as the local tests show, until a controller stops it by identity. On a Droplet the systemd unit is what bounds that case, and that is unverified.
- **Fence and ledger live on the guest.** A guest rebuilt or tampered with loses them, which the boot id, package and hash checks are meant to catch, not prevent. A guest is not a trusted party.
- **Readiness smoke during resume** overwrites the earlier readiness logs on the guest. Readiness evidence kept by the controller is unaffected.
