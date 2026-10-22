# AoI diagnosis resolution and correctness handoff

[Diagnose strict AoI failures in the valid-load CAX11 Strategy 150 condition](https://github.com/Operatorr/godot-networking-poc/issues/41)
resolves the demonstrated **mixed-time measurement defect**, not capacity or the
broader clean-run requirement. [The report](REPORT.md) records the single matched
observation and [the shared ledger](../2026-10-21-udp-diagnosis/BUG-LEDGER.md)
classifies the fix and remaining findings.

The regression failed before the correction at the real codec/application/assertion
seam; same-Snapshot validation fixes that failure without changing prediction,
wire format, authority or visibility radii. Unknown observer state cannot pass.
All retained anomalies in the remote diagnostic were independently matched to
same-Tick authoritative centers and classified as false positives. Complete
Snapshot-count reconciliation supports the separate emission audit. Full-state
replies still bypass AoI, but no such requests occurred in the workload.

The diagnostic was **generator-invalid** because two peers missed wire cadence,
despite valid offered cadence. It is not the requested valid-load capacity pass,
and the standalone strict bot assertion remains incomplete. These limitations
are handed to [Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39),
which already owns final matched clean validation. No additional workload or
capacity ladder step is authorized by this resolution; no historical result is
upgraded, and no cause is inferred for historical maxima that lack provenance.

Remaining work in that existing ticket: explain the offered-to-wire cadence
deficit, establish complete trustworthy AoI validation (preserving unknowns and
separating emission from receipt), fix/triage oversized Snapshot and replication
findings, and obtain its required valid-load clean rerun. No new decision ticket
is needed: these fall within the existing correctness question.

Validation: Rust workspace tests, Clippy (two existing warnings), formatting and
client extension rebuild passed for candidate `4c33a3e`. The delegated diagnostic
suite passed 25 checks; the parent reran the 16 AoI-specific tests and independently
verified both retained archive hashes and cleanup/preservation records. Sources
and evidence are committed; both remote hosts are restored.
