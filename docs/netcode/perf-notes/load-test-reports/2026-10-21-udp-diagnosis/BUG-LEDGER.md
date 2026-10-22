# Defects exposed by UDP capacity diagnosis

This is the capacity investigation's defect handoff to
[Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39),
not a resolution of that broader correctness ticket.

**Closing status:** see [the investigation conclusion](CONCLUSION.md) and the final
section below. Historical pending statements record when findings were discovered;
subsequent observations supply their validation. No report in this investigation
is a new capacity pass or a bug-free certificate.

## Controller cleanup defects found during PR review

The restored review workflow confirmed three failure paths using the actual
controller teardown statements with mocked hosts, without another remote run:

- In `udp_generator_profile`, `udp_generator_profile_fixed`, `udp_dodge150` and
  `udp_send150`, a failed bot stop left `game_stopped_utc_ns` absent. Journal
  argument construction then raised before restoration and cleanup publication.
- In `udp_baseline`, `udp_control`, `udp_bitmap` and `udp_profile`, a failed final
  socket snapshot skipped swarm and collector termination because those actions
  shared one exception handler.
- In those same four earlier controllers, a staging failure before the original
  service was stopped still caused cleanup to stop it. The ownership flag remained
  false, so restoration was skipped and no restore timer had yet been armed.

Current controller sources now attempt each release independently, stop the game
only after taking ownership, and require a successful game stop before recording
its timestamp. An unavailable journal interval is recorded explicitly and does
not block restoration. Manifest-write failures cannot prevent resource cleanup
or the separate cleanup-result write. The sibling checks include all eleven
controller families, including the already-independent bounded/buffer variants.

`test_udp_cleanup.py` covers ordinary teardown, failed socket collection, bot stop,
game stop, journal export, manifest writes and partial setup. The tests execute
the complete real cleanup bodies with mocked dependencies; they reproduced the
failures before the fixes. Historical executed copies, private archives and
reported observations remain unchanged. These are local recovery fixes, not
another capacity measurement or a retrospective validation of a failed run.

## Missing bot observations during failed joins

**Confirmed measurement defect.** The [baseline reproduction](baseline-reproduction.md)
terminated during the join ramp, leaving `bots.ndjson` empty. The recorder was
only called after joining finished. This prevents per-bot offered-load and
delivery/error analysis exactly when overload prevents the swarm from joining.

Fix revision: [`3b910cd`](https://github.com/Operatorr/godot-networking-poc/commit/3b910cd).

The integration regression `unsettled_join_records_ramp_before_phase_two` starts
the actual bot binary against a local UDP endpoint that never answers the ENet
handshake. It failed on the original code because no observations were flushed.
The fix records approximately once per second in both settling and stagger loops;
the regression now passes. Ramp rows explicitly use `phase_s: null` and do not
start or change the 60-second global warmup clock. Additional cumulative observer
timing includes serialization and flush cost, reported in the following sample.

Validation: `cargo test --workspace`, `cargo clippy --workspace --all-targets`,
and `cargo fmt --check` passed (existing Clippy warnings remain). The client
GDExtension rebuild also passed. Remote matched
observation and causal overhead comparison are pending. This is an instrumentation
change, not a performance optimization.

Earlier failed ramps remain evidence of failure and socket overflow; they cannot
establish generator validity retrospectively. Existing valid steady windows are
not invalidated by this missing ramp evidence alone.

## Oversized unreliable Snapshot warnings

The frozen reproduction's bounded log tail contains 3,907 channel-0 warnings for
1,201–1,356-byte payloads. This supports the existing oversized-Snapshot suspect
in the correctness ticket. The full-run warning count, its CPU cost, and causal
role in UDP overflow are not yet established; the current profile experiment
will help discriminate that role. No fix or capacity improvement is claimed here.

## Wire collector stopped at two million reliable commands

**Confirmed measurement defect.** Both instrumented-control readers exhausted the
per-command history guard. This truncated late wire cadence/retry evidence and
prevented final port mappings and parser totals. Existing missing values remain
null. A real-path regression reproduced the same guard failure locally.

[The collector repair](COLLECTOR-REPAIR.md) replaces growing per-command state with
a bounded per-stream sequence window and labels the changed retry semantics in a
new evidence format. It incrementally preserves mappings and parser status,
including failure status for a truncated pcap. Five Rust tests and six replay
tests pass; remote sustained coverage and collector perturbation remain pending.
The active bitmap comparison uses the old collector unchanged, so this repair
cannot contaminate that comparison.

## Diagnostic ConnectAuth mapping used the wrong wire offset

**Confirmed measurement defect.** The bounded reader completed but produced empty
bot maps. The parser and synthetic fixture both omitted the u32 `character_id`
that the real encoder writes before the name. The contract's prose layout was
also wrong. This invalidated identity-aligned wire cadence, not the retained
aggregate input/ACK/packet observations.

The actual protocol encoder now drives a failing-then-passing integration test
through the diagnostic parser. Corrected extraction reads unsigned name length
at byte 8 and name at byte 9. Tests cover zero/nonzero character IDs, bot IDs,
non-bot names and truncation; replay fixtures and contract prose are corrected.
[Details and remote limitations](COLLECTOR-REPAIR.md). No wire format or application
binary behavior changed, and earlier empty mappings cannot be reconstructed.

## Non-atomic window publication restarted the measured service

**Confirmed controller defect.** The receive-buffer controller copied `window.json`
directly into the active measurement directory. The server read an empty/partial
file and its deliberately strict parser panicked before the swarm. Systemd
restarted it, while the controller retained the old invocation/hash proof. The
report recovered workload logs and qualifies the replacement's runtime hash as
inferred; no missing proof is filled in retrospectively.

`atomic_publish.publish_file` now transfers to a sibling `.partial` and renames
within that directory only after a successful copy. Two filesystem tests reproduce
partial-reader exposure under direct copying and pass with atomic publication,
including interrupted initial transfer and paths containing spaces. Future
controllers must use the helper for every measurement schedule destination,
reverify PID/invocation/executable hash/buffers immediately before launching bots,
and treat any subsequent restart as invalidating the cell. Historical executed
controllers remain unchanged. The sustained Strategy 150 cell verified atomic
publication 52.421 seconds before the measured window, with one unchanged runtime
identity throughout and no panic/restart.

## Sustained Strategy 150 findings and journal export defect

[The sustained observation](capacity150.md) is generator-invalid: every bot offered
18.34025 Hz, with bot CPU averaging 97.71% of one logical CPU. No new capacity or
bug-free result is claimed. It also retained 637 game zero-byte sends matching
SndbufErrors, two bots failing ActionConfirm-age guards, a strict AoI failure,
7 baseline-reference misses, 15 unknown delta-entity observations and 350,000
oversized-unreliable warnings during the measured window. Their causes remain
separate from the proven offered-load failure.

The executed controller's post-run journal exporter assumed `MESSAGE` was a JSON
string; journald also returned byte arrays. Byte-aware recovery helpers and a
regression test now handle both forms. Primary bundles remain unchanged. A bounded
24 MiB raw prefix and complete compact counts over all 427,425 journal records
were retained and checksum-verified without another workload. The full raw journal
was not retained locally. Future controllers must use the byte-aware counting path
and bound retained bytes without truncating the scan used for totals.

## Profiler completion gate rejected an intentional SIGINT

**Confirmed diagnostic controller defect.** The recorder deliberately ends perf
with SIGINT. The sustained profile's controller required `rc == 0`, rejecting the
observed `rc == -2` despite `reason=nominal-window-end`, no recorder error and a
complete usable recording. The disposable sampler had returned the same code.
This stopped the workload before the sustained window and late profile.
[Early evidence and limitations](generator-profile.md) remain retained; no new
capacity claim follows. A corrected gate must accept only the expected nominal
completion while continuing to reject crashes, forced stops, recorder errors and
failed/missing dispatch results. Preflight and live control must use that same gate.

The parent extracted the existing live predicate as `profile_failure`, reproduced
the false rejection, and changed only the accepted nominal return codes to
`0` / `-SIGINT`. Tests also reject abnormal termination and retain dispatch/missing
status guards. The source in `e5f5ee0` and private executed copies preserves the
historical defect; subsequent source contains the repair. Remote validation is
pending the [corrected diagnostic attempt](GENERATOR-PROFILE-PLAN.md).

The [corrected attempt](generator-profile-fixed.md) completed both profiles and the
full workload: disposable preflight and live recording statuses all passed the
same shared gate, followed by successful independent data validation. It remained
generator-invalid at 18.213 Hz. Separate steady findings include 264 game zero-byte
sends/SndbufErrors, nine delivery-gate failures, strict AoI failure, two baseline
reference misses, four unknown delta entities and 349,506 oversized warnings.
The owner/map hot paths now justify a focused generator search optimization; no
new capacity or clean-run claim follows from profiling.

## Valid offered load exposes remaining send/AoI failures

[The dodge-search comparison](dodge150.md) restored valid offered/wire load at 150,
and all per-peer delivery gates passed. It retained 2,290 steady / 2,295 full-workload
game SndbufErrors matching nonempty adapter zero-byte sends. The pinned ENet std
adapter maps `WouldBlock` to zero; the deeper transmit/drain cause is not measured.
The strict AoI assertion still failed for 19 peers, with six baseline-reference
misses and eight unknown delta entities affecting peers 91/123, and 349,181 steady
oversized warnings. No clean-run or capacity certificate follows. The next transport
comparison leaves the assertion and its thresholds unchanged.

## Send allowance result and remaining correctness plateau

[The final send-buffer observation](send150.md) is generator-valid. Both hosts
recorded zero UDP errors throughout the workload, including zero game nonempty
zero-byte sends. Population, delivery, Tick and backlog gates all passed. This
validates the bounded intervention at Strategy 150, not the exact kernel cause or
a permanent default change. Original configuration and buffers were restored.

Strict AoI still fails: **24/150 violators**, versus 19 in the comparator. The
latest run has zero baseline-reference misses and unknown delta entities, but
there was no corresponding correctness fix; the earlier findings remain unresolved.
Oversized warnings remain **348,964 steady / 429,554 full workload**. Their cause
and the existing packet-size invariant remain in the broader correctness ticket.

The focused next task is
[Diagnose strict AoI failures in the valid-load CAX11 Strategy 150 condition](https://github.com/Operatorr/godot-networking-poc/issues/41),
which blocks the broader correctness ticket. Source inspection identifies a
measurement ambiguity, not a proven remote cause: `Bot::apply_snapshot` measures
incoming entity positions against the bot's current predicted/confirmed `self.pos`,
and the ordinary delta may omit the observer's own position. Baselines, confirms,
respawn grace and Snapshot application can therefore carry different times. The
strict assertion uses a lifetime maximum, including warmup. Existing retained
maxima cannot identify the offending packet or its authoritative AoI center.
Server visibility defects and application/transport ordering remain competing
explanations. The follow-up must preserve the threshold and capture or reproduce
the actual offending state before declaring the measurement or server fixed.

Measurement repairs completed here: ramp observations, bounded reader history,
actual-encoder ConnectAuth mapping, atomic schedule publication, byte-aware full
journal counting with bounded retention, and shared intentional-SIGINT profile
completion validation. Later cells demonstrate their use; they do not repair
missing historical evidence. The optimized Strategy search restored valid offered
load while preserving nearest-choice semantics; it does not establish correctness
of replication or AoI. Exact application input delivery, queue residence and causal
instrumentation slowdown remain unknown. Historical Strategy **100** remains the
highest validated population; no previous invalid or failed result is upgraded.


## Focused AoI follow-up — local correction, remote validation pending

[The focused diagnosis plan](../2026-10-22-aoi-diagnosis/PLAN.md) records a
**confirmed measurement defect**, fixed locally in `4c33a3e`: an incoming delta
with observer (0,0) and entity (1000,0) was measured as 1200 units against current
prediction (-200,0). The regression failed before the correction at the actual
codec/application/assertion seam, then passed. Same-Snapshot observer positions
now drive the check independently of prediction, record order and respawn grace.
Missing observer positions are explicitly unknown and block a standalone strict
pass. A per-emitted-Snapshot audit supplies separate authoritative-center evidence;
it neither changes the wire nor certifies delivery.

Workspace tests, Clippy (two existing load-test warnings), formatting and the client
extension rebuild passed. Tests also cover missing own state despite cached state,
older Baseline arrival, record order/respawn grace, true violations, actual server
packet quantization and full-state selection. **Full-state reply AoI bypass is
confirmed in a regression but unchanged**; bots do not request it, so it does not
explain this workload and remains a broader correctness concern.

Exactly one matched remote observation is delegated; results and cleanup are pending.
Historical `send150` maxima do not retain enough provenance to establish their
cause retrospectively. No historical result is upgraded, no new capacity is
validated, and this is not a bug-free certificate. The broader correctness ticket
remains open.
