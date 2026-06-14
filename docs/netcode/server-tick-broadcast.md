# Server tick loop & snapshot broadcast

**Status:** Implemented (verified 2026-06-14 against `rust/`). This describes the **Rust
`omega-server`** (`rust/server/`) — the only authoritative server. One process = one instance
(an Arena or a Sanctuary). The legacy GDScript headless server is retired (the client refuses
server mode); none of this runs on a Godot node anymore. What remains open is measurement at the
500–1000-player target, not missing mechanism.

This is the server-side counterpart to [`interpolation.md`](interpolation.md) and
[`client-prediction.md`](client-prediction.md): how the authoritative simulation advances one
**Tick** at a time, and how it turns world state into per-client **Snapshots**. The tick order is
grounded in [`rust/server/src/sim/world.rs`](../../rust/server/src/sim/world.rs) (`World::tick`); the
snapshot/baseline/byte-budget machinery in [`rust/server/src/net/broadcast.rs`](../../rust/server/src/net/broadcast.rs).
The wire layer is the bit-packed `protocol` crate, spec'd in [`../server/contract.md`](../server/contract.md).

## The two cadences are decoupled

| Cadence | Rate | Period | Where | Drives |
| --- | --- | --- | --- | --- |
| **Tick** (simulation) | 30 Hz | 33.3 ms | `World::tick` (`world.rs`) | inputs, movement, abilities, AI, collisions, backstop, game events |
| **Snapshot** | **30 Hz live** | 33.3 ms | `snapshot_due` gate in `World::tick`, broadcast in `broadcast.rs` | replicated entity state to clients |

The Tick rate is `config.tick_rate` = 30 (`ServerConfig::default`, `config.rs`; overridable via
`server_config.json`). The Snapshot rate is decoupled through a separate accumulator
(`World::snapshot_accumulator`, seeded from `config.snapshot_rate_hz()`): a raw value of `0`
falls back to the Tick rate, and the effective rate is `min(raw, tick_rate)` (`config.rs`
`snapshot_rate_hz`). The shipped default is `0` ⇒ **30 Hz live Snapshot rate, matching the Tick**.
(The 30-vs-60 trial is in [`perf-notes/tick-rate-30-vs-60.md`](perf-notes/tick-rate-30-vs-60.md).)

## The tick loop is a synchronous accumulator on the main thread

There is no Godot engine loop here. `main()` (`rust/server/src/main.rs`) runs a fixed-tick
accumulator: the **main thread IS the tick thread (D8)**. Each pass it drains
`host.service()` (decode + route ENet events in arrival order), flushes staged packets, then
advances the sim:

```rust
tick_timer += now.duration_since(last_loop).as_secs_f64();
while tick_timer >= tick_interval {
    tick_timer -= tick_interval;
    world.tick(now_ms(start), &mut outbox);   // one Tick
    flush_outbox(&mut outbox, &mut host, ...); // its packets leave
    host.flush();
    collector.record_tick_time(...);
}
std::thread::sleep(Duration::from_millis(1));
```

Consequences, all deliberate:

- **Catch-up `while`-loop:** if a pass ran long, multiple Ticks fire to keep wall-clock cadence.
  No tick is skipped. The Snapshot accumulator has a **runaway-drift guard** — at most one
  snapshot per catch-up burst (`world.rs`: if the accumulator overshoots a full interval after
  one decrement it resets to 0).
- **`sleep(1 ms)`** at the bottom yields the CPU between passes instead of busy-spinning; ENet is
  still serviced each pass so acks/retransmits stay timely. Side I/O (Go API region heartbeat,
  server→API progression jobs) runs on a **separate thread** over `std::sync::mpsc` so the tick
  never blocks on HTTP.

### One Tick, in order

`World::tick` (`world.rs`) does exactly this, every Tick. The order is the ported
`_process_server_tick` order, with the D11 backstop and world-effect passes added:

| Step | What | Call(s) in `world.rs` |
| --- | --- | --- |
| set `snapshot_due` | advance snapshot accumulator (+ drift guard) | inline |
| 0 | apply async progression replies (hydrate / hardcore death) | `poll_progression` |
| 1 | inputs → movement steps → shoot/ability spawns → **per-input `ActionConfirm`** | `players.process_all_inputs`, `process_shoot_inputs`, `process_ability_activations`, `process_charge_blasts` |
| 2 | projectiles integrate; spawner; invuln/respawn/stealth/regen timers; progression flush; hardcore deaths; leaderboard cadence | `projectiles.update_all`, `spawner.update`, per-player timers, `flush_dirty_progression`, `process_hardcore_deaths` |
| 3 | monster AI (+ `PROJECTILE_FIRED` events, non-zero projectile id) | `ai.update_all` |
| 4 | **lag-comp position history** for monsters **and players** (post-move, pre-collision) | `monsters.record_position_snapshot`, `players.record_position_snapshot` |
| 5 | collisions / damage / kills (players pass, then monsters); healthorb rolls | `combat::process_collisions`, `roll_healthorbs` |
| 5b | **D11 backstop** — blatant unreported monster-bullet overlaps | `backstop.update` |
| 5c | ability/loot world entities (bibles, mines, DOT zones, healthorb pickups) | `tick_world_entities` |
| 6 | **build + broadcast Snapshot — only if `snapshot_due`**; then release quarantined ids | `collect_entities` + `broadcast.broadcast_state_updates` |
| 7 | cleanup dead monsters (they got exactly one death snapshot) | `monsters.cleanup_dead_monsters` |

**Game events** (DAMAGE, KILL, PROJECTILE_FIRED, RESPAWN, PLAYER_INFO, ABILITY_EFFECT, PROGRESS,
PICKUP, LEADERBOARD_UPDATE) are staged inline during steps 0–5c on *every* Tick — only the
continuous `Snapshot` is gated by `snapshot_due`. With the live Snapshot rate equal to the 30 Hz
Tick, positions and events stream at the same cadence; the gate still exists so a future lower
snapshot rate decouples cleanly. Step 4 snapshots **player** positions too — the history the PvP
lag-comp rewind reads (see [`hit-authority-model.md`](hit-authority-model.md)).

## ENet replaces the BATCH frame: per-tick send, channel-routed

There is no application-level BATCH frame anymore. Instead the sim stages every packet in an
**`Outbox`** (`outbox.rs`) — `send(peer, …)` / `broadcast(…)` — and the net layer drains and
encodes it **once per Tick** in `flush_outbox` (`main.rs`), right after `world.tick` returns and
before `host.flush()`. This preserves the "a tick's packets for a peer leave together, in order"
property that BATCH gave, but the coalescing is now ENet's own per-channel framing, not a custom
frame over TCP.

Each packet self-routes to one of **three ENet channels** (`ServerPacket::channel` / `reliable`
in `rust/protocol/src/server.rs`; see [`../server/contract.md`](../server/contract.md) §Channels):

| Channel | Const | ENet mode | Carries (S→C) |
| --- | --- | --- | --- |
| 0 | `CH_SNAPSHOT` | unreliable **sequenced** | **delta `Snapshot`s**, `ActionConfirm` |
| 1 | `CH_RELIABLE` | reliable ordered | `AuthResult`, `GameEvent`, `ServerMetrics`, **baseline `Snapshot`s** (incl. full-state replies) |
| 2 | `CH_INPUT` | unreliable sequenced | (C→S only: `PlayerInput`) |

The split that matters here: **delta snapshots ride ch0 unreliable** (a newer delta supersedes a
lost one), but **baseline snapshots ride ch1 reliable** because they are must-arrive and may
exceed the unreliable MTU budget. Letting an oversized ch0 datagram silently upgrade to
reliable-fragmented would reintroduce head-of-line blocking, so baselines are sent reliable
*explicitly* instead. Ordering stays safe: the server only emits deltas against an **acked**
baseline, so no delta referencing tick T is in flight before the client holds baseline T.

Keep every ch0 datagram **< 1200 B** (`MAX_UNRELIABLE_PAYLOAD`); `flush_outbox` warns loudly if an
unreliable packet exceeds it. The per-peer byte budget enforces this for deltas; baselines are
exempt (hence ch1).

`server_ms` (server monotonic ms, u32-wrapped) rides **every** snapshot header — the relocated
clock-sync that the old app HEARTBEAT carried. The client feeds it through an EMA filter using
**ENet-native RTT** for the half-trip estimate; there is no longer an application heartbeat.

## Building one Snapshot tick (`broadcast.rs`)

`broadcast_state_updates` runs **once per snapshot tick** with the entity set `collect_entities`
built fresh in `world.rs` (authenticated players incl. dead, alive projectiles, all monsters,
alive world-effect entities). It:

1. Builds one **shared `SpatialGrid`** (cell size `aoi_exit_radius / 4`) over the whole entity
   set, inserting each entity once.
2. **Loops over every authenticated peer.** For each, it queries the shared grid for a candidate
   band (`grid.query_radius(self_position, effective_exit)`) instead of walking all entities —
   turning the former **O(players × entities)** scan into **O(players × nearby)** — then runs the
   hysteresis-aware AoI filter, delta diff, and byte-budget scheduler.

AoI uses **enter/exit hysteresis** with strict `>` culling (exactly-on-radius stays visible):
an already-visible entity is kept out to `aoi_exit_radius`, a new one must be inside `aoi_radius`
to enter. Defaults (`config.rs`): enter 1000 / exit 1100, LOD near 400 / mid 1000. See
[`interest-mgmt-aoi.md`](interest-mgmt-aoi.md). (The projectile/monster *collision* grids in the
sim are separate and unchanged.)

## Delta compression

Each per-player packet is either a **baseline** (full state) or a **delta**, decided per peer by
its `DeltaStateCache` (`broadcast.rs`).

- **Delta mask** is a 5-bit field on the wire (`delta_mask` in `protocol`): `POSITION` (bit 0),
  `ANIMATION` (bit 1), `FLAGS` (bit 2), `REMOVED` (bit 3), `FULL` (bit 4). `calculate_delta_mask`
  diffs current state against the per-peer cache and sets only changed bits; an entity whose mask
  is 0 is **omitted entirely** (costs zero bits). See [`../server/contract.md`](../server/contract.md)
  §Snapshot for the exact bitstream layout and quantization (positions ×10 truncate-toward-zero,
  clamp i16; 16-bit entity flags; 3-bit anim).
- Position equality uses a **0.05-unit epsilon** per axis (`POSITION_EPSILON`), half the 0.1-unit
  wire quantization step.
- **Forced baseline every 100 Ticks** (`DELTA_FULL_STATE_INTERVAL`,
  `needs_full_state_for_interval`). At the 30 Hz live Snapshot rate that is one full resync per
  peer every ~3.3 s.
- **Baseline acks + proactive resend.** The 100-Tick cadence is a **floor**, not the only repair:
  the client acks each received baseline with `BaselineAck{baseline_tick}`
  (`World::on_packet` → `broadcast.mark_baseline_acked`), and the server tracks per-peer
  `baseline_tick` / `pending_baseline_tick` / `acked_baseline_tick`. `needs_baseline_resend`
  re-sends a baseline once an un-acked one has been outstanding `BASELINE_ACK_TIMEOUT_TICKS` = 30
  ticks (~1 s). **On ENet/UDP this is live, not inert** (unlike the old TCP transport) — a dropped
  unreliable-path baseline is genuinely possible, though baselines themselves ride ch1 reliable so
  the common case is covered; the ack path is the belt-and-suspenders repair. A client can still
  force a resync with `RequestFullState`, which replies with an unfiltered full-state baseline plus
  a `PLAYER_INFO` replay for every authenticated player (Authority-sync recovery).
- **Lossless deferral.** Only fields whose bit actually went out update the cache
  (`update_cache_partial`); a withheld field stays dirty so a deferred entity re-prioritizes next
  tick.
- **AoI exits and stale-cache entries** are emitted as explicit **pinned `REMOVED`** deltas so a
  client never strands an entity.
- **Baseline defers when removals are pending:** if a baseline is due the same tick an entity
  exits AoI, the delta (carrying the REMOVED) is sent instead, and the true baseline goes out the
  next tick — so a baseline is never mixed with pending removals.

## Per-peer byte budget (bandwidth-derived) + priority scheduler

Each delta packet is sized by a greedy **scheduler** (`schedule` in `broadcast.rs`) against that
peer's byte budget. The service-global ceiling is `max_snapshot_bytes` = **1200** (`config.rs`),
but each peer's effective cap is derived from the bandwidth budget it advertised in `ConnectAuth`:
the client sends `bandwidth_budget_bps`; the server clamps it to
`[min_client_bandwidth_bps, max_client_bandwidth_bps]` (defaults 24000 / 200000; absent ⇒
`default_client_bandwidth_bps` = 120000) and computes
`per_peer_bytes = clamp(budget / snapshot_rate_hz, MIN_SNAPSHOT_FLOOR=256, max_snapshot_bytes)`
(`World::handle_auth`), stored via `broadcast.set_peer_byte_budget`. This is the **per-second**
ceiling: a marginal connection gets fewer bytes per Snapshot. The scheduler scores every
candidate:

```
priority = importance(type) + ticks_since_last_sent − distance_penalty(lod) + change_bonus(mask)
```

| Term | Values | Source (`broadcast.rs`) |
| --- | --- | --- |
| importance | player 10, projectile 8, monster 4, **world-effect 4**, default 1 | `importance` |
| distance_penalty (LOD) | NEAR 0, MID 4, FAR 8 | `DISTANCE_PENALTY_BY_LOD` |
| change_bonus | full/removed 6; else +2 per changed field | `change_bonus` |
| `ticks_since_last_sent` | raw add — starved entities climb until they win | per-candidate |

`schedule` sorts by (priority desc, entity_id asc) and greedily admits while
`bits + encoded_bits <= max_bits` — **no early break** (a smaller item may still fit). **Pinned**
candidates (AoI-exit removals, stale-cache cleanup) **bypass and consume** the budget so a despawn
is never dropped. Anything that doesn't fit is **deferred** — not sent this Snapshot, accrues
`ticks_since_last_sent`, and bubbles up next time. Net effect under budget pressure: far/low-priority
entities update at a *fraction* of the Snapshot rate rather than being lost. Encoded sizes are the
**real bit-level wire sizes** (`EntityRecord::wire_bits`), so no speculative encode is needed.

> **Baselines have no byte budget.** `create_full_state_packet` emits every visible entity with no
> scheduler and no 1200-byte cap (that is why they ride ch1 reliable). The wire `entity_count` is a
> `u16`, so a crowded baseline doesn't silently truncate; the only soft ceiling left is
> `STATE_MAX_FULL_ENTITIES` = 7280 (a per-packet diagnostic carried from the old 64 KB frame),
> and `snapshot_count_overflow` is incremented if it is ever brushed.

### Scheduler diagnostics

`broadcast_state_updates` aggregates per-tick scheduler stats into `BroadcastService.diagnostics`
(`TickDiagnostics`): `entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct`,
`peers_evaluated`, plus the cumulative `snapshot_count_overflow`. These feed the 1 Hz
`ServerMetrics` packet (`main.rs` builds it via `collector.build_packet`, reading
`world.broadcast.diagnostics`; fields `sched_*` in `protocol`), broadcast on ch1 and rendered in
the client's server-status HUD — so budget starvation is observable. The Prometheus exporter
(`:9100` Arena / `:9101` Sanctuary) carries the same counters. See
[`performance-budgets.md`](performance-budgets.md).

## Connect / disconnect bookkeeping

- A new peer gets a fresh `DeltaStateCache` on connect (`World::on_peer_connected` →
  `broadcast.get_or_create_delta_cache`); its byte budget is set at auth. Both the cache and the
  per-peer visibility/budget maps are dropped on disconnect (`broadcast.remove_peer`).
- Departure replicates via the delta stream's pinned `REMOVED` records — there is **no** explicit
  "player left" game event. Entity ids are quarantined until a snapshot carries their removal, then
  released (`players.release_quarantined_ids` after step 6).
- On shutdown each peer is sent a reasoned native ENet `disconnect`, then a short service window
  lets the disconnect packets actually leave before the process exits (`main.rs`).

## The eight questions

- **Client:** nothing — this doc is the authoritative server's hot path. The Godot client only
  *consumes* the Snapshots ([`interpolation.md`](interpolation.md)) (and runs the same `sim_core`
  crate for prediction, [`client-prediction.md`](client-prediction.md)).
- **Server:** the entire synchronous 30 Hz Tick loop, 30 Hz Snapshot build, shared-grid AoI
  filter, delta compression, bandwidth-derived priority scheduler, baseline-ack tracking, and the
  per-tick ENet channel-routed flush.
- **Predicted:** nothing here — prediction is client-side; the server is authoritative.
- **Replicated:** all entity state, as per-peer delta/baseline `Snapshot`s; game events replicate
  inline (ch1 reliable) every Tick.
- **Persisted:** nothing in this loop — all sim state is in-memory. Only the Go API persists
  accounts/characters/leaderboard/progression (server→API jobs leave on the I/O thread).
- **Validated:** inputs (NaN/Inf guard in `on_packet`, position/cheat thresholds during step 1);
  the broadcast itself validates nothing beyond entity-id typing.
- **Can fail:** unmeasured at the 500–1000-player target (the shared grid + 1000/1100 radius should
  hold but are unproven — now observable via the surfaced scheduler diagnostics); a clustered
  baseline can exceed 1200 B (no truncation — `entity_count` is u16, and it rides ch1 reliable so
  it arrives fragmented). The unreliable ch0 delta path can drop datagrams — repaired by the next
  delta and, for baselines, the ack/resend path.
- **Tested:** `broadcast.rs` unit tests cover baseline→delta→removal sequencing, AoI hysteresis,
  baseline-defer-on-removals, the ack/resend flow, and scheduler admission/deferral; `world.rs`
  tests cover the tick order (join, input/confirm, shoot, respawn gate, abilities, sanctuary).
  `protocol`'s `baselines_ride_the_reliable_channel` test pins the channel split. End-to-end load
  is driven by the Rust bot swarm (`rust/load_test/`, scenarios `baseline`/`target`/`stress`);
  `ServerMetrics` reports avg/max tick time plus the `sched_*` diagnostics.

## See also

- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — the AoI filter and LOD bands this loop runs per player
- [`../server/contract.md`](../server/contract.md) — the as-built wire/channel spec: Snapshot bitstream, delta mask, typed-id, quantization, budget cadence
- [`../server/design.md`](../server/design.md) — architecture & rationale (transport, shared sim, tick, auth, persistence, hits)
- [`hit-authority-model.md`](hit-authority-model.md) — the two-netcode hit model the lag-comp history (step 4) feeds
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md) — the client side of these Snapshots
- [`performance-budgets.md`](performance-budgets.md) — tick-time and bandwidth targets vs. measured
- [ADR 0003 — ENet/UDP transport](../adr/0003-enet-udp-transport.md) · [ADR 0004 — schema-driven wire protocol](../adr/0004-schema-driven-wire-protocol.md)
