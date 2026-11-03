# CAX11 Tick work climb, 225 strategy bots — 2026-11-03

Task: [Hill-climb CAX11 Tick work with a frozen harness](https://github.com/Operatorr/godot-networking-poc/issues/79).
Contract: [the resolution of Choose the next CAX11 experiment after Change A socket drops](https://github.com/Operatorr/godot-networking-poc/issues/78#issuecomment-6576194917).

**Tick work p95 on the frozen case: 35.89 → 23.53 ms (−34.4%).** The final server passes all gates
except absolute RTT in 5/5 runs. It is one CAX11 with Mac mini bots, so **the 200-player rung stays
unchecked**: bot RTT p95 is about 219 ms and the idle path alone is about 207 ms. The historical
failed run is unchanged.

## Method

- Generator: Mac mini, bot binary `a8ff3501`. Server: one CAX11, Ubuntu 26.04, 2 shared vCPUs.
- Harness: `scripts/cax11_climb/climb.py`, frozen after the sensitivity runs (`freeze` pins hashes
  and later sessions refuse drift). Replaying it on the failed 200-player run reproduces Tick p95
  27.65 ms, 3/1800 overruns and 5,656 drops. Rebuilding from the branch reproduced the frozen
  server binary `df42e73b` exactly.
- Window: first 1800 consecutive Ticks at full population. Bot RTT and loss include ramp.
- Budget: 9 of 10 attempts, 100 of 100 load runs. Raw evidence and `decision.tsv` are in the
  ignored `loadtest-runs/cax11-climb/`.

## Baseline tuning: receive buffer, 200 players

| Measure, median [range] | Control (n=5) | `udp_receive_buffer_bytes=2097152` (n=5) |
|---|---|---|
| Socket drops, whole run | 47,893 [17,947..70,737] | **0 [0..0]** |
| Tick work p95 ms | 30.74 [28.76..31.28] | 27.61 [26.83..30.84] |
| Ticks over 33.3 ms | 0.944% [0.333..1.389] | 0.111% [0.056..0.889] |
| Excess RTT ms | 19 [16..24] | 20 [19..22] |
| All gates but absolute RTT | 0/5 | **5/5** |

This is the first row of the resolution's table: the overflow was queue capacity. The setting was
kept as a harness lever. **No production config changed.**

## Sensitivity and the frozen case

Tuned server, one binary:

| Bots | Runs | Tick p95 ms | Overruns | Socket drops | Connected |
|---|---|---|---|---|---|
| 150 | 2 | 17.7, 17.2 | 0.06%, 0% | 0, 0 | all |
| 200 | 5 | 27.61 median | 0.111% median | 0 | all |
| **225** | 2 | 31.7, 31.6 | **2.5%, 1.9%** | 0, 0 | **all** |
| 250 | 2 | 54.3, 40.3 | 15.5%, 11.3% | 213,422, 136,015 | all |
| 300 | 2 | none, 63.8 (partial window) | n/a | 501,855 in the run with data | 295, 279 |
| 350 | 2 | no window | n/a | n/a | 245, 170 |

**Frozen case: 225 players** (ladder step 25), not the roughly 300 the resolution expected. Mac
workers stayed under 46% with no Mac UDP drops, so the generator's CPU and socket buffers were not
the limit.

## Attempts

Screens compare one run against the current range. Comparisons are 5 vs 5, alternating.

| # | Change | Result, Tick p95 ms | Verdict |
|---|---|---|---|
| 1 | Id bitsets replace per-peer HashSets | Screen 33.25 inside [32.26..48.31] | Reverted, near-miss |
| 2 | Heap orders only the admitted head | Screen 32.74; Snapshot build flat | Reverted |
| 3 | Multiply-rotate hash for Snapshot keys | 32.77 → 30.23, ranges separate | **Kept** |
| 4 | Id bitsets again, on 3 | Screen 30.66 inside range | Reverted, near-miss |
| 5 | Byte-at-a-time bit writer | Screen 31.60; outbox flush 4.34 → 2.27 ms | Reverted, near-miss |
| 6 | Combine 4 + 5 | 31.25 → 28.77 | **Kept** |
| 7 | Sort compact rank keys | 28.64 → 25.89; stop rule fires | **Kept** |
| 8 | Presize per-peer Vecs | 26.26 → 25.42, not past noise | Not kept alone |
| 9 | Combine 8 + one cache probe + 20-byte entry | 25.99 → 23.53 | **Kept** |

Attempt 2 refutes the sort half of the early "deferred records" hypothesis. The first profile put
Snapshot build at 57% of server CPU; the largest parts were delta-cache lookups (13.1%), the
deferred observer (10.7%), rebuilt HashSets (about 12%) and the sort (7.1%).

## Result on the frozen case

| Measure, median [range] | Baseline (n=15) | Final (n=5) |
|---|---|---|
| **Tick work p95 ms** | **35.89 [31.60..48.31]** | **23.53 [23.18..25.69]** |
| Ticks over 33.3 ms | 10.333% | 0.222% [0.056..0.278] |
| All gates but absolute RTT | 0/15 | 5/5 |
| Zero-drop runs | 3/15 | 5/5 |

Baseline here pools three sessions of the one frozen binary. Baseline and final never ran in one
session, so the −34.4% is cross-session. The two direct comparisons are:

| Measure, median [range] | Baseline (n=5) | Attempt 7 (n=5) | Attempt 7 (n=5) | Attempt 9 (n=5) |
|---|---|---|---|---|
| Tick work p95 ms | 37.39 [35.89..38.11] | 26.67 [24.52..27.89] | 25.99 [25.59..27.13] | 23.53 [23.18..25.69] |
| Tick work mean ms | 28.64 | 21.33 | 20.99 | 19.02 |
| Snapshot build ms/Tick | 19.76 | 13.88 | 13.58 | 11.90 |
| Server CPU, % of a core | 98.5 | 75.8 | 74.7 | 68.3 |
| Socket drops, whole run | 67,742 | 0 [0..918] | 0 [0..65] | 0 [0..0] |
| Excess RTT ms | 177 | 18 | 13 | 7 |
| Bot errors | 0 | 0 | 0 | 0 |

Offered datagrams were within 10% in both: +9.9% and 0.0%. Bot RTT p95 is 219 ms [218..221] and bot
loss 0.02% on the final server.

Every Snapshot change is byte-identical to the old pipeline: `optimized_output_matches_reference`
compares every encoded packet per Tick against a test-only frozen copy, and three seeded mutations
fail it. The final Rust run: 244 passed, 0 failed, clippy and fmt clean of new warnings.

## Limits and judgment calls

- **The final 5/5 is a small sample.** Attempt 7 also scored 5/5 when the stop rule fired, then 18/21
  over more sessions. Those misses were two runs with drops (918 and 65) and one over the Tick gate.
  Attempt 9 has only 5 runs because the budget ran out.
- **Rare stalls remain, cause unknown.** Runs with drops show a single 65–79 ms `service_and_route`
  call or a read gap over 100 ms, with peer RTT jumping. 1 Hz sampling shows no Mac pause but cannot
  rule out a short one, so this is not attributed to the path or the server.
- **Deferred records p95 is the open guard.** It rose from 15,752 to 18,116 in Attempt 9, higher in
  all 5 pairs, and rose similarly in Attempts 3 and 7. Each time the median left that session's
  comparison range or came close, but stayed inside the pooled same-binary range. Deferred mean is
  flat (10,374 → 10,194), deferred wait is unchanged (p95 9, max 10) and scheduler output is
  byte-identical, so these were kept. Deferred totals track bot clustering, but that does not explain
  the 5-of-5 pairing, and this needs a closer look.
- **One bot error on Attempt 6.** One connect timed out near 140 players at about 9 ms Ticks, zero
  drops, leaving 224/225. It did not recur in 32 later runs of later binaries, and the frozen binary
  shows the same failure at 300. Attempt 6 did not touch ENet.
- **Observer inflation.** The measurement-only deferred observer was 15.7% of server CPU when
  re-profiled after Attempt 6. It was deliberately left in, so production Tick work is lower than
  measured.
- **Two deviations.** Attempt 9 skipped its screen because 10 runs funded only the comparison.
  Near-miss combinations (Attempts 6 and 9) bundle changes, as the playbook allows at a plateau.
- **One lost run.** An agent restart killed `15-a7-5v5/03-a7`. It counts against the budget and was
  rerun, so 100 counted runs have 99 ledger rows.
- **Host changes.** `linux-perf` and its dependencies were installed for the two profiles and purged
  afterwards. `~/omega-realm` now holds the final source and binary; the frozen binary and raw runs
  are in `~/omega-climb`. `net.core.rmem_max` was already 4 MiB and was not changed.

## Next

- Higher rungs on Attempt 7 (not rerun on the final binary): 250 had Tick p95 30.28 and 32.63 ms,
  1.56% and 3.94% overruns, and drops in one of two runs; 300 lost players (296 and 298 connected).
- Best next idea: re-profile the final binary at 250 and make the delta cache flat rather than
  hashed. It was the largest production cost at the last profile, taken before Attempt 9. Reliable
  ACK handling and `sendto` were next in line.
- After this, 500 players is the next hill: a new round with its own baseline, per the contract.
