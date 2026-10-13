# CAX11 load-test campaign — 2026-10-13

**Status: measurement preflight passed; scored matrix running.**
This report resolves [Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31)
only when the agreed matrix and its permitted failure truncations are recorded. The
[matrix resolution](https://github.com/Operatorr/godot-networking-poc/issues/30#issuecomment-6145030523)
is canonical. Five-minute steady windows follow the excluded join ramp and 60-second
global warmup. Short preflights and overhead controls are explicitly unscored.

## Provenance and scope

- Separate CAX11 game and bot hosts, Falkenstein, same Hetzner `eu-central` network zone.
  Ubuntu 26.04.1 LTS, Linux 7.0.0-30-generic, aarch64/Neoverse-N1, 2 vCPUs and 4 GB each.
- Untouched handoff revision: `89348a21dcc3ce190aa851bb5f2cb49256097297`.
  Original game binary SHA-256 `5eeb9d511549f23e84769ca1e937dfa99e08592c184f64ccfd56a24f3b09d1c1`;
  bot binary `1523ba6df984ad4758f00f4ea7ac2a135422285a23309610c1297df303b2c494`;
  config `631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6`.
  Copies remain on both hosts and the original checkouts are preserved.
- First measurement revision: `05cf4f3`; recorded separately from the original build.
  Builds use Rust 1.95.0, locked dependencies, ordinary release settings and thin LTO.
  A subsequent measurement revision supplies actual deferred scheduler waiting, after
  preflight exposed misleading semantics in the existing queue-age diagnostic.
  Scored server build: revision `642c1472232a5d3681654ab2965ba09db12ad69d`,
  SHA-256 `80c94e7071887212594285b90960b41f11a97438ad2b2b0b8e15278e210e41b1`.
  Bot build SHA-256 `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`.
- Isolated unsigned dev mode, no API or persistence, source-restricted UDP 8081 and
  loopback-only Prometheus. No CCX13 provisioning or historical-report retrieval.
- Bots use 30 inputs/s, seed 30, 100 ms stagger, difficulty 1.0, default advertised byte
  budget and Warrior/Rogue/Mage round-robin. The server seeds from entropy; these are
  comparable workloads, not deterministic world replays.

## Initial measurement validation

The original 3-bot control sustained 30 Tick/s. Four original 50-bot movement controls,
ordered light/full/full/light, all sustained 30 Tick/s. Their matched mean Tick-work
observations were 2.602, 2.823, 2.714 and 2.657 ms. Light/full averages were 2.630/2.768 ms;
whole-host CPU averages were 8.74/11.06% of the two-core allocation. Workload and shared-host
variation remain visible; these differences are an observed collection envelope, not an
isolated causal estimate. Those full controls used 128-byte packet capture plus host
collection; later controls additionally validate the complete-datagram flow recorder.

The first instrumented 50-bot preflight sustained 30 Tick/s and 30 inputs/s for every bot,
with Tick-work p99 4.446 ms. It recorded zero capture drops and parser errors. Outbound
game-flow transfer was 443,071 bytes/s and 8,861 bytes/authenticated player-second during
its **60-second, unscored** observation. Do not use this short 50-player rate as validated
100/1000-CCU economics or capacity evidence.

The [final measurement gate](measurement-preflight-resolution.json) passed native 50-bot
collection and selective impairment checks. With the same final binary and full host/flow
collection, recording-on/off mean Tick work was 3.149/2.979 ms; server CPU was 15.47/14.82%
of one core, generator CPU 18.02/16.85%. The direct raw observer averaged 0.010 ms/Tick.
These include different entropy-seeded worlds and shared-host noise. The final native
recording-on check sustained 30 Tick/s, per-bot inputs 29.984–30.000/s, p99 work 4.424 ms,
and zero actual deferred backlog. All 90,000 scheduled Snapshots were enqueued and first
transmitted during its 60-second unscored window; all four capture paths were clean.

The 3-bot mirrored combined-profile check measured 49.82/50.86 ms average one-way delay
and 1.18/1.14% loss outbound/inbound around configured 50 ms ±20 ms normal jitter and
1% independent loss each direction. Its short 30-second interval is measurement validation,
not a scored robustness result. Pre-qdisc mirrors are necessary: post-qdisc interface
captures alone omit injected drops and delay. The earlier combined-profile attempt is
retained as collector-incomplete, even though RTT and qdisc counters confirmed shaping.

## Collection and interpretation

Each bundle includes redacted original bot reports/logs, timestamped Prometheus exposition
and host observations, exact counter endpoints, config/build provenance, raw Tick work and
bot telemetry, plus derived steady-window JSON. Packet evidence is retained separately,
off the temporary hosts, in ignored `deployment/hetzner/results/campaign-20261013/`;
each bundle's `retained-evidence.json` identifies original archives and SHA-256 checksums.
Connection addresses, access records and credentials are not published.

The full-datagram recorder preserves 128-byte packet headers and binary observations of
every ENet command, UDP payload fingerprints, lengths and timestamps. This enables
directional packet matching, reliable payload retry accounting and observed unacknowledged
reliable data commands; it does not inspect unsent private ENet queues. Application queue
bytes, emitted/received reliable data and delivery freshness provide complementary evidence.
Capture drops and parser errors invalidate packet accounting. Generator validity checks
both accepted input enqueues and pre-qdisc input commands on every bot socket against
29.7 Hz, plus bot-host UDP error counters. Game-host UDP receive/send-buffer errors fail
the native sustainability gate; raw socket tables retain evidence for attributing any
positive whole-host counter. The first clustered run's game UDP 8081 socket accumulated
8 receive drops and the host 61 send-buffer errors, so its earlier timing-only candidate
classification is corrected to a valid failing observation. This does not alter the run
or workload. [Needed fixes](needed-fixes.md) keeps the investigation separate.

Primary economics use game-port outbound IPv4 IP bytes (including ENet, UDP/IP and retries)
from post-qdisc packet capture over integrated authoritative authenticated player-seconds.
The nftables output counter measures pre-qdisc offered bytes, including injected drops;
pre-qdisc mirroring supplies directional delay/loss evidence. Interface bytes and unrelated
SSH/collector traffic are separate. Counter reads have timestamp brackets; small boundary
differences are reported rather than hidden. Packet matching includes a receiver context
outside the steady window to avoid counting delayed boundary-crossing packets as loss.

The Tick exporter is a **summary**. Preserved quantiles are exporter estimates, not an exact
whole-run distribution; sum/count deltas yield a mean. Exact Tick-work percentiles use raw
observations. Work timing excludes between-Tick ENet dispatch and the raw observer; wall-clock
Tick cadence, scheduling lag and CPU cover their effect on sustainability. Old harness pass/fail
and lifetime bandwidth remain diagnostic and separate from campaign validity gates.

## Current results and forecast status

[Summary CSV](summary.csv) keeps every scored row's validity, authenticated/alive
player-seconds, outbound IP rate, conditional economics and delivery/server/generator
quality together. [Repeat spread](repeat-spread.json) includes all rows and marks groups
incomplete until three repeats are present; individual successful runs are candidates,
not an established capacity rung. [Attempt inventory](attempt-inventory.json) also retains
short preflights, setup failures and analysis errors outside the scored-row table.

Measured 100-player and validated 999-player economics remain pending those matrix cells.
The following **[MEASURE] sensitivities are hypothetical fixed rates**, not extrapolations
from the 3- or 50-player runs. They assume continuous use and do not demonstrate that one
Instance can support 1000 CCU. Exact bytes and all calendar months are in
[the sensitivity artifact](unmeasured-cost-sensitivity.json).

| CCU model | Hypothetical KiB/player/s | 30-day TB / TiB | 365-day TB / TiB | Decimal USD 30-day / year | Binary sensitivity USD 30-day / year |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 5 | 1.327 / 1.207 | 16.146 / 14.685 | $7.59 / $91.08 | $7.59 / $91.08 |
| 100 | 15 | 3.981 / 3.621 | 48.439 / 44.055 | $7.59 / $91.08 | $7.59 / $91.08 |
| 100 | 30 | 7.963 / 7.242 | 96.879 / 88.111 | $7.59 / $91.08 | $7.59 / $91.08 |
| 1000 | 5 | 13.271 / 12.070 | 161.464 / 146.851 | $7.59 / $91.08 | $7.59 / $91.08 |
| 1000 | 15 | 39.813 / 36.210 | 484.393 / 440.553 | $31.37 / $384.35 | $27.04 / $331.74 |
| 1000 | 30 | 79.626 / 72.420 | 968.786 / 881.106 | $79.14 / $965.62 | $70.49 / $860.41 |

Both cost columns are conditional game-host production totals before tax, including
$6.99 compute and assumed $0.60 Primary IPv4. Decimal uses 20 TB/month and $1.20/excess TB
rounded to 100 MB; binary sensitivity uses 20 TiB/month and $1.20/excess TiB rounded to
100 MiB. Excess rate, exact account units and IPv4 quote remain unverified. Calendar
2027 uses 365 days and twelve independently renewed allowances, so yearly costs are not
12 times the 30-day example. The retained test generator adds a separate host base.

## Billing evidence

The user's CAX11 bot-host overview screenshot confirms **$6.99/month compute** and a nominal
**20 TB included outgoing transfer**, displaying `0/20 TB` on 2026-10-13. It does not expose
an exact-byte allowance or excess rate. A later game-host tooltip at 21:39:34 Taipei
shows **0.00008464 TB**, while its main display remains `0/20 TB`. Under decimal units
this is 84,640,000 bytes, with a displayed last-place step of 10,000 bytes.
[The timestamped reading](game-provider-counter-before.json) precedes the external-client
check; intervening SSH/archive egress and unverified provider reporting delay prevent
treating it as an immediate before-run counter. The screenshot is retained privately with a checksum because it contains connection
details. The quoted production base remains conditionally $6.99 + $0.60 IPv4 = $7.59/month,
or $91.08/year, before tax/overage. The retained two-host test pair is separate: $15.18/month,
$182.16/year before tax/overage.

Hetzner bills outgoing internet traffic; same-zone Cloud traffic over public IPs is exempt.
Excess traffic is rounded to 100 MB increments. Its example relates 0.0001 TB to 100 MB,
supporting decimal units as the preferred interpretation, while account-specific exact units
and the assumed $1.20/excess TB remain conditional. Forecasts will include the agreed binary
sensitivity, a 30-day illustrative month and all 12 months of non-leap 2027 with separately
renewing allowances. [Hetzner billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).

## External accounting check

Three combat bots on the operator Mac used the real Taiwan–Falkenstein internet path,
with the CAX11 bot host idle. The matched five-minute window was 13:55:26.700671–
14:00:26.700671 UTC. All three stayed connected and achieved 29.9999 inputs/s, with
zero missed schedules, send/decode failures or game capture drops. Mean/p95 RTT was
247.64/256 ms. This checks small-flow accounting, not high-CCU internet capacity.

[Recorded observations](external-combat-3-r1/steady.json) contain **4,844,642 outbound
IPv4 IP bytes**, 30,048 outbound datagrams, 900 authenticated player-seconds and
845.53 alive player-seconds: **16,148.81 bytes/s**, or **5,382.94 bytes/player-second**.
The separately bracketed nftables counter differs by only 38 bytes. Interface TX was
5,265,776 bytes; 420,672 bytes correspond to 14-byte Ethernet headers on the captured
game datagrams, leaving 462 bytes of other/boundary traffic. These are distinct accounting
layers; provider billing-layer semantics remain conditional.

The external generator uses a passive libc socket observer because local privileged
NIC capture was unavailable. Packet payloads, lengths and successful send/receive times
are retained; its IPv4/Ethernet envelope is synthetic. Game-host packet lengths and
64-bit flow/interface counters determine outbound transfer. Observed unmatched rates
were 0.0133% outbound and 0.0424% inbound; operator NIC/kernel drops were not independently
measured. One-way socket/capture delays carry the recorded ±35.746 ms operator clock
uncertainty, so RTT is the stronger external latency measurement.

[Fresh pre-scored-window account readings](provider-counters-external-before.json),
recorded during the excluded warmup, were
0.00008464 TB on the game host and 0.00013999 TB on the bot host. The game display was
unchanged from the earlier reading despite intervening archive downloads. [The post-check game reading](provider-counters-external-after.json) remains
0.00008464 TB. Thus invoice reconciliation remains pending provider update/account
billing semantics; the unchanged display does not mean zero measured external egress.
Provider reporting delay, UI refresh/cache status and unrelated archive egress remain
explicit.

## Failures and separate work

All failed/invalid attempts remain evidence. The first original three-bot setup attempt failed
before swarm startup because the collector's nftables declaration lacked chain separators; it
was corrected and rerun. An analysis controller initially read an archive while SCP was still
writing it; the retry preserves the run, and downloads now use atomic completion with a remote
checksum check. Neither attempt is a scored capacity result.

The first scored combat run's analysis stopped on absent `VmSwap` at the exact bot
endpoint: its process was already a zombie. The original traceback and raw endpoint
remain retained. Cgroup and zombie CPU totals, exact counter boundaries and bot end
telemetry are complete, so this was an analyzer failure rather than invalid workload
collection. Analysis now explicitly reports endpoint resident/swap memory unavailable
for exited processes and supplies sampled peak RSS from the retained 1 Hz host series.
Re-analysis validated the five-minute run without repeating or replacing its evidence.

The first scored strategy attempt is retained as **collector-invalid**. One unrelated
104-byte IPv4 Internet probe reached the bot host's UDP 8081 port and entered the
port-only capture; parsing that payload as ENet produced one recorder error. Bot codec
errors, capture drops and kernel socket errors were zero, but the accounting scope was
incorrect. Offline peer filtering excludes exactly that one packet and preserves all
1,819,123 test-peer packet headers. Capture and nftables counters now require the test
peer IPv4 address as well as the game port. Native 3-bot, controlled 3-bot and native
50-bot checks validate the correction before a separately named scored retry. The
original attempt remains in raw evidence and the summary; replacement selection is
explicit and applies only to collector-invalid attempts, never valid server/generator
failures.

[Needed fixes](needed-fixes.md) records baseline diagnostic/harness issues without optimizing
the baseline. A five-minute campaign does not establish long-term stability; 1000 CCU is a
financial model, while the executable Instance admission ceiling remains 999.
