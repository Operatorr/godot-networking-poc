# Performance budgets — targets vs measured

**Status:** Reference (verified 2026-06-14 against `rust/`). Reconciled against the Rust
`omega-server` (single-threaded synchronous 30 Hz tick over `rusty_enet` `=0.4.0`); the GDScript
headless server is retired and being deleted — do not cite `client/scripts/server/*.gd` as live code.

> A single table of the numbers everything else is judged against. Three sources disagree —
> the **POC success criteria** ([`../ops/architecture.md`](../ops/architecture.md)), the **engineering
> budgets** ([`../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md)),
> and **what the code actually does**. This doc reconciles them and flags the drift so an agent
> tuning the netcode picks the right target. Numbers only; mechanism lives in the sibling docs and
> in [`../server/contract.md`](../server/contract.md) (the as-built wire spec).

## How to read this

- **POC target** — the release gate from `ops/architecture.md` "Success Criteria"
  (`docs/ops/architecture.md` §POC Goals & Success Criteria). That file's own preamble flags it has
  drifted from the code (it still lists a "≥20 Hz" tick gate; the server runs 30 Hz).
- **Eng budget** — the tighter engineering numbers in the CODEX plan's "Performance Targets"
  (`plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`).
- **Load-test gate** — the threshold the bot swarm actually asserts on, from
  `rust/load_test/src/metrics.rs` (`SERVER_FPS_MIN`, `LATENCY_*_MAX_MS`, `BANDWIDTH_PER_PLAYER_MAX_KBPS`,
  `PACKET_LOSS_MAX_PCT`, `CRASH_RATE_MAX_PCT`). This is the gate that runs in CI/regression.
- **Code today** — the value actually compiled/configured in `rust/`, with a module-path cite.
- **Gap** — what measurement is missing, or where code contradicts a target. "—" means the code
  value is a configured constant, not a load-tested measurement; nothing here is a *measured*
  number at 500–1000 players yet (no captured `docs/PERFORMANCE_NOTES.md` snapshot exists).

## The budget table

| Metric | POC target | Eng budget | Load-test gate | Code today | Gap |
| --- | --- | --- | --- | --- | --- |
| **Tick rate** (sim) | ≥20 Hz under load | ≥30 Hz sustained | ≥30 Hz (`SERVER_FPS_MIN`, `rust/load_test/src/metrics.rs`) | **30 Hz** — `SERVER_TICK_RATE` (`rust/sim_core/src/constants.rs`), single synchronous tick loop in `rust/server/src/main.rs` over `rusty_enet` | Code beats the 20 Hz POC floor; matches eng + the load-test gate. No captured number at scale yet; 60 Hz trial gated (perf-notes). |
| **Snapshot rate** (Snapshot send) | not specified separately | 20 Hz default | — (gate is on tick rate, not snapshot rate) | **30 Hz LIVE** — `snapshot_rate_hz=30` in `deployment/server_config.{arena,sanctuary}.json`; `snapshot_rate_hz_raw=0` default ⇒ tick-rate fallback (`Config::snapshot_rate_hz`, `rust/server/src/config.rs`) | Matches the 30 Hz tick. The 30-vs-60 tick/snapshot trial is gated in [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) (results PENDING). |
| **Tick time, avg** | <50 ms frame time | <8 ms at target load | reported, not asserted (`server_avg_tick_time_ms`, `rust/load_test/src/metrics.rs`) | — `avg_tick_time_ms_x100` over last 30 ticks (`MetricsCollector::build_packet`, `rust/server/src/metrics.rs`); also a Prometheus `tick_duration_ms` histogram + `avg_tick_time_ms` gauge | Measured, not captured at scale. POC's 50 ms is 6× looser than eng's 8 ms. Load test prints avg/max but does not gate on either. |
| **Tick time, p95** | (none) | <16 ms at target load | not asserted | **not in the wire packet** — only avg + max in `ServerMetrics`; a full `tick_duration_ms` **histogram** does exist in Prometheus (`rust/server/src/metrics.rs`), so p50/p95/p99 are scrapeable there even though they never hit the wire | No percentile on the `SERVER_METRICS` wire / load-test report; query Prometheus for them. No over-budget tick count. |
| **Tick time, max** | (none) | <25 ms outside startup | reported, not asserted (`server_max_tick_time_ms`) | — `max_tick_time_ms_x100` over the last 30 ticks (`rust/server/src/metrics.rs`) | 30-tick window only (`METRICS_SAMPLE_SIZE`); transient spikes outside it are lost from the wire field (the Prometheus histogram still catches them). |
| **Bandwidth / player** | **<2 KB/s** | <5 KB/s | **<5 KB/s** (`BANDWIDTH_PER_PLAYER_MAX_KBPS`, asserted) | — per-peer **byte budget** derived from the client's advertised `bandwidth_budget_bps` (in `ConnectAuth`): `clamp(advertised_bps / snapshot_rate, 256, max_snapshot_bytes)` (`World::handle_connect_auth`, `rust/server/src/world.rs`; floor `MIN_SNAPSHOT_FLOOR=256`, ceiling `max_snapshot_bytes=1200`). At the 1200 B cap × 30 Hz that is **36 KB/s** before AoI/delta culling; measured avg is `avg_bandwidth_per_client` (`rust/server/src/metrics.rs`). | **Drift:** POC table says 2 KB/s; eng + the load-test gate align on **5 KB/s** — the gate is the one that runs. |
| **Latency p95** | <150 ms same-region | <150 ms (avg <100) | **<150 ms p95 + <100 ms avg** (`LATENCY_P95_MAX_MS` / `LATENCY_AVG_MAX_MS`, asserted) | **measured client-side** by the swarm as **ENet-native RTT** (`rust/load_test/src/metrics.rs`); no server-side RTT histogram (the app HEARTBEAT echo died with the WebSocket protocol — clock sync now rides `Snapshot.server_ms`) | Aligned target; latency is gated, but only from the load-test client. No server-side per-peer RTT distribution. |
| **Packet loss** | (none) | (none) | **<2 %** (`PACKET_LOSS_MAX_PCT`, asserted) | **measured client-side** as ENet's mean loss ratio (`enet_packet_loss`, `rust/load_test/src/metrics.rs`) — replaced the old snapshot-tick-gap estimate | Gated by the swarm; no server-side counterpart. |
| **Crash rate** | (none) | (none) | **<5 %** (`CRASH_RATE_MAX_PCT`, asserted) | bots that never reached Running or were dropped unexpectedly, over all bots (`Aggregated::crash_rate_pct`, `rust/load_test/src/metrics.rs`) | Lumps connect-time timeouts with mid-run drops (documented bias in the source). |
| **CPU / player** | **<0.5%** vs **<1%** | (via tick-time budget) | not measured | **not measured** — no per-player CPU attribution; inferred only from tick time | **Drift:** POC table says 0.5%, the old per-player-cost table said 1%. No CPU/player metric exists. |
| **Memory / player** | <5 MB | (none) | not measured | **not measured** — no heap/player metric | No mem-per-player instrumentation. |
| **Max players** | 500–1000 / server | (release gate) | swarm `--bots N` drives it; no in-binary cap asserted | **`max_players` = 100** (`Config` default + `deployment/server_config.{arena,sanctuary}.json`, `rust/server/src/config.rs`) | Shipped cap is 100; the 500–1000 goal is unproven. The old u8 entity-count wire cap (255/packet) is **gone** — `entity_count` is `u16` (`Snapshot` header, `../server/contract.md`; `ServerMetrics.entity_count`, `rust/server/src/metrics.rs`). |
| **Render delay** (remote) | (none) | ~100 ms suggested | — | **66.7 ms** — 2 ticks @30 Hz (`REMOTE_ENTITY_RENDER_DELAY_TICKS=2`, `rust/sim_core/src/constants.rs`) | Below the ~100 ms the plan argues for, but with snapshot rate == tick rate (33.3 ms interval) 2 ticks absorbs ~2 missed snapshots. |

## Doc drift, called out explicitly

Numbers stated inconsistently across the canonical docs. Use the **Code today** / **Load-test gate**
columns as ground truth; treat the others as aspirational and stale:

1. **Tick rate — 20 Hz vs 30 Hz.** `ops/architecture.md` gates at "≥20 Hz". The code runs **30 Hz**
   (`SERVER_TICK_RATE`, `rust/sim_core/src/constants.rs`) and the load-test gate is **≥30 Hz**
   (`SERVER_FPS_MIN`). The 20 Hz figure predates the 30 Hz decision; it is a floor, not the target.
   `ops/architecture.md`'s own preamble already flags this drift.
2. **Snapshot rate — aligned at 30 Hz.** `snapshot_rate_hz_raw` defaults to `0` (= match tick = 30 Hz)
   and the live configs set it to **30**. The server sends Snapshots at **30 Hz (33.3 ms)**, matching
   the tick — the old 20-vs-30 drift is resolved.
3. **Bandwidth — 2 vs 5 KB/s.** The POC success table says "<2 KB/s"; the CODEX plan and the
   **load-test gate that actually runs** use **5 KB/s** (`BANDWIDTH_PER_PLAYER_MAX_KBPS`). The 2 KB/s
   figure is the optimistic theoretical-minimum narrative; 5 KB/s is the enforced working budget.
4. **CPU/player — 0.5% vs 1%.** The POC table says "<0.5% per player"; the older per-player-cost
   table said "<1% per player". Neither is measured.

## What the server's MetricsCollector measures today

`MetricsCollector` (`rust/server/src/metrics.rs`) builds the **`ServerMetrics` packet at 1 Hz** (type 68,
ch1 reliable — see [`../server/contract.md`](../server/contract.md)) and mirrors a subset into
Prometheus gauges/histograms exported on `127.0.0.1:<metrics_port>` (arena `:9100`, sanctuary `:9101`,
loopback-only, scraped over an SSH tunnel):

| Field (wire) | Source | Notes |
| --- | --- | --- |
| `avg_tick_time_ms_x100` / `max_tick_time_ms_x100` | last 30 ticks (`METRICS_SAMPLE_SIZE`) | avg + max only on the wire; `tick_duration_ms` **histogram** in Prometheus gives true p50/p95/p99. Saturating ×100 encode (deliberate u16-wrap fix). |
| `player_count` / `entity_count` | per build (`build_packet`) | `u16` each (the old u8 entity cap is gone); `entity_count` excludes players, for GDScript parity. |
| `total_bytes_sent` / `total_bytes_received` | `record_sent` / `record_received` | cumulative `u32` (wraps at 4 GB on the wire). |
| `avg_bandwidth_per_client` | per-peer byte delta ÷ elapsed ÷ peers | a **rate** (bytes/sec); avg across peers, not a distribution. |
| `sched_entities_deferred` / `sched_max_queue_age_ticks` / `sched_peers_at_budget_pct` / `sched_peers_evaluated` / `sched_snapshot_overflow` | `broadcast::TickDiagnostics` (`rust/server/src/broadcast.rs`) | the byte-budget scheduler diagnostics — on the `SERVER_METRICS` wire and re-exported to the client HUD. |

Prometheus also exports `players_online`, `entities`, `avg_tick_time_ms`,
`avg_bandwidth_per_client_bytes`, and `snapshot_entities_deferred` gauges plus the `tick_duration_ms`
histogram (`MetricsCollector::record_tick_time` / `build_packet`).

## The byte-budget scheduler

The per-snapshot byte budget is the thing that keeps ch0 datagrams under the MTU and bounds bandwidth.
It is enforced by the priority scheduler in `rust/server/src/broadcast.rs`
(`BroadcastService` / `schedule`):

- Each peer gets a per-tick byte budget = `clamp(advertised_bandwidth_bps / snapshot_rate, 256, 1200)`,
  derived at join from the client's `ConnectAuth.bandwidth_budget_bps` (`World::handle_connect_auth`,
  `rust/server/src/world.rs`; defaults `default/min/max_client_bandwidth_bps` = 120k/24k/200k bps in
  `rust/server/src/config.rs`).
- Entity records are admitted greedily in priority order; pinned items (the player's own entity)
  bypass the budget; smaller items can still fit after a larger one is rejected (no early break).
- **Baselines are exempt** from the budget — they ride ch1 reliable and may exceed the MTU
  (fragmentation is fine there). The server only emits deltas against an **acked** baseline, so no
  delta can reference a baseline the client doesn't hold. Baseline interval 100 ticks, resend 30 ticks
  (`DELTA_FULL_STATE_INTERVAL`, `rust/server/src/broadcast.rs`; see [`../server/contract.md`](../server/contract.md)).
- Diagnostics (`entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct`,
  `peers_evaluated`, `snapshot_count_overflow`) are populated per tick and ride the `SERVER_METRICS`
  packet → load-test report + client HUD, so deferral / queue-age / peers-at-budget are observable at load.

## What the load test measures and gates

`rust/load_test/src/metrics.rs` aggregates per-bot stats and evaluates the POC success criteria
(`evaluate_success`). It reports both **client-estimated** and **server-reported** figures:

- **Client-side, gated:** avg/p95 latency (ENet RTT), packet loss (ENet mean), crash rate,
  bandwidth/player, estimated tick rate. These six are the pass/fail criteria.
- **Client-side, reported:** p99 latency, min/max latency, decode failures, send failures, bot panics,
  max observed entity distance (AoI-cull assertion input).
- **Server-reported (echoed from the latest `ServerMetrics` packet):** avg/max tick time, player count,
  entity count, total bytes out, avg bandwidth/client. Printed but **not** gated.

The estimated tick rate is `(tick_max - tick_min) / duration` and is a mild **under-count** (bias noted
in source); the server-reported `avg_tick_time_ms` is the authoritative figure, this is a sanity cross-check.

## Still missing

- Tick-time **percentiles** on the wire / in the load-test report (they exist only in the Prometheus
  `tick_duration_ms` histogram) and an over-budget tick count.
- Per-client send detail: entities considered vs sent vs deferred-by-budget vs zero-delta-skipped.
- Delta effectiveness (baseline/delta/full-state/position-only counts).
- Server-side **latency** distribution, **CPU/player**, **mem/player**.
- Captured load-run numbers at 500–1000 players (every "not measured" / "—" row is still a configured
  constant, not a measurement — including the gated 30-vs-60 tick trial, whose protocol is in
  [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md), results PENDING).

## The eight questions

- **Client:** the load-test bots measure ENet RTT, packet loss, and observed entity distance; the human
  client shows the `SERVER_METRICS` channel breakdown + scheduler diagnostics in the HUD.
- **Server:** owns the metrics above via `MetricsCollector` (`rust/server/src/metrics.rs`), sampled at
  1 Hz onto the `SERVER_METRICS` packet and into Prometheus.
- **Predicted:** nothing here — budgets are observations, not gameplay state.
- **Replicated:** the metric subset is broadcast to clients in `SERVER_METRICS` (ch1).
- **Persisted:** nothing yet; the plan calls for a captured `docs/PERFORMANCE_NOTES.md` snapshot per phase.
- **Validated:** budgets are release gates checked by the bot-swarm regression suite (`evaluate_success`),
  not by the sim.
- **Can fail:** any "not measured" row can silently breach its budget at scale. The two former live
  traps are gone: the 255-entity/packet u8 cap is now u16 (overflow warns via `snapshot_count_overflow`)
  and the 20-vs-30 Hz snapshot drift is resolved (now 30 Hz).
- **Tested:** `rust/load_test/` bot swarm (`baseline` / `target` / `stress` scenarios) +
  `rust/load_test/src/assertions.rs`; no automated percentile or CPU/mem-per-player assertion exists today.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the 30 Hz tick + 30 Hz snapshot loop these budgets bound
- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) · [`../server/contract.md`](../server/contract.md) — where the per-snapshot byte budget and the (u16) `entity_count` come from
- [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) — the gated 30-vs-60 tick measurement protocol (results PENDING)
- [`latency-budget.md`](latency-budget.md) — the p95-latency target broken down per stage
- [`../ops/architecture.md`](../ops/architecture.md) — POC success criteria (the contradictory source; its preamble flags the drift)
- [`../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md) · [`../../plans/NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/NETWORK_PERFORMANCE_UPGRADES.md) — the engineering budgets and the phased instrumentation plan
- `rust/load_test/README.md` — load-test scenarios + flags
