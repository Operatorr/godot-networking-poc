# Active exec-plan — prioritized netcode performance fixes

**Status:** Active (verified 2026-06-03 against code)

> This is the **roadmap** and the single entry point for netcode performance work. It supersedes
> the four detailed plans in `plans/` (linked below) as the *ordering* of work: read this for
> *what to do next and why*, then drop into the cited plan for the *full design*.
>
> Ordering is **impact-on-felt-sluggishness first, then effort.** "Felt sluggishness" = the
> visceral "looks like 30 fps / steering a boat / molasses" complaint, distinct from raw ping.
> The two cheapest fixes (P0) are also the most decisive — do them first.

## How to read this

Each fix is one row. Columns: **problem** (1 line) · **fix** · **evidence** (`file:line`) ·
**effort** (trivial / small / medium / large) · **impact** (decisive / high / medium / low) ·
**status** (Done / In-progress / Planned). Terms follow [`../../CONTEXT.md`](../../CONTEXT.md)
(Tick ≠ Frame ≠ Snapshot; Render delay; AoI; Reconciliation; Lag compensation).

Mapping to the `plans/` phases (so you can see what's already shipped):

| `plans/` phase | State | Covers fixes here |
| --- | --- | --- |
| Phase 1 | **Shipped** | per-channel byte metrics, AoI dict-alloc removal, clock sync, teleport-parity, decoupled snapshot rate (the *knob* behind #3) |
| Phase 2 | **Shipped** | priority/budget snapshot scheduler; #15 (diagnostics→ServerMetrics) and #13 (per-client rate budget) **done 2026-06-04** |
| Phases 3–6 | **Shipped** | #9 spatial grid, #10 AoI tune, #11 wire u16, #7 PvP lag-comp, #12 transport seam, #14 baseline acks **done 2026-06-04** (#12 ENet impl behind the seam is still deferred) |

Note: several of the highest-felt fixes (#1, #2, #4) are **client-render / ownership** problems
that the `plans/` docs barely cover — they came out of the latency/smoothness investigation in
[`../../netcode/`](../../netcode/), not the bandwidth-focused plans. They lead this list because
they are what actually make localhost feel sluggish.

---

## ⚑ Applied on branch `perf/p0-p1-netcode-fixes` (2026-06-03 — pending play-test)

Fixes **#1, #2, #3, #4, #5, #6** below are **implemented** on that branch (headless import
parses clean; the *feel* is not yet play-tested). When the branch merges,
fold these into "Already done" and flip the affected netcode docs' status tags.

## ⚑ P2/P3 batch landed (2026-06-04)

Fixes **#7, #8, #9, #10, #11, #12, #13, #14, #15** below are **implemented** (headless import
parses clean). Their rows are marked **Status: Done (2026-06-04)** in place. The one caveat: #12
ships only the **transport seam** (`Transport` / `WebSocketTransport`) — the ENet-over-UDP impl
behind it is a deferred, human-approved follow-up (see
[`../../adr/0003-enet-udp-transport.md`](../../adr/0003-enet-udp-transport.md)). #14 (baseline
acks) is **inert on today's TCP** transport and only earns its keep once #12's ENet datagram path
lands.

## P0 — decisive, small. Do these first.

### 1. The "30 fps at 100 fps" stutter — enable physics interpolation
- **Problem:** Every visible node position is written only in `_physics_process` (30 Hz) and Godot's physics interpolation is off, so motion steps 30×/s at any frame rate.
- **Fix:** Set `physics/common/physics_interpolation = true`; call `reset_physics_interpolation()` on every discontinuity (spawn / teleport / hard correction); in 2D, drive Camera2D from the local player's post-prediction physics-tick visual position instead of raw render-frame `.position` because `get_global_transform_interpolated()` is 3D-only.
- **Evidence:** `project.godot:100-103` (tick 30, no interpolation key → off); writes in `prediction.gd:602-607`, `interpolation_controller.gd:454`; camera reads raw position at `arena_base.gd:122-123`.
- **Effort:** small · **Impact:** decisive · **Status:** Planned
- Full design: [`../../netcode/smoothness-render.md`](../../netcode/smoothness-render.md) — this is fix #1 there too.

### 2. Double-movement ("steering a boat") — make PredictionController the sole local mover
- **Problem:** After Authority sync the arena re-enables `Player.gd` input, so `Player.gd._physics_process` (CharacterBody2D `move_and_slide`, speed 200) AND `PredictionController` (analytic move, speed 200 / sprint 320) both move the Local player each Tick — two integrators leapfrog.
- **Fix:** Stop calling `set_input_enabled(true)` for the networked Local player; `PredictionController` owns its motion exclusively (`Player.gd` movement stays disabled for the local entity).
- **Evidence:** re-enable sites `arena_base.gd:374`, `:418`, `:493`; predicted writes `prediction.gd:602-607`.
- **Effort:** small · **Impact:** decisive · **Status:** Planned
- Full design: [`../../netcode/client-prediction.md`](../../netcode/client-prediction.md), [`../../systems/players-movement.md`](../../systems/players-movement.md). Invariant noted in [`../../../AGENTS.md`](../../../AGENTS.md) ("Known invariant violations under active fix").

---

## P1 — high impact, small effort.

### 3. Live Snapshot rate is 20 Hz, not 30 — raise to match the Tick
- **Problem:** Tick runs 30 Hz but the runtime config sets `snapshot_rate_hz=20`, so clients get state every 50 ms (66.7 ms older worst-case than the sim) — extra latency and choppier Remote entities than the sim can deliver.
- **Fix:** Set `snapshot_rate_hz: 30` in `client/data/config/server_config.json` (or `0` to follow tick rate). Re-measure bandwidth; only keep 20 if egress is the binding constraint (the budget scheduler #13 is the right way to cut bandwidth, not a blanket rate cut).
- **Evidence:** Tick loop `server_main.gd:170-183`; live override `data/config/server_config.json:10`. The decoupling knob itself is **Phase 1 / Shipped**; this is just the value.
- **Effort:** trivial · **Impact:** high · **Status:** Planned
- See: [`../../netcode/server-tick-broadcast.md`](../../netcode/server-tick-broadcast.md), [`../../netcode/latency-budget.md`](../../netcode/latency-budget.md).

### 4. Render delay is a fixed 66.7 ms — make it adaptive
- **Problem (was):** Remote entities were always drawn 2 Ticks (66.7 ms) in the past regardless of connection quality, so even localhost play felt laggy on everyone else's motion.
- **Fix (done):** Render delay is now driven by measured inter-arrival **jitter**: `render_delay_ticks_smooth = clamp(1 interval + 2× jitter, MIN=1, MAX=3 ticks)`, with **asymmetric** adaptation (grow fast on a jitter spike, shrink slowly when clean), applied as `render_tick = server_tick − round(render_delay_ticks_smooth)`. Collapses toward ~33 ms (1 Tick) on a clean LAN/localhost; grows under jitter to avoid extrapolation/freeze. (Jitter-driven, not raw-RTT — the buffer only needs to hide arrival variance.)
- **Evidence:** `interpolation_controller.gd:206-226`; bounds `:16-17` (`MIN/MAX_RENDER_DELAY_TICKS = 1/3`); seed `game_constants.gd` `REMOTE_ENTITY_RENDER_DELAY_TICKS=2`.
- **Effort:** small · **Impact:** high · **Status:** Done (2026-06-10).
- See: [`../../netcode/interpolation.md`](../../netcode/interpolation.md), [`../../netcode/latency-budget.md`](../../netcode/latency-budget.md). (`plans/CODEX…` P1 "interpolation under jitter" argues the *opposite* — raise to 3 ticks for safety. Resolve per-target: localhost wants lower, lossy WAN wants higher. Adaptive subsumes both.)

### 5. Paired-shots — one trigger pull fires twice
- **Problem:** `_process_shoot_inputs` fires from two paths in one Tick — drained rising-edge `pending_shots` AND held auto-fire — and rising-edge can over-count when ≥2 input packets land in one Tick (the whole queue is drained, each edge appended).
- **Fix:** Dedup: in a Tick, either the rising-edge shot OR the held-auto-fire shot fires, not both; snapshot the held/edge state once before draining so multiple queued inputs in one Tick can't multiply edges. (Client doubling is **refuted** — `Player.gd` local projectile spawn is disabled at `arena_base.gd:220`.)
- **Evidence:** dual fire `server_main.gd:284-293`; full-queue drain `player_manager.gd:111`; edge detect/append `player_state.gd:147-158`.
- **Effort:** small · **Impact:** high · **Status:** Planned
- See: [`../../systems/combat-hits.md`](../../systems/combat-hits.md).

### 6. Interpolation timing seeded from 20 Hz — seed from the real Tick interval
- **Problem:** Two interpolation constants assume a 50 ms (20 Hz) Tick while the server runs 30 Hz (33.3 ms), causing micro-stutter until the EMA estimate converges; comments saying "20Hz"/"250ms"/"150ms" are stale.
- **Fix:** Initialize `estimated_tick_interval` and the buffer's `TICK_INTERVAL_SEC` from `GameConstants.SERVER_TICK_INTERVAL`; fix the stale comments. (`plans/CODEX…` P0 "stale constants" tracks this.)
- **Evidence:** `interpolation_controller.gd:75` (`estimated_tick_interval = 0.05`); `entity_state_buffer.gd:14` (`TICK_INTERVAL_SEC=0.05`); correct source `game_constants.gd:18`.
- **Effort:** trivial · **Impact:** medium · **Status:** Planned
- See: [`../../netcode/interpolation.md`](../../netcode/interpolation.md).

---

## P2 — high impact, medium effort.

### 7. PvP hits use no lag compensation and tunnel — add rewind + swept test + client feedback
- **Problem (was):** PvP collision used the *current* Tick, a point-distance check, no rewind and no swept path — so projectiles tunneled through players (~13 px/Tick at 400 u/s vs a 24 px hit window) and you had to lead targets. The client also showed **no** muzzle feedback until the full round-trip, since projectiles spawned only from server `STATE_UPDATE`. (PvE already lag-compensated with a swept segment, cap 6 Ticks / 200 ms.)
- **Fix (done):** `check_collisions_with_players` now rewinds each player roster to a per-projectile PvP lag-comp tick (`get_lag_compensated_player_tick`) drawn from `PlayerManager.record_position_snapshot` history, and tests the swept segment `previous_position → position` with `_closest_point_on_segment` — mirroring the PvE path. The rewind is capped stricter than PvE at `MAX_PVP_PROJECTILE_COMPENSATION_TICKS=4` (~133 ms) so a peeker who broke line of sight can't be retro-hit. Client draws a **cosmetic muzzle flash** on the SHOOT rising edge (`PredictionController.shoot_predicted` → `arena_base._on_local_shoot_predicted`); damage stays server-confirmed. *(A cosmetic shot tracer was also added here but later removed per play-test feedback — it read like a hitscan beam.)*
- **Evidence:** swept PvP rewind `projectile_manager.gd:273-331`,`:302`; rewind tick `projectile_state.gd:158-161`; player history `player_manager.gd:256-285`, recorded `server_main.gd:254`; PvP cap clamp `server_main.gd:382-386`, `game_constants.gd:45` (`MAX_PVP_PROJECTILE_COMPENSATION_TICKS=4`); shoot edge `prediction.gd:281-302`, handler `arena_base.gd:764`; local spawn stays disabled `arena_base.gd:244`.
- **Effort:** medium · **Impact:** high · **Status:** Done (2026-06-04).
- See: [`../../systems/combat-hits.md`](../../systems/combat-hits.md) · [`../../netcode/interpolation.md`](../../netcode/interpolation.md) (Render delay the shooter saw).

### 8. Input/Tick at 30 Hz limits responsiveness — evaluate 60 Hz
- **Problem:** Input is sampled and sent at 30 Hz inside `_physics_process`; raising to 60 Hz halves input latency and the per-Tick stutter floor — but doubles client prediction/interpolation CPU and roughly doubles upstream packet rate.
- **Fix (done — toggle + protocol, default stays 30):** `GameConstants.SERVER_TICK_RATE` is now the single client-side tick authority; `game_manager._ready()` applies it via `Engine.physics_ticks_per_second`, and `server_config.gd`'s default `tick_rate` derives from it (with a `GAME_SERVER_TICK_RATE` env override; JSON still wins for the server sim). The 30-vs-60 **measurement protocol** is captured in [`../../netcode/perf-notes/tick-rate-30-vs-60.md`](../../netcode/perf-notes/tick-rate-30-vs-60.md) (**results PENDING** — no load run yet). **Default is 30 Hz** and stays 30 until a run proves 60 fits the budgets.
- **Evidence:** single authority `game_constants.gd:22` (`SERVER_TICK_RATE := 30.0`); client clock `game_manager.gd:70`; config default `server_config.gd:13`, env override `server_config.gd:161-164`; send cadence `prediction.gd:73` (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`).
- **Effort:** medium · **Impact:** medium · **Status:** Done (2026-06-04) — toggle + protocol shipped; **60 Hz measurement pending**, default 30.
- See: [`../../netcode/smoothness-render.md`](../../netcode/smoothness-render.md) ("Raise 30→60" alternative), [`../../netcode/perf-notes/tick-rate-30-vs-60.md`](../../netcode/perf-notes/tick-rate-30-vs-60.md), [`../../netcode/performance-budgets.md`](../../netcode/performance-budgets.md).

### 9. AoI is O(N²) per Snapshot — add a spatial-grid broad-phase
- **Problem (was):** Broadcast filtered AoI per player → O(players × entities) every Snapshot Tick, with no shared spatial broad-phase. `projectile_manager` had a 64-unit collision grid but it was not reused for AoI.
- **Fix (done):** New `spatial_grid.gd` (`class_name SpatialGrid`); the broadcast service builds **one shared current-tick grid** via `build_aoi_grid` and the per-peer AoI scan queries it (`query_radius`) instead of walking every entity. Same visible-set semantics. Projectile/monster collision grids are unchanged.
- **Evidence:** new grid `spatial_grid.gd:7` (`SpatialGrid`),`:53` (`query_radius`); shared grid built `server_main.gd:269`, `server_broadcast_service.gd:79-103`; AoI query `server_broadcast_service.gd:161`.
- **Effort:** medium · **Impact:** high (at scale; low felt at small counts) · **Status:** Done (2026-06-04).
- See: [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md).

### 10. AoI radius barely culls — tune it down vs the map
- **Problem (was):** AoI enter radius 1000 on a 2000×2000 Arena covers ~78% of the map, so when players cluster it culled almost nothing — defeating the point of AoI.
- **Fix (done):** Enter radius 1000→**700**, exit 1100→**800** (keeps hysteresis). 700 stays gameplay-safe: it is ≥ `MONSTER_DETECTION_RANGE` (650), so a monster that can aggro a player is always inside that player's AoI. `regression_assertions.py` defaults updated to 700/800 in lockstep.
- **Evidence:** defaults `server_config.gd:19` (`aoi_radius:700.0`),`:23` (`aoi_exit_radius:800.0`); JSON `data/config/server_config.json` (`aoi_radius:700.0`, `aoi_exit_radius:800.0`); detection range `game_constants.gd:347` (`MONSTER_DETECTION_RANGE:650.0`); harness `load_testing/regression_assertions.py:29-30`.
- **Effort:** small · **Impact:** medium · **Status:** Done (2026-06-04).
- See: [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md).

### 11. `entity_count` u8 caps a Snapshot at 255 entities (silent truncation) — widen to u16
- **Problem (was):** Per-Snapshot entity count was written as u8, so any Snapshot with >255 entities silently dropped the overflow.
- **Fix (done):** `entity_count` widened **u8 → u16** in both full-state and delta paths (encode + decode); `STATE_MAX_ENTITIES=65535` added. The old hard 255 cap is **gone** — the real ceiling is now the `MAX_PACKET_SIZE`/byte budget, not the count field. The broadcast service tracks `snapshot_count_overflow` and `push_warning`s on the (now far rarer) wire-cap overflow. The Python bot decoder was updated in lockstep. No `PROTOCOL_VERSION` constant was added.
- **Evidence:** `state_update_packet.gd:195-196,210-211` (`write_u16(mini(.., STATE_MAX_ENTITIES))`), decode `:254,268`; `packet_types.gd:13` (`STATE_MAX_ENTITIES:=65535`); overflow metric `server_broadcast_service.gd:509-510`.
- **Effort:** medium (wire change) · **Impact:** medium · **Status:** Done (2026-06-04).
- See: [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md).

---

## P3 — architecture. Larger surface; do after the wins above are measured.

### 12. WebSocket/TCP head-of-line blocking — move state to datagrams
- **Problem:** All traffic is WebSocket-over-TCP both directions, so one lost segment stalls **all** subsequent state until retransmit — exactly the wrong failure mode for continuous Snapshots.
- **Fix (seam done; ENet impl deferred):** A **transport abstraction seam** now exists — `transport.gd` (`class_name Transport`) + `websocket_transport.gd` (`class_name WebSocketTransport`); `network_manager.gd` delegates every raw socket verb through it with **zero behaviour / wire change**. The datagram target is **ENet-over-UDP** (not WebRTC/WebTransport — the game is native-only and the server will be ported to Rust, so `rusty_enet` keeps one wire format across both languages). The ENet `Transport` subclass is a deferred, human-approved follow-up; `STATE_UPDATE`+`PLAYER_INPUT` ride unreliable/unsequenced ch0, reliable traffic ch1. Recorded in [ADR 0003](../../adr/0003-enet-udp-transport.md), which supersedes 0001's substrate.
- **Evidence:** seam `client/scripts/network/transport/transport.gd:22`, `websocket_transport.gd:11`; ADR `../../adr/0003-enet-udp-transport.md`.
- **Effort:** large · **Impact:** high (on lossy WAN; ~nil on localhost) · **Status:** Done — seam landed (2026-06-04); **ENet datagram impl deferred** (human-approved follow-up).
- See: [`../../netcode/transport-websocket.md`](../../netcode/transport-websocket.md), [`../../adr/0003-enet-udp-transport.md`](../../adr/0003-enet-udp-transport.md).

### 13. No per-client bandwidth budget — add a `rate` ceiling
- **Problem (was):** The priority scheduler deferred per-Snapshot bytes (`max_snapshot_bytes=1200`) but there was no per-second per-peer ceiling, so a marginal connection could still be saturated.
- **Fix (done):** `CONNECT_AUTH` gained a trailing `[u32 bandwidth_budget_bps]` (length-gated read; old clients fall back to the server default). The server clamps the advertised budget to `[min,max]` config and derives a per-peer `max_snapshot_bytes = clamp(budget / snapshot_rate_hz, MIN_SNAPSHOT_FLOOR=256, max_snapshot_bytes)`. New config keys `default_client_bandwidth_bps=120000`, `max=200000`, `min=24000`.
- **Evidence:** wire field `auth_packet.gd:33,82-85`, client encoder `network_manager.gd:848`; per-peer derive `server_main.gd:51` (`MIN_SNAPSHOT_FLOOR:=256`),`:700-702`; config keys `server_config.gd:43,45,47`; per-peer cap `server_broadcast_service.gd:300-308`.
- **Effort:** medium (wire change) · **Impact:** medium · **Status:** Done (2026-06-04).
- See: [`../../netcode/server-tick-broadcast.md`](../../netcode/server-tick-broadcast.md).

### 14. Baselines are never acked — add baseline acks
- **Problem (was):** A forced full-state Baseline was sent every 100 Ticks with no acknowledgement, so a dropped Baseline left the client diffing deltas against a stale base until the next forced one.
- **Fix (done — inert on TCP):** New `BASELINE_ACK=12` packet (C→S, `[u32 baseline_tick]`). The client acks the `server_tick` of each received full-state Baseline in `interpolation_controller`; the server (`delta_state_cache` + `server_broadcast_service`) tracks per-peer acked/pending Baseline and resends on a gap, retaining the 100-Tick interval as a floor. **Inert on today's TCP** (reliable in-order delivery means Baselines don't drop) — this is forward-looking for the #12 ENet/UDP transport.
- **Evidence:** packet `packet_types.gd:28` (`BASELINE_ACK=12`); client ack `interpolation_controller.gd:185`; server track/resend `delta_state_cache.gd:44-47,210,218-224`, `server_broadcast_service.gd:446-452`; decode `network_manager.gd:1017`.
- **Effort:** medium · **Impact:** low (medium under loss, once on UDP) · **Status:** Done (2026-06-04) — inert on TCP.
- See: [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md), [`../../adr/0003-enet-udp-transport.md`](../../adr/0003-enet-udp-transport.md).

### 15. Scheduler diagnostics not surfaced — plumb them to ServerMetrics
- **Problem (was):** The Phase 2 scheduler computed `entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct` into `last_tick_diagnostics`, but they never reached `ServerMetrics` / the `SERVER_METRICS` packet — so you couldn't see whether the queue was starving entities.
- **Fix (done):** `broadcast_service.last_tick_diagnostics` (`entities_deferred_per_tick`, `max_queue_age_ticks`, `peers_at_budget_pct`, `peers_evaluated`, plus #11's `snapshot_count_overflow`) now flow into `ServerMetrics`, get encoded into the `SERVER_METRICS` packet as appended fixed-length `sched_*` fields, and render in the HUD `server_status` panel.
- **Evidence:** diagnostics `server_broadcast_service.gd:62-67,221-226`; metrics fields `server_metrics.gd:27-31,74-75`; wire encode/decode `network_manager.gd:876-880,1010-1014`; HUD `server_status.gd:65-69,125-127`.
- **Effort:** small · **Impact:** low (enabling — unblocks tuning #9/#10/#13) · **Status:** Done (2026-06-04).
- See: [`../../netcode/performance-budgets.md`](../../netcode/performance-budgets.md).

---

## Already done (context — do not redo)

These shipped in **Phase 1** and in the legacy desync fix; listed so the roadmap is honest about
what's solved.

| Item | Where | Source |
| --- | --- | --- |
| Per-channel byte metrics (`bytes_sent_by_type`) | `network_manager.gd` → `ServerMetrics` | Phase 1 |
| AoI per-entity dict-alloc removed (parallel `PackedByteArray` of LOD) | `server_broadcast_service.gd` | Phase 1 |
| Clock sync (HEARTBEAT carries `server_ms`, client EMA offset) | `network_manager.gd`, 1 Hz | Phase 1 |
| Client/server teleport-threshold parity | `interpolation_controller.gd` ← `GameConstants.TELEPORT_THRESHOLD` | Phase 1 |
| Decoupled Snapshot rate *knob* | `ServerConfig.snapshot_rate_hz` | Phase 1 (value is #3) |
| Priority/budget Snapshot scheduler (built & wired) | `snapshot_scheduler.gd`, `server_broadcast_service.gd` | Phase 2 (diagnostics = #15) |
| Server walked 1/3 client speed (persistent-input model) | `player_state.gd` ingest/step, `player_manager.gd` | legacy desync plan Fix A (historical; see git history) |
| Ghost player (Local player never learned its id) | auth defer + `PLAYER_INFO` force-sync, `arena_base.gd` | legacy desync plan Fix B/C (historical; see git history) |

---

## The eight questions

- **Client:** fixes #1, #2, #4, #6, the feedback half of #7, and #8's cadence are client-render / prediction / interpolation changes.
- **Server:** #3, #5, #7 rewind, #9, #10, #11, #13, #14, #15 are authoritative-server / broadcast changes.
- **Predicted:** the Local player (sole owner must be `PredictionController`, #2); #7 adds cosmetic-only client shoot prediction (no predicted damage).
- **Replicated:** Remote entities via Snapshots — #3/#4/#6 govern their cadence and smoothness; #9/#10/#11/#13/#14 govern what/how much is replicated.
- **Persisted:** nothing here touches persistence — all gameplay state stays in-memory; the Go API owns only accounts/characters/leaderboard.
- **Validated:** server stays authoritative for every fix; #7 keeps damage server-confirmed, client shows only cosmetics.
- **Can fail:** #1 without `reset_physics_interpolation()` → lerp across teleports; #7 PvP rewind is capped at 4 Ticks so a peeker can't be "shot around corners"; #11 is now u16 (overflow only at the far rarer `MAX_PACKET_SIZE`/byte ceiling, which `snapshot_count_overflow` warns on); #12's ENet datagram impl (deferred) must fall back to the `WebSocketTransport` seam on negotiation failure.
- **Tested:** `load_testing/bot_swarm.py` scenarios (baseline/target/clustered/combat/stress) + `regression_assertions.py` (AoI cull, LOD cadence, batch-decode) gate #3/#9/#10/#11/#13; #1/#2/#7 need manual play-test + smoke test (no automated frame-pacing/feel test today).

## See also

- [`../../netcode/smoothness-render.md`](../../netcode/smoothness-render.md) — fix #1, full design
- [`../../netcode/latency-budget.md`](../../netcode/latency-budget.md) — start-here latency accounting (#3, #4)
- [`../../netcode/client-prediction.md`](../../netcode/client-prediction.md) · [`../../netcode/interpolation.md`](../../netcode/interpolation.md) · [`../../netcode/server-tick-broadcast.md`](../../netcode/server-tick-broadcast.md)
- [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md) · [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md) · [`../../netcode/transport-websocket.md`](../../netcode/transport-websocket.md)
- [`../../systems/combat-hits.md`](../../systems/combat-hits.md) · [`../../systems/players-movement.md`](../../systems/players-movement.md)
- Detailed source plans (superseded by this ordering): [`../../../plans/NETWORK_PERFORMANCE_UPGRADES.md`](../../../plans/NETWORK_PERFORMANCE_UPGRADES.md) · [`../../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md) · [`../../../plans/RECOMMENDATIONS.md`](../../../plans/RECOMMENDATIONS.md) · the legacy desync plan (historical; see git history)
