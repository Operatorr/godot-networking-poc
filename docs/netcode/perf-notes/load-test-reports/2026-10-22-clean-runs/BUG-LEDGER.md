# Correctness fixes and rerun ledger

Status: **open; no clean-build certificate**. The [campaign plan](PLAN.md) owns
the remaining matched observations and final ladder/overload rerun. Prior
[UDP diagnosis](../2026-10-21-udp-diagnosis/BUG-LEDGER.md) and
[AoI diagnosis](../2026-10-22-aoi-diagnosis/REPORT.md) remain immutable evidence.

## Confirmed defects fixed in this candidate

| Defect | Evidence and regression | Correction | Remote validation |
| --- | --- | --- | --- |
| Delta sizing excludes its header and pinned removals can exceed the unreliable limit | `delta_budget_includes_header_and_pinned_removals` failed against real encoded packets before the fix; historical warnings exceed 1200 B | Reserve the 16-byte header; admit pinned records first; enforce <1200 B including byte rounding; use a reliable replacement Baseline if the pinned removal set cannot fit | R1 workload has zero findings; see limits below |
| Deltas emitted while their Baseline is unacknowledged; future ACKs accepted | `delta_waits_for_exact_baseline_ack_and_carries_observer_position` failed with ACK 0 before the fix; exercises actual broadcast/outbox | First Snapshot is a Baseline; pause dependent deltas/cache mutation until its exact ACK; ENet owns reliable retransmission, without repeatedly replacing a pending Baseline | R1 workload has zero findings; see limits below |
| Retired deltas can recreate entities after a newer Baseline arrives on another channel | `late_previous_channel_delta_cannot_recreate_entities_after_baseline` failed at real codec/bot application seam; Godot `replication_smoke` also failed before the receiver guard | Both receivers reject deltas referencing retired Baselines before applying entities or requesting recovery; bots separately count ignored stale packets | R1 workload has zero findings; see limits below |
| Strict received-AoI evidence incomplete when stationary observer position is omitted | Prior diagnostic recorded 29,723,783 unknown positional observations; broadcast regression requires observer position after ACK | Every delta carries the observer's authoritative position as a pinned record within the same hard packet limit; no fallback to prediction or grace | R1: 202,963,596 matched positions, zero unknowns/violations |
| Server Baseline count exceeds decoder cap (7280 vs 4096) | `maximum_baseline_roundtrips_through_real_decoder` failed with `BadValue("snapshot entity count")` before fix | Use protocol decoder cap and include observer first even under truncation | R1: zero decoder errors; high-count edge remains local-only |
| Full-state recovery bypasses AoI | Existing audit reproduced >1150-unit recovery records; `aoi_audit_matches_wire_and_full_state_recovery_respects_aoi` failed before fix | Share AoI radius/hysteresis predicate with broadcast; filter identity replay to included players | Recovery edge remains local-only; R1 bots made no requests |
| Tick estimator divides ramp/drain span by fixed run duration | `tick_rate_pairs_snapshot_clocks_even_when_ramp_and_drain_extend_the_run` failed with original estimator and passed after repair | Pair each bot's first/last Snapshot Ticks with those same server monotonic timestamps; aggregate matching spans; absent clock stays unknown (0 estimate) | R1 workload has zero findings; see limits below |

Before the first remote workload, the parent caught and corrected an introduced
coverage gap: retired packets were rejected before received-AoI observation.
`retired_snapshot_is_still_checked_as_received_aoi_evidence` failed first, then
passed when same-Snapshot validation moved ahead of the application-order guard.
A retired packet can now fail AoI without mutating the entity model. This is part
of the pinned campaign candidate, not a retrospective remote measurement.

Local checks: workspace tests pass; Clippy passes with the two pre-existing bot
match warnings; formatting and client extension rebuild pass. Godot replication
regression and real ENet smoke pass after editor import. A 20-bot, 15-second local
Strategy probe had 30.0 Hz, zero decode/send/panic errors and complete passing AoI;
its generic report exits 1 because the known, out-of-scope 5 KB/s product target
is exceeded (10.25 KB/s). This is not a remote capacity observation. Exact candidate revision is recorded in
the run manifest/build proof, never inferred from a branch name. Tests model
delayed application ACK and cross-channel reordering; they do not claim to
reconstruct which historical datagram triggered each reference/unknown finding.

## Classified naming drift: bandwidth units

`bandwidth_budget_bps` is deliberately interpreted as **bytes/s** throughout the
existing client/server contract: Godot's `DEFAULT_CLIENT_BUDGET` comment explicitly
says bytes/sec and both clients advertise the same wire value. The protocol/config
field names are misleading; interpreting them as bits/s would change negotiated
behavior by a factor of eight and invalidate compatibility. Preserve wire names
and behavior, document bytes/s in the protocol type and current contract. The
allowance budgets Snapshot scheduling, not total connection traffic: Baselines,
Game events and mandatory pinned records are exempt from the soft allowance.
No capacity improvement is attributed to a units conversion.

## Historical-result validity

- Raw observations, original failures, binary hashes and compact archives still
  describe their recorded builds/conditions; nothing is erased or relabelled.
- Oversized-packet behavior and unguarded Baseline transitions affect old game
  builds. Their ladder results cannot certify the fixed build or support a
  bug-free capacity claim; the passing cells must be rerun.
- Mixed-time AoI outputs are not standalone visibility proof. The focused emission
  audit validated emission only, and its matched run failed wire cadence. Neither
  becomes a received-AoI pass retrospectively.
- Historical Baseline misses/unknown entities remain real observations; these
  regressions establish causal failure mechanisms, not exact retrospective packet
  attribution. New cells must retain both full-workload and steady counts.
- The historical 32.9 Hz estimate is invalid as a true Tick-rate measurement.
  Independent retained Tick timestamps/counters can still be scored separately.
- Strategy 100 remains the historically recorded highest validated population,
  **not** a clean-build certificate. The article's final cited ladder/capacity
  numbers await this campaign. Original overload failures may be discussed only
  as affected-build failure evidence with the defect qualification attached.

## Carried findings awaiting evidence

Offered-to-wire cadence deficit in the previous AoI run; input delivery and queue
residence; baseline-reference/unknown-entity observations under matched load;
all UDP/application errors, strict AoI, packet sizes, population, Tick, delivery
and backlog gates. A passing local regression or one zero-error remote cell does
not close the final full-rerun gate.


## Matched Strategy 150 round 1

[The complete run report](clean-strategy150-r1-20261022.md) and its immutable
machine summary retain one workload at candidate `487b6d9`, with matching hashes
on both hosts. All measured workload, generator, per-peer delivery, population,
Tick, backlog, transport and received-AoI gates pass. Every full/steady correctness
counter is zero. This validates the exercised workload paths, not unprovoked
high-count, stale-channel or manual-recovery edge cases. It is **valid-failure**:
the autonomous recovery shell returned 1, despite later independent proof that
original state was restored. The parent independently reruns cleanup verification.
The two prior private derived-scratch files lack pre-replay hashes; raw archives,
executables, source controllers and committed historical reports are preserved.
No final clean-run certificate or historical capacity upgrade follows.

### Recovery readiness/checkpoint defect

The actual recovery shell failed regressions for a `Type=simple` service whose
PID appears after `start` returns and whose pre-exec image becomes the pinned
binary shortly afterward. The shell assumed immediate executable readiness and
recorded no failure checkpoint. The correction waits for two pinned observations
under a finite attempt bound, rejects PID changes or automatic restarts, preserves
all prior hash/environment/evidence guards and prints bounded checkpoint/result
lines. Genuine start, identity, environment, preservation and reload failures
still fail. This establishes a reproducible readiness defect, **not** which check
failed in the historical run; that immediate historical cause remains unknown.
[systemd's service contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
explicitly permits `Type=simple` to return before execve. Remote validation is
pending the next individually delegated matched run.

### Legacy criterion precision and budget interpretation

R1's generic report fails the unchanged 5 KB/s product target at 39.56 KB/s.
This target is outside the map's optimization scope and is distinct from the
passing matrix validity/capacity gates. No bandwidth pass is claimed.
The estimated Tick criterion also fails while displaying rounded 30.0 Hz; R1 did
not retain its unrounded comparison operand, so its exact value cannot be recovered.
An end-to-end criterion regression reproduces a failure at 29.99991 that previously
displayed 30.0. The report now displays the float's round-trip value, retains raw
estimate, Tick/clock spans and 1 ms clock resolution in JSON, and says `>= 30` to
match its existing predicate. **No threshold changes.** Finite Snapshot timestamp
precision may straddle this exact threshold; independent 300-second Tick counts
remain the matrix's separately scored 29.7 Hz gate, not a replacement legacy pass.

R1's maximum offered-to-wire deficit is 0.206093 Hz for bot 52, with both captures
agreeing and all wire rates above 29.7 Hz. These are different observation windows,
not exact loss or application-delivery counts. Cause and exact application input
delivery remain unknown; no network-code defect is inferred without reproduction.


### Repeat-verification evidence overwrite

The parent's independent cleanup audit passes on both hosts; compact checks and
private-output hashes are in [parent verification](parent-r1-cleanup-verification.json).
Running the original `verify` again overwrote its fixed local output names. The
original published summary was recovered from committed values, with byte-identical
SHA-256 `7986ca62638ff061efb051161337dde819eb8ef3d01d5c2ee839b24a126ba777`.
The previous unpinned local raw audit details cannot be reconstructed; the new raw
details are retained separately. Primary workload archives and committed reports
remain unchanged. The controller now refuses existing verification outputs before
any host call and supports fresh `--verification-label` values for later audits.
An actual-verifier regression exercises this preservation guard; restoration and
all other audit gates remain required.


## Matched Strategy 150 round 2 — clean cell

[Round 2](clean-strategy150-r2-20261022.md) is **clean-cell-pass** on `fea24dd`:
all 36 matrix gates, including automatic recovery, pass. Full/steady correctness
and UDP counters are zero; 203,603,817 received positions have no unknowns or
violations. Recovery reaches `step=restored`, without manual intervention; two
independent 68-command restoration/preservation audits pass. The parent separately
checked all 36 reported gate values and both local archive hashes against the
published summary. No historical analyzer or evidence file was rewritten.
The immutable candidate game hash matches round 1; its bot hash changes only for
the explicit precision/raw-clock reporting correction. Local helper tests total
31 clean-run + 42 relevant existing checks, all passing.

The legacy failures remain: 39.66 KB/s and estimated 29.99998120034632 Hz against
unchanged >=30. Arithmetic is 1,659,604 * 1000 / 55,320,168, with 1 ms timestamps.
For 150 paired spans, endpoint quantization alone allows approximately
29.99989985596..30.00006254517 Hz; this interval includes 30 but does not establish
the exact underlying rate or relabel the failed estimated criterion. Independent
9,000 Ticks / 300 s passes the separately declared matrix gate.

The [campaign ledger](campaign-ledger.json) tracks the remaining sequential ladder
and overload cells. All use the now-stabilized 2 MiB requested game socket setting,
with unchanged input/stagger/warmup/window, native network, AoI and thresholds.
This is explicitly a new fixed-build condition versus the historical native ladder's
smaller socket setting. Source/executable identities remain fixed across report-only
commits; proven binary reuse avoids unnecessary rebuilds. The first remaining
ladder workload is Idle 100; full campaign and ticket resolution remain pending.


## Passing ladder: Idle 100

[Idle 100](clean-idle100-r1-20261022.md) passes all 36 matrix gates on the same
`fea24dd` source and executable pair. Full/steady correctness and UDP counters
are zero; all 20,079,446 received-AoI records are matched, without unknown,
empty-observation or violating peers. All 1,095,167 accepted Snapshots reconcile
through drain. Both labelled 68-command audits pass, and restoration reaches
`step=restored`. The parent separately verified the 36 gate values, cleanup proof
and both local workload archive hashes. No host workload or historical analyzer
was repeated by that parent check.

The legacy bandwidth target still fails at 6.56 KB/s; raw estimated Tick rate
30.00001887944889 Hz passes unchanged >=30. Authoritative measurement records
9,000 Ticks / 300 s. The new helper tests distinguish empty Remote entity evidence
from unknown positions, while both continue to fail closed. Idle's zero action
inputs still require normal ActionConfirm delivery; all peers pass it. No code
or threshold change alters the fixed workload source or historical observations.
The parent reruns the applicable helper tests. Idle 150 is the next single
sequential workload; the campaign remains incomplete.


## Idle 150 round 1 — generator validity blocks the ladder

[Idle 150](clean-idle150-r1-20261022.md) is **generator-invalid**: 35/36 matrix
gates pass; only per-peer mapped wire cadence fails, for 122/150 peers on both
captures. Wire is 28.62–29.86 Hz versus offered 29.98235–29.99902 Hz. Full/steady
correctness, UDP and AoI counters remain zero, all received positions are matched,
and both restoration/preservation audits pass. The parent independently verified
the single failed gate and both workload archive hashes. No capacity pass or
clean-cell certificate is issued. The remaining ladder is held for diagnosis.

The pinned ENet code documents adaptive shedding of unreliable packets after
queue admission. A deterministic local lossless-link test using the actual 0.4.0
engine reproduces 10,700 accepted queue submissions but only 10,699 socket sends;
all socket sends arrive. A stable-delay control sends all 10,700. Its observed
throttle minimum is 28 (scale 32) during the varying-delay condition. This proves
a possible transport mechanism and that queue admission is not a wire guarantee;
it does **not** reproduce the remote deficit's magnitude or attribute the
historical run. Throttle settings remain unchanged.

Ranked, falsifiable diagnostic hypotheses: (1) native adaptive throttle sheds
queued inputs before Socket::send; submission-to-socket differences should follow
throttle state, with no native send failures. (2) queue-flush delays retain inputs;
service gaps and pending age should explain differences that later drain.
(3) collector counting misses inputs; socket input-command counts would exceed
both capture counts after accounting for timestamp boundaries. Existing evidence
cannot distinguish these paths. A bounded matched diagnostic will compare queue
admission, actual socket sends and both captures without weakening the rate gate,
changing packet reliability or disabling congestion behavior. Exact application
input delivery remains unknown.


## Native diagnostic preflight and storage recovery

The [first native diagnostic](clean-idle150-audit-r1-20261022.md) launched zero workloads: an early SSH timeout and insufficient preservation-copy headroom stopped it. Both independent idle/preservation audits passed. All remote causal counts remain unknown; its opt-in real-ENet observer tests pass locally. This does not classify the historical wire deficit.

The parent subsequently recovered 360,927,232 bytes of regenerable APT caches, with the installed-package database and all inventoried executable hashes unchanged; see [storage recovery proof](storage-recovery-20261023.md). A separate child will own one fresh-namespace diagnostic using the same proven instrumented binaries, an economical new Rust source checkout and a full new resource/ownership preflight. The original reservation, evidence and blocked classification remain intact. The ladder is still held.


## Native diagnostic round 2 and local measurement corrections

[R2](clean-idle150-audit-r2-20261023.md) is **aborted-generator-invalid**, 34/36 matrix gates passing; every peer fails offered and wire cadence. The parent independently verifies all 36 gate values and both archive hashes. Both hosts restored and the two 72-command audits pass. Native prefix accounting strongly supports specified ENet shedding for 21,991 stable-throttle events; 222 transitions remain ambiguous, 150 final pending inputs lack a post-drain snapshot, and game-side capture counts are lower by 11 lifetime / 7 steady commands. These findings neither certify application delivery nor attribute the historical deficit. The held ladder remains incomplete.

Two confirmed measurement defects now have failing-before/passing-after regressions. The real CLI/ENet lifecycle test demonstrates that the native recorder ended before disconnect/reset: `a1abdf8` retains the original `end` endpoint and adds a separate `drained` observation after force-close, closing native packet lifetime and final counters. Historical missing suffixes stay unknown. The controller also treated socket disappearance during ordinary terminal teardown as an abort before the watchdog published its result. `4db3cf2` retains all in-window identity/buffer checks, still validates any observed process identity, and waits at most ten seconds after the scheduled endpoint for the terminal guard; the replay-shaped regression covers missing/incorrect identity/buffers and bounded timeout. Historical R2 classification is unchanged.

The opt-in peer numeric parser rescanned full Debug text and allocated a key for each whitelisted field. `a1abdf8` scans once, retaining strict missing/duplicate/nondecimal/range rejection. A release-mode actual-peer probe measured 7,978 ns/call before and 5,222 ns/call after on this laptop (100,000 calls each). This limited probe is not a causal estimate of total remote overhead or proof of restored cadence. It is retained as a manually invoked ignored timing test. All 240 workspace tests pass, with three intentionally ignored probes; Clippy (two existing warnings), formatting and extension checks pass. Forty applicable Python checks pass.

Disk headroom remains bounded. `4db3cf2` adds an explicit diagnostic-only `rename-v1` preservation option: while the original service is stopped, hash its measurement directory and atomically rename it into the existing backup layout; verify hashes before restart, then recreate the original destination with its prior owner/mode. No copy fallback exists across filesystems, and partial rename/config progress can be retried without overwriting evidence. Actual-shell regressions prove inode preservation, interrupted-progress recovery, conflict rejection, rename failure and original recoverability. The ordinary copy path remains tested. This resource option has not yet been exercised remotely; a fresh diagnostic must validate filesystem identity and the complete additive storage allowance first.


## Native diagnostic round 3 — cached controller freshness defect

[R3](clean-idle150-audit-r3-20261023.md) is **aborted-collector-invalid**, 14/36 fail-closed matrix gates passing. The parent independently verifies all gate flags and both archive hashes. It stopped 38.759 s before measurement: the controller acquired a 0.565 s old game status, spent 17.950 s publishing schedules, then called that cached status stale. The retained recorder continued at approximately 1 Hz, with its latest sample only 0.513 s old at the decision. This establishes a controller sequencing defect; it does not invalidate the recorder's retained prefix. The same sequencing exposed cached bot timestamps.

`32b48bd` moves the real monitor loop to an executable test seam. Freshness is checked before blocking publication; both hosts are queried again afterward before any subsequent freshness/mapping/runtime decision. Publication must still complete with the required ten-second warmup lead. A regression drives the real monitor loop with the retained 17.950 s delay: it fails before correction and passes afterward. Genuine stale game/bot samples still abort before publication, and missed publication lead time fails closed. Sixty-five applicable Python checks pass; Rust source and its prior workspace/Clippy/fmt/extension validation are unchanged.

The child also corrected offline steady journal scoring: an unobserved scheduled interval can no longer pass its zero-error gate merely because it contains no rows. The actual aborted recorder regression failed before correction and passes after requiring complete coverage. Original derived outputs remain sealed; no historical result was upgraded.

Automatic restoration and two independent 81-command audits pass, including the first remote `rename-v1` backup/inode/manifest/recovery proof. All 5,696 earlier local files remain unchanged. Native final drain, terminal natural-exit handling, steady workload correctness and cadence remain unobserved; a separately owned fresh diagnostic is still required. All 83 retained prefix no-attempt retirements match stable native throttle witnesses, while application delivery, historical cause and total causal observer overhead remain unknown. No extra remote workload was performed by the parent checks.


## Native diagnostic round 4 — resource block before launch

[R4](clean-idle150-audit-r4-20261023.md) launched zero workloads: the second additive allowance was short by 2,674,688 bytes after fresh source/binary staging. All 36 gates remain unscored; steady, final-drain and controller matched validation remain unobserved. Both independent 63-command idle/preservation audits pass and all 6,070 prior local files are unchanged. The parent separately verifies the zero-launch/null-gate summary. No new code defect or performance result is inferred.

[Second storage recovery](storage-recovery-r2-20261023.md) recovers 261,967,872 bytes of regenerated APT metadata/download caches, with installed-package database and 29 executable hashes unchanged. Cargo caches remain intact. The unchanged 8 GiB reserve and R4 evidence/margin allowances remain; a fresh independent run must pass its complete new preflight. R4 remains sealed and is never retried in place.


## Native diagnostic round 5 — closed lifecycle, failed cadence retained

[R5](clean-idle150-audit-r5-20261023.md) completes once as **generator-invalid**, 34/36 gates passing: 48/150 peers fail offered cadence and all 150 fail mapped wire cadence. The parent independently verifies all gate flags and both workload archive hashes. All observed full/steady correctness, UDP/socket and received-AoI unknown/violation counters are zero (32,579,659 matched positions). Automatic restoration and both independent 103-command audits pass; all 6,234 prior local files remain unchanged.

The final native lifecycle is now closed: 1,644,645 created/admitted/retired, zero pending after the separate `drained` row. Both lifetime captures equal all 1,619,035 native full input Socket handoffs per peer. Of 25,610 no-attempt retirements, 25,187 have independent stable-throttle witnesses; 273 changed-throttle events and 150 endpoint-to-drain retirements remain ambiguous. Stable witnesses demonstrate specified native shedding in that subset. They do not attribute every retirement, the original historical deficit or application delivery. Exact-window game capture differences remain qualified by clock/boundary uncertainty and the 1-in-64 identity sample.

The cached-publication abort does not recur: schedules publish with 38.836 s lead, both statuses are reacquired, and natural termination with the required watchdog result is accepted. The missing-guard grace interval was not exercised remotely; its bounded regression remains the evidence for that edge. End/drained separation is validated remotely, without moving the measurement endpoint. Native observation consumes 70.153 s in measured internal sections; this is not total causal observer cost. No clean/capacity or pure performance claim follows.

The next matched Idle150 observation disables native diagnostics while retaining the exact R5 source/binary identities, original input/transport behavior and every gate. Ranked hypotheses: (1) removing observer work improves offered cadence; (2) specified native shedding still causes lower wire cadence with valid admissions and zero transport errors; (3) ordinary polling or environmental load keeps admissions deficient. A single sequential comparison cannot establish total causal overhead or retrospectively reclassify earlier runs. No throttle, packet-mode, scheduling or rate change is proposed. The ladder remains held until that ordinary condition is evaluated.


## Ordinary Idle150 round 2 — offered load passes, wire predicate remains failed

[Ordinary R2](clean-idle150-r2-20261023.md) uses the identical R5 source/executable hashes with native diagnostics absent from actual runtime, recorder rows and archives. Every offered peer passes at 29.98213–29.99546 Hz; 113/150 fail unchanged wire cadence at 28.08–29.95333 Hz on both captures. It remains **generator-invalid**, 35/36 flags passing. The parent verifies all flags and both archives. All full/steady correctness, UDP/socket and received-AoI unknown/violation counts remain zero (32,069,870 matched positions). Both independent 107-command release audits pass; 6,876 earlier local files are unchanged.

Ordinary offered cadence recovery is consistent with observer-load dependence, without establishing total causal overhead in a single entropy/timing-varying comparison. Native private counters are absent, not zero; ordinary shedding magnitude and application delivery remain unknown. The user has been asked to interpret offered-load validity versus wire delivery against the agreed matrix; [the concrete classification proposal](CLASSIFICATION-PROPOSAL.md) retains every predicate, historical result and non-pass outcome. No classification change is implemented pending an answer.

The original campaign hold was broader than the matrix's per-workload ladder stop. Movement50 is independent of the failed Idle150 control. Required independent workload cells can continue under existing strict gates without certifying Idle150, advancing a failed workload rung or claiming capacity. The ticket remains open until the full required rerun and unresolved findings are assessed.


## Movement50 — independent strict clean-cell pass

[Movement50](clean-movement50-r1-20261023.md) completes once with **36/36 original gates passing**, no failed gates. The parent independently verifies every gate and both local workload archive hashes. All full/steady correctness/transport and received-AoI unknown/violation counts are zero, including 22,152,858 matched positions. Offered cadence is 29.99648–29.99981 Hz, mapped wire 29.97–30 Hz on both captures, and Tick count is 9,000/300 s with 5.565 ms work p99. Both 111-command release audits pass; 7,368 prior local files remain unchanged. Movement100 is the next rung of this independent workload. Idle150 remains unchanged and uncertified.

The exact source/executables match ordinary Idle150 R2. Game/bot packages were reused, but the frozen controller did compile the standalone capture reader once on each host, contrary to the overly broad no-compilation task wording. Exact commands, source and output hashes are retained. This provenance deviation does not change a gate or invalidate matching capture evidence; future task briefs explicitly authorize that existing frozen-reader staging step while forbidding unnecessary game/bot rebuilds. Legacy bandwidth still fails at 10.95 KiB/s; raw estimated Tick passes at 30.000015991038843 Hz. No campaign certificate or historical capacity upgrade follows.


## Movement100 and approved classification separation

[Movement100](clean-movement100-r1-20261023.md) completes once with **36/36 original gates passing**. The parent independently verifies every flag and both archive hashes. Offered cadence is 29.999863 Hz, wire 29.99–30 Hz; all full/steady correctness and transport errors, AoI unknowns and actual violations are zero across 61,180,349 matched positions. Both 115-command release audits pass and all 7,855 prior local files remain unchanged. Movement150 is next; legacy bandwidth still fails at 13.58 KiB/s.

The user selected versioned generator-validity/wire-delivery separation. [Policy details](CLASSIFICATION-PROPOSAL.md) and `22b1a43` implement explicit `offered-load-v2`, leaving strict-v1 as the default and every original gate unchanged. A wire-only deficit remains both a clean-cell and capacity non-pass. Actual frozen Idle150 and Movement100 evidence reproduces the distinction in read-only/in-memory regressions; unknown versions fail before derived writes. Ninety-five applicable Python checks pass. No historical report, raw evidence or classification was replaced. Future cell manifests explicitly identify the version.

[Third cache recovery](storage-recovery-r3-20261023.md) archives and verifies exact crates.io cache/index bytes before removing only regenerable cached copies. Cargo source, all inventoried executables, package database and existing evidence remain unchanged. Movement150 still requires a full fresh allowance above the unchanged reserve.
