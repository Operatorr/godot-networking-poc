# CAX11 revised one-pass execution

Execution of [Execute the revised one-pass CAX11 load-test matrix](https://github.com/Operatorr/godot-networking-poc/issues/35),
following the [amended matrix](https://github.com/Operatorr/godot-networking-poc/issues/30#issuecomment-6145030523).
**In progress.** This directory does not establish complete matrix coverage.

The fresh namespace is `one-pass-20261014`. The historical administrative hold and all
earlier campaign state remain unchanged. Initial checks found no active swarm, native
`fq_codel` on both hosts and the expected separate game/bot executable hashes. Game
`b1266c1` and bot `642c147` remain frozen; the controller starts from integration revision
`f0b9c33`. No API/persistence or additional host is part of this execution.

The [execution binding](execution-binding.json) records the pinned hashes and authorization.
The [pilot binding](matrix-replacements.json) selects the retained corrected clustered
50-player pilot for `core-clustered-50-r1`. Its archive hashes, executable provenance,
resolved settings and unchanged primary collectors were verified. The additional dedicated
tracefs diagnostic is retained in the original pilot report; this is reuse of one observation.

All new scored observations use 60 seconds of global warmup and 300 measured seconds,
after the 100 ms join stagger. Collection on/off and small-load impairment/cleanup checks
are short, unscored preflights. Each scored cell records cumulative warmup errors as well
as steady-window counters. Only Strategy proceeds above 150 players. Failure boundaries
are refined to at most 25 players; generator faults cannot establish a server ceiling.

Run from the repository root:

```bash
python3 scripts/load_campaign/one_pass.py init       # once; refuses existing namespace
python3 scripts/load_campaign/one_pass.py preflight
python3 scripts/load_campaign/one_pass.py resolve-preflight
python3 scripts/load_campaign/one_pass.py all
```

Future observations use `article-points-v1`, following the operator's 2026-10-14 logging amendment. The collector retains only the points needed for the article:

- Numeric Tick work/population/backlog points for exact p99/deadline counts and player-second integrals.
- One-second host CPU/steal/RSS/swap, kernel UDP errors, interface traffic, flow counters and qdisc metrics, with matched boundaries.
- One-second bot input cadence, delivery ages, RTT and error counters; per-bot boundaries preserve the minimum offered-load check.
- Exact whole-window traffic/input/retry counters and one-second traffic graph points, computed while packets pass through the recorder.
- A deterministic 1/64 UDP fingerprint sample for cross-endpoint delivery/delay estimates. No packet payload, packet header dump or per-command archive is retained. Identical retransmissions share a fingerprint, so the sample is correlated; no exact zero-loss or independent-packet confidence claim is supported.
- Bounded diagnostics (first 20 warning/error lines and last 20 bot log lines), settings, source/executable hashes and compact bundle checksums.

Full packet records and full host/socket dumps are no longer a future campaign requirement. Existing historical evidence remains unchanged. Compact bundles are verified off the hosts before removing remote unpacked duplicates. Collection refuses to overwrite an existing generation; absent window coverage invalidates the observation before any server/generator conclusion. Host update timers are temporarily masked during measurement to prevent maintenance from restarting collectors; the runtime masks are recorded and must be restored after the campaign.

Validate the new collector with `python3 scripts/load_campaign/one_pass.py points-preflight` before resuming scored cells. The prior full-collector preflight remains historical evidence; the compact collector has its own on/off, impairment and cleanup observations.

Transfer forecasts use 2027 calendar months and separately renewed monthly allowances.
The account quote retained earlier supplies the conditional $6.99 compute plus $0.60 IPv4
base. Exact allowance/excess billing units remain unverified; decimal and binary sensitivity
models remain conditional. Same-zone traffic models external game egress but is exempt
from billed transfer; evidence downloads have a separate scope. These distinctions follow
the [provider billing FAQ](https://docs.hetzner.com/cloud/billing/faq/), checked 2026-10-14.
The fresh collaborative browser reached the account login page, so it supplies no new
authenticated provider counter or invoice-unit evidence. The earlier independent provider
graph comparison remains available in the stabilization report.

The compact collector preflight passed on 2026-10-14. [Resolution and overhead](measurement-preflight-resolution.json) records the native cleanup, per-direction realized impairment and measurement limitations. The earlier full-collector combined probe retained 12 Baseline-reference misses and one unknown-entity delta in its measured minute; its [legacy preflight](legacy-measurement-preflight-resolution.json) is preserved separately. Native compact on/cleanup checks were clean through the retained warmup and measurement observations. The game/bot binaries remain unchanged. All 29 Python campaign tests pass, including isolated systemd launch/cleanup names for fresh campaigns.

## First population checkpoint

All four 50-player native cells passed their single observation, including the explicitly reused clustered pilot. Movement and combat subsequently passed at 100 players. Clustered at 100 had a valid kernel UDP buffer failure, pending a 75-player boundary observation. The original Strategy 100 is collector-invalid: host maintenance restarted both bot captures and their retained prefix begins 201.9 seconds into measurement. Its apparent wire cadence/loss must not be interpreted as generator saturation or a server ceiling. The interrupted movement 150 attempt is unscored. See the [capture-window audit](capture-window-audit.json); all other retained core windows span the complete measurement. No Strategy 1000-CCU forecast is supported yet.

| Workload | Outbound IP bytes/s | Bytes/authenticated-player-second | Living fraction | Tick Hz | Tick work p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| movement | 643,523.82 | 12,870.48 | 96.50% | 29.997 | 5.848 |
| combat | 1,086,436.92 | 21,728.74 | 85.69% | 30.000 | 6.874 |
| clustered | 1,239,239.71 | 24,784.79 | 87.32% | 30.000 | 7.951 |
| strategy | 1,093,347.36 | 21,866.95 | 85.75% | 30.000 | 6.993 |

[Checkpoint timing/storage](checkpoint-50.json) distinguishes the five-minute observations from controller time. The three new 50-player cells took about 9.8–10.8 minutes each to the recorded controller checkpoint, before final cleanup/publication. Their archive pairs ranged from 264 to 327 MiB; all four retained cells occupy about 1.22 GiB. Larger-population storage and processing remain unmeasured. The primary core limits remain planned (movement/combat/clustered stop at 150). The earlier archive sizes describe the retired full collector, not the compact policy.

The [compact storage validation](compact-storage-validation.json) measured 1.12 MiB for both endpoint bundles in the new 50-player/120-second preflight, versus 110.50 MiB previously (98.99% smaller). This is a measured checkpoint, not a universal bound for 999 players. No additional private archive destination is required for this checkpoint. Rust workspace tests, Clippy and formatting checks pass; Clippy retains two existing bot match warnings. Exact packet totals are independent of sampling. Sampled one-way timestamp differences are signed and include clock offset; sub-ms negative values do not imply negative network latency.

The [collector binding](compact-collector-binding.json) records the actual deployed recorder/script hashes. Recovered Strategy 100 and movement 150 observations have new identities in [matrix replacements](matrix-replacements.json); the original invalid/interrupted evidence remains preserved. Collector-invalid and failing cells do not generate cost forecasts. Summary CSV rows identify the collection format, delivery sample size and estimated-loss status beside the measurements.

The [100-player checkpoint](checkpoint-100.json) is now recorded. The replacement Strategy 100 passed its complete 300-second native observation with 30.000 Tick Hz, 29.999 bot input Hz, 29.981 exact wire input Hz, zero missed schedules and clean cumulative/steady error counters. Tick work p99 was 15.960 ms; outbound traffic was 3,670,419.81 IP bytes/s. Both compact endpoint bundles total 6.54 MiB. This replaces the invalid observation without repeating any passing cell. The controller has advanced to the 150-player rung; full matrix coverage remains pending.

The movement 150 replacement also passed (30.000 Tick Hz, Tick work p99 12.957 ms); combat 150 is now measuring. The [maintenance restoration watchdog](maintenance-restoration-watchdog.json) bounds the temporary update deferral. The automatic finish watcher performs the already-authorized external accounting check/audit after measurement phases finish, then restores update timers. Tracker resolution still requires a review of complete coverage; the task stays open during execution.

[CPU utilization and capacity evidence](CPU.md) now provides one-second CPU timelines, game/generator means and peaks, near-95% durations, per-core metrics and whole-host normalization. CPU observations were already retained; this adds readable derived reports without changing the collectors or rerunning passing cells. The Combat 150 timeline shows why its 15.1% whole-window game CPU average conceals a 99.4% episode followed by mass disconnects. Strategy 150 shows a different limitation: generator CPU near one core's budget while game CPU averages 69.9%.

The operator requested Strategy 200 → 250 → 500 → 750 → 999 overload observations, with one subagent per run. The [documented lower-ladder checkpoint and execution amendment](PRE-STRATEGY-EXTENSION.md) precedes those runs. Existing first-failure boundaries remain unchanged; the network/transfer sequence is deferred while the requested Strategy continuation takes priority.
