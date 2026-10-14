# CPU utilization and capacity evidence

CPU was already collected every second on **both** isolated hosts. The original `summary.csv` exposed matched-window game-process and generator CPU averages; `steady.json` also contained whole-host and per-core averages. Those averages hid short periods near a core's full budget and, in failing tests, the CPU drop after clients disconnected.

[cpu-summary.csv](cpu-summary.csv) now exposes matched-window means, 1 Hz p95/p99/maximum CPU, sampled time at or above 95%, longest contiguous near-95% interval, busiest-core statistics, and host utilization in both scales. Every completed case also has `cpu-summary.json` and `game/cpu-timeseries.csv.gz` / `bots/cpu-timeseries.csv.gz`. These are derived from existing observations; the game/bot binaries and host collectors remain unchanged and no passing test is repeated.

| Metric | Meaning of 100% | Scope |
| --- | --- | --- |
| Game process CPU | One logical CPU | `omega-server`, summed across its threads; excludes collector processes |
| Bot generator unit CPU | One logical CPU | Bot process plus its small launch wrapper |
| Whole-host CPU, one-core scale | One logical CPU; two CPUs allow 200% | OS, game/bots, observers and other executing work |
| Whole-host CPU, capacity scale | All available logical CPUs | 100% capacity = 200% on the one-core scale for these two-vCPU hosts |
| Per-core CPU | That core is fully executing | Includes all work on that core; game thread migration can distribute its usage |

The screenshots label **1 vCPU = 100%**. The bot-host graph exceeding 100% therefore does not mean the game server reached its CPU limit. Compare dashboard host utilization with whole-host metrics; use game-process CPU to identify the application's budget. The authoritative Tick is single threaded, so spare capacity on another core does not automatically increase Tick throughput. Process CPU is an indicator; the Tick thread was not measured separately.

Executing host CPU excludes idle, I/O wait and CPU steal; steal remains separately reported. Kernel counters use USER_HZ, and aggregate `cpu` sums the per-core counters. See the [Linux kernel `/proc` documentation](https://docs.kernel.org/filesystems/proc.html#miscellaneous-kernel-statistics-in-proc-stat). The provider's sampling and virtualization accounting need not exactly match guest observations.

## What the completed observations show

All percentages below use **100% = one logical CPU**. Peaks are interval averages from approximately one-second observations, not instantaneous CPU maxima.

| Case | Game mean | Game sampled peak | Bot mean | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Movement 150 | 37.1% | 44.3% | 43.0% | Passing single observation; no near-95% game intervals |
| Strategy 100 | 39.7% | 46.6% | 77.3% | Passing single observation |
| Combat 150 | 15.1% | **99.4%** | 19.4% | Game CPU near 95–100% for about **11 seconds**, then 135 bots disconnected and load collapsed; whole-window average hides the peak |
| Strategy 150 | 69.9% | 81.3% | **97.8%** | Bot CPU near one core's budget for almost the entire measurement; actual input cadence averaged 18.0 Hz instead of 30 Hz |

[Combat 150 timeline](core-combat-150-r1/cpu-timeline.png) shows CPU and the authoritative population dropping from 150 to 15. [Strategy 150 timeline](core-strategy-150-r1/cpu-timeline.png) separates bot and game CPU. Both observations also recorded game-host UDP buffer errors. The `generator-invalid` classification means offered-load validation failed; it does **not** by itself identify generator CPU as the cause. Combat 150's bot CPU did not approach one core's full budget, while its disconnects and kernel errors invalidated the offered load.

[CPU versus requested population](cpu-vs-population.png) separates workloads and marks failed/invalid observations with crosses. Means after load collapse must not be interpreted as spare capacity at the requested population. The matched boundary mean is exact for the collected counters; interval percentile bands describe temporal variation, not repeated-test uncertainty.

A sustained, valid 30 Hz workload at the game's CPU ceiling has **not** been established. Capacity also depends on Tick deadlines, maintained population, UDP errors and replication/delivery backlog; failure can occur before whole-host CPU reaches 100%. The present data supports a near-one-core game CPU episode at combat 150 and a generator CPU limitation at Strategy 150, not a validated 200–999-player capacity claim.

## Reproduce and refresh

Numeric reports use the Python standard library:

```bash
python3 scripts/load_campaign/cpu_report.py --no-charts
```

Charts additionally require Matplotlib. This session uses an isolated environment at `/tmp/omega-cpu-plots`:

```bash
/tmp/omega-cpu-plots/bin/python scripts/load_campaign/cpu_report.py
```

The local CPU-report watcher refreshes completed observations throughout the ongoing matrix/accounting sequence. It only reads published metric points. Peak statistics exclude intervals outside 0.5–2.5 seconds so tiny matched-boundary intervals cannot create misleading CPU spikes. Missing intervals or process/counter resets break sustained-utilization streaks. The 95% threshold is descriptive; it does not change matrix pass/fail gates.
