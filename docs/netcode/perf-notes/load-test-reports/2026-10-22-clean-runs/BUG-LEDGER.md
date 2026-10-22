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
