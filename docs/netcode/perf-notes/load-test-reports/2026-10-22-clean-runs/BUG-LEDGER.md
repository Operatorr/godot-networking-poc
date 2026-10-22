# Correctness fixes and rerun ledger

Status: **open; no clean-build certificate**. The [campaign plan](PLAN.md) owns
the remaining matched observations and final ladder/overload rerun. Prior
[UDP diagnosis](../2026-10-21-udp-diagnosis/BUG-LEDGER.md) and
[AoI diagnosis](../2026-10-22-aoi-diagnosis/REPORT.md) remain immutable evidence.

## Confirmed defects fixed in this candidate

| Defect | Evidence and regression | Correction | Remote validation |
| --- | --- | --- | --- |
| Delta sizing excludes its header and pinned removals can exceed the unreliable limit | `delta_budget_includes_header_and_pinned_removals` failed against real encoded packets before the fix; historical warnings exceed 1200 B | Reserve the 16-byte header; admit pinned records first; enforce <1200 B including byte rounding; use a reliable replacement Baseline if the pinned removal set cannot fit | Pending |
| Deltas emitted while their Baseline is unacknowledged; future ACKs accepted | `delta_waits_for_exact_baseline_ack_and_carries_observer_position` failed with ACK 0 before the fix; exercises actual broadcast/outbox | First Snapshot is a Baseline; pause dependent deltas/cache mutation until its exact ACK; ENet owns reliable retransmission, without repeatedly replacing a pending Baseline | Pending |
| Retired deltas can recreate entities after a newer Baseline arrives on another channel | `late_previous_channel_delta_cannot_recreate_entities_after_baseline` failed at real codec/bot application seam; Godot `replication_smoke` also failed before the receiver guard | Both receivers reject deltas referencing retired Baselines before applying entities or requesting recovery; bots separately count ignored stale packets | Pending |
| Strict received-AoI evidence incomplete when stationary observer position is omitted | Prior diagnostic recorded 29,723,783 unknown positional observations; broadcast regression requires observer position after ACK | Every delta carries the observer's authoritative position as a pinned record within the same hard packet limit; no fallback to prediction or grace | Pending; unknowns remain failures |
| Server Baseline count exceeds decoder cap (7280 vs 4096) | `maximum_baseline_roundtrips_through_real_decoder` failed with `BadValue("snapshot entity count")` before fix | Use protocol decoder cap and include observer first even under truncation | Pending; historical occurrence not established |
| Full-state recovery bypasses AoI | Existing audit reproduced >1150-unit recovery records; `aoi_audit_matches_wire_and_full_state_recovery_respects_aoi` failed before fix | Share AoI radius/hysteresis predicate with broadcast; filter identity replay to included players | Pending; prior diagnostic bots made no requests |
| Tick estimator divides ramp/drain span by fixed run duration | `tick_rate_pairs_snapshot_clocks_even_when_ramp_and_drain_extend_the_run` failed with original estimator and passed after repair | Pair each bot's first/last Snapshot Ticks with those same server monotonic timestamps; aggregate matching spans; absent clock stays unknown (0 estimate) | Pending |

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
