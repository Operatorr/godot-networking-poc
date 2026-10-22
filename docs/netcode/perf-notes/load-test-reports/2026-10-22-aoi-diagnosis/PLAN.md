# Strict AoI diagnosis — matched Strategy 150

Task: [Diagnose strict AoI failures in the valid-load CAX11 Strategy 150 condition](https://github.com/Operatorr/godot-networking-poc/issues/41).

## Reproduction and ranked hypotheses

The real codec → `Bot::handle_server_packet` → `apply_snapshot` → assertion
regression reproduced 1200 units where both observer and remote entity in the
Snapshot were 1000 units apart. The delta carried the observer at (0,0), while
current prediction was (-200,0). The original implementation measured against
prediction even when the delta carried a contemporaneous observer. This proves
a local measurement defect, not the cause of the historical remote failures.

1. Mixed-time observer positions: a same-Snapshot center eliminates false distance.
2. Baseline/delta cross-channel ordering and respawn: the check must be invariant
   to entity order, older Baseline arrival and wall-clock grace.
3. Actual server selection/packet defects: per-emitted-Snapshot audit distances
   against the exact authoritative selection center would still exceed 1150.
4. Full-state replies: they bypass AoI today, but this bot never requests one.

## Correction and evidence semantics

The bot measures incoming positional records against its own explicit position
in that same Snapshot, independently of prediction, cached entities, confirms,
respawn grace and record order. Prediction/application behavior is unchanged.
Missing same-Snapshot observer state counts as **unknown**; any unknown prevents
the standalone strict assertion from passing. A bot without observations cannot
pass either. Radius 1100 + tolerance 50 and 95% pass ratio are unchanged.

The legacy check remains diagnostic only. Its first 16 anomalies per bot and latest
lifetime maximum are retained, with Snapshot Tick/server_ms/baseline/channel,
application order, receive time, observer/entity coordinates, position provenance,
last confirm's 16-bit Tick, input sequence and death/grace context. These are
lifetime observations including warmup, never silently relabelled steady-window.
The inferred channel follows the protocol; packet receive order counts packets
at the actual receive seam, while Snapshot application order counts Snapshots.

Opt-in `OMEGA_AOI_AUDIT=1` together with `OMEGA_MEASURE_DIR` records `aoi.csv`:
one row per constructed Snapshot, exact authoritative observer center, Tick,
server_ms, baseline/full-request origin, record/positional counts and maximum
wire-quantized remote position distance. It runs after packet scheduling and before
outbox enqueue. The audit is limited to 2,000,000 rows and fails visibly if exhausted;
rows flush per Tick. It is **emission evidence**, not proof of delivery. The remote
analysis must match retained anomalies to unique (observer, Tick, server_ms) rows,
reject missing/ambiguous matches, reconcile audit coverage with emitted Snapshot
counts, and score authoritative emission separately from the bot's incomplete
standalone check. Missing rows/state are unknown, never a pass. Window membership
comes from the exact Tick timestamps in `ticks.csv`, not bot receive time alone.

Regression coverage: false mixed-time delta, order permutations, true violations
during respawn grace, older Baseline after delta, missing observer despite cached
state, actual server selection/codec quantization, and the full-state bypass.
No production wire, visibility, gameplay, scheduler or buffer-default change.

## Exactly one authorized remote observation

Use the existing isolated CAX11 pair, sequentially in its own subagent. Build the
committed candidate game and bots in a new checkout, preserving every old artifact.
Use the prior send150 config unchanged (SHA-256
`0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`): game receive/send
requests 2,097,152 bytes each, effective 4,194,304 each; native bot buffers.
Keep collector `994cce8`, repaired atomic publication/journal/cleanup helpers,
Strategy 150, seed 30, difficulty 1, original Class mix/AoI/LOD/budgets,
30 Hz offered input, 100 ms stagger, 60-second warmup + 300-second measurement.
Enable the server AoI audit. The game/bot diagnostic build change and collection
overhead are explicit condition changes; do not claim a pure performance comparison.

Reuse all predeclared [capacity/delivery gates](../2026-10-21-udp-diagnosis/CAPACITY-150-PLAN.md).
Record hashes/source/compiler/config/collector identity, all assertions and per-peer
cadence, full and steady errors, Tick/backlog/delivery, and nulls for exact application
input delivery/queue residence. Do not suppress oversized warnings. No additional
workload, retune, CCX13, capacity ladder or historical-result upgrade. Verify cleanup
independently after the run, including original binaries/config/network/maintenance,
zero players, no owned processes, preserved evidence and remote/local archive hashes.

The parent handles the shared defect ledger, resolution and correctness-ticket
handoff only after inspecting evidence. The broader correctness ticket stays open.
