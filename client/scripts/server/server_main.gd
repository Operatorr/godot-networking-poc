## ServerMain - Main server scene controller
## Coordinates server-side game logic and manages authoritative game state
## Delegates collision, broadcasting, and metrics to focused helper classes
extends Node

const LeaderboardManager := preload("res://scripts/server/leaderboard_manager.gd")
const ServerBroadcastService := preload("res://scripts/server/server_broadcast_service.gd")
const ServerCollisionHandler := preload("res://scripts/server/server_collision_handler.gd")
const ServerMetrics := preload("res://scripts/server/server_metrics.gd")

@export_group("Monster Spawning")
@export_range(0.05, 5.0, 0.05)
var monster_spawn_rate: float = GameConstants.MONSTER_SPAWN_RATE * 2.0

## Server configuration
var config: ServerConfig = null

## Server state
var server_running: bool = false
var server_time: float = 0.0

## Player management (TASK-012)
var player_manager: PlayerManager = null

## Projectile management (TASK-014)
var projectile_manager: ProjectileManager = null

## Monster management (TASK-015)
var monster_manager: MonsterManager = null
var monster_spawner: MonsterSpawner = null

## Monster AI system (TASK-016)
var monster_ai: MonsterAI = null

## Entity management (entity_id -> EntityState)
## Used for additional entities beyond players/projectiles/monsters
var game_entities: Dictionary = {}

## Extracted service components
var collision_handler: ServerCollisionHandler = null
var broadcast_service: ServerBroadcastService = null
var server_metrics: ServerMetrics = null

## Leaderboard broadcast timer (periodic fallback)
var leaderboard_timer: float = 0.0
const LEADERBOARD_BROADCAST_INTERVAL := 5.0
const REGION_STATUS_HEARTBEAT_INTERVAL := 2.0

## Floor for the per-peer snapshot byte cap (#13). Even a marginal/hostile budget
## must leave room for pinned removals + a few deltas so entities never strand.
const MIN_SNAPSHOT_FLOOR := 256

## Tick loop state
var tick_timer: float = 0.0
var tick_count: int = 0

## Snapshot scheduler state (§1.1 of NETWORK_PERFORMANCE_UPGRADES.md). Decoupled
## from the physics tick: snapshots may fire less often than ticks under a
## reduced snapshot_rate_hz. snapshot_due is set by the accumulator at the top
## of the tick and consumed by the broadcast step.
var snapshot_accumulator: float = 0.0
var snapshot_interval: float = 0.0
var snapshot_due: bool = false

## Live region status publisher for the API region list.
var region_status_timer: float = 0.0
var region_status_request: HTTPRequest = null
var region_status_request_in_flight: bool = false
var region_status_warning_logged: bool = false


## Called when the node enters the scene tree
func _ready() -> void:
	print("[ServerMain] ========================================")
	print("[ServerMain] Omega Realm - Dedicated Server Starting")
	print("[ServerMain] ========================================")

	# Load configuration
	config = ServerConfig.new()
	config.print_config()

	# Verify we're running as server
	if not _is_server_mode():
		push_error("[ServerMain] Not running as dedicated server! Aborting.")
		get_tree().quit(1)
		return

	# Connect to NetworkManager signals
	_connect_network_signals()

	# Initialize server state
	_initialize_server()

	print("[ServerMain] Server initialization complete")
	print("[ServerMain] Waiting for client connections...")


## Check if running in dedicated server mode
func _is_server_mode() -> bool:
	return OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"


## Connect to NetworkManager signals for client events
func _connect_network_signals() -> void:
	var nm = _get_network_manager()
	if nm == null:
		push_error("[ServerMain] NetworkManager not found!")
		return

	if nm.has_signal("server_client_connected"):
		nm.server_client_connected.connect(_on_client_connected)
	if nm.has_signal("server_client_disconnected"):
		nm.server_client_disconnected.connect(_on_client_disconnected)
	if nm.has_signal("server_client_message"):
		nm.server_client_message.connect(_on_client_message)

	print("[ServerMain] Connected to NetworkManager signals")


## Initialize server state
func _initialize_server() -> void:
	server_running = true
	server_time = 0.0
	tick_count = 0

	# Core managers
	player_manager = PlayerManager.new()
	player_manager.debug_logging = config.debug_logging

	projectile_manager = ProjectileManager.new()
	projectile_manager.debug_logging = config.debug_logging

	# Data-driven monster catalogue: spawning flows through MonsterFactory so new
	# archetypes are added as JSON, not code. See docs/systems/monster-architecture.md.
	var monster_database := MonsterDatabase.get_shared()
	monster_database.debug_logging = config.debug_logging
	monster_manager = MonsterManager.new()
	monster_manager.debug_logging = config.debug_logging
	monster_manager.set_factory(MonsterFactory.new(monster_database))
	print("[ServerMain] Monster catalogue: %s" % ", ".join(PackedStringArray(monster_database.get_all_ids())))
	monster_spawner = MonsterSpawner.new(monster_manager, player_manager, monster_spawn_rate)
	monster_spawner.debug_logging = config.debug_logging

	monster_ai = MonsterAI.new(player_manager, projectile_manager, config.monster_ai_difficulty)
	monster_ai.debug_logging = config.debug_logging

	# Extracted service components
	collision_handler = ServerCollisionHandler.new()
	collision_handler.debug_logging = config.debug_logging

	broadcast_service = ServerBroadcastService.new()
	broadcast_service.debug_logging = config.debug_logging
	broadcast_service.aoi_radius = config.aoi_radius
	broadcast_service.aoi_exit_radius = config.aoi_exit_radius
	broadcast_service.lod_near_radius_sq = config.lod_near_radius * config.lod_near_radius
	broadcast_service.lod_mid_radius_sq = config.lod_mid_radius * config.lod_mid_radius
	broadcast_service.max_snapshot_bytes = config.max_snapshot_bytes
	broadcast_service.leaderboard_manager = LeaderboardManager.new()
	broadcast_service.leaderboard_manager.debug_logging = config.debug_logging

	server_metrics = ServerMetrics.new()
	server_metrics.debug_logging = config.debug_logging
	_setup_region_status_publisher()

	game_entities.clear()

	# Snapshot interval is derived from the configured snapshot rate. When the
	# snapshot rate equals the tick rate (default) snapshot_due is true on
	# every tick, preserving the legacy behavior.
	snapshot_interval = 1.0 / float(maxi(1, config.snapshot_rate_hz))
	snapshot_accumulator = 0.0

	set_process(true)
	print("[ServerMain] Server running at %d Hz tick rate" % config.tick_rate)
	print("[ServerMain] Snapshot rate: %d Hz" % config.snapshot_rate_hz)
	print("[ServerMain] Monster spawn rate set to %.2f monsters/sec" % monster_spawn_rate)


## Process loop - runs the server tick
func _process(delta: float) -> void:
	if not server_running:
		return

	server_time += delta

	# Fixed tick rate processing
	tick_timer += delta
	var tick_interval := 1.0 / config.tick_rate

	while tick_timer >= tick_interval:
		tick_timer -= tick_interval
		_process_server_tick()

	# Update metrics periodically (every second)
	if server_time - server_metrics.metrics.last_metrics_time >= 1.0:
		var nm = _get_network_manager()
		var entity_count := game_entities.size() + projectile_manager.get_projectile_count() + monster_manager.get_monster_count()
		var network_stats := {}
		if nm:
			network_stats = nm.get_stats()
			network_stats["peer_bytes_sent"] = nm.peer_bytes_sent
		server_metrics.update_metrics(player_manager.get_player_count(), entity_count, tick_count, network_stats, broadcast_service.last_tick_diagnostics)
		# Broadcast server metrics to all connected clients
		_broadcast_server_metrics(nm)

	region_status_timer += delta
	if region_status_timer >= REGION_STATUS_HEARTBEAT_INTERVAL:
		region_status_timer = 0.0
		_publish_region_status()


## Process a single server tick - core game loop
func _process_server_tick() -> void:
	var tick_start := Time.get_ticks_usec()
	tick_count += 1

	# Snapshot accumulator (§1.1): only mark a snapshot due when enough wall
	# time has elapsed at the configured snapshot rate. Events still fire every
	# tick - state-update bandwidth is decoupled, but damage/kill broadcasts
	# stay snappy.
	var tick_dt: float = 1.0 / float(maxi(1, config.tick_rate))
	snapshot_accumulator += tick_dt
	if snapshot_accumulator >= snapshot_interval:
		snapshot_accumulator -= snapshot_interval
		# Guard against runaway accumulator drift if tick stalls (e.g. spike).
		if snapshot_accumulator > snapshot_interval:
			snapshot_accumulator = 0.0
		snapshot_due = true

	var nm = _get_network_manager()

	# Open a packet-batch window for this tick (TASK-066). Every send_to_client
	# / broadcast_to_clients call within the tick is queued per-peer and flushed
	# as a single WebSocket frame at the end, slashing per-frame overhead when
	# inputs, collisions, and state updates all fire on the same tick.
	var batching: bool = nm != null and config.packet_batching_enabled
	if batching:
		nm.begin_batch()

	# 1. Process incoming client inputs
	_process_client_inputs()

	# 2. Update game state
	_update_game_state()

	# 3. Run AI/monster logic
	_update_monster_ai()

	# 4. Snapshot monster and player positions before collision/damage mutates
	# state. Player projectile hit tests rewind to this short history (monsters for
	# PvE, players for PvP). Recorded here so the snapshot reflects end-of-tick
	# positions after inputs/AI moved everyone but before collision resolution.
	monster_manager.record_position_snapshot(tick_count)
	player_manager.record_position_snapshot(tick_count)

	# 5. Process collisions (delegated to CollisionHandler)
	collision_handler.process_collisions(
		projectile_manager, player_manager, monster_manager, nm, broadcast_service
	)

	# 6. Broadcast state updates only on snapshot ticks (§1.1).
	if snapshot_due:
		# Build the shared current-tick spatial grid (#9) once from the now-final
		# entity positions, then feed it to the per-peer AoI scan. Built here (vs a
		# separate tick step) so it reflects the same post-collision state the
		# broadcast would otherwise re-collect, and only on snapshot ticks to avoid
		# wasted builds at the higher tick rate. Monster lag-comp collisions still
		# use their own per-rewind-tick history grids (see ProjectileManager).
		broadcast_service.build_aoi_grid(player_manager, projectile_manager, monster_manager)
		broadcast_service.broadcast_state_updates(
			player_manager, projectile_manager, monster_manager, nm, tick_count
		)
		snapshot_due = false

	# 7. Remove dead monsters after death/removed state has been broadcast.
	monster_manager.cleanup_dead_monsters()

	if batching:
		nm.flush_batches()

	# Track tick performance
	var tick_time := (Time.get_ticks_usec() - tick_start) / 1000.0
	server_metrics.record_tick_time(tick_time)


## Process queued client inputs and validate movement (TASK-012, TASK-013)
func _process_client_inputs() -> void:
	var tick_interval := 1.0 / config.tick_rate

	# Drain queued inputs into the persistent input model and advance one tick.
	# Rising-edge SHOOT presses are queued onto state.pending_shots during ingest.
	var move_results = player_manager.process_all_inputs(tick_interval, tick_count)

	# Spawn projectiles for shoot edges captured during this tick's ingest pass,
	# then continue auto-fire while SHOOT remains held across cooldown cycles.
	_process_shoot_inputs()

	# Confirm every processed move so clients can prune acknowledged inputs.
	if move_results.size() > 0:
		_send_move_confirmations(move_results)


## Spawn projectiles for immediate shoot edges and sustained held auto-fire.
func _process_shoot_inputs() -> void:
	for state: PlayerState in player_manager.get_all_players():
		# Fire at most ONE shot per player per tick. SHOOT_COOLDOWN (0.3s) makes more
		# than one legitimate shot per 33ms tick impossible, so collapsing duplicate
		# same-tick rising edges AND the held auto-fire into a single fire here removes
		# the "shots come out as pairs" bug (two firing surfaces firing the same tick).
		var fired_this_tick := false
		while true:
			var shot := state.pop_pending_shot()
			if shot.is_empty():
				break
			if not fired_this_tick:
				fired_this_tick = true
				_try_spawn_projectile(state, shot)
			# else: duplicate rising-edge drained in the same tick — coalesced/dropped.

		# Held auto-fire only if no rising-edge press already fired this tick.
		if not fired_this_tick and state.is_shoot_held() and state.can_shoot():
			_try_spawn_projectile(state, state.get_held_shot_input())


## Send authoritative move confirmations/corrections to clients (TASK-013)
func _send_move_confirmations(move_results: Array[Dictionary]) -> void:
	var nm = _get_network_manager()
	if nm == null:
		return

	for result in move_results:
		var peer_id: int = result.peer_id
		var sequence: int = result.sequence
		var position: Vector2 = result.position
		var success: bool = result.success
		var cheat_detected: bool = result.cheat_detected

		# Create correction packet using ActionConfirmPacket. Stamina/mana ride along
		# as an owner-only authoritative resource sync for the predicted HUD bars.
		var confirm_packet = ActionConfirmPacket.create_move_confirm(
			sequence,
			position,
			tick_count,
			success,
			result.get("stamina", 100),
			result.get("mana", 100)
		)

		# Send correction to the specific client
		nm.send_to_client(
			peer_id,
			NetworkManager.MessageType.ACTION_CONFIRM,
			confirm_packet.to_dict()
		)

		# Log potential cheating attempts
		if cheat_detected:
			print("[ServerMain] CHEAT DETECTED: peer=%d teleport attempt (deviation=%.1f)" % [
				peer_id, result.deviation
			])
		elif config.debug_logging and not success:
			print("[ServerMain] Position correction: peer=%d seq=%d deviation=%.1f" % [
				peer_id, sequence, result.deviation
			])


## Try to spawn a projectile from player shoot input (TASK-014)
func _try_spawn_projectile(player: PlayerState, input: Dictionary) -> void:
	if player.life_state == PlayerState.PlayerLifeState.INVULNERABLE:
		player.end_invulnerability()

	# Check shoot cooldown
	if not player.can_shoot():
		return

	# Get aim direction from input
	var aim_angle: float = input.get("aim_angle", player.aim_angle)
	var aim_direction := Vector2.from_angle(aim_angle)
	var fire_origin_data: Dictionary = _get_validated_fire_origin(player, input)
	var fire_origin: Vector2 = fire_origin_data.get("position", player.position)
	var compensation_data: Dictionary = _get_pve_projectile_compensation(input)
	var rewind_ticks: int = compensation_data.get("rewind_ticks", GameConstants.REMOTE_ENTITY_RENDER_DELAY_TICKS)
	# Reuse the already-derived render-tick/RTT rewind, but re-clamp to the stricter
	# PvP cap so a peeker who has broken line of sight cannot be retro-hit.
	var pvp_rewind_ticks: int = clampi(
		compensation_data.get("rewind_ticks", 0),
		0,
		GameConstants.MAX_PVP_PROJECTILE_COMPENSATION_TICKS
	)

	# Spawn position slightly in front of player to avoid self-collision
	var spawn_offset := aim_direction * (GameConstants.PLAYER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0)
	var spawn_position := fire_origin + spawn_offset

	# Spawn the projectile
	var projectile := projectile_manager.spawn_projectile(
		player.entity_id,
		spawn_position,
		aim_direction,
		tick_count,
		rewind_ticks,
		compensation_data.get("client_render_tick", 0),
		compensation_data.get("client_rtt_ms", 0),
		compensation_data.get("source", "none"),
		pvp_rewind_ticks
	)

	if projectile != null:
		if config.debug_logging:
			_log_player_projectile_spawn(player, projectile, aim_angle, fire_origin_data)

		# Start cooldown on successful spawn
		player.start_shoot_cooldown()
		_broadcast_projectile_fired(player.entity_id, projectile.entity_id, spawn_position, tick_count)


func _get_validated_fire_origin(player: PlayerState, input: Dictionary) -> Dictionary:
	var client_position: Vector2 = input.get("client_position", Vector2.INF)
	var tolerance := _get_fire_origin_tolerance(input)
	if client_position != Vector2.INF:
		var delta := player.position.distance_to(client_position)
		if delta <= tolerance:
			return {
				"position": client_position,
				"source": "client_position",
				"delta": delta,
				"tolerance": tolerance
			}

	return {
		"position": player.position,
		"source": "server_position",
		"delta": 0.0,
		"tolerance": tolerance
	}


func _get_fire_origin_tolerance(input: Dictionary) -> float:
	var client_rtt_ms: int = clampi(input.get("client_rtt_ms", 0), 0, 65535)
	var one_way_seconds := float(client_rtt_ms) * 0.0005
	var tick_interval := 1.0 / float(config.tick_rate)
	var max_compensation_seconds := float(GameConstants.MAX_PVE_PROJECTILE_COMPENSATION_TICKS) / float(config.tick_rate)
	one_way_seconds = minf(one_way_seconds, max_compensation_seconds)

	# Bound client fire-origin trust much tighter than movement correction tolerance.
	var predicted_gap := GameConstants.PLAYER_SPRINT_SPEED * (one_way_seconds + tick_interval)
	return clampf(
		predicted_gap + GameConstants.PROJECTILE_RADIUS,
		GameConstants.PROJECTILE_RADIUS * 2.0,
		GameConstants.POSITION_TOLERANCE
	)


func _get_pve_projectile_compensation(input: Dictionary) -> Dictionary:
	var client_render_tick_16: int = input.get("client_render_tick", 0) & 0xFFFF
	var client_rtt_ms: int = clampi(input.get("client_rtt_ms", 0), 0, 65535)

	if client_render_tick_16 > 0:
		var resolved_render_tick := _resolve_client_tick_u16(client_render_tick_16)
		var render_tick_rewind := tick_count - resolved_render_tick
		if render_tick_rewind >= 0:
			return {
				"rewind_ticks": clampi(render_tick_rewind, 0, GameConstants.MAX_PVE_PROJECTILE_COMPENSATION_TICKS),
				"client_render_tick": resolved_render_tick,
				"client_rtt_ms": client_rtt_ms,
				"source": "client_render_tick" if render_tick_rewind <= GameConstants.MAX_PVE_PROJECTILE_COMPENSATION_TICKS else "client_render_tick_clamped"
			}

	var one_way_latency_ticks := 0
	if client_rtt_ms > 0:
		var tick_ms := 1000.0 / float(config.tick_rate)
		one_way_latency_ticks = ceili((float(client_rtt_ms) * 0.5) / tick_ms)

	var fallback_rewind := GameConstants.REMOTE_ENTITY_RENDER_DELAY_TICKS + one_way_latency_ticks
	return {
		"rewind_ticks": clampi(fallback_rewind, 0, GameConstants.MAX_PVE_PROJECTILE_COMPENSATION_TICKS),
		"client_render_tick": 0,
		"client_rtt_ms": client_rtt_ms,
		"source": "rtt_fallback" if client_rtt_ms > 0 else "render_delay_fallback"
	}


func _resolve_client_tick_u16(client_tick_16: int) -> int:
	var server_tick_16 := tick_count & 0xFFFF
	var diff := client_tick_16 - server_tick_16
	if diff > 32767:
		diff -= 65536
	elif diff < -32768:
		diff += 65536
	return tick_count + diff


## Update game state (positions, timers, etc.)
func _update_game_state() -> void:
	var tick_interval := 1.0 / config.tick_rate

	# Update projectile positions (TASK-014)
	projectile_manager.update_all(tick_interval)

	# Update monster spawner (TASK-015)
	monster_spawner.update(tick_interval)

	# Update player invulnerability timers
	_update_invulnerability_timers(tick_interval)

	# Advance death timers. Clients must request respawn after the delay expires.
	_update_respawn_timers(tick_interval)

	# Broadcast leaderboard periodically
	leaderboard_timer += tick_interval
	if leaderboard_timer >= LEADERBOARD_BROADCAST_INTERVAL:
		leaderboard_timer = 0.0
		broadcast_service.broadcast_leaderboard(player_manager, _get_network_manager())


## Update monster AI behavior (TASK-016)
func _update_monster_ai() -> void:
	if monster_ai == null or monster_manager == null:
		return

	var tick_interval := 1.0 / config.tick_rate
	var alive_monsters := monster_manager.get_alive_monsters()

	# Update all monster AI - handles movement, targeting, and shooting
	var monster_fire_events: Array[Dictionary] = monster_ai.update_all(alive_monsters, tick_interval)

	for fire_event: Dictionary in monster_fire_events:
		# Carry the real projectile id so clients can attribute the bullet to its
		# monster owner and run client-side incoming-hit detection.
		_broadcast_projectile_fired(
			int(fire_event.get("source_id", 0)),
			int(fire_event.get("projectile_id", 0))
		)

	if config.debug_logging and monster_fire_events.size() > 0:
		print("[ServerMain] Monsters spawned %d projectiles this tick" % monster_fire_events.size())


## Broadcast a compact authoritative fire event after projectile creation.
func _broadcast_projectile_fired(
	source_entity_id: int,
	projectile_entity_id: int = 0,
	spawn_position: Vector2 = Vector2.ZERO,
	server_tick: int = 0
) -> void:
	var nm = _get_network_manager()
	if nm == null:
		return

	var event_packet = GameEventPacket.create_projectile_fired(
		source_entity_id,
		projectile_entity_id,
		spawn_position,
		server_tick
	)
	nm.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		event_packet.to_dict()
	)


func _log_player_projectile_spawn(
	player: PlayerState,
	projectile: ProjectileState,
	aim_angle: float,
	fire_origin_data: Dictionary
) -> void:
	var closest := monster_manager.get_closest_alive_monster(projectile.position)
	var closest_text := "none"
	if closest != null:
		closest_text = "monster=%d pos=%s dist=%.2f" % [
			closest.entity_id,
			closest.position,
			projectile.position.distance_to(closest.position)
		]

	print("[ServerMain] Player projectile fired: player=%d projectile=%d tick=%d rewind_ticks=%d compensation=%s client_render_tick=%d client_rtt_ms=%d fire_origin=%s fire_origin_source=%s fire_origin_delta=%.2f fire_origin_tolerance=%.2f player_pos=%s spawn_pos=%s aim_angle=%.4f closest=%s" % [
		player.entity_id,
		projectile.entity_id,
		tick_count,
		projectile.collision_rewind_ticks,
		projectile.lag_compensation_source,
		projectile.client_render_tick,
		projectile.client_rtt_ms,
		fire_origin_data.get("position", player.position),
		fire_origin_data.get("source", "server_position"),
		fire_origin_data.get("delta", 0.0),
		fire_origin_data.get("tolerance", 0.0),
		player.position,
		projectile.position,
		aim_angle,
		closest_text
	])


## Update invulnerability timers for all players
func _update_invulnerability_timers(delta: float) -> void:
	for state: PlayerState in player_manager.get_all_players():
		state.update_invulnerability(delta)


## Advance dead-player respawn timers without automatically respawning them.
func _update_respawn_timers(delta: float) -> void:
	for state: PlayerState in player_manager.get_authenticated_players():
		state.update_respawn_timer(delta)


## Handle client connection (TASK-012)
func _on_client_connected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client connected: %d" % peer_id)

	if player_manager.get_player_count() >= config.max_players:
		print("[ServerMain] Server full, rejecting client: %d" % peer_id)
		var nm = _get_network_manager()
		if nm:
			nm.disconnect_client(peer_id, "Server full")
		return

	# Create player state via PlayerManager
	var state = player_manager.add_player(peer_id)
	if state == null:
		print("[ServerMain] Failed to create player state for: %d" % peer_id)
		return

	# Create delta cache for this client (TASK-021)
	broadcast_service.get_or_create_delta_cache(peer_id)

	print("[ServerMain] Player count: %d/%d" % [player_manager.get_player_count(), config.max_players])


## Handle client disconnection (TASK-012)
func _on_client_disconnected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client disconnected: %d" % peer_id)

	# Remove from leaderboard before player_manager (need entity_id)
	var state = player_manager.get_player(peer_id)
	if broadcast_service.leaderboard_manager and state:
		broadcast_service.leaderboard_manager.remove_player(state.entity_id)
		broadcast_service.broadcast_leaderboard(player_manager, _get_network_manager())

	player_manager.remove_player(peer_id)
	_local_hit_report_window.erase(peer_id)

	# Remove delta cache for this client (TASK-021)
	broadcast_service.remove_delta_cache(peer_id)

	print("[ServerMain] Player count: %d/%d" % [player_manager.get_player_count(), config.max_players])


## Handle incoming client message (TASK-012)
func _on_client_message(peer_id: int, message_type: int, data: Dictionary) -> void:
	if not player_manager.has_player(peer_id):
		if config.debug_logging:
			print("[ServerMain] Message from unknown peer: %d" % peer_id)
		return

	# Handle message based on type
	match message_type:
		NetworkManager.MessageType.PLAYER_INPUT:
			player_manager.queue_player_input(peer_id, data)
		NetworkManager.MessageType.CONNECT_AUTH:
			_handle_auth_request(peer_id, data)
		NetworkManager.MessageType.REQUEST_FULL_STATE:
			broadcast_service.handle_full_state_request(
				peer_id, player_manager, projectile_manager, monster_manager,
				_get_network_manager(), tick_count
			)
		NetworkManager.MessageType.RESPAWN_REQUEST:
			_handle_respawn_request(peer_id)
		NetworkManager.MessageType.LOCAL_HIT_REPORT:
			_handle_local_hit_report(peer_id, data)
		NetworkManager.MessageType.BASELINE_ACK:
			# Client confirmed receipt of a full-state Baseline (#14). On TCP this is
			# informational; under #12 UDP transport it lets the broadcast loop resend
			# a lost Baseline before the 100-tick cadence floor.
			broadcast_service.handle_baseline_ack(peer_id, int(data.get("baseline_tick", 0)))
		_:
			if config.debug_logging:
				print("[ServerMain] Unhandled message type %d from peer %d" % [message_type, peer_id])


## Handle authentication request (TASK-012)
func _handle_auth_request(peer_id: int, data: Dictionary) -> void:
	if config.debug_logging:
		print("[ServerMain] Auth request from peer %d" % peer_id)

	var character_id = data.get("character_id", "")
	var character_name = data.get("character_name", "Player_%d" % peer_id)
	var player_color: Color = data.get("player_color", Color(0.27, 0.53, 1.0))

	# Resolve the client-advertised egress budget (#13). 0 (or an old client that
	# omits the field) falls back to the configured default; then clamp into the
	# server's [min, max] bounds so a marginal/hostile advert can't starve or
	# inflate the stream.
	var advertised := int(data.get("bandwidth_budget_bps", 0))
	var effective_budget: int = advertised if advertised > 0 else config.default_client_bandwidth_bps
	effective_budget = clampi(effective_budget, config.min_client_bandwidth_bps, config.max_client_bandwidth_bps)

	# Authenticate player via PlayerManager
	# TODO: Validate character_id with API server
	var authenticated := player_manager.authenticate_player(peer_id, character_id, character_name, player_color, effective_budget)
	if not authenticated:
		return

	# Derive the per-peer snapshot byte cap from the effective budget and the
	# effective snapshot rate (the same value that seeds snapshot_interval at boot).
	# Clamped UP by the global max_snapshot_bytes (never raise above today's
	# behavior) and DOWN by MIN_SNAPSHOT_FLOOR (so pinned removals always fit).
	var rate := config.snapshot_rate_hz
	var per_peer_bytes := int(effective_budget / float(maxi(1, rate)))
	per_peer_bytes = clampi(per_peer_bytes, MIN_SNAPSHOT_FLOOR, config.max_snapshot_bytes)
	broadcast_service.set_peer_byte_budget(peer_id, per_peer_bytes)
	var state_resolved = player_manager.get_player(peer_id)
	if state_resolved:
		state_resolved.max_snapshot_bytes = per_peer_bytes
	if config.debug_logging:
		print("[ServerMain] Peer %d budget=%d B/s -> per-snapshot cap=%d bytes (rate=%d Hz)" % [
			peer_id, effective_budget, per_peer_bytes, rate
		])

	# Broadcast PLAYER_INFO to all clients for the newly authenticated player
	var nm = _get_network_manager()
	broadcast_service.broadcast_player_info(peer_id, player_manager, nm)

	# Send PLAYER_INFO for all existing players to the new client
	broadcast_service.send_all_player_info_to_client(peer_id, player_manager, nm)

	var state = player_manager.get_player(peer_id)
	if broadcast_service.leaderboard_manager and state:
		broadcast_service.leaderboard_manager.register_player(state.entity_id)
		broadcast_service.broadcast_leaderboard(player_manager, nm)


## Handle client respawn request
func _handle_respawn_request(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Respawn request from peer %d" % peer_id)

	var state = player_manager.get_player(peer_id)
	if state == null:
		return

	# Only allow respawn if player is dead
	if state.is_alive:
		if config.debug_logging:
			print("[ServerMain] Respawn rejected: peer %d is still alive" % peer_id)
		return

	if state.respawn_timer > 0.0:
		if config.debug_logging:
			print("[ServerMain] Respawn rejected: peer %d has %.2fs remaining" % [peer_id, state.respawn_timer])
		return

	_respawn_player_and_broadcast(peer_id)


## Max client hit reports honoured per peer per second (anti-spam bound).
const LOCAL_HIT_REPORT_MAX_PER_SECOND := 20

## Slack (units) added to the real hit radius when validating a client report
## against the player's authoritative position history. Absorbs the legitimate
## prediction + interpolation offset; this is an anti-grief bound, not a
## pixel-accurate re-check of the client's collision.
const LOCAL_HIT_VALIDATION_MARGIN := 64.0

## Per-peer sliding-window counter for hit-report rate limiting.
var _local_hit_report_window: Dictionary = {}  # peer_id -> { start_ms, count }


## Handle a client-reported monster-projectile hit on the reporting player.
## Monster-fired bullets vs. the local player are detected client-side (predicted
## self vs. rendered bullet) so dodging matches what the player sees; the server
## validates plausibility here before applying damage. See docs/systems/combat-hits.md.
func _handle_local_hit_report(peer_id: int, data: Dictionary) -> void:
	var projectile_id := int(data.get("projectile_id", 0))
	if projectile_id <= 0:
		return

	var player := player_manager.get_player(peer_id)
	if player == null or not player.authenticated or not player.is_alive:
		return

	if not _allow_local_hit_report(peer_id):
		return

	var proj: ProjectileState = projectile_manager.projectiles.get(projectile_id, null)
	if proj == null or not proj.alive:
		return

	# Only monster-fired projectiles are client-authoritative for the victim's
	# dodge; player-fired (PvP) projectiles stay server-authoritative.
	if proj.owner_id < GameConstants.MONSTER_ENTITY_ID_START:
		return

	if not _local_hit_is_plausible(proj, player.entity_id):
		if config.debug_logging:
			print("[ServerMain] Rejected implausible local hit report: peer=%d projectile=%d" % [peer_id, projectile_id])
		return

	# Apply through the shared path, then despawn the bullet for everyone.
	collision_handler.apply_player_hit(
		proj.owner_id, player.entity_id, player_manager, _get_network_manager(), broadcast_service, proj.position
	)
	projectile_manager.remove_projectile(projectile_id, "player_hit")


## Sliding 1-second window rate limiter for client hit reports.
func _allow_local_hit_report(peer_id: int) -> bool:
	var now := Time.get_ticks_msec()
	var entry: Dictionary = _local_hit_report_window.get(peer_id, {})
	var start_ms: int = entry.get("start_ms", 0)
	var count: int = entry.get("count", 0)
	if now - start_ms >= 1000:
		start_ms = now
		count = 0
	count += 1
	_local_hit_report_window[peer_id] = { "start_ms": start_ms, "count": count }
	return count <= LOCAL_HIT_REPORT_MAX_PER_SECOND


## A reported hit is plausible if the bullet's traveled path passes within a
## generous radius of the reporting player's authoritative position anywhere in
## the recorded history window. We test the bullet's FULL straight-line flight
## (reconstructed spawn -> current position), not just the last tick: the client
## reports the hit ~render-delay + RTT after the bullet's authoritative position
## passed the player, so by the time we process the report the live bullet is
## downrange of the contact point. Rejects fabricated "hit me from across the map".
func _local_hit_is_plausible(proj: ProjectileState, entity_id: int) -> bool:
	var threshold := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS + LOCAL_HIT_VALIDATION_MARGIN
	# Straight-line flight start (distance_traveled is exact for a still-alive
	# bullet that has not been clamped by an obstacle).
	var flight_start := proj.position - proj.direction * proj.distance_traveled
	var positions := player_manager.get_recent_positions(entity_id)
	for pos: Vector2 in positions:
		var closest := GameConstants.closest_point_on_segment(pos, flight_start, proj.position)
		if pos.distance_to(closest) < threshold:
			return true
	return false


## Respawn a player and broadcast the authoritative respawn event.
func _respawn_player_and_broadcast(peer_id: int) -> bool:
	var state = player_manager.get_player(peer_id)
	if state == null:
		return false

	# Respawn via PlayerManager
	var success = player_manager.respawn_player(peer_id)
	if not success:
		return false

	# Broadcast RESPAWN event to all clients
	var nm = _get_network_manager()
	if nm == null:
		return true

	var respawn_packet = GameEventPacket.create_respawn(state.entity_id, state.position)
	nm.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		respawn_packet.to_dict()
	)

	if config.debug_logging:
		print("[ServerMain] Player %d respawned at %s" % [state.entity_id, state.position])

	return true


## Prepare the HTTP publisher used by the API's region list.
func _setup_region_status_publisher() -> void:
	if config.api_server_url.is_empty():
		return

	region_status_request = HTTPRequest.new()
	add_child(region_status_request)
	region_status_request.request_completed.connect(_on_region_status_published)
	_publish_region_status()


## Publish current live capacity to the API so menus can show connected bots/players.
func _publish_region_status(status: String = "online") -> void:
	if region_status_request == null or region_status_request_in_flight:
		return

	var url := config.api_server_url.rstrip("/") + "/api/regions/heartbeat"
	var body := JSON.stringify({
		"region_id": config.region,
		"active_players": player_manager.get_player_count(),
		"max_players": config.max_players,
		"websocket_url": "ws://localhost:%d" % config.port,
		"status": status
	})
	var headers := PackedStringArray(["Content-Type: application/json"])
	var heartbeat_token := OS.get_environment("REGION_HEARTBEAT_TOKEN")
	if not heartbeat_token.is_empty():
		headers.append("X-Region-Heartbeat-Token: %s" % heartbeat_token)
	var error := region_status_request.request(url, headers, HTTPClient.METHOD_POST, body)
	if error != OK:
		region_status_request_in_flight = false
		if config.debug_logging and not region_status_warning_logged:
			push_warning("[ServerMain] Failed to publish region status: %d" % error)
			region_status_warning_logged = true
		return

	region_status_request_in_flight = true


func _on_region_status_published(result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	region_status_request_in_flight = false

	if config.debug_logging and (result != HTTPRequest.RESULT_SUCCESS or response_code < 200 or response_code >= 300):
		if not region_status_warning_logged:
			push_warning("[ServerMain] Region status publish failed: result=%d response=%d" % [result, response_code])
			region_status_warning_logged = true
		return

	region_status_warning_logged = false


## Broadcast server metrics to all clients
func _broadcast_server_metrics(nm: Node) -> void:
	if nm == null or player_manager.get_player_count() == 0:
		return
	var m: Dictionary = server_metrics.get_metrics()
	nm.broadcast_to_clients(
		NetworkManager.MessageType.SERVER_METRICS,
		m
	)


## Get NetworkManager singleton
func _get_network_manager() -> Node:
	return get_tree().root.get_node_or_null("NetworkManager")


## Get current server metrics
func get_metrics() -> Dictionary:
	return server_metrics.get_metrics()


## Get connected player count
func get_player_count() -> int:
	return player_manager.get_player_count()


## Check if server is running
func is_running() -> bool:
	return server_running


## Shutdown server gracefully
func shutdown(reason: String = "Server shutdown") -> void:
	print("[ServerMain] Shutting down: %s" % reason)
	server_running = false

	# Notify all connected clients
	var nm = _get_network_manager()
	if nm != null:
		# Discard any half-built tick batch - shutdown takes precedence and we
		# need each peer to receive the DISCONNECT immediately.
		if nm.has_method("clear_batches"):
			nm.clear_batches()
		for state: PlayerState in player_manager.get_all_players():
			nm.send_to_client(
				state.peer_id,
				NetworkManager.MessageType.DISCONNECT,
				{"reason": PacketTypes.DisconnectReason.SERVER_SHUTDOWN}
			)

	player_manager.clear_all()
	projectile_manager.clear_all()
	monster_manager.clear_all()
	monster_ai = null
	if broadcast_service.leaderboard_manager:
		broadcast_service.leaderboard_manager.clear()
	broadcast_service.clear_all_caches()
	game_entities.clear()
	server_metrics.clear()

	print("[ServerMain] Server shutdown complete")


## Called when scene is exited
func _exit_tree() -> void:
	if server_running:
		shutdown("Scene exit")
