# Defects exposed by UDP capacity diagnosis

This is the capacity investigation's defect handoff to
[Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39),
not a resolution of that broader correctness ticket.

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
