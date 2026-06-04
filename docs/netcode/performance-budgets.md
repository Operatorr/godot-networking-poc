# Performance budgets — targets vs measured

**Status:** Reference (verified 2026-06-04 against code; #13 rate budget + #15 scheduler diagnostics
now surfaced, snapshot rate raised to 30 Hz, entity-count cap lifted to u16).

> A single table of the numbers everything else is judged against. Three sources disagree —
> the **POC success criteria** ([`../ARCHITECTURE.md`](../ARCHITECTURE.md)), the **engineering
> budgets** ([`../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md)),
> and **what the code actually does**. This doc reconciles them and flags the drift so an agent
> tuning the netcode picks the right target. Numbers only; mechanism lives in the sibling docs.

## How to read this

- **POC target** — the release gate from `ARCHITECTURE.md` "Success Criteria" (ARCHITECTURE.md:37-44)
  and "Success Metrics to Monitor" (ARCHITECTURE.md:805-811). These two sub-tables already disagree
  with each other.
- **Eng budget** — the tighter engineering numbers in the CODEX plan's "Performance Targets"
  (CODEX_NETWORK_PERFORMANCE_UPGRADES.md:41-60).
- **Code today** — the value actually compiled/configured in the repo, with `file:line`.
- **Gap** — what measurement is missing, or where code contradicts a target. "—" means the code
  value is a configured constant, not a load-tested measurement; nothing here is a *measured*
  number at 500-1000 players yet (no captured `docs/PERFORMANCE_NOTES.md` snapshot exists).

## The budget table

| Metric | POC target | Eng budget | Code today | Gap |
| --- | --- | --- | --- | --- |
| **Tick rate** (sim) | ≥20 Hz under load (ARCHITECTURE.md:41) | ≥30 Hz sustained | **30 Hz** — `SERVER_TICK_RATE` (game_constants.gd:22, now the single client+server-default authority), manual accumulator in `_process` (server_main.gd:178-188) | Code beats the 20 Hz POC gate; matches eng. No load measurement yet; 60 Hz trial gated (perf-notes). |
| **Snapshot rate** (STATE_UPDATE send) | not specified separately | 20 Hz default (§1.1) | **30 Hz LIVE** — `server_config.json` sets `snapshot_rate_hz=30` (#3 raised it from 20); `server_config.gd` default is `0`→tick-rate fallback | Now matches the 30 Hz Tick. The 30-vs-60 tick/snapshot trial is gated in [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) (results PENDING). |
| **Tick time, avg** | <50 ms frame time (ARCHITECTURE.md:807) | <8 ms at target load | — `avg_tick_time_ms` measured (server_metrics.gd:86) | Measured, but not captured at scale. POC's 50 ms is 6× looser than eng's 8 ms. |
| **Tick time, p95** | (none) | <16 ms at target load | **not measured** — only avg + max tracked (server_metrics.gd:86-87) | No p50/p95/p99 percentile or over-budget tick count. Eng plan §P0 wants them. |
| **Tick time, max** | (none) | <25 ms outside startup | — `max_tick_time_ms` over last 30 ticks (server_metrics.gd:26,87) | 30-tick window only; transient spikes outside it are lost. |
| **Bandwidth / player** | **<2 KB/s** (ARCHITECTURE.md:43) **vs <5 KB/s** (ARCHITECTURE.md:809) | <5 KB/s | — `avg_bandwidth_per_client` bytes/sec from per-peer deltas (server_metrics.gd:62-77) | **Drift:** ARCHITECTURE contradicts itself (2 vs 5 KB/s); eng aligns on 5. Per-peer **byte budget** = 1200 B/snapshot global ceiling (`max_snapshot_bytes`, server_config.gd:37) → ≈ 1200 × 30 Hz = **36 KB/s** before AoI/delta. Each peer's *effective* cap is now bandwidth-derived (#13): `clamp(advertised_bps / snapshot_rate, 256, 1200)`. |
| **Latency p95** | <150 ms same-region (ARCHITECTURE.md:42) | <150 ms (avg <100) | **not measured server-side** — RTT is carried in `PlayerInputPacket` but ServerMetrics has no latency field | Aligned target; no server-side RTT histogram. Load harness measures client-side. |
| **CPU / player** | **<0.5%** (ARCHITECTURE.md:44) **vs <1%** (ARCHITECTURE.md:810) | (via tick-time budget) | **not measured** — no per-player CPU attribution | **Drift:** ARCHITECTURE says 0.5% in one table, 1% in another. No CPU/player metric exists; inferred only from tick time. |
| **Memory / player** | <5 MB (ARCHITECTURE.md:44) | (none) | **not measured** — no heap/player metric | No mem-per-player instrumentation. |
| **Max players** | 500-1000 / server (ARCHITECTURE.md:39) | (release gate) | **`max_players` = 100** (server_config.json `max_players`) | Shipped cap is 100; the 500-1000 goal is unproven. The old u8 entity-count wire cap (255/packet) that blocked naive scaling is **gone** — `entity_count` is now u16 (#11). |
| **Render delay** (remote) | (none) | ~100 ms suggested (§P1; CODEX:98) | **66.7 ms** — 2 ticks @30 Hz (`REMOTE_ENTITY_RENDER_DELAY_TICKS`, game_constants.gd:31-37) | Below the ~100 ms the plan argues for, but now the snapshot rate matches the tick (33.3 ms interval), so 2 ticks absorbs ~2 missed snapshots. |

## Doc drift, called out explicitly

Three numbers are stated inconsistently across the canonical docs. Use the **Code today** column as
ground truth; treat the others as aspirational and stale:

1. **Tick rate — 20 Hz vs 30 Hz.** `ARCHITECTURE.md:41` gates at "≥20 Hz". The code runs **30 Hz**
   (game_constants.gd:12). The ARCHITECTURE figure predates the 30 Hz decision; it is a floor, not
   the target.
2. **Snapshot rate — now aligned at 30 Hz.** `server_config.gd` defaults `snapshot_rate_hz` to `0`
   (= match tick = 30 Hz), and `server_config.json` now sets it to **30** (raised from 20 by #3). The
   live server sends Snapshots at **30 Hz (33.3 ms)**, matching the Tick — the old 20-vs-30 drift is
   resolved.
3. **Bandwidth — 2 vs 5 KB/s.** `ARCHITECTURE.md:43` says "<2 KB/s average"; `ARCHITECTURE.md:809`
   says "<5 KB/s per player average"; the CODEX plan uses **5 KB/s** (CODEX:46). The 2 KB/s figure is
   the optimistic theoretical-minimum narrative (ARCHITECTURE.md:560-568); 5 KB/s is the realistic
   working budget.
4. **CPU/player — 0.5% vs 1%.** `ARCHITECTURE.md:44` says "<0.5% per player"; `ARCHITECTURE.md:810`
   says "<1% per player". Neither is measured.

## What ServerMetrics measures today

`ServerMetrics` (server_metrics.gd) tracks, per periodic `SERVER_METRICS` broadcast:

| Field | Source | Notes |
| --- | --- | --- |
| `avg_tick_time_ms` / `max_tick_time_ms` | last 30 ticks (server_metrics.gd:25-26,79-87) | avg + max only; **no p50/p95/p99**, no over-budget count |
| `player_count` / `entity_count` | per update (server_metrics.gd:52-54) | totals, not per-AoI-visible |
| `total_bytes_sent` / `total_bytes_received` | network stats (server_metrics.gd:55-56) | cumulative |
| `avg_bandwidth_per_client` | per-peer byte delta ÷ elapsed ÷ peers (server_metrics.gd:62-77) | a **rate** (bytes/sec); avg across peers, not a distribution |
| `bytes_sent_by_type` | `NetworkManager.bytes_sent_by_type` (server_metrics.gd:59-60) | per-`MessageType` cumulative bytes (§8.1, Phase 1) — the one rich channel |
| `sched_entities_deferred` / `sched_max_queue_age_ticks` / `sched_peers_at_budget_pct` / `sched_peers_evaluated` / `sched_snapshot_overflow` | `ServerBroadcastService.last_tick_diagnostics` (server_metrics.gd:27-31,74-75) | scheduler diagnostics (#15) — now on the `SERVER_METRICS` wire and HUD |

## What's now surfaced — scheduler diagnostics (#15) + rate budget (#13)

The CODEX plan's §8.2 scheduler diagnostics **now reach the client.** `SnapshotScheduler` /
`ServerBroadcastService` populate `last_tick_diagnostics` (`entities_deferred_per_tick`,
`max_queue_age_ticks`, `peers_at_budget_pct`, `peers_evaluated`, plus the #11
`snapshot_count_overflow` counter), and these are plumbed all the way through:
`ServerBroadcastService.last_tick_diagnostics` → `ServerMetrics.sched_*` fields
(`server_metrics.gd:27-31,74-75`) → the `SERVER_METRICS` packet as fixed-length appended fields
(`network_manager.gd:876-880` encode, `:1010-1014` decode) → the HUD `server_status` panel
(`server_status.gd:65-69,125-127`). So deferral / queue-age / peers-at-budget are now observable at
load. The **per-client rate budget** (#13) also landed — clients advertise a bytes/sec budget in
`CONNECT_AUTH` and the server derives a per-peer snapshot byte cap from it (see
[`server-tick-broadcast.md`](server-tick-broadcast.md)).

## Still missing

- Tick-time **percentiles** (p50/p95/p99) and over-budget tick count.
- Per-client send detail: entities considered vs sent vs deferred-by-budget vs zero-delta-skipped.
- Delta effectiveness (baseline/delta/full-state/position-only counts).
- Server-side **latency** distribution, **CPU/player**, **mem/player**.
- Captured load-run numbers at 500–1000 players (every "not measured" row below is still a
  configured constant, not a measurement — including the gated 30-vs-60 tick trial, whose protocol
  is in [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md), results PENDING).

## The eight questions

- **Client:** load-test bots/clients measure RTT and observed entity distance; the human client shows
  the `SERVER_METRICS` channel breakdown in the HUD.
- **Server:** owns all the metrics above via `ServerMetrics`, sampled on the snapshot/metrics cadence.
- **Predicted:** nothing here — budgets are observations, not gameplay state.
- **Replicated:** the high-level metric subset is broadcast to clients in `SERVER_METRICS`.
- **Persisted:** nothing yet; the plan calls for a captured `docs/PERFORMANCE_NOTES.md` snapshot per phase.
- **Validated:** budgets are release gates checked by the bot-swarm regression suite, not by the sim.
- **Can fail:** any "not measured" row can silently breach its budget at scale. The two former live
  traps are gone: the 255-entity/packet u8 cap is now u16 (#11, overflow warns via
  `snapshot_count_overflow`) and the 20-vs-30 Hz snapshot drift is resolved (now 30 Hz).
- **Tested:** `load_testing/bot_swarm.py` (`baseline` / `target` / `stress`) + `regression_assertions.py`;
  no automated percentile or CPU/mem-per-player assertion exists today.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the 30 Hz tick + 30 Hz snapshot loop that these budgets bound
- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) · [`wire-protocol.md`](wire-protocol.md) — where the per-snapshot byte budget and the (now u16) entity_count come from
- [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md) — the gated 30-vs-60 tick measurement protocol (results PENDING)
- [`latency-budget.md`](latency-budget.md) — the p95-latency target broken down per stage
- [`transport-websocket.md`](transport-websocket.md) — TCP head-of-line blocking, the unmeasured risk behind the latency gate
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — POC success criteria (the contradictory source)
- [`../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md) · [`../../plans/NETWORK_PERFORMANCE_UPGRADES.md`](../../plans/NETWORK_PERFORMANCE_UPGRADES.md) — the engineering budgets and the phased instrumentation plan
