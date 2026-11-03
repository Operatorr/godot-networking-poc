# Stage 4 coverage: deferred load-test evidence and economics

Evidence-only pass for [Complete deferred load-test evidence and economics — Stage 4](https://github.com/Operatorr/godot-networking-poc/issues/47), 2026-11-04. No tests, reruns, workloads, deployments, host access or provider API calls were made. Historical files were not changed. `derive.py` regenerates `fixed-build-transfer.csv` and `economics-and-reconciliation.json` from retained evidence. The JSON's `archive_check` counts depend on the machine it runs on.

## Coverage

| Deferred requirement | What the retained evidence supports | Status |
|---|---|---|
| Controlled network groups and native controls | Combat100 native-before and delay25 only, on the old build. No after-control. Combined profile exists only as 3-player preflights. | **Not established.** 1 of 9 impairment profiles at one position |
| Transfer comparisons | Every clean-run config, climb config diff and retained report variant is at Snapshot 30 Hz, AoI 1000. No Snapshot15 or AoI600 observation exists. | **Not established.** Savings stay `[MEASURE]` |
| External-client accounting | One valid 3-client run on the old build. Provider display did not change across it. | **Measured; not reconciled** |
| Case, source and archive verification | Attempt counts reconcile. Committed bundles are intact. Original archives are on the author's MacBook and haven't been hash-checked. | **Partial.** Archive check outstanding |
| Fixed-build transfer and economics | Ten clean cells have matched 299 s wire bytes and player-seconds. | **Established for build `de92e120`, same-zone volume only** |

## Fixed-build transfer

All ten clean cells ran game binary `de92e120…`, Snapshot 30 Hz, AoI 1000/1100, with Hetzner same-zone bots. Bot binaries were `a4e6e7a6…` or `56c2139e…`.

`r_out` = game-host outbound IP bytes ÷ active bot-seconds, both over the 299 complete common UTC seconds inside the 300-second Tick window. Authenticated population stayed at the requested value throughout each window.

| Cell | r_out (B/player-s) | Outbound (B/s) | Median alive | r_out per median alive | IP+UDP headers | Reliable retry |
|---|---:|---:|---:|---:|---:|---:|
| Idle100 | 8,945 | 894,488 | 96 | 9,318 | 14.8% | 0.00% |
| Movement50 | 13,431 | 671,542 | 48 | 13,990 | 8.3% | 0.00% |
| Movement100 | 15,856 | 1,585,574 | 99 | 16,016 | 7.0% | 0.00% |
| Movement150 | 16,067 | 2,410,057 | 150 | 16,067 | 6.1% | 0.00% |
| Combat50 | 21,529 | 1,076,437 | 43 | 25,033 | 4.6% | 0.00% |
| Combat100 (R3) | 37,521 | 3,752,069 | 88 | 42,637 | 3.3% | 0.00% |
| Clustered50 | 24,480 | 1,223,979 | 43 | 28,465 | 4.3% | 0.00% |
| Strategy50 | 21,986 | 1,099,311 | 43 | 25,565 | 4.5% | 0.00% |
| Strategy100 (R3) | 36,132 | 3,613,172 | 86 | 42,014 | 3.4% | 0.00% |
| Strategy150 (R2) | 46,236 | 6,935,325 | 120 | 57,794 | 3.9% | 1.13% |

The rate per player is not flat. Strategy goes 21,986 → 36,132 → 46,236 from 50 to 150 players, so scaling any of these to 1000 needs fan-out data nobody has measured.

Limits:

- **Living population is a median.** The summaries keep alive quantiles, not the integral, and the raw archives aren't available here. Treat that column as approximate.
- **Payload share is not a steady-window figure.** First-transmission payload is 75–90% of game IP bytes, but that counter spans the whole capture including join and warmup. It is in the CSV, not the table.
- **Billing layer is unknown.** Interface TX runs 1.6–7.5% above IP bytes, and which layer the provider bills is unverified.
- **Five-minute observations.** These are single observations, not long-term rates. Worlds are not deterministic replays.
- **Not the current build.** Revisions were `fea24dd` and `a1abdf8c`. Master has since gained Change A (AoI-scoped events) and the climb changes, so **current-master transfer is unmeasured**.
- **Climb runs are not used here.** The final 225-player runs report about 40.6 kB/player-s, but that is application bytes over 59 s across a 207 ms path, and those five runs recorded 1,344–5,946 zero-byte sends each. It isn't comparable to IP-layer `r_out`.

## Conditional economics

Continuous full occupancy, 2027 calendar months, separately renewed allowances, one CAX11. These are projections from same-zone volume, not invoices.

Prices are the matrix's retained conditional figures: $6.99 compute + $0.60 IPv4 = **$7.59/month, $91.08/year** per production game host, before tax. 20 TB allowance, $1.20 per excess TB in 100 MB increments. The separate two-host test pair is **$15.18/month, $182.16/year**.

| Model | Status | 30-day TB (TiB) | Peak month TB | Mean Mbit/s | Overage/year | Host + overage/year |
|---|---|---:|---:|---:|---:|---:|
| 100 CCU Idle | Measured population | 2.32 (2.11) | 2.40 | 7.2 | $0 | $91.08 |
| 100 CCU Movement | Measured population | 4.11 (3.74) | 4.25 | 12.7 | $0 | $91.08 |
| 100 CCU Strategy | Measured population | 9.37 (8.52) | 9.68 | 28.9 | $0 | $91.08 |
| 100 CCU Combat | Measured population | 9.73 (8.85) | 10.05 | 30.0 | $0 | $91.08 |
| 150 CCU Movement | Measured population | 6.25 (5.68) | 6.46 | 19.3 | $0 | $91.08 |
| 150 CCU Strategy | Measured population | 17.98 (16.35) | 18.58 | 55.5 | $0 | $91.08 |
| 1000 CCU at the Strategy150 rate | **`[MEASURE]` hypothetical** | 119.84 (109.00) | 123.84 | 369.9 | $1,461.70 | not meaningful |
| 1000 CCU at the default client budget, read as 120,000 bytes/s | **`[MEASURE]` hypothetical** | 311.04 (282.89) | 321.41 | 960.0 | $4,253.18 | not meaningful |

Decimal versus binary reading of the allowance changes nothing at measured populations.

One CAX11's 20 TB covers about 7.47 MB/s sustained through a 31-day month. Clean Strategy150 uses 92.9% of that, so continuous full-occupancy Strategy traffic would start paying overage just above 150 players. Each extra TB costs $1.20 at the retained rate, and real occupancy would be lower, so this is a worst case.

**No validated 1000-CCU forecast exists.** There is no valid 999-player cell, and no host is shown to carry that load. The two hypothetical rows are overage sensitivities only.

### Price verification

Not verified to invoice precision.

- [Hetzner's billing FAQ](https://docs.hetzner.com/cloud/billing/faq/) confirms outgoing-only billing, free same-zone traffic and 100 MB round-up. Its 0.0001 TB = 100 MB example implies decimal units but does not define them.
- [Hetzner's cost-optimized listing](https://www.hetzner.com/cloud/cost-optimized/), read 2026-11-04 through a summarizing fetch, shows CAX11 at €6.49/month excluding VAT, labelled as including IPv4, with 20 TB. It also showed the product as currently unavailable and €1.00 per extra TB (the fetched text read "per hour", which I took as an extraction error). That is a different currency and structure from the retained USD figures.
- The price page the matrix cited now returns 404.

The account's invoice is the only source that can settle this.

## External-client accounting

`2026-10-13/external-combat-3-r1`: 3 Combat bots, real Taiwan–Falkenstein path, classified `external-accounting-check-valid`. Measured 4,844,642 outbound IP bytes, 900 authenticated player-seconds, **5,382.94 B/player-s**, on the old instrumented build.

The provider display read 0.00008464 TB both before and about five minutes after the window. No later matched reading exists. About 12 hours later the game-host reading had reached 0.00177221 TB, with about 1.89 GB of evidence downloads in the same period, so this run's 0.27% of that total cannot be isolated retrospectively. That pattern is consistent with same-zone traffic being exempt, but it does not reconcile anything.

The 3-client rate is not a stand-in for fixed-build rates at higher populations.

## Network evidence

| Run | Profile | r_out | Classification |
|---|---|---:|---|
| `network-control-before-combat-100-r1` | Native | 38,758.40 | `native-stable-candidate` |
| `network-combat-100-delay25-r1` | Delay 25 ms each way | 38,554.28 (−0.53%) | `controlled-profile-valid` |

Both are old-build, with no after-control. This is a descriptive difference between single observations, not an effect size. Delay25 stays absent from the top-level `summary.csv` and `scored-runs.json`, and that is left unchanged.

Missing: delay50/100, jitter5/20, loss0.1/1/3%, combined at scored populations, and all Strategy positions.

## Case and archive reconciliation

| Campaign | Attempts | Scored | Selected | Replacements |
|---|---:|---:|---:|---:|
| 2026-10-13 | 31 | 12 | 11 | 1 |
| 2026-10-14 one-pass | 27 | 18 | 17 | 3 |
| 2026-10-22 clean runs | 23 (18 ledger + 5 diagnostic) | 10 clean of 12 planned cells | n/a | n/a |

- **Committed bundles:** no historical report file has been modified since 2026-10-24, apart from the later 2026-10-29 reports. Hash lists passed: Idle150 8/8, Strategy200 12/12, Change A run 60/60.
- **Clean-run campaign:** lives at `fcf4f62`, protected by tag `archive/issue39-campaign-20261024`. It is not on master.
- **Original archives:** 68 retained manifests name 134 archive hashes under `deployment/hetzner/results/…`, and the clean-run summaries name 976 further evidence hashes. None of those files are on the Mac mini where this pass ran. The author reports the originals are on their MacBook, so **they are not hash-verified yet**. To check them, run `python3 derive.py --check-archives` on the MacBook, or on the Mac mini after a transfer. It only reads and prints. Remote retention was not checked.
- **2026-10-24 audit files:** `RESULTS.md` and `attempt-inventory.csv` were gitignored and are not on the Mac mini. They may be on the MacBook too, which hasn't been confirmed. The audit's tracker comment remains the record.
- **Retained qualifications:** the known scratch/verifier overwrites, the concurrent-ledger census exception, `original-3-full` left `not_yet_classified`, and the one-pass `matrix-coverage.json` and `source-audit.json` both reading `complete: false`. Nothing was regenerated.

## What this does not establish

No clean-campaign certificate, universal capacity limit, causal speedup, long-term stability, invoice precision, current-master transfer rate or 1000-CCU forecast.
