# Load-test egress costs

**Status:** Research and hypothetical budgeting, verified 2026-10-13. No new server measurements yet. Related: [Hetzner setup and benchmark plan](hetzner-load-testing.md), [Set up a Hetzner server for load testing](https://github.com/Operatorr/godot-networking-poc/issues/29).

The primary economic metric is sustained **server outbound bytes per second per connected player**, measured separately at each population and scenario. CPU architecture affects compute cost; reducing bytes sent affects transfer cost. A combined inbound/outbound number, including the earlier reported 14.85 KB/s, cannot be substituted for outbound traffic.

## Provider billing

DigitalOcean Droplets charge **$0.01/GiB** above the included outbound allowance; inbound is free. Allowances are pooled across a team's Droplets and accrue with resource lifetime, capped at a full month's allowance after 28 days. These examples assume one continuously running Droplet contributes **1,000 GiB/month**, with no other team usage or allowance. The user's historical $7 plan is unidentified; check its actual size and allowance before applying these numbers. The current regular 1 GiB/$6 plan includes 1,000 GiB, but this does not establish the historical plan. Sources: [bandwidth billing](https://docs.digitalocean.com/platform/billing/bandwidth/), [plan catalog](https://www.digitalocean.com/pricing/droplets).

Hetzner EU **CAX11 and CCX13 list 20 TB/month**, with **$1.20 per additional TB** before tax. This was verified in the first-party [Cloud calculator data](https://www.hetzner.com/_resources/app/data/bench/cloud_data.json), referenced by the [Cloud pricing page](https://www.hetzner.com/cloud/): each EU location's USD entry has `traffic: {"0": 0, "20": "1.200000"}`. The general [traffic documentation](https://docs.hetzner.com/robot/general/traffic/) confirms CAX EU20 TB and CCX EU20–60 TB depending on plan, with calendar-month accounting.

Hetzner bills outgoing traffic; incoming and internal traffic are free. Cloud traffic to another Hetzner Cloud server in the **same network zone, even over public IPs**, is internal. Public traffic across zones counts. Excess is rounded up to 100 MB blocks. Deleting a server ends compute billing, but separately retained paid Primary IPv4s continue billing. Source: [Cloud billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).

### Resolve Hetzner's byte units before treating forecasts as invoice estimates

The pricing pages use `TB`, without an unambiguous byte definition. Hetzner's own [Go SDK fixture](https://github.com/hetznercloud/hcloud-go/blob/main/hcloud/server_test.go) represents a nominal 20 TB allowance as `21,990,232,555,520` bytes, which equals **20 TiB**, rather than 20 decimal TB. A fixture for another plan is evidence, not verification of newly created CAX11/CCX13 billing.

The table below conservatively assumes **20 × 10^12 bytes** included and **$1.20 per 10^12 excess bytes**. At provisioning, save the server/type API `included_traffic` byte value and current `price_per_tb_traffic`, and confirm the excess billing unit. If both allowance and rate use TiB, the 1,000-player 15 KiB/s row becomes **$19.45/month and $240.66/year** instead of $23.78/$293.27; 30 KiB/s becomes **$62.90/month and $769.33/year** instead of $71.55/$874.54. Do not silently mix decimal transfer totals and binary quotas.

## Reproducible hypothetical costs

`1 KiB = 1,024 bytes`; `1 GiB = 2^30 bytes`; decimal `1 TB = 10^12 bytes`.

```text
B(N, r, days) = N × r × 1024 × days × 86400
DigitalOcean month = max(0, B / 2^30 - 1000) × $0.01
Hetzner month (decimal assumption) = max(0, B / 10^12 - 20) × $1.20
Annual cost = sum of 12 calendar-month costs, each with its own allowance
```

All rows assume a constant population, constant **outbound** rate per player, 24/7, and no unrelated server traffic. Transfer includes transport overhead only if the input rate was measured at that level. Rates are illustrative, **not observed game performance**. Compute, IPv4, tax, bots, storage, and other services are excluded.

| CCU | Outbound/player | Transfer/30 days (decimal TB) | Transfer/365 days (decimal TB) | DO egress/30 days | DO egress/365 days | Hetzner EU egress/30 days* | Hetzner EU egress/365 days* |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 5 KiB/s | 1.327 | 16.146 | $2.36 | $30.38 | $0 | $0 |
| 100 | 15 KiB/s | 3.981 | 48.439 | $27.08 | $331.13 | $0 | $0 |
| 100 | 30 KiB/s | 7.963 | 96.879 | $64.16 | $782.25 | $0 | $0 |
| 1,000 | 5 KiB/s | 13.271 | 161.464 | $113.60 | $1,383.75 | $0 | $0 |
| 1,000 | 15 KiB/s | 39.813 | 484.393 | $360.79 | $4,391.26 | $23.78 | $293.27 |
| 1,000 | 30 KiB/s | 79.626 | 968.786 | $731.58 | $8,902.52 | $71.55 | $874.54 |

\*Conditional decimal unit assumptions above; rounding to 100 MB affects less than one cent here. Annual estimates use a non-leap year and monthly allowances, not 12 × a 30-day month. Every row exceeds DO's assumed quota even in February, so subtracting 12,000 GiB from annual transfer gives the same annual DO sum. Hetzner rows either stay below quota every month or exceed it every month.

The 1,000 CCU rows model economics only: the current player id range is **1–999**, so a single Instance cannot admit 1,000 players without a separately reviewed limit change. A measured per-player rate at 100 CCU must not be assumed constant at 999: entity density and replication fanout can change it.

## How to turn tests into reliable forecasts

The user selected a CAX11 game host and a separate CAX11 bot host first. Capture the original CAX11 build, profile before optimizing, and repeat the same scenarios after improvements. CCX13 is deferred until this phase is stabilized; compare the same final revision there afterward. Comparing CCX13 to CAX11 establishes practical host value; it cannot isolate ARM versus x86 because dedicated/shared CPU allocation and hardware also change. Compare original versus optimized CAX11 runs repeatedly, with identical Tick/Snapshot rates, population, seed, layout, movement, and combat load. ARM-only code generation should not inherently change bytes transmitted. The current isolated runs use dev-mode bots without an API host, so API authentication and persistence costs are excluded.

Measure server game-port outbound packet bytes, packet count, and payload bytes separately; include UDP/IP/ENet framing, acknowledgements and retransmissions in network measurements. Measure inbound separately and collect whole-interface TX/RX to expose other services' traffic. Reconcile with provider counters for a small external-client run. Bots in the same Hetzner network zone are useful for cheap repeated load tests, but their exempt traffic does **not** validate an internet-egress invoice. Preserve raw counters and workload metadata before deletion.

Report sustained outbound at 100 and 999 CCU across spread-out and crowded combat scenarios, plus successful player-seconds, disconnects, packet loss, and Tick deadline misses. Normalize by actual connected player-seconds rather than requested bots. Reject apparent bandwidth savings caused by missed Ticks or dropped players. Use scenario-specific measured rates in the formulas; record month/year transfer and cost alongside CPU/Tick results. Protocol/replication changes should be benchmarked separately from ARM optimizations so the cause of a saving remains clear.
