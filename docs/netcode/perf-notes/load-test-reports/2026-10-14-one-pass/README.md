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

Every case checks free space and pinned binaries. Remote unpacked duplicates are removed
only after comparing local/remote archive SHA-256; archives remain retained off the hosts.
The cleanup ledger records each removal. Original pilots and failed attempts are preserved.
The 8 GiB storage guard remains a stop condition, not an estimate of campaign requirements.

Transfer forecasts use 2027 calendar months and separately renewed monthly allowances.
The account quote retained earlier supplies the conditional $6.99 compute plus $0.60 IPv4
base. Exact allowance/excess billing units remain unverified; decimal and binary sensitivity
models remain conditional. Same-zone traffic models external game egress but is exempt
from billed transfer; evidence downloads have a separate scope. These distinctions follow
the [provider billing FAQ](https://docs.hetzner.com/cloud/billing/faq/), checked 2026-10-14.
The fresh collaborative browser reached the account login page, so it supplies no new
authenticated provider counter or invoice-unit evidence. The earlier independent provider
graph comparison remains available in the stabilization report.

Preflight passed on 2026-10-14. [Resolution and overhead](measurement-preflight-resolution.json) records the native cleanup, per-direction realized impairment and measurement limitations. The combined probe retained 12 Baseline-reference misses and one unknown-entity delta in its measured minute; native on/cleanup checks were clean including warmup. The game/bot binaries remain unchanged. All 23 Python campaign tests pass, including isolated systemd launch/cleanup names for fresh campaigns.

## First population checkpoint

All four 50-player native cells passed their single observation, including the explicitly reused clustered pilot. The 100-player observations are pending; no measured 100-CCU or Strategy 1000-CCU forecast is claimed yet.

| Workload | Outbound IP bytes/s | Bytes/authenticated-player-second | Living fraction | Tick Hz | Tick work p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| movement | 643,523.82 | 12,870.48 | 96.50% | 29.997 | 5.848 |
| combat | 1,086,436.92 | 21,728.74 | 85.69% | 30.000 | 6.874 |
| clustered | 1,239,239.71 | 24,784.79 | 87.32% | 30.000 | 7.951 |
| strategy | 1,093,347.36 | 21,866.95 | 85.75% | 30.000 | 6.993 |

[Checkpoint timing/storage](checkpoint-50.json) distinguishes the five-minute observations from controller time. The three new 50-player cells took about 9.8–10.8 minutes each to the recorded controller checkpoint, before final cleanup/publication. Their archive pairs ranged from 264 to 327 MiB; all four retained cells occupy about 1.22 GiB. Larger-population storage and processing remain unmeasured. The primary core limits remain planned (movement/combat/clustered stop at 150); none has failed yet.
