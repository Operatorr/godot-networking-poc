export const meta = {
  name: 'write-netcode-docs',
  description: 'Write the remaining netcode/systems/exec-plan/ADR docs in parallel, grounded in audit findings',
  phases: [{ title: 'Write docs', detail: 'one agent per doc, each verifies against code then writes its file' }],
}

const CANON = `
CANONICAL FACTS (verified 2026-06-03 against code; use these exact numbers — do not contradict them):
- Project: Omega Realm networking POC — top-down 2D bullet-hell multiplayer shooter; deliberately minimal gameplay to stress-test netcode for 500-1000 players. Authoritative server (Godot 4.6 headless) + Go API (auth/characters/leaderboard/regions) + Postgres + Redis.
- Server simulation Tick rate: 30 Hz, driven by a manual accumulator in Node._process (NOT _physics_process), server_main.gd:170-183. No Engine.max_fps cap.
- Snapshot/STATE_UPDATE send rate: ServerConfig.gd default 0 -> falls back to tick rate (30 Hz), BUT data/config/server_config.json:10 sets snapshot_rate_hz=20, and the JSON wins at runtime -> LIVE rate is 20 Hz (50 ms). Flag this discrepancy.
- Client input: sampled AND sent at 30 Hz inside _physics_process (prediction.gd:71,142,157). 8-bit sequence numbers (wrap 256), replay buffer 256.
- Local player IS predicted; reconciliation snaps predicted_position on drift>4u (epsilon) and replays unacked inputs; visual correction lerp speed 12.0; teleport snap threshold 150u.
- Remote entities interpolated, render_tick = server_tick - 2 ticks = FIXED 66.7 ms render delay (game_constants.gd:20, interpolation_controller.gd:11,186). EntityStateBuffer = 5-slot ring (~166 ms @30Hz). Max extrapolation 2 ticks then freeze. Despawn after 3 missing updates.
- STALE constants: entity_state_buffer.gd:14 TICK_INTERVAL_SEC=0.05 and interpolation_controller.gd:75 estimated_tick_interval=0.05 assume 20 Hz; server is 30 Hz. Causes micro-stutter until EMA converges. Comments saying "20Hz"/"250ms"/"150ms" are stale.
- Transport: WebSocket over TCP both directions (network_manager.gd: TCPServer.listen + WebSocketPeer.accept_stream server; connect_to_url + TLS client). Polled once per render frame in _process (not on Tick). Inbound full-drain each poll. Server coalesces a tick's packets per-peer into BATCH frames flushed at end-of-tick (adds up to ~33 ms server queuing); client sends one ws.send per message. No buffer sizing / max_queued_packets / NODELAY set (Godot defaults). TCP head-of-line blocking: one lost segment stalls all state until retransmit.
- Wire: header [u8 type][u16 length]; MAX_PACKET_SIZE 65535. Positions quantized 0.1 unit s16 (POSITION_SCALE 10). Full-state entity = 9 bytes (id2+type1+pos4+anim1+flags1); delta entity 3-10 bytes (position-only 7). Full header 10 bytes; delta header 14 bytes. entity_count field is u8 -> HARD CAP 255 entities/packet (silent truncation; baselines have no byte budget). Delta mask = 8-bit (position/anim/flags). Forced full-state baseline every 100 ticks; NO baseline ack.
- Per-peer snapshot byte budget = 1200 bytes (max_snapshot_bytes). Snapshot scheduler priorities player=10, projectile=8, monster=4, LOD penalty 0/4/8; defers entities over budget (far entities update at fraction of snapshot rate).
- Broadcast is PER-PLAYER: O(players x entities) AoI filter + delta + scheduler each snapshot tick (O(N^2) in players). AoI radius 1000 enter / 1100 exit (hysteresis); LOD near 400 / mid 700. Map is 2000x2000 (MAP_MIN -1000,-1000 .. MAP_MAX 1000,1000) so radius-1000 covers ~78% -> culls almost nothing when players cluster. No shared spatial broad-phase (projectile_manager has a 64-unit grid for collisions, not reused for AoI).
- Combat: one shooting ability. SHOOT_COOLDOWN 0.3s. PROJECTILE_SPEED 400, PROJECTILE_RADIUS 8, PLAYER_HITBOX_RADIUS 16 (PvP hit window 24). PvE/monster hits ARE lag-compensated (swept segment, get_lag_compensated_monster_tick, MAX_PVE_PROJECTILE_COMPENSATION_TICKS=6=200ms). PvP hits use CURRENT tick, point-distance check, NO rewind, NO swept path (projectile_manager.gd:251,269) -> tunneling (~13px/tick at 400u/s) + must lead targets. Client has NO shoot prediction/feedback (full round-trip before any muzzle/impact shows; projectiles spawned ONLY from server STATE_UPDATE, client_entity_manager.gd:114).
- PAIRED-SHOTS bug: server _process_shoot_inputs (server_main.gd:284-293) fires from TWO paths in one tick — pending rising-edge AND held-auto-fire — plus rising-edge over-count when >=2 input packets arrive in one tick (player_manager.gd:111 drains whole queue; player_state.gd:147-158 edge detect). Client doubling is REFUTED (Player.gd local projectile spawning disabled at arena_base.gd:220, never re-enabled).
- DOUBLE-MOVEMENT bug ("steering boat"): after authority sync, arena_base calls local_player.set_input_enabled(true) (arena_base.gd:374, also 418, 493), so Player.gd._physics_process runs _handle_movement + move_and_slide (CharacterBody2D physics, layer1/mask6, speed 200 no sprint) WHILE PredictionController also reads input and writes player_node.position (analytic move_with_obstacle_collision, speed 200/sprint 320). Two integrators leapfrog. Fix: PredictionController sole owner; do not re-enable Player.gd movement for the networked local player.
- THE 30FPS-LOOK: all node positions written only in _physics_process at 30 Hz; physics/common/physics_interpolation absent (off) in project.godot:100-103; camera reads local_player.position each frame (arena_base.gd:122). So motion steps 30x/sec at any FPS. Fix = enable physics_interpolation + reset_physics_interpolation() on spawns/teleports + camera via get_global_transform_interpolated(). (Already documented in docs/netcode/smoothness-render.md.)
- Movement validation: POSITION_TOLERANCE 75, CORRECTION_THRESHOLD 112.5, TELEPORT_THRESHOLD 150. PLAYER_SPEED 200, PLAYER_SPRINT_MULTIPLIER 1.6 (sprint 320).
- Monsters: one type, server-side AI. MONSTER_SPEED 120, MONSTER_PROJECTILE_SPEED 300, MONSTER_SHOOT_COOLDOWN 0.75, MONSTER_MAX_COUNT 100, MONSTER_SPAWN_RATE 0.2/s. Entity IDs: players 1-999, projectiles 10000-29999, monsters 30000-39999.
- Heartbeat 1 Hz (carries server_ms for clock sync; client EMA offset alpha 0.2); timeout 5s. Reconnect backoff base 1s, cap 32s, max 5 attempts.
- POC targets (docs/ARCHITECTURE.md success table): tick >=20 Hz under load, <2 KB/s per player, latency p95 <150ms, CPU <0.5%/player, mem <5MB/player, 500-1000 players. Engineering budgets in plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md: tick avg <8ms p95<16ms max<25ms; <5 KB/s; latency avg<100 p95<150. NOTE doc drift: ARCHITECTURE says 2KB/s & 20Hz; plans say 5KB/s; code is 30Hz.
- Existing analysis: plans/NETWORK_PERFORMANCE_UPGRADES.md + plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md (6-phase plan; Phase 1 shipped: per-channel metrics, AoI dict-alloc removal, clock sync, decoupled snapshot rate; Phase 2 IN PROGRESS: priority/budget scheduler exists & wired but diagnostics not surfaced to ServerMetrics & per-client rate budget pending; Phases 3-6 PLANNED: spatial grid, wire v3, PvP lag comp, transport change). plans/RECOMMENDATIONS.md, docs/DESYNC_PLAN.md (legacy desync root causes — server walked 1/3 speed; ghost player; both fixed in code).
`

const HOUSE_RULES = `
HOUSE STYLE (match docs/netcode/smoothness-render.md exactly — Read it first as the exemplar):
- Start with a "# Title" then a "**Status:**" line. Status tag is ONE of: Implemented / Partial / Planned / Vision, plus "(verified 2026-06-03 against code)". Use Partial when built-but-has-known-gaps.
- Use the canonical glossary terms from docs/CONTEXT.md (Tick != Frame != Snapshot; Render delay; AoI; Local player; Remote entity; Reconciliation; Game event; Lag compensation). Read docs/CONTEXT.md.
- Cite evidence as file:line inline (e.g. server_main.gd:178). Verify the specific lines exist by reading the source files named in your spec — correct them if drifted.
- End EVERY doc with a "## The eight questions" section answering: What runs on the client? the server? What is predicted? replicated? persisted? validated? What can fail? How is it tested? Keep each to 1 line.
- End with a "## See also" section cross-linking sibling docs by relative path.
- Be tight and high-signal — no filler, no marketing. Prefer tables for numbers. This is for AI agents and engineers diagnosing performance.
- Do NOT invent features. If something isn't built, say so and tag it Planned/Vision. This is a minimal POC, not an MMO.
- After writing, return ONLY the structured result (the file is the deliverable).
`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['path', 'status_tag', 'summary', 'inconsistencies'],
  properties: {
    path: { type: 'string' },
    status_tag: { type: 'string', enum: ['Implemented', 'Partial', 'Planned', 'Vision', 'Reference', 'Active'] },
    summary: { type: 'string', description: 'One line: what the doc covers' },
    inconsistencies: { type: 'string', description: 'Any place the canonical facts disagreed with current code, or "none"' },
  },
}

const DOCS = [
  { path: 'docs/netcode/overview.md', title: 'Netcode overview — authority model, loops, packet map', status: 'Implemented',
    sources: 'server_main.gd, network_manager.gd, shared/networking/packet_types.gd, prediction.gd, interpolation_controller.gd',
    spec: `The map of the netcode subtree. Cover: the authoritative-server model (client requests, server decides); the THREE loops (server 30Hz Tick accumulator in _process; server 20Hz-live Snapshot cadence; client _physics_process prediction+interpolation at 30Hz); the packet/message map (enumerate the MessageType enum from packet_types.gd: AUTH/CONNECT, PLAYER_INPUT, STATE_UPDATE, GAME_EVENT, ACTION_CONFIRM, HEARTBEAT, DISCONNECT, REQUEST_FULL_STATE — read packet_types.gd for exact names/values). Provide a "where to go next" index linking every sibling netcode doc. Keep it an OVERVIEW — point to the deep docs rather than duplicating them.` },
  { path: 'docs/netcode/client-prediction.md', title: 'Client prediction & reconciliation', status: 'Partial',
    sources: 'client/scripts/client/prediction.gd, shared/player/player.gd, shared/networking/packets/player_input_packet.gd, shared/arena_base.gd',
    spec: `Document how the Local player is predicted and reconciled. Input sampling+send 30Hz; sequence numbers; replay buffer 256; reconciliation (snap on drift>4u + replay unacked); smoothing lerp 12.0; teleport threshold 150u. Tag Partial because of the DOUBLE-MOVEMENT bug (cross-link systems/players-movement.md for the full bug + fix) and 30Hz input coupling (cross-link latency-budget.md). Read prediction.gd fully to get exact line numbers.` },
  { path: 'docs/netcode/interpolation.md', title: 'Entity interpolation & render delay', status: 'Partial',
    sources: 'client/scripts/client/interpolation_controller.gd, entity_state_buffer.gd, client_entity_manager.gd, shared/player/remote_player.gd, shared/game_constants.gd',
    spec: `Document how Remote entities are drawn: EntityStateBuffer 5-slot ring; fixed 66.7ms Render delay (render_tick = server_tick-2); sub-tick blend; extrapolation 2 ticks then freeze; despawn after 3 missing. Tag Partial: STALE 20Hz constants causing micro-stutter, fixed (non-adaptive) delay, and it interpolates the newest two snapshots rather than STRADDLING client_time-delay (janky under variable spacing). List the Planned fixes (adaptive delay, buffer 8-10, straddle search, seed constants from SERVER_TICK_INTERVAL). Cross-link smoothness-render.md (different problem!) and latency-budget.md.` },
  { path: 'docs/netcode/server-tick-broadcast.md', title: 'Server tick loop & snapshot broadcast', status: 'Partial',
    sources: 'client/scripts/server/server_main.gd, server_broadcast_service.gd, delta_state_cache.gd, snapshot_scheduler.gd, server_metrics.gd, server_config.gd',
    spec: `Document the server hot path: 30Hz tick via _process accumulator (not _physics_process; catch-up while-loop; no max_fps); decoupled 20Hz-live Snapshot cadence; per-player O(N^2) snapshot build; delta compression (8-bit mask, baseline every 100 ticks, no ack); per-peer 1200-byte budget + priority scheduler; per-tick BATCH flush at tick end (adds up to 33ms). Tag Partial: O(N^2) build, scheduler diagnostics not surfaced to ServerMetrics. Cross-link interest-mgmt-aoi.md, wire-protocol.md, transport-websocket.md.` },
  { path: 'docs/netcode/transport-websocket.md', title: 'Transport — WebSocket over TCP', status: 'Implemented',
    sources: 'client/autoload/network_manager.gd, client/project.godot',
    spec: `Document the transport: WebSocket-over-TCP both directions; poll once per render frame in _process (not on Tick); inbound full-drain; server BATCH coalescing vs client one-send-per-message; no buffer/queue/NODELAY tuning. The key limitation: TCP head-of-line blocking under loss freezes all state. Note the deferred transport change (WebRTC/WebTransport) and link adr/0001-websocket-tcp-transport.md. List Planned: poll-on-tick, buffer sizing, send!=OK as backpressure.` },
  { path: 'docs/netcode/interest-mgmt-aoi.md', title: 'Interest management (AoI) & LOD', status: 'Partial',
    sources: 'client/scripts/server/server_broadcast_service.gd, server_config.gd, snapshot_scheduler.gd, projectile_manager.gd, shared/game_constants.gd',
    spec: `Document AoI: per-client radius 1000 enter / 1100 exit hysteresis; 3-tier LOD near400/mid700; byte-budget scheduler deferral. Tag Partial: radius 1000 on a 2000x2000 map culls ~nothing when clustered; O(players x entities) scan with no shared spatial broad-phase (the 64-unit projectile grid is not reused); far entities starve under budget pressure. List Planned: shared spatial grid, tune radius, surface scheduler diagnostics. Cross-link server-tick-broadcast.md, performance-budgets.md.` },
  { path: 'docs/netcode/wire-protocol.md', title: 'Wire protocol & packet formats', status: 'Implemented',
    sources: 'client/scripts/shared/networking/packet_types.gd, packet_writer.gd, packet_reader.gd, packets/*.gd (state_update_packet.gd, player_input_packet.gd, game_event_packet.gd, auth_packet.gd, action_confirm_packet.gd, heartbeat_packet.gd, disconnect_packet.gd)',
    spec: `Document the binary wire format: header [u8 type][u16 length]; position quantization 0.1u s16; full-state entity 9 bytes, delta entity 3-10 bytes, headers 10/14 bytes; 8-bit delta mask; baseline every 100 ticks. CALL OUT the u8 entity_count HARD CAP of 255 entities/packet (silent truncation; baselines unbudgeted) as a correctness cliff. Read packet_types.gd for the exact MessageType + GameEventType enums and document each packet schema briefly (esp. PLAYER_INPUT 16-byte payload, HEARTBEAT carrying server_ms). List Planned wire-v3 changes (u16 count, s8 small-delta, drop redundant entity_type).` },
  { path: 'docs/netcode/performance-budgets.md', title: 'Performance budgets — targets vs measured', status: 'Reference',
    sources: 'docs/ARCHITECTURE.md, plans/NETWORK_PERFORMANCE_UPGRADES.md, plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md, client/scripts/server/server_metrics.gd, shared/game_constants.gd',
    spec: `A reference table of budgets: POC success criteria (ARCHITECTURE.md) vs engineering budgets (CODEX plan) vs MEASURED/current code reality, with a Gap column. Cover: tick rate, tick time, snapshot rate, per-player bandwidth, latency p95, CPU/player, mem/player, max players, render delay. Explicitly call out the DOC DRIFT (ARCHITECTURE 20Hz/2KB vs plans 5KB vs code 30Hz/20Hz-live). Note what ServerMetrics actually measures today vs what's missing (scheduler diagnostics). Tag Reference.` },
  { path: 'docs/systems/players-movement.md', title: 'Players & movement', status: 'Partial',
    sources: 'client/scripts/shared/player/player.gd, prediction.gd, shared/arena_base.gd, shared/game_constants.gd, shared/player/remote_player.gd, shared/player/hp_component.gd',
    spec: `Document the player system: CharacterBody2D layer1/mask6; PLAYER_SPEED 200, sprint 1.6x=320; 8-dir free movement; movement state machine IDLE/WALKING; HP-only stats (hp_component); Local player predicted vs Remote interpolated; validation thresholds (POSITION_TOLERANCE 75, CORRECTION_THRESHOLD 112.5, TELEPORT_THRESHOLD 150). Tag Partial and document the DOUBLE-MOVEMENT bug in full (two integrators after set_input_enabled(true) at arena_base.gd:374/418/493) with the fix (PredictionController sole owner). This is the canonical home for that bug. Cross-link netcode/client-prediction.md.` },
  { path: 'docs/systems/combat-hits.md', title: 'Combat — projectiles, hits, shooting', status: 'Partial',
    sources: 'client/scripts/server/projectile_manager.gd, server_collision_handler.gd, server_main.gd, server/player_state.gd, server/player_manager.gd, client/prediction.gd, shared/game_constants.gd, client/client_entity_manager.gd, shared/projectile/projectile.gd',
    spec: `Document combat: one shooting ability, SHOOT_COOLDOWN 0.3s, PROJECTILE_SPEED 400, hit window 24 (PROJECTILE_RADIUS 8 + PLAYER_HITBOX_RADIUS 16). PvE/monster hits lag-compensated (swept, rewind, cap 6 ticks); PvP hits CURRENT tick + point check + NO rewind/swept -> tunneling + must-lead. No client shoot prediction/feedback. Document the PAIRED-SHOTS server bug (two firing paths + multi-packet edge over-count) and the dropped-first-shot risk, with fixes. Tag Partial. This is the canonical home for the shoot/hit bugs. Cross-link latency-budget.md, monsters-ai.md.` },
  { path: 'docs/systems/monsters-ai.md', title: 'Monsters & server-side AI', status: 'Implemented',
    sources: 'client/scripts/server/monster_ai.gd, monster_manager.gd, monster_state.gd, monster_spawner.gd, shared/monster/monster.gd, shared/game_constants.gd',
    spec: `READ monster_ai.gd, monster_state.gd, monster_manager.gd, monster_spawner.gd FULLY — the canonical facts give you the numbers but you must document the actual AI behavior from code: the AI state machine (states, transitions), perception/aggro/target selection, movement (MONSTER_SPEED 120), shooting (MONSTER_PROJECTILE_SPEED 300, MONSTER_SHOOT_COOLDOWN 0.75), spawning (MONSTER_MAX_COUNT 100, MONSTER_SPAWN_RATE 0.2/s), entity IDs 30000-39999. AI runs server-side on the tick. Be accurate to what the code actually does — if it's a simple state machine, say so (this is a minimal POC).` },
  { path: 'docs/systems/audio.md', title: 'Audio manager & procedural sound', status: 'Implemented',
    sources: 'client/autoload/audio_manager.gd, client/scripts/shared/audio/procedural_audio.gd, client/scripts/client/client_entity_manager.gd, client/scripts/shared/arena_base.gd',
    spec: `READ audio_manager.gd and procedural_audio.gd FULLY. Document: AudioManager autoload (client-only, disabled in server mode), procedurally-GENERATED audio (no audio asset files), sound categories/mixer if any, how gameplay events trigger sounds (server-confirmed Game events -> local sound on nearby clients), the lazy _get_audio_manager() caching pattern in ClientEntityManager/arena_base. Be accurate to what's actually implemented.` },
  { path: 'docs/systems/ui-hud.md', title: 'UI, HUD & menus', status: 'Implemented',
    sources: 'client/scripts/client/hud/* (minimap, hp_bar, death_screen, pause_menu, leaderboard, kill_feed, server_status, settings_menu, connection_lost_overlay), client/scripts/client/* (login_screen, character_creation, main_menu, loading_screen, user_preferences), client/scripts/client/effects/* (damage_number, particle_effects, screen_effects), client/scripts/client/ui/*',
    spec: `READ the hud/ directory and client menu scripts. Document each HUD component and menu briefly (one line each: what it shows / does), the scene flow (login -> main menu -> loading -> arena), and the arena_base HUD-creation pattern (load() + Control.new().set_script() to stay server-safe). Also note the effects (damage_number, particle_effects, screen_effects). Keep it a concise catalogue, not exhaustive per-widget detail.` },
  { path: 'docs/systems/state-machines.md', title: 'State machines (player life, movement, scene, connection, AI)', status: 'Implemented',
    sources: 'client/scripts/server/player_state.gd, client/autoload/scene_manager.gd, client/autoload/network_manager.gd, client/scripts/server/monster_ai.gd, client/autoload/game_manager.gd',
    spec: `Enumerate the state machines across the project (READ the sources to get the real states): PlayerLifeState (ALIVE/DEAD/INVULNERABLE; invulnerability ends on input or 3s), player movement (IDLE/WALKING), the UI/scene flow (scene_manager routing; note it skips routing for res://scenes/test/), the connection lifecycle (network_manager connect/auth/reconnect backoff), and the monster AI states (cross-link monsters-ai.md). For each: states, transitions, where it lives, client vs server.` },
  { path: 'docs/exec-plans/active/netcode-perf-fixes.md', title: 'Active exec-plan — prioritized netcode performance fixes', status: 'Active',
    sources: 'plans/NETWORK_PERFORMANCE_UPGRADES.md, plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md, plans/RECOMMENDATIONS.md, docs/DESYNC_PLAN.md',
    spec: `THIS IS THE ROADMAP — the most important doc. Read the four plans/ docs to align phase/status, then produce a single PRIORITIZED fix list that supersedes them as the entry point (link them as detailed source). Order by impact-on-felt-sluggishness then effort. For EACH fix give: problem (1 line), fix, evidence file:line, effort (trivial/small/medium/large), impact (decisive/high/medium/low), status (Done/In-progress/Planned). Use this priority order:
  P0 (decisive, small): (1) Enable physics_interpolation to kill the 30fps-look [see smoothness-render.md]; (2) Make PredictionController the sole local mover (kill double-movement/steering-boat).
  P1 (high, small): (3) Set live snapshot rate 20->30 Hz (server_config.json); (4) Make Render delay adaptive (collapse to ~1 tick on localhost); (5) Fix paired-shots (dedup edge+held firing; snapshot flags before drain); (6) Seed interpolation timing constants from SERVER_TICK_INTERVAL (kill 20Hz micro-stutter).
  P2 (high, medium): (7) PvP lag compensation + swept-segment hit test + client muzzle/tracer feedback; (8) Raise input sample+tick to 60 Hz (responsiveness; weigh CPU/bandwidth); (9) Spatial-grid broad-phase for AoI (break O(N^2)); (10) Tune AoI radius down vs map; (11) Widen entity_count u8->u16 (fix 255 truncation).
  P3 (architecture): (12) Transport change to WebRTC/WebTransport datagrams (TCP HOL) [adr/0001]; (13) Per-client bandwidth budget; (14) Baseline acks; (15) Surface scheduler diagnostics to ServerMetrics.
Note which already map to plans/ phases (Phase 1 shipped, Phase 2 in progress). Cross-link the netcode docs for each. Tag Active.` },
  { path: 'docs/adr/0001-websocket-tcp-transport.md', title: 'ADR 0001 — WebSocket-over-TCP transport', status: 'Implemented',
    sources: 'client/autoload/network_manager.gd, docs/ARCHITECTURE.md, plans/NETWORK_PERFORMANCE_UPGRADES.md',
    spec: `Write a SHORT ADR per docs/adr (read ../../.claude/skills/grill-with-docs/ADR-FORMAT.md style: 1-3 sentences core, optional Considered Options / Consequences). Decision: use WebSocket-over-TCP as the transport for the POC. Context: browser-reachability + Godot WebSocketPeer simplicity + works through proxies. Trade-off/Consequence: TCP head-of-line blocking under packet loss stalls ALL state behind one lost segment — the main latency risk for a 30Hz action game; UDP/WebRTC/ENet would avoid it but cost reach/complexity. Status: accepted for POC; transport change deferred until snapshot/wire wins are quantified (link exec-plan + transport-websocket.md). Keep it tight.` },
  { path: 'docs/adr/0002-authoritative-server-fixed-tick.md', title: 'ADR 0002 — Authoritative server, fixed 30 Hz tick', status: 'Implemented',
    sources: 'client/scripts/server/server_main.gd, docs/ARCHITECTURE.md',
    spec: `Write a SHORT ADR. Decision: a single authoritative Godot headless server per Arena running a fixed 30 Hz timestep; clients send input intent only ("client requests, server decides"). Context: anti-cheat + determinism + the POC's goal of proving per-server player density. Consequences: every action costs a round-trip (mitigated by client prediction); 30 Hz is low for a twitch shooter (raising it costs CPU/bandwidth — a scale trade-off); single-server-per-arena (sharding deferred). Keep it tight; link performance-budgets.md and the exec-plan.` },
]

phase('Write docs')

const results = await parallel(
  DOCS.map((d) => () =>
    agent(
      `${CANON}\n${HOUSE_RULES}\n\nYOUR TASK: write the file ${d.path} (title: "${d.title}", status tag: ${d.status}).\n` +
      `First Read these for format/terms: docs/netcode/smoothness-render.md (exemplar), docs/CONTEXT.md, AGENTS.md.\n` +
      `Then Read these source files to verify every file:line before citing: ${d.sources}.\n` +
      `Doc spec: ${d.spec}\n` +
      `Write the complete markdown file at exactly ${d.path}. Then return the structured result.`,
      { label: d.path.replace('docs/', ''), phase: 'Write docs', schema: SCHEMA }
    )
  )
)

return results.filter(Boolean)
