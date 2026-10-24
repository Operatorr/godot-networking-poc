# Correctness campaign progress and stopping rule

Checkpoint: **2026-10-24 06:34:32 UTC / 14:34:32 Taipei**. This scorecard answers the author's request for measurable progress and a bounded finish. It does not change any historical classification, numeric gate, runtime condition or resource reserve.

## Attempt accounting

There are **21 completed test-attempt reports**, plus **Strategy100 R3 in progress: 22 test attempts total**. The 21 reported attempts comprise **18 launched workloads** and **3 resource blocks before workload**. **9/18 reported launched workloads (50%)** earned clean-cell-pass; **9/21 reported attempts (42.9%)** earned it. These are campaign yield measures, not server performance improvements. The current R3 workload has launched and ended, but its task/report is not yet final, so its outcome is excluded. One additional delegated idle-preservation maintenance task ran zero workloads; it is excluded from test-attempt totals. Parent cache/duplicate preservation operations also ran no workload.

At this checkpoint's exact rolling 24-hour cutoff, 11 of the reported workloads started within the interval, plus the current R3 workload: **12 launched workloads**, and **one blocked attempt**, or **13 test attempts**. One maintenance task is separate. The 22-attempt thread total spans more than 24 hours; the first reported workload began October 22 at 13:02:58 UTC.

The plan has **12 distinct scenario/population cells** including the initial Strategy150 reference and Strategy200 overload. Nine have a clean observation (**75%**): Strategy150, Idle100, Movement50/100/150, Combat50/100, Clustered50 and Strategy50. Idle150 has a retained wire-delivery deficit; Strategy100 matched validation and Strategy200 overload assessment remain outstanding. This percentage measures clean-cell coverage, not percentage of bugs fixed or overall project completion. A characterized overload limit can satisfy correctness assessment without passing capacity.

## Actual performance deltas

The following compare [Combat100 R1](clean-combat100-r1-20261023.md) with [Combat100 R3](clean-combat100-r3-20261023.md): same runtime source/executable identities and requested load; controller fixes differ. R1 completed its measured window but failed terminal handling, so its historical classification remains aborted-valid-failure. These are descriptive changes between two observations, not statistically demonstrated causal improvements.

| KPI | R1 | R3 | Observed change | Direction |
|---|---:|---:|---:|---|
| Reported bandwidth per bot | 33.10 KiB/s | 32.87 KiB/s | −0.69% | Lower, but both fail <5 KiB/s |
| Server Tick work p99 | 14.582160 ms | 14.606882 ms | +0.17% | Higher |
| Received Snapshot age p95 | 28.322440 ms | 29.558611 ms | +4.36% | Higher |
| Actual measured Tick rate | 30 Hz | 30 Hz | 0.00% | Unchanged |

Formula: `(later − earlier) / earlier × 100`. Bandwidth uses the reported two-decimal values; other rows use raw summary measurements. Zero-to-zero error counts do not have a defined percentage reduction. Different populations, behaviors, invalid windows or diagnostic modes must not be pooled into a speedup claim. No meaningful overall throughput/latency/bandwidth improvement has been established by this correctness campaign.

## Bounded finish from this checkpoint

Objective: establish whether the fixed build exposes another correctness/measurement defect across the specified cells, and publish a final evidence-backed pass/blocked assessment with surviving and invalidated historical claims. It is not a capacity or bandwidth optimization objective.

1. Finish the already-running Strategy100 R3 task and verify its report.
2. If that is clean and the original full preflights pass, authorize **at most one Strategy200 overload attempt**, in a separate agent.
3. Stop adding remote attempts on any further storage block, collector/harness failure or newly discovered defect. Record the blocker and the smallest proposed next action for review instead of automatically retrying. Preserve safe restoration and evidence completion.
4. **Reporting checkpoint: 2026-10-24 08:35 UTC / 16:35 Taipei.** Deliver the final assessment by then if these tasks finish; otherwise deliver an explicit incomplete assessment and launch no further workload after the checkpoint. Safe restoration/archival may continue if necessary. Do not close the issue or certify the campaign unless its actual requirements are met.

From this checkpoint there is one current task and at most one further workload attempt. No additional automatic retry sequence is authorized by this operating plan. For every remaining result, report its matched comparator, correctness/error counts, offered/wire rates, Tick work p99, Snapshot age p95, bandwidth, terminal/recovery result and percentage changes where the comparison is valid. Clearly distinguish observed variation from demonstrated improvement.

## Update after Strategy100 R3

At 2026-10-24 06:49 UTC, all **22 attempts have final reports**: 19 launched workloads and three pre-workload blocks. Ten clean results give **52.6% yield among launched workloads**, or **45.5% among all attempts**. Clean distinct-cell coverage is **10/12 = 83.3%**. Strategy100 is now validated; Idle150 remains a retained deficit and the single Strategy200 overload assessment is outstanding. The local census qualification from the parent documentation edit is retained in the R3 report.

Matched Strategy100 R1 → R3 observations: **Tick work p99 −3.24%** (14.619642 → 14.146315 ms); **Snapshot age p95 −2.38%** (29.180649 → 28.485562 ms); **bandwidth +0.74%** (31.703594591 → 31.937993191 KiB/s); actual Tick rate unchanged at 30 Hz. These are descriptive differences between single observations with identical runtime binaries. The established improvement is correct prefix acquisition and a clean matched execution, not a proven performance effect. The final one-attempt allowance and 08:35 UTC reporting checkpoint remain unchanged.

## Final update — remote testing stopped

Strategy200 R1 completed as aborted-collector-invalid before measurement. Final totals: **23 attempts, 20 launched workloads, three pre-workload blocks, ten clean results**. Clean workload yield is **50.0%**; attempt yield **43.5%**; clean distinct-cell coverage **10/12 = 83.3%**. One zero-workload maintenance task remains separate. These are full-campaign totals, not rolling 24-hour totals.

The final overload attempt produced no valid complete-window KPI comparison, so its percentage improvement is **N/A**. Both hosts are restored and released. The bounded attempt allowance is exhausted; there is no further automatic retry, clean campaign certificate or issue closure. See [FINAL-ASSESSMENT.md](FINAL-ASSESSMENT.md) for the final evidence, limitations and separately reviewed future decision.
