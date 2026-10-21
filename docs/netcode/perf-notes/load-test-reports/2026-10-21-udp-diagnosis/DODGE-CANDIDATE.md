# Strategy dodge-search candidate

The [completed sustained profile](generator-profile-fixed.md) places 51.21% of
late sampled generator CPU inside Strategy decisions, versus 19.37% early.
Hash-map iteration and hashing dominate that increase. Source inspection finds
`nearest_incoming_projectile` iterating all remembered projectile owners and then
probing the visible entity map. Owner events can exist without a visible entity;
the bot retains owners across baseline replacement. Actual remote owner occupancy
was not recorded, so growth is a hypothesis, not a measured count.

## Intervention and preserved behavior

Search the intersection from the table with smaller allocated capacity. When
visible entities are smaller, inspect each visible entity's recorded owner instead
of inspecting every historical owner. Exclude own shots and keep the same distance
calculation and `f32::total_cmp` ordering. If the nearest distance ties, fall back
to the original owner-order scan so the selected projectile and dodge direction
are identical. Empty maps return immediately; the original path remains when the
owner table is smaller. No ownership records are discarded.

This changes only the load generator's search implementation. Input cadence,
reaction cache, RNG draws, targeting, ability/combat rules, hit-report scans,
transport and measurement remain unchanged. In particular, the separate monster
hit-report owner scan is not optimized in this comparison. A large table with
many nearest-distance ties can still take the original full scan plus the initial
visible scan; the local fast-path timing is not a worst-case bound.

Rust documents HashMap iteration as depending on capacity, including empty
buckets; this is why capacity selects the scan direction.
[HashMap iterator documentation](https://doc.rust-lang.org/std/collections/struct.HashMap.html#method.iter).
Floating-point ordering remains the original total order.
[f32 total_cmp documentation](https://doc.rust-lang.org/std/primitive.f32.html#method.total_cmp).
Context7 was unavailable in this session; primary documentation and the pinned
local source were consulted instead.

## Local feedback and validation

A bounded release harness calls the actual search and `BehaviorState::decide`,
with 200 visible entities and 200 / 2,000 / 20,000 remembered owners. These are
synthetic counts, not an assertion about the remote maps. Apple M1 Pro,
`aarch64-apple-darwin`, Rust 1.95.0 (`59807616e`), LLVM 22.1.2, workspace thin LTO.
Each row below times 2,000 searches in the same post-change process/maps, comparing
the frozen implementation with the candidate:

| Remembered owners | Original search, ms | Candidate search, ms |
| --- | ---: | ---: |
| 200 | 4.198 | 4.161 |
| 2,000 | 32.079 | 3.599 |
| 20,000 | 540.181 | 2.842 |

Before the change, the same real search took 5.322 / 24.557 / 453.531 ms and
2,000 full Strategy decisions took 6.074 / 23.412 / 451.937 ms. Afterward the full
decision times were 4.424 / 4.496 / 3.608 ms. Different process/map layouts and
ordinary timing variation qualify cross-process numbers; none predicts a remote
capacity multiplier. The slow local case was measured before changing production
code. The retained independent original search is also the differential oracle.

Two differential tests cover 2,000 owner/visibility changes, baseline-style clear,
own shots, missing owners, owner changes, sparse retained capacity, randomized
map-order ties and nonfinite coordinates. Selected result bits match the original.
Existing Strategy tests cover actual dodge/sprint/ability behavior. Workspace tests,
Clippy and formatting pass; Clippy retains two pre-existing `bot.rs` match warnings.
The client extension release build passes. The ignored timing harness is manually
run in release mode; timing thresholds are not flaky pass/fail assertions.

```sh
cd rust
cargo test -p omega-load-test --release nearest_shot -- --include-ignored --nocapture
```

Compared with the control `cc86869`, the only production source difference in the
load-test crate and its local protocol/sim dependencies is this behavior search.
The protocol diagnostic integration test added elsewhere does not enter the bot
release binary. Build the candidate from the exact commit containing this change,
in a separate remote checkout; record revision, compiler and both-host SHA-256.

## Predeclared matched remote observation

Exactly one new **unprofiled Strategy 150** cell, namespace
`udp-dodge150-20261021`, under all [capacity gates](CAPACITY-150-PLAN.md).
The direct comparator is the earlier **unprofiled** [capacity150](capacity150.md)
cell. The subsequent profile is supporting diagnosis, not an identical overhead
condition. The one workload change is the candidate bot binary.

- Keep the existing game `f1cc5d6`, SHA-256
  `dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`.
- Keep private config SHA-256
  `642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`,
  effective game receive/send 4,194,304 / 524,288; bot buffers 212,992 each.
- Keep 150 Strategy bots, seed 30, difficulty 1, Class mix, original AoI/LOD/budgets,
  30 Hz input/Tick/Snapshot, 100 ms stagger, 60 s global warmup plus 300 s measurement.
- Keep collector source `994cce8` and 600-second wrapper/counting semantics. Use
  atomic schedules, continuous runtime identity proof and corrected byte-aware
  bounded journal export. Missing socket process attribution remains null, using
  the already-tested analysis handling from the fixed profile cell.

Prediction: if the history-driven dodge search materially limits the generator,
the candidate should improve per-peer offered/wire cadence through the full window
and reduce processing work per offered input. Failure to sustain at least 29.7 Hz
for every peer remains generator-invalid. Increased traffic may expose game-host
limits previously hidden by underload; retain any such regression without lowering
the required load. The separate owner hit scan, ties, decode/transport, or another
cost may remain limiting. Do not infer a server capacity pass from population or
Tick rate alone.

Build only the new bot package in isolated paths on both hosts and verify identical
artifacts before launch; preserve old game/bot executables. Retain all original
180/550/600/720-second ramp/workload/capture/restoration bounds and size/cgroup
guards. No perf, kernel trace, network tuning, schedule catch-up, gameplay change,
logging suppression or automatic next rung. Preserve baseline measurement files
before service restart, verify cleanup independently, checksum bundles and leave
remote originals intact. A separate agent owns the one run and returns findings
before the parent chooses any subsequent step. Historical Strategy 100 remains
the highest validated capacity until a valid cell passes all gates.

## Completed remote comparison

[The one matched cell](dodge150.md) restored every peer to valid offered/wire load:
29.993–30.000 Hz offered, 29.843–29.997 Hz wire, generator CPU 78.30% versus 97.71%.
All 150 authenticated, Tick and per-peer delivery gates passed. This supports the
generator-pressure prediction. The cell remained a capacity failure because of
2,290 steady game send-buffer errors and 19 strict AoI violators. Actual map size,
tie frequency and poll-cycle duration remain unknown; no general multiplier is
claimed. Candidate SHA-256 is identical on both hosts:
`73b957c7cb090ac8c433aa66dfba983ec8ad62305f527cab83be596dce524b1e`.
