# Article drafts: load testing Omega Realm & why realtime games cap at ~64–150 players

First drafts for [Write the full first draft of the article](https://github.com/Operatorr/godot-networking-poc/issues/33),
on the map [Article: load testing Omega Realm & why realtime games cap at ~64 players](https://github.com/Operatorr/godot-networking-poc/issues/23).
Audience: gamedev engineers. The author rewrites by hand, so the drafts favour complete facts,
derivations and sources over polished prose.

## The three drafts

Per the [outline decision](https://github.com/Operatorr/godot-networking-poc/issues/32#issuecomment-6186284697),
there are three drafts so the author can compare them and choose.

| Draft | File | Shape | Body (prose / incl. tables & code) |
|---|---|---|---|
| **A** | [`omega-load-testing.A.md`](omega-load-testing.A.md) | One article, cold open on our wall: §0 cold open, §1 Omega, §2 industry + Battlefield, §3 math + Rust, §4 tab-target MMOs, §5 wire format, §6 method + fix-and-rerun loop, §7 results, §8 which wall `[PENDING]`, §9 conclusion | ~6.8k / ~8.9k words |
| **C1** | [`omega-load-testing.C1.md`](omega-load-testing.C1.md) | Part 1, "Why realtime games cap at ~64–150": new intro, A §2–§4 with cross-references adjusted, new conclusion handing off to Part 2 | ~3.5k / ~4.6k words |
| **C2** | [`omega-load-testing.C2.md`](omega-load-testing.C2.md) | Part 2, "Load-testing Omega": cold open, Omega, a one-page recap of Part 1's math (E = N·D, AoI, Battlefield vs Rust), wire format, method, results, which wall, conclusion. Condensed from A | ~3.2k / ~3.9k words |
| shared | [`omega-load-testing.appendices.md`](omega-load-testing.appendices.md) | A formula sheet and derived checks, B full bit layouts, C how to reproduce, D sources by section | outside budgets |

C1's sections are A's sections nearly verbatim; C2 trims A. Numbers are identical across drafts.

## Evidence rules the drafts follow

- **Results cite only the [accepted bounded results audit](https://github.com/Operatorr/godot-networking-poc/issues/31#issuecomment-6382173465)**
  (author-accepted 2026-10-25), under the [bounded correctness closure](https://github.com/Operatorr/godot-networking-poc/issues/39#issuecomment-6382109701).
  No complete clean campaign, general capacity limit, 500–1000-player result, long-term stability or
  causal speedup percentage is claimed.
- **Two builds, never pooled.**
  - *Original build*: game `b1266c1`, 14 Oct 2026 campaign, 512 KiB effective socket buffers. Source of
    the five failed Strategy ramps (191/185/176/180/190), the original ladder, Strategy 50/100 transfer.
  - *Fixed build*: game SHA-256 `de92e120…`, 22–24 Oct 2026 correctness campaign, 4 MiB effective game
    buffers. Source of the ten clean cells, including Strategy 150. Its extracted fixes on `master`
    were validated locally, not load-tested again.
- Failed and invalid classifications stand: the ramps are **failed join ramps, not a capacity**;
  Idle150 is non-clean; fixed-build Strategy200 is collector-invalid; Strategy125/150 (original) are
  generator-invalid. Unknowns stay unknown.
- The wire-format byte breakdown comes from a local 50-bot tally on commit `62fbfc3`, before the
  correctness fixes. Layouts didn't change, so bit costs stand; byte shares are marked indicative.
- The "14.85 KB/s vs 5 KB/s" sidebar from the prototype outline is cut, as decided. The 32.9 Hz
  estimator story appears only as an optional "number that lied" sidebar, using the fixed
  estimator's behaviour, which the correctness work supports.
- Industry numbers carry the research notes' confidence tags: [P] primary, [S] first-party via press
  or mirror, [U] unverified (mostly cut), [O] observed third-party, [D] our arithmetic. Every [D] is
  reproduced in Appendix A.

## Markers

| Marker | Meaning | Where |
|---|---|---|
| `[MEASURE]` | Needs fixed-build data we don't have: fixed-build byte shares; fixed-build outbound bytes per player-second; external transfer, monthly/yearly cost, 1000-CCU forecast; network-impairment and Snapshot15/AoI600 comparisons. All deferred to [Stage 4](https://github.com/Operatorr/godot-networking-poc/issues/47) | A §5, §7; C2 §3, §5 |
| `[PENDING]` | Editorial decision: the titles and the headline claim in "Which wall did we hit?" (draft framing: "same wall, with a twist: the receive path fails before the CPU"). On the map this stays fog | A title, §8, §9; C1 title; C2 title, §6, §7 |
| `[AUTHOR]` | A note or question for the rewrite (caveats to keep, sidebars to keep or cut) | all |
| `[FIGURE Fn — new]` | A figure still to render. F1 and F5 exist as campaign PNGs and are embedded | see below |

## Figures

| # | Figure | Status |
|---|---|---|
| F1 | CPU + population per Strategy ramp (original build) | exists: `strategy-extension-timelines.png`, embedded in A §0, C2 §0 |
| F2 | Server egress vs N, naive vs AoI-64, 30/60 Hz | **new**; data table in A §3 / C1 §2 |
| F3 | Snapshot bit layout | **new**; ASCII stand-in in A §5 / C2 §3 |
| F4 | Where the bytes go at 50 bots | **new**; data table in A §5 / C2 §3 |
| F5 | CPU vs requested population (original build) | exists: `cpu-vs-population.png`, embedded in A §7, C2 §5 |

## Follow-ups this draft does not do

- [Retrieve historical load-test reports and incorporate them after the first draft](https://github.com/Operatorr/godot-networking-poc/issues/28):
  the historical raw reports (including the 32.9 Hz run) are still missing; the drafts say so where it matters.
- [Complete deferred load-test evidence and economics — Stage 4](https://github.com/Operatorr/godot-networking-poc/issues/47):
  fills the `[MEASURE]` slots, under its own reviewed plan.
- Choosing A or C1+C2, the headline, figure rendering and venue: editorial work after the author's read.
