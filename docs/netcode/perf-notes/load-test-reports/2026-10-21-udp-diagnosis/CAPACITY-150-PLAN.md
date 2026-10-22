# First sustained rung after the receive-buffer diagnostic

The 200-player, effective-4-MiB diagnostic reached its population but collapsed.
The next adaptive rung is **Strategy 150** with the same candidate game and receive
request, between the historical 100-player pass and the 200-player failure. This
is one scored observation, not an automatic repeat of the closed campaign.

## Frozen workload and identities

- Game revision `f1cc5d6`, existing executable SHA-256
  `dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`.
- Existing control bot SHA-256
  `831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`.
- Collector source `994cce8`, unchanged counting and repaired mapping semantics.
- Receive request 2,097,152 game bytes; verify effective 4,194,304. Native send and
  bot buffers, original Strategy/Class/AoI/budgets/Snapshot/game settings remain.
- 30 Hz input and Tick, 100 ms stagger, seed 30, bot difficulty 1. Global warmup
  60 seconds after Phase 2, followed by the full 300-second measurement.

The new controller publishes the schedule atomically using `atomic_publish.py`,
and rechecks actual PID/invocation/runtime hash/buffers immediately before bots.
It detects restarts throughout the run and collects every experiment invocation.
No dummy schedule may be cached before the real Phase-2-derived window exists.
No game or bot rebuild is needed. Capture duration/resource changes necessary for
a full cell are explicitly recorded: ramp at most 180 s, postjoin 360 s, workload
hard bound 550 s, captures/host sampling at most 600 s, restoration 720 s. Retain
48 MiB aggregate capture guard, 64 MiB per file, 512 MiB cgroup and compact formats.
Stop bots before shutting down game/captures; preserve a short drain tail on both
hosts. Do not stop a healthy capture before the measurement end.

## Predeclared classification gates

Use the existing campaign's offered-load and sustainability rules without
relaxing them: all 150 identities and authenticated population throughout the
window; per-bot offered and mapped wire input at least 29.7 Hz; zero bot socket
errors; complete coverage and mappings; Tick rate at least 29.7 Hz from the actual
window; Tick work p99 below 33.333 ms; ending lag below 100 ms; no growing
replication backlog; zero game UDP errors and application decode/send/panic errors.
Evaluate enabled strict bot assertions and preserve every result.

The larger queue also needs an explicit delivery check. **Supplemental operational
thresholds chosen before this rung:** every bot receives increasing Snapshot and
ActionConfirm counts across the window; Snapshot-age p99 below 250 ms and
ActionConfirm-age p99 below 500 ms; no observed per-bot age of 1 second or more
inside the measured window. These are guardrails against hidden backlog, not a
new project-wide latency SLA. Report per-bot as well as aggregate tails so a small
number of stalled peers cannot disappear in an aggregate percentile. Missing
observations fail validation rather than becoming zero-age samples.

Report both full-workload and steady-window error deltas, including baseline
reference misses, unknown entities and oversized payloads. These correctness
findings remain part of [the correctness loop](https://github.com/Operatorr/godot-networking-poc/issues/39);
a performance result is not a bug-free/article-ready certificate. If those
findings compromise interpretation, qualify or withhold the capacity claim.
Application-delivered input counts and exact receive-queue residence remain
unknown; interface capture and message ages are not substitutes.

Do not retune or launch another cell after a failure. Retain the outcome and
verify original service/config/network/maintenance restoration, zero players,
no owned processes and checksummed evidence before the parent chooses a next rung.
