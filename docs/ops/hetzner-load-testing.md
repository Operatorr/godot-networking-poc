# Hetzner host selection for load testing

**Researched:** 2026-10-13. **Status:** two CAX11 hosts provisioned; three-bot remote smoke
passed. No capacity or latency sweep performed yet. One host runs the
authoritative **game server**, with the bot generator on the other.

## Recommendation

The user confirmed on 2026-10-13 that **CX23 is unavailable in every region**. Choose the
**CAX11 in Falkenstein shown in the supplied screenshot** for the cheapest useful starting
point among the available quoted options. It is a starting point for measurement, not
evidence that it can hold 500–1000 players. Compared with CPX02, CAX11 costs $0.50 less per
month and provides substantially more RAM and another vCPU. This is a cost-and-resource
recommendation, not a measured performance
ranking. [Plan specifications](https://www.hetzner.com/cloud/cost-optimized/),
[current published EU prices](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/).

One Omega Instance has a single 30 Hz Tick loop: it gets about **33.3 ms per Tick**.
More vCPUs help separate Instances and background work; they do not automatically speed up
one Instance. This follows the [server design](../server/design.md). Run the bots elsewhere
to keep generator CPU and network work out of the server measurement. The generator is also
currently single-threaded ([source](../../rust/load_test/src/main.rs)); a larger bot host
does not automatically make one swarm process use its extra cores.

## EU shortlist and quoted costs

USD, excluding VAT; monthly total includes one $0.60 Primary IPv4. CAX11 and CPX02 prices
come from the user's 2026-10-13 Hetzner Console screenshots. Other prices below come from
Hetzner's published 15 June 2026 new-order table. Always use the final account console quote
if it differs. No availability or exact CPU model is guaranteed by this table.

| Plan | Architecture / CPU allocation | vCPU / RAM / disk | Server monthly | With IPv4 | Server hourly | Use here |
| --- | --- | --- | --- | --- | --- | --- |
| CX23 | x86, shared Intel/AMD | 2 / 4 GB / 40 GB | $6.49 | $7.09 | $0.0104 | Unavailable in every region, confirmed by user |
| CAX11 | Arm64, shared Ampere | 2 / 4 GB / 40 GB | $6.99 | $7.59 | $0.0112 published; screenshot rounds to $0.011 | Recommended available budget starting point |
| CPX02 | x86, shared AMD | 1 / 1 GB / 20 GB | $7.49 | $8.09 | $0.012 shown | Small smoke-test candidate; poor starting budget for full stack |
| CAX21 | Arm64, shared Ampere | 4 / 8 GB / 80 GB | $12.49 | $13.09 | $0.0200 | Extra memory / multiple Instances; no automatic Tick speedup |
| CPX22 | x86, shared AMD | 2 / 4 GB / 80 GB | $22.99 | $23.59 | $0.0368 | Newer CPU generation comparison, after measuring baseline |
| CCX13 | x86, dedicated AMD vCPUs | 2 / 8 GB / 80 GB | $50.49 | $51.09 | $0.0809 | Brief controlled CPU benchmark, rather than permanent budget host |

Sources: [cost-optimized specifications](https://www.hetzner.com/cloud/cost-optimized/),
[regular-performance specifications](https://www.hetzner.com/cloud/regular-performance/),
[dedicated-vCPU specifications](https://www.hetzner.com/cloud/general-purpose/),
[June new-order prices](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
[IPv4 pricing](https://docs.hetzner.com/cloud/servers/primary-ips/overview/).
CPX02 launched on 6 October 2026; CPX12 (1 vCPU / 2 GB / 40 GB) also exists, but has no
account quote in the supplied screenshots. [Hetzner release notes](https://docs.hetzner.cloud/whats-new).

The public cost-optimized page currently displays unavailable entries, while the supplied
console shows a CAX11 selected. The user subsequently confirmed CX23 is unavailable in
every region. Availability changes and must be checked in the account's console at order
time. CX uses older Intel/AMD hardware and the customer cannot select which;
CPX uses newer AMD hardware. Neither statement establishes which is faster for Omega.
[Hetzner server FAQ](https://docs.hetzner.com/cloud/servers/faq/),
[server categories](https://docs.hetzner.com/cloud/servers/overview/).

## Arm64 suitability

**Arm64 is viable; being Arm64 does not establish that it is better for this game.**
Rust's Linux Arm64 target is Tier 1 with host tools and supports ordinary native builds.
[Rust target documentation](https://doc.rust-lang.org/rustc/platform-support/aarch64-unknown-linux-gnu.html).

Hetzner documents CAX as Ampere Altra. Ampere describes Altra as having single-threaded
cores and consistent frequency, useful characteristics for parallel independent workloads.
However, CAX is still a **shared VM plan**: Altra's physical core design does not reserve a
core for this VM or remove hypervisor contention. Dedicated CCX reserves CPU resources;
one dedicated vCPU represents a physical CPU thread, not an entire bare-metal server.
[Hetzner hardware](https://docs.hetzner.com/cloud/technical-details/faq/),
[Altra product brief](https://www.amperecomputing.com/briefs/ampere-altra-family-product-brief),
[shared/dedicated FAQ](https://docs.hetzner.com/cloud/servers/faq/).

Start with the ordinary release build. Later, profile the measured hotspots and compare an
appropriate CPU-targeted build against that baseline. Rust supports `-C target-cpu`, including
`native` for the build host; a native build on a Mac targets that Mac, not the Hetzner CPU.
There is no quantified optimization benefit yet. Preserve the shared simulation's f32/f64
operations and truncation contract; architecture-specific math changes require checking client
prediction parity across the actual client/server targets.
[Rust codegen documentation](https://doc.rust-lang.org/rustc/codegen-options/index.html#target-cpu),
[Omega numerics contract](../server/contract.md#numerics-policy-sim_core--protocol).

An Arm64 VM cannot rescale directly to an x86 plan such as CPX or CCX; that comparison requires
a new VM and a build for the target architecture. [Hetzner architecture restrictions](https://docs.hetzner.com/cloud/servers/faq/).

## Location, topology, and keeping the bill small

The three European locations share the same prices. Arm CAX is offered there, while Singapore
and the US require other plan families. EU plans include at least 20 TB traffic; entry regular
plans in Singapore include 0.5 TB. For inexpensive capacity testing choose an available EU
location. For human play testing from Taiwan, separately measure Singapore latency; capacity
results do not establish how responsive a distant EU host feels.
[Locations](https://docs.hetzner.com/cloud/general/locations/),
[regular plans and traffic](https://www.hetzner.com/cloud/regular-performance/).

The game host can run game Instances only and use the existing remote API, as described in
[multi-region topology](multi-region.md). That avoids putting PostgreSQL, Redis, and the Go
API into this benchmark host's resource budget. For a whole-stack deployment the repo's
[infrastructure guide](infrastructure.md) calls 2 vCPU / 4 GB the useful starting size and
1 vCPU / 1 GB a tight smoke-test floor. These are existing deployment guidelines, not a new
500–1000-player capacity claim.

Hetzner bills full rounded-up hours while the VM exists, capped at its monthly price; powering
off does not stop charges. Ten billed hours of CCX13 cost **$0.809 compute**, or **$0.819 with
ten IPv4 hours**, before VAT and any other resources. Retain test results before deleting the
temporary host, and also delete any chargeable Primary IPv4 that is no longer needed. IPv6 is
free, but saving $0.60/month is not a reason to assume the current end-to-end path supports an
IPv6-only host. [Billing FAQ](https://docs.hetzner.com/cloud/billing/faq/),
[Primary IP pricing](https://docs.hetzner.com/cloud/servers/primary-ips/overview/).

Only outgoing traffic counts toward traffic billing; incoming traffic and internal traffic
within a Hetzner network zone are free. Cross-zone traffic is treated as internet traffic.
Falkenstein, Nuremberg and Helsinki all belong to `eu-central`: moving a bot from
Falkenstein to Helsinki does not make its public-IP traffic count against the included
outgoing allowance. Use a client outside Hetzner or a Cloud server in another network
zone to independently check the provider's external-transfer meter. Evidence downloads
to the operator also produce billable external egress and must be accounted separately
from game-port traffic. [Network-zone locations](https://docs.hetzner.com/cloud/general/locations/),
[same-zone public-IP exemption](https://docs.hetzner.com/cloud/billing/faq/).
The included TB allowance is a billing quantity, not a guarantee of sustained packet rate
or bandwidth. [Billing FAQ](https://docs.hetzner.com/cloud/billing/faq/),
[location billing](https://docs.hetzner.com/cloud/general/locations/).

## What remains to measure

Record the commit/build, CPU model, region, scenario and bot count for every run. Watch Tick
duration and overruns, server CPU/steal time, memory/swap, traffic, RTT/loss, and achieved bot
input rate. Ramp from existing baseline scenarios toward the intended target only after each
step is stable; respect the configured player cap and the protocol's current player-id range.
Repeat comparable runs to expose shared-host variance, then use a short CCX comparison if
contention prevents a useful capacity conclusion. No result here proves that 1000 bots or
players fit any plan.

Current harness scenarios and interpretation live in the
[load-test README](../../rust/load_test/README.md); protocol limits and server authority live
in the [contract](../server/contract.md). The host choice is provisional until that evidence
exists.

## Setup for the selected game-server role

The user created **two CAX11 hosts in Falkenstein**, one game host and one bot generator.
Both run Ubuntu 26.04.1 LTS, aarch64 (Neoverse-N1), 2 vCPUs / 4 GB, and Rust 1.95.0.
CCX13 is deferred until the CAX11 load/latency tests and stabilization are complete; see
[Benchmark the stabilized CAX11 build on a later CCX13 host](https://github.com/Operatorr/godot-networking-poc/issues/34).
Connection details are recorded in the ignored `deployment/hetzner/access.local.json`.

There is **no existing API host**. The current benchmark therefore uses the server's
built-in unsigned **dev mode**, with host firewall rules restricting UDP 8081 to the
operator's public IP and the bot VPS. This measures an isolated Arena's sim, replication,
latency and transfer; accounts, signed-ticket auth, progression/persistence and the API
are outside these runs. No game/API signing secret is required. The SSH key still secures
administrative access; it is unrelated to gameplay session tickets.

The [load-test config](../../deployment/server_config.loadtest.json) preserves live Arena
network/gameplay tuning, with `max_players=999`, `region=local`, unsigned tickets allowed,
and `api_server_url=""`. The empty URL disables heartbeat and progression workers
([startup](../../rust/server/src/main.rs)). The current
[player allocator](../../rust/server/src/sim/player.rs) allows **999 concurrent players**;
a 1000th join tests capacity rejection, not CPU performance.

The [creation checklist](../../deployment/hetzner/README.md) and
[cloud-init file](../../deployment/hetzner/cloud-init.yaml) bootstrap `deploy`, SSH access,
build/measurement packages and the pinned Rust toolchain on both architectures. Both
hosts are checked out at commit `89348a21dcc3ce190aa851bb5f2cb49256097297`; build only the
role-specific binary, using the locked dependencies and existing release profile:

```bash
cd /home/deploy/omega-realm/rust
source "$HOME/.cargo/env"
cargo build --release --locked -j 2 -p omega-server     # game host
# On the separate bot host:
cargo build --release --locked -j 2 -p omega-load-test
```

The game config is installed at `/etc/omega-loadtest/arena.json`, with the game-only
[unit](../../deployment/hetzner/omega-loadtest-arena.service) installed as
`omega-loadtest-arena.service`. It has no dependency on an API/database service.
Metrics remain loopback-only on `127.0.0.1:9100`. The bot host has only inbound SSH from
the operator, while the game host also allows UDP 8081 from the operator and bot host.
A Hetzner Cloud Firewall can impose an additional gate: its UDP sources must also include
the bot host's IPv4 `/32`; SSH cannot modify that provider firewall without API access.

On the **bot** host, the unsigned smoke command is:

```bash
cd /home/deploy/omega-realm/rust
source "$HOME/.cargo/env"
env -u OMEGA_TICKET_API -u OMEGA_LOAD_TEST_SECRET \
  ./target/release/omega-load-test --server GAME_IPV4:8081 \
  --bots 3 --behavior movement --duration 30 --assertions strict \
  --output /home/deploy/omega-results/smoke.json
```

Replace `GAME_IPV4` using the local access record. Verify all three bots connect and receive
Snapshots, no decode/send errors occur, and server metrics show the corresponding players.
If a pre-existing ticket-related environment variable is present, removing it for this
command keeps the harness on the intended dev path. **Do not use `--live`**: it targets
the former live API/Arena and requires signed-ticket credentials.

Read metrics with an SSH tunnel from the operator computer:

```bash
ssh -i deployment/hetzner/ssh/omega_loadtest_ed25519 \
  -L 19100:127.0.0.1:9100 deploy@GAME_IPV4
# In a second local terminal:
curl -fsS http://127.0.0.1:19100/metrics
```

Preserve reports locally before deleting hosts. The detailed workload and controlled-
latency sweep belongs to
[Define the new load-test matrix](https://github.com/Operatorr/godot-networking-poc/issues/30),
then [Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31).
The current bot harness is single-threaded, so generator saturation must be ruled out
before attributing a breaking point to the game server.

## Proposed comparison and priority metrics

### Generator location and a one-day budget

The user clarified that the planned bot generator is their **personal computer**. This
keeps the generator separate from the game host and is suitable for initial smoke and
100-player runs if the computer and internet connection sustain the offered load. At an
illustrative 15 KiB/s outbound per player, the generator receives about 12.3 Mbit/s at
100 players, or 122.9 Mbit/s in the 1000-player financial model, before other traffic.
Use a wired connection, keep the computer awake, and check actual input cadence, CPU,
packet loss and receive throughput. A home's router, access link, or the swarm's one
polling thread can become the limiting resource; a VPS does not fix that thread limit
automatically. [Swarm implementation](../../rust/load_test/src/main.rs).

For repeated 500–999-player capacity comparisons, prefer a temporary independent bot
VPS near the two EU game hosts, using the same generator allocation for both. This
reduces variation from the home link and long-distance internet path. Confirm generator
headroom before treating a run as a server-capacity result; sizing and any necessary
harness changes remain part of the load-test matrix. Keep a smaller personal-computer
run to observe actual external-client behavior. Same-zone Hetzner bot traffic is exempt
from transfer charges, so raw transferred bytes still need an external-egress forecast.

The **current purchased pair of CAX11 hosts** costs about **$0.59 for 24 billed hours**,
including one IPv4 each, before VAT and transfer overage (2 × 24 × $0.0122).
For the later comparison, **24 billed hours** of CCX13 and CAX11 cost approximately
**$1.97 + $0.29 = $2.26 total**, including one Primary IPv4 each, before VAT and transfer
overage. This is an example using $0.0809/h and $0.0112/h compute plus $0.0010/h per IPv4.
A third CCX13 used as a generator for the same period adds about $1.97, bringing the
three-host total to **$4.22**. These are existence hours, not benchmark runtime: powered-off
servers still bill. Delete servers and unused paid IPs after exporting results. Rounded
hours, the actual account quote, and any other retained resources determine the invoice.
[Compute rates](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
[hourly billing](https://docs.hetzner.com/cloud/billing/faq/),
[IPv4 hourly rate](https://docs.hetzner.com/cloud/servers/primary-ips/overview/).

### Comparison protocol

The current user-selected sequence is **CAX11 game host + CAX11 bot host first**, completing
load/controlled-latency tests and chosen improvements, then a **later CCX13 game host** to
compare against the stabilized CAX11 build. That supersedes the earlier suggestion to
start with CCX13. See the [deferred comparison task](https://github.com/Operatorr/godot-networking-poc/issues/34).
Save results before deleting temporary hosts. The primary economic metric is **external outbound transfer**, because
their earlier approximately $7 DigitalOcean host reportedly used only 20–30% CPU while
transfer was the costly resource. That CPU observation is user-reported and does not yet
establish CPU headroom at 500–999 players.

Capture the CAX11 baseline before optimizing. For the later host comparison, keep the commit, compiler,
release settings, scenario, seed, bot input rate, Tick/Snapshot rates, AoI, and budgets
identical. Use the same generator and network topology, verify the generator sustains the
offered load, and separate warmup/join traffic from steady gameplay. Repeat runs to expose
variance. CCX13 versus CAX11 is a comparison of two purchasable hosting choices: CPU family,
shared/dedicated allocation, and memory differ, so it cannot isolate architecture alone.
For CAX11 optimization, compare current versus optimized builds on the same allocation;
retain baseline reruns so a different shared-host load is not credited to code changes.

Capture server egress/ingress bytes and packet rates, application bytes by message type,
process and per-core CPU, steal time, RSS/swap, Tick duration percentiles, achieved input
rate, authenticated player count, RTT/loss and replication deferrals. Preserve the raw
time series, run metadata and reports before deleting the hosts and unused billed IPv4s.

**Billing measurement:** the current harness's `bandwidth_per_player_kbps` divides combined
bot upload + download by 1024, so its unit is KiB/s, despite the label. It counts application
payloads, excluding ENet/UDP/IP overhead, and its sampling includes startup inconsistencies.
The server's wire `total_bytes_sent` also wraps at 2^32. These are useful diagnostic fields,
not authoritative billable egress totals. Use public-interface byte-counter deltas over a
defined steady interval (64-bit counters), distinguish unrelated SSH/build/metrics traffic,
and reconcile with provider transfer accounting for actual internet traffic.
[Harness aggregation](../../rust/load_test/src/metrics.rs),
[server payload counters](../../rust/server/src/net/metrics.rs).

Report outbound bytes per authenticated player-second as well as total bytes/sec. Calculate
cost separately at each tested load/scenario: higher density can increase bytes per player,
so a 50-player measurement cannot safely be multiplied to predict 999-player replication.
Hetzner exempts traffic between Cloud servers in the same network zone even over public
IPs; a free internal benchmark must still measure traffic volume and model public internet
egress for real players. [Hetzner billing](https://docs.hetzner.com/cloud/billing/faq/).

CPU optimization alone normally preserves the wire format and send rate, and therefore
does not inherently reduce egress. For transfer savings, separately evaluate replication
changes: projectile updates, event AoI, unchanged-state suppression, and Snapshot rate/LOD.
Keep gameplay and delivery quality comparable; shedding updates due to overload is not a
successful bandwidth optimization. The existing research identifies projectile replication
and unfiltered broadcast events as contributors, but savings are not yet measured.
[Wire-cost research](https://github.com/Operatorr/godot-networking-poc/blob/research/omega-wire-format-and-cost/docs/research/omega-wire-format-and-cost.md).

Detailed cost formulas and hypothetical 100/1000-CCU forecasts are in
[the egress cost note](load-test-egress-costs.md). The 1000-player figure is a financial
scenario; executable runs currently stop at 999. Detailed run choices remain with
[Define the new load-test matrix](https://github.com/Operatorr/godot-networking-poc/issues/30).

## Completion record

[Set up a Hetzner server for load testing](https://github.com/Operatorr/godot-networking-poc/issues/29)
is ready for resolution: both hosts were supplied by the user, provisioned over SSH, and
the separate bot host passed a three-bot / 30-second dev-mode smoke run. Connection/build
provenance is in ignored `deployment/hetzner/access.local.json`; raw smoke JSON/log and
server metrics/service state were copied to ignored
`deployment/hetzner/results/smoke-20261013/`. The operator controls the Hetzner lifecycle;
export later results before deleting hosts and unused paid IPv4s. These smoke artifacts
verify setup only and do not establish high-population capacity or monthly billable egress.
