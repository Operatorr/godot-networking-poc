# Load-test correctness fixes extracted for master

This change extracts the server/client/bot correctness fixes from the load campaign. The complete experiment history is preserved at [archive/issue39-campaign-20261024](https://github.com/Operatorr/godot-networking-poc/tree/archive/issue39-campaign-20261024), commit `fcf4f62`. Campaign controllers, native transport diagnostics, storage scripts and generated reports are excluded from this change.

## Corrections

- Delta packet budgets include the header, rounding and pinned records; unreliable payloads remain below 1200 bytes. Oversized pinned sets use a reliable Baseline.
- Dependent deltas wait for the exact pending Baseline ACK. ENet handles reliable retransmission. Old channel-0 deltas cannot recreate entities after a newer Baseline.
- Received AoI checks use the observer position carried in that same Snapshot, including retired Snapshots before discard.
- Baselines obey the decoder entity-count cap; full-state recovery uses AoI selection and corresponding identity replay.
- The load-test Tick estimate pairs Snapshot Tick spans with their server-clock spans. Reports expose the raw estimate, numerator, denominator and clock resolution without changing acceptance thresholds.

## Validation and limits

The extracted branch passes `cargo test --workspace`, `cargo clippy --workspace --all-targets` (two existing collapsible-match warnings), and `cargo fmt --check`. The release client extension rebuild, Godot 4.6.3 headless import, `replication_smoke.tscn`, and `net_smoke.tscn` against a freshly built local server with `--allow-unsigned-tickets` also pass. The owned local server was stopped afterward. Regression tests exercise real encoded packet bounds, exact ACK gating, Baseline decoding, cross-channel retirement, same-Snapshot AoI and clock-paired Tick estimates.

The [archived final assessment](https://github.com/Operatorr/godot-networking-poc/blob/fcf4f62/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs/FINAL-ASSESSMENT.md) records 23 attempts, 20 launched workloads and ten clean scenario/population cells out of 12. Those runs used their recorded executable identities; this extracted branch is locally revalidated, not a newly load-tested binary. Idle150's wire deficit and Strategy200's invalid overload assessment remain unresolved. No capacity certificate or performance-improvement claim is made. High-count decoding and manual recovery edges retain local-only validation where remote workloads did not exercise them.

Related to [Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39); this extraction does not close that issue. No protocol layout, dependency, production configuration or acceptance threshold changes are included.
