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
| Phase 2 | **In progress** | priority/budget snapshot scheduler exists & is wired; #15 (diagnostics→ServerMetrics) and #13 (per-client rate budget) are the open tail |
| Phases 3–6 | **Planned** | #9 spatial grid, #11/#7 wire+PvP, #12 transport |

Note: several of the highest-felt fixes (#1, #2, #4) are **client-render / ownership** problems
that the `plans/` docs barely cover — they came out of the latency/smoothness investigation in
[`../../netcode/`](../../netcode/), not the bandwidth-focused plans. They lead this list because
they are what actually make localhost feel sluggish.

---

## P0 — decisive, small. Do these first.

### 1. The "30 fps at 100 fps" stutter — enable physics interpolation
- **Problem:** Every visible node position is written only in `_physics_process` (30 Hz) and Godot's physics interpolation is off, so motion steps 30×/s at any frame rate.
- **Fix:** Set `physics/common/physics_interpolation = true`; call `reset_physics_interpolation()` on every discontinuity (spawn / teleport / hard correction); read the camera from `local_player.get_global_transform_interpolated()` instead of raw `.position`.
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
- **Problem:** Remote entities are always drawn 2 Ticks (66.7 ms) in the past regardless of connection quality, so even localhost play feels laggy on everyone else's motion.
- **Fix:** Drive Render delay from measured jitter/RTT: collapse toward ~1 Tick on a clean LAN, grow under jitter, capped. Pair with timestamp-straddle interpolation (#6) so spaced Snapshots stay smooth.
- **Evidence:** fixed `REMOTE_ENTITY_RENDER_DELAY_TICKS=2` at `game_constants.gd:20`; applied `interpolation_controller.gd:11,186`.
- **Effort:** small · **Impact:** high · **Status:** Planned
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
- **Problem:** PvP collision uses the *current* Tick, a point-distance check, no rewind and no swept path — so projectiles tunnel through players (~13 px/Tick at 400 u/s vs a 24 px hit window) and you must lead targets. The client also shows **no** muzzle/tracer until the full round-trip, since projectiles spawn only from server `STATE_UPDATE`. (PvE already lag-compensates with a swept segment, cap 6 Ticks / 200 ms.)
- **Fix:** Mirror the PvE rewind for players (stricter cap, ~4 Ticks per the "shooting around corners" rule); replace point-distance with a swept-segment test; add **client-side muzzle/tracer feedback** on shoot input (cosmetic only — damage stays server-confirmed).
- **Evidence:** PvP point-distance, current Tick `projectile_manager.gd:251,269`; client spawns projectiles only from state `client_entity_manager.gd:114`; PvE cap `game_constants.gd` (`MAX_PVE_PROJECTILE_COMPENSATION_TICKS`).
- **Effort:** medium · **Impact:** high · **Status:** Planned (**Phase 5** in `plans/NETWORK_PERFORMANCE_UPGRADES.md §4`; depends on #9 grid + clock sync from Phase 1).
- See: [`../../systems/combat-hits.md`](../../systems/combat-hits.md) · [`../../netcode/interpolation.md`](../../netcode/interpolation.md) (Render delay the shooter saw).

### 8. Input/Tick at 30 Hz limits responsiveness — evaluate 60 Hz
- **Problem:** Input is sampled and sent at 30 Hz inside `_physics_process`; raising to 60 Hz halves input latency and the per-Tick stutter floor — but doubles client prediction/interpolation CPU and roughly doubles upstream packet rate.
- **Fix:** Trial `physics_ticks_per_second=60` (input cadence follows it via `INPUT_SEND_INTERVAL`); measure CPU and bandwidth against the budgets before committing. Complement to #1, not a replacement.
- **Evidence:** sample+send in `_physics_process` `prediction.gd:142,157`; cadence derives from tick `prediction.gd:71` (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`); tick `project.godot:102`.
- **Effort:** medium · **Impact:** medium · **Status:** Planned
- See: [`../../netcode/smoothness-render.md`](../../netcode/smoothness-render.md) ("Raise 30→60" alternative), [`../../netcode/performance-budgets.md`](../../netcode/performance-budgets.md).

### 9. AoI is O(N²) per Snapshot — add a spatial-grid broad-phase
- **Problem:** Broadcast filters AoI per player → O(players × entities) every Snapshot Tick, with no shared spatial broad-phase. `projectile_manager` has a 64-unit collision grid but it is not reused for AoI.
- **Fix:** Promote that ad-hoc grid into a shared `spatial_grid.gd` (cell ≈ aoi_radius/4) built once per Tick; AoI, projectile broad-phase, and monster spawn-validity query it.
- **Evidence:** per-player AoI scan `server_broadcast_service.gd:86-120`; existing collision grid `projectile_manager.gd` (`_build_entity_grid` / `_query_nearby`).
- **Effort:** medium · **Impact:** high (at scale; low felt at small counts) · **Status:** Planned (**Phase 3**, `plans/NETWORK_PERFORMANCE_UPGRADES.md §3.1`).
- See: [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md).

### 10. AoI radius barely culls — tune it down vs the map
- **Problem:** AoI enter radius 1000 on a 2000×2000 Arena covers ~78% of the map, so when players cluster it culls almost nothing — defeating the point of AoI.
- **Fix:** Lower enter/exit radii (keep hysteresis) so AoI meaningfully bounds visible entity count at the cluster; validate against the `clustered` load scenario. Cheap once #9 lands.
- **Evidence:** `aoi_radius=1000` / exit 1100 `data/config/server_config.json` + `server_broadcast_service.gd:24,30`; map bounds `game_constants.gd` (MAP_MIN/MAP_MAX ±1000).
- **Effort:** small · **Impact:** medium · **Status:** Planned
- See: [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md).

### 11. `entity_count` u8 caps a Snapshot at 255 entities (silent truncation) — widen to u16
- **Problem:** Per-Snapshot entity count is written as u8, so any Snapshot with >255 entities silently drops the overflow — and forced full-state baselines have no byte budget, so a crowded baseline truncates with no signal.
- **Fix:** Widen the count field to u16 (wire-version bump); add a metric/warning when a Snapshot would exceed the count. The budget scheduler (#13) makes 255 less likely but does not remove the hard cap.
- **Evidence:** `state_update_packet.gd:194,207` (`write_u8(mini(entities.size(), 255))`), decode `:250,264`.
- **Effort:** medium (wire change) · **Impact:** medium · **Status:** Planned (**Phase 4** wire batch, `plans/NETWORK_PERFORMANCE_UPGRADES.md §2`; the truncation risk is flagged P0 in `plans/CODEX…`).
- See: [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md).

---

## P3 — architecture. Larger surface; do after the wins above are measured.

### 12. WebSocket/TCP head-of-line blocking — move state to datagrams
- **Problem:** All traffic is WebSocket-over-TCP both directions, so one lost segment stalls **all** subsequent state until retransmit — exactly the wrong failure mode for continuous Snapshots.
- **Fix:** Keep WebSocket for the reliable channel (auth, Game events, leaderboard); move `STATE_UPDATE` + `PLAYER_INPUT` to a WebRTC/WebTransport datagram channel with WebSocket fallback. Define a transport abstraction first.
- **Evidence:** server `TCPServer.listen` + `WebSocketPeer.accept_stream`, client `connect_to_url` in `network_manager.gd`; polled per Frame in `_process`.
- **Effort:** large · **Impact:** high (on lossy WAN; ~nil on localhost) · **Status:** Planned (**Phase 6**, `plans/NETWORK_PERFORMANCE_UPGRADES.md §6`).
- See: [`../../netcode/transport-websocket.md`](../../netcode/transport-websocket.md), [`../../adr/0001-websocket-tcp-transport.md`](../../adr/0001-websocket-tcp-transport.md).

### 13. No per-client bandwidth budget — add a `rate` ceiling
- **Problem:** The priority scheduler defers per-Snapshot bytes (`max_snapshot_bytes=1200`) but there is no per-second per-peer ceiling, so a marginal connection can still be saturated.
- **Fix:** Clients advertise a bytes/sec budget in `CONNECT_AUTH`; scheduler sizes `max_snapshot_bytes = budget / effective_snapshot_rate` and gates non-essential events. Hard-cap server-side.
- **Evidence:** budget field exists `server_broadcast_service.gd` (`max_snapshot_bytes`) + `snapshot_scheduler.gd`; no per-sec gate yet.
- **Effort:** medium (wire change) · **Impact:** medium · **Status:** Planned (**Phase 2 / §1.3** — the open tail of the in-progress phase).
- See: [`../../netcode/server-tick-broadcast.md`](../../netcode/server-tick-broadcast.md).

### 14. Baselines are never acked — add baseline acks
- **Problem:** A forced full-state Baseline is sent every 100 Ticks with no acknowledgement, so a dropped Baseline leaves the client diffing deltas against a stale base until the next forced one.
- **Fix:** Have clients ack the Baseline Tick; server tracks per-peer acked Baseline and resends on gap instead of waiting for the 100-Tick cadence.
- **Evidence:** forced baseline cadence in `state_update_packet.gd` / `server_broadcast_service.gd` (no ack path).
- **Effort:** medium · **Impact:** low (medium under loss) · **Status:** Planned
- See: [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md).

### 15. Scheduler diagnostics not surfaced — plumb them to ServerMetrics
- **Problem:** The Phase 2 scheduler computes `deferred_count`, `max_queue_age_ticks`, `peers_at_budget` into `last_tick_diagnostics`, but they never reach `ServerMetrics` / the `SERVER_METRICS` packet — so you can't see whether the queue is starving entities.
- **Fix:** Copy `broadcast_service.last_tick_diagnostics` into `ServerMetrics.update_metrics` and the `SERVER_METRICS` payload; surface in the HUD.
- **Evidence:** diagnostics produced in `snapshot_scheduler.gd` + `server_broadcast_service.gd` (`last_tick_diagnostics`); not consumed by `server_metrics.gd`.
- **Effort:** small · **Impact:** low (enabling — unblocks tuning #9/#10/#13) · **Status:** In-progress (**Phase 2 / §8.2** open item).
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
| Server walked 1/3 client speed (persistent-input model) | `player_state.gd` ingest/step, `player_manager.gd` | `../../DESYNC_PLAN.md` Fix A |
| Ghost player (Local player never learned its id) | auth defer + `PLAYER_INFO` force-sync, `arena_base.gd` | `../../DESYNC_PLAN.md` Fix B/C |

---

## The eight questions

- **Client:** fixes #1, #2, #4, #6, the feedback half of #7, and #8's cadence are client-render / prediction / interpolation changes.
- **Server:** #3, #5, #7 rewind, #9, #10, #11, #13, #14, #15 are authoritative-server / broadcast changes.
- **Predicted:** the Local player (sole owner must be `PredictionController`, #2); #7 adds cosmetic-only client shoot prediction (no predicted damage).
- **Replicated:** Remote entities via Snapshots — #3/#4/#6 govern their cadence and smoothness; #9/#10/#11/#13/#14 govern what/how much is replicated.
- **Persisted:** nothing here touches persistence — all gameplay state stays in-memory; the Go API owns only accounts/characters/leaderboard.
- **Validated:** server stays authoritative for every fix; #7 keeps damage server-confirmed, client shows only cosmetics.
- **Can fail:** #1 without `reset_physics_interpolation()` → lerp across teleports; #7 PvP rewind without a cap → "shot around corners"; #11 left as u8 → silent entity drop >255; #12 datagram negotiation failure → must fall back to WebSocket.
- **Tested:** `load_testing/bot_swarm.py` scenarios (baseline/target/clustered/combat/stress) + `regression_assertions.py` (AoI cull, LOD cadence, batch-decode) gate #3/#9/#10/#11/#13; #1/#2/#7 need manual play-test + smoke test (no automated frame-pacing/feel test today).

## See also

- [`../../netcode/smoothness-render.md`](../../netcode/smoothness-render.md) — fix #1, full design
- [`../../netcode/latency-budget.md`](../../netcode/latency-budget.md) — start-here latency accounting (#3, #4)
- [`../../netcode/client-prediction.md`](../../netcode/client-prediction.md) · [`../../netcode/interpolation.md`](../../netcode/interpolation.md) · [`../../netcode/server-tick-broadcast.md`](../../netcode/server-tick-broadcast.md)
- [`../../netcode/interest-mgmt-aoi.md`](../../netcode/interest-mgmt-aoi.md) · [`../../netcode/wire-protocol.md`](../../netcode/wire-protocol.md) · [`../../netcode/transport-websocket.md`](../../netcode/transport-websocket.md)
- [`../../systems/combat-hits.md`](../../systems/combat-hits.md) · [`../../systems/players-movement.md`](../../systems/players-movement.md)
- Detailed source plans (superseded by this ordering): [`../../../plans/NETWORK_PERFORMANCE_UPGRADES.md`](../../../plans/NETWORK_PERFORMANCE_UPGRADES.md) · [`../../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md`](../../../plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md) · [`../../../plans/RECOMMENDATIONS.md`](../../../plans/RECOMMENDATIONS.md) · [`../../DESYNC_PLAN.md`](../../DESYNC_PLAN.md)
