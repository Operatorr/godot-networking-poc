# Codex Network Performance Upgrades Spec

## Purpose

Define concrete upgrades that can improve Omega Realm's networked gameplay performance: lower perceived latency, smoother remote entities, lower bandwidth per player, and better server tick stability under load.

This spec is based on:

- `plans/RECOMMENDATIONS.md`
- `plans/Server In-game Protocol Design and Optimization - Valve Developer Community.md`
- Current project code in `client/autoload/network_manager.gd`, `client/scripts/client/prediction.gd`, `client/scripts/client/interpolation_controller.gd`, `client/scripts/server/server_broadcast_service.gd`, `client/scripts/server/server_main.gd`, and shared packet scripts.

## Guiding Model

The design should keep the authoritative-server model. Clients should only send intent, not truth. The client may predict local motion and local feedback, but the server owns the game state and corrections.

The baseline model from the recommendation and Valve docs maps well to this project:

- The local player lives in a predicted present using client-side prediction and server reconciliation.
- Remote entities live in an interpolated past using buffered server snapshots.
- The server runs fixed ticks, consumes user commands, broadcasts authoritative snapshots, and applies bounded lag compensation where the game design accepts it.
- Bandwidth should be managed as a per-client budget, not as "send every changed thing every tick."

## Current Baseline

The repo already has many of the right pieces:

- Server tick target is 30 Hz via `GameConstants.SERVER_TICK_RATE`, `project.godot`, and `ServerConfig`.
- `PredictionController` predicts local movement, stores input snapshots, replays unacknowledged inputs, and handles action confirmations.
- `InterpolationController` renders remote entities behind the newest server tick with per-entity `EntityStateBuffer` history.
- `PlayerInputPacket` is compact at 16 bytes payload, including position, velocity, input flags, aim angle, sequence, render tick, and RTT.
- `StateUpdatePacket` uses compressed positions, delta masks, baseline ticks, and an 8-bit entity count.
- `ServerBroadcastService` already has delta compression, AoI filtering, AoI hysteresis, distance-based LOD throttling, and explicit despawn deltas.
- `NetworkManager` batches per-tick server packets into one WebSocket frame per peer when batching is enabled.
- `ServerMain` has PvE projectile lag compensation using client render tick and RTT fallback.
- Load testing exists in `load_testing/` with baseline, target, stress, clustered, movement, combat, and strategy scenarios.

That means the next performance gains should come from measurement, correctness under jitter, reducing hot-path allocations, and adaptive send policy before considering a transport rewrite.

## Performance Targets

Use the existing load-test criteria as release gates:

- Server tick rate: sustain at least 30 Hz.
- Average latency: less than 100 ms.
- P95 latency: less than 150 ms.
- Bandwidth per player: less than 5 KB/s.
- Packet loss estimate: less than 2%.
- Bot crash/disconnect rate: less than 5%.

Add these engineering budgets:

- Average server tick time: under 8 ms at target load.
- P95 server tick time: under 16 ms at target load.
- Max server tick time: under 25 ms outside startup/shutdown.
- Interpolation underruns: below 1 per 10 seconds per active client during normal network conditions.
- Local prediction correction distance: P95 under 8 units after warmup, excluding teleport/respawn.
- Full-state resyncs: no repeated retry loops during stable connections.
- Per-client state update payload: remain below the 5 KB/s budget after including events, confirms, heartbeats, and metrics.

## Priority 0: Instrument Before Tuning

### Problem

The current metrics are useful but too coarse to tell whether bandwidth, CPU, jitter, or reconciliation is the bottleneck. We should not tune tick rate, AoI, LOD, interpolation delay, or packet formats without better visibility.

### Proposed Work

Add metric collection for:

- Server tick times: p50, p95, p99, max, and over-budget tick count.
- Per-message bytes sent by type: `STATE_UPDATE`, `GAME_EVENT`, `ACTION_CONFIRM`, `SERVER_METRICS`, `HEARTBEAT`, and `BATCH`.
- Per-client state send rate: bytes/sec, packets/sec, entities considered, entities sent, entities removed, and current AoI visible count.
- Delta effectiveness: baseline packets, delta packets, zero-delta skips, full-state entities, position-only deltas, animation deltas, flags deltas, removed deltas.
- Batching effectiveness: packets per batch, bytes per batch, single-packet flushes, multi-packet flushes.
- Prediction health: corrections/minute, correction distance histogram, replayed input count histogram, max input buffer size.
- Interpolation health: buffer size per entity, underruns, extrapolation frames, freeze frames, teleports, full-state request retries.
- Input pressure: queued input count per player before each server tick and dropped/stale input counts if we add caps.
- Entity pressure: players, monsters, projectiles, total entities, AoI-visible entities per client, and collision candidates.

Expose the high-level subset through `SERVER_METRICS` and write detailed snapshots to load-test JSON.

### Acceptance Criteria

- A target load test report can identify whether a failure came from server tick time, bandwidth, RTT, packet loss estimate, interpolation underruns, or prediction corrections.
- Metrics have negligible overhead in normal mode.
- Debug logging is not required to collect performance data.

## Priority 0: Fix Hard Protocol Limits And Stale Constants

### Problem

Some current constants and packet limits can become hidden performance or correctness failures:

- `StateUpdatePacket` writes entity count as `u8` and clamps to 255 entities. With 100 players, 100 monsters, and active projectiles, a client can exceed this if AoI is disabled or too wide.
- `PacketTypes.DELTA_FULL_STATE_INTERVAL` is 100 ticks, but its comment says "about 5 seconds at 20Hz." At 30 Hz, this is about 3.33 seconds.
- `EntityStateBuffer.BUFFER_SIZE` comment assumes 20 Hz. At 30 Hz, 5 snapshots are about 167 ms, not 250 ms.
- `InterpolationController.RENDER_DELAY_TICKS` is 2 ticks, which is about 67 ms at 30 Hz. The Valve-style recommendation typically wants around 100 ms or enough delay to absorb one missed packet.

### Proposed Work

- Replace silent entity truncation with explicit paging, prioritization, or a larger/chunked entity count format.
- Add a metric and warning when a state update would exceed the packet's supported entity count.
- Update stale comments and tie interval documentation to tick rate, not fixed 20 Hz assumptions.
- Make baseline interval, interpolation buffer size, render delay, max extrapolation, and full-state interval explicit server/client config values.
- Add compatibility/version fields if packet format changes.

### Acceptance Criteria

- No state update silently drops entities due to the 255 entity cap.
- Comments and config names reflect 30 Hz behavior.
- Load tests include a worst-case entity-count scenario that validates no state truncation occurs.

## Priority 0: Lock Down Fixed-Step Prediction And Reconciliation

### Problem

The client predicts in `_physics_process`, sends one input per server tick interval, and replays inputs using `GameConstants.move_with_obstacle_collision`. This is the right shape, but prediction quality depends on deterministic client/server movement and consistent tick assumptions.

### Proposed Work

- Establish one authoritative movement step function used by both client prediction and server movement validation.
- Add deterministic replay tests: same starting position, input flags, tick delta, and obstacle layout must produce identical client/server positions.
- Ensure client input snapshots represent exactly one authoritative tick, not variable render-frame time.
- Track and alert when replay count grows unexpectedly, which usually means packet loss, stalled acks, or sequence handling issues.
- Keep effects out of replay loops. Sounds, particles, muzzle flashes, and other one-shot effects should only fire on first prediction, not on reconciliation replay.
- Keep the server authoritative over action results. Client-side weapon feedback can be predicted, but damage and kills remain server-confirmed.

### Acceptance Criteria

- Automated tests cover straight movement, diagonal movement, sprinting, obstacle sliding, bounds clamping, respawn/teleport sync, and sequence wrap.
- Local player correction P95 stays under 8 units in target load tests after the initial authoritative spawn sync.
- One-shot effects do not repeat during forced reconciliation tests.

## Priority 1: Improve Remote Interpolation Under Real Jitter

### Problem

Remote interpolation currently uses tick-based buffers and allows limited extrapolation. At 30 Hz, the default 2-tick render delay is only about 67 ms. This may be too small under jitter, especially if one snapshot is delayed or dropped. Extrapolating remote players can create the exact visual warping the Valve doc warns against.

### Proposed Work

- Increase the default remote render delay to 3 ticks at 30 Hz, about 100 ms, then validate with load tests.
- Increase `EntityStateBuffer` history from 5 snapshots to a configurable 8-10 snapshots so the client has enough history for jitter and compensation.
- Track interpolation by server timestamp or server tick plus measured tick interval, and prefer finding snapshots that straddle the render target.
- Make interpolation delay adaptive within safe bounds: grow during jitter, shrink slowly after stability returns.
- Disable or reduce extrapolation for remote players and monsters by default. Freezing briefly is often less damaging than showing enemies in guessed future positions.
- Keep projectile extrapolation separate. Projectiles are more ballistic than players and may tolerate short extrapolation.
- Track `interpolation_underrun`, `extrapolation_used`, and `freeze_used` per entity type.

### Acceptance Criteria

- Under a test with one missed state update, remote entities continue smoothly without large warp.
- Under sustained jitter, interpolation delay adapts but does not exceed a configured maximum.
- Remote players do not rubber-band forward due to speculative extrapolation.

## Priority 1: Make Snapshot Sending Budget-Aware

### Problem

The server currently builds entity state every tick and sends per-client deltas. AoI, LOD, and batching are already present, but the sender still needs an explicit budget model so a crowded arena degrades gracefully instead of saturating the connection or spending too much CPU per client.

### Proposed Work

- Add a per-peer send budget in bytes/sec and bytes/tick.
- Prioritize state fields and entities before encoding:
  - Local player authoritative state and corrections.
  - Nearby enemy players.
  - Nearby projectiles.
  - Nearby monsters in combat.
  - Game events.
  - Mid/far monsters and idle entities.
  - Cosmetic-only or low-importance state.
- Stagger full baseline packets across clients so all clients do not receive heavy baselines on the same server tick.
- Make LOD intervals configurable in `client/data/config/server_config.json`, not only in defaults.
- Record entities skipped by budget separately from entities skipped by zero delta.
- Preserve reliable delivery for critical events and explicit despawns. Snapshots can be dropped or superseded; events generally should not.
- Avoid sending empty delta packets unless the client needs heartbeat-like snapshot cadence for tick tracking.

### Acceptance Criteria

- Target load stays under 5 KB/s per player without severe correction spikes.
- Clustered load test has bounded bandwidth and does not create packet storms.
- Full baseline spikes are visible in metrics and spread over time.

## Priority 1: Reduce Server Hot-Path Allocations

### Problem

The server hot path creates arrays and dictionaries every tick for all entities and then per client. This is pragmatic and readable, but it can become expensive with 100 players, 100 monsters, active projectiles, and per-client AoI/delta work.

### Proposed Work

- Profile allocations and tick cost before changing structure.
- Replace repeated per-tick dictionaries in the broadcast path with lightweight typed state records or reusable buffers.
- Reuse `PacketWriter` buffers where practical.
- Avoid duplicating entity dictionaries just to tag `_lod`; store LOD separately or use a transient typed record.
- Avoid unnecessary `PackedByteArray.slice()` in batch receive hot paths if profiler shows it is expensive.
- Pool projectile nodes, damage numbers, particles, and remote entity visuals on the client.
- Disable `_process` and `_physics_process` on inactive or pooled nodes.

### Acceptance Criteria

- Server average and P95 tick time improve in target and stress tests.
- Object/allocation counts per second decrease in the broadcast path.
- Client frame-time spikes during entity spawn/despawn bursts decrease.

## Priority 1: Add Spatial Partitioning For AoI, AI, And Collision

### Problem

AoI filtering currently compares each visible candidate to each player. Collision and AI systems likely have similar scaling pressure. This is acceptable at small counts but becomes O(players * entities) or worse under target/stress load.

### Proposed Work

- Add a server-side spatial hash/grid sized around gameplay ranges, for example 100-200 world units per cell.
- Insert players, monsters, and projectiles into the grid each tick or when they move.
- Query nearby cells for:
  - AoI candidate selection.
  - Projectile collision candidates.
  - Monster detection and retargeting.
  - Spawn validation and anti-stacking checks.
- Keep grid logic deterministic and server-only.
- Add metrics for broadphase candidate count versus final accepted count.

### Acceptance Criteria

- AoI candidate checks scale with local density, not total entity count.
- Clustered tests still work correctly and expose worst-case load honestly.
- Collision tests still pass for map bounds, obstacles, players, monsters, and projectiles.

## Priority 1: Clarify Lag Compensation Boundaries

### Problem

PvE projectile lag compensation exists and is bounded by `MAX_PVE_PROJECTILE_COMPENSATION_TICKS`. The system should formalize which gameplay interactions are compensated and which are not. This avoids fairness regressions when PvP or new weapons are added.

### Proposed Work

- Keep PvE projectile compensation bounded and validate it with monster position history length.
- Track compensation source: client render tick, clamped client render tick, RTT fallback, or none.
- Add metrics for compensation ticks used and clamped compensation count.
- Do not add broad PvP projectile compensation without a design decision. PvP compensation needs stricter caps because "shot around corner" complaints are a design tradeoff, not only a technical issue.
- If instant-hit PvP weapons are added, implement server-side rewind against historical player states using client render tick plus interpolation delay, capped by a maximum rewind window.
- Never trust the client-provided position beyond a tight, latency-derived tolerance.

### Acceptance Criteria

- PvE shots against moving monsters feel consistent at normal latency and remain bounded at high latency.
- Compensation cannot rewind beyond the configured cap.
- PvP behavior is documented before implementation.

## Priority 2: Improve Client-Side Rendering Costs

### Problem

Network performance and frame performance interact. If the client hitches while processing spawns, particles, HUD updates, or minimap work, networking will feel worse even if packets arrive on time.

### Proposed Work

- Pool remote player, monster, projectile, particle, and damage-number nodes.
- Decouple HUD updates from per-frame loops where possible. Update only when values change or at a low fixed UI rate.
- Throttle minimap and server-status refreshes.
- Use signals for state changes rather than polling where practical.
- Cache node references and avoid repeated scene-tree lookups in hot paths.
- Keep server/headless mode free of client-only visual/audio work.

### Acceptance Criteria

- Client frame time remains stable during spawn/despawn bursts.
- HUD and minimap updates do not show up as meaningful spikes in profiler captures.
- Headless server mode does not instantiate client-only visual/audio systems beyond required autoload guards.

## Priority 2: Evaluate Transport Options

### Problem

The current WebSocket transport is simple and compatible, but it is TCP-based. TCP head-of-line blocking can make real-time snapshots arrive late behind older data. Batching helps overhead, but it does not change TCP delivery semantics.

### Proposed Work

- Keep WebSocket as the baseline until instrumentation shows it is the bottleneck.
- Prototype a UDP-style transport path only after P0/P1 work is measured.
- Evaluate Godot ENet or WebRTC data channels for:
  - Unreliable snapshots.
  - Reliable game events.
  - Ordered or unordered channels by message type.
  - NAT/firewall/deployment complexity.
- Define a transport abstraction before rewriting gameplay code.

### Acceptance Criteria

- A prototype demonstrates better behavior under packet loss/jitter than WebSocket in the same load tests.
- Deployment requirements are documented.
- The protocol preserves reliable delivery for critical events and allows snapshots to be superseded.

## Testing Plan

### Baseline

Run before and after each meaningful change:

- `python load_testing/bot_swarm.py --scenario baseline`
- `python load_testing/bot_swarm.py --scenario target`
- `python load_testing/bot_swarm.py --scenario clustered`
- `python load_testing/bot_swarm.py --scenario combat`

### Network Conditions

Add a repeatable network impairment layer or proxy tests for:

- 50 ms RTT, 0% loss.
- 100 ms RTT, 1% loss, 20 ms jitter.
- 150 ms RTT, 2% loss, 40 ms jitter.
- One dropped state update every few seconds.
- Burst loss of 2-3 consecutive state updates.

### Correctness Tests

Add automated tests for:

- Input sequence wrap and ack pruning.
- Prediction replay determinism.
- Full-state baseline recovery after a broken delta chain.
- Explicit despawn through AoI exit.
- Entity-count overflow/pagination behavior.
- Teleport/respawn buffer clearing.
- Projectile compensation clamping.

## Rollout Plan

### Phase 1: Measurement And Safety

- Add detailed performance metrics.
- Fix stale tick-rate comments and config surfacing.
- Add hard warnings/tests for state entity-count overflow.
- Add deterministic movement and prediction replay tests.

### Phase 2: Smoothing And Bandwidth

- Tune interpolation delay and buffer size using jitter tests.
- Add budget-aware snapshot prioritization.
- Stagger full baselines.
- Add per-client delta/budget metrics to load-test reports.

### Phase 3: CPU And Allocation

- Profile server broadcast, AoI, collision, AI, and packet encode/decode paths.
- Introduce spatial partitioning.
- Replace high-allocation hot-path dictionaries where profiler data justifies it.
- Pool high-churn client visuals.

### Phase 4: Advanced Protocol Work

- Evaluate transport abstraction and unreliable snapshot delivery.
- Decide PvP lag-compensation policy before implementing PvP rewind.
- Consider protocol versioning and chunked state-update formats.

## Open Questions

- What is the intended maximum concurrent projectile count at 100 players?
- Should the server support more than 100 active monsters in future regions?
- Is the design target 30 Hz long-term, or should we plan for 60 Hz competitive modes?
- Is WebSocket required for deployment simplicity, or can a UDP-like transport be introduced later?
- How much "shot around corner" behavior is acceptable for PvP if lag compensation is added?
- Should clients be allowed to tune interpolation delay, or should the server/client choose it automatically?

## Recommended Next Step

Start with Phase 1. It is the lowest-risk work and will make every later optimization measurable. The highest immediate correctness risks are silent state-update truncation, stale 20 Hz assumptions in comments/config, and lack of direct metrics for interpolation underruns and prediction corrections.
