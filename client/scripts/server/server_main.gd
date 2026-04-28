## ServerMain - Main server scene controller
## Coordinates server-side game logic and manages authoritative game state
## Delegates collision, broadcasting, and metrics to focused helper classes
extends Node

const LeaderboardManager := preload("res://scripts/server/leaderboard_manager.gd")
const ServerBroadcastService := preload("res://scripts/server/server_broadcast_service.gd")
const ServerCollisionHandler := preload("res://scripts/server/server_collision_handler.gd")
const ServerMetrics := preload("res://scripts/server/server_metrics.gd")

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

## Tick loop state
var tick_timer: float = 0.0
var tick_count: int = 0


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

	monster_manager = MonsterManager.new()
	monster_manager.debug_logging = config.debug_logging
	monster_spawner = MonsterSpawner.new(monster_manager, player_manager)
	monster_spawner.debug_logging = config.debug_logging

	monster_ai = MonsterAI.new(player_manager, projectile_manager)
	monster_ai.debug_logging = config.debug_logging

	# Extracted service components
	collision_handler = ServerCollisionHandler.new()
	collision_handler.debug_logging = config.debug_logging

	broadcast_service = ServerBroadcastService.new()
	broadcast_service.debug_logging = config.debug_logging
	broadcast_service.aoi_radius = config.aoi_radius
	broadcast_service.leaderboard_manager = LeaderboardManager.new()
	broadcast_service.leaderboard_manager.debug_logging = config.debug_logging

	server_metrics = ServerMetrics.new()
	server_metrics.debug_logging = config.debug_logging

	game_entities.clear()

	set_process(true)
	print("[ServerMain] Server running at %d Hz tick rate" % config.tick_rate)


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
		server_metrics.update_metrics(player_manager.get_player_count(), entity_count, tick_count, network_stats)
		# Broadcast server metrics to all connected clients
		_broadcast_server_metrics(nm)


## Process a single server tick - core game loop
func _process_server_tick() -> void:
	var tick_start := Time.get_ticks_usec()
	tick_count += 1

	var nm = _get_network_manager()

	# 1. Process incoming client inputs
	_process_client_inputs()

	# 2. Update game state
	_update_game_state()

	# 3. Run AI/monster logic
	_update_monster_ai()

	# 4. Snapshot monster positions before collision/damage mutates state. Player
	# projectile hit tests rewind to this short history.
	monster_manager.record_position_snapshot(tick_count)

	# 5. Process collisions (delegated to CollisionHandler)
	collision_handler.process_collisions(
		projectile_manager, player_manager, monster_manager, nm, broadcast_service
	)

	# 6. Broadcast state updates (delegated to BroadcastService)
	broadcast_service.broadcast_state_updates(
		player_manager, projectile_manager, monster_manager, nm, tick_count
	)

	# 7. Remove dead monsters after death/removed state has been broadcast.
	monster_manager.cleanup_dead_monsters()

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
		while true:
			var shot := state.pop_pending_shot()
			if shot.is_empty():
				break
			_try_spawn_projectile(state, shot)

		if state.is_shoot_held() and state.can_shoot():
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

		# Create correction packet using ActionConfirmPacket
		var confirm_packet = ActionConfirmPacket.create_move_confirm(
			sequence,
			position,
			tick_count,
			success
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
		compensation_data.get("source", "none")
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
	var monster_fire_events: Array[int] = monster_ai.update_all(alive_monsters, tick_interval)

	for monster_entity_id: int in monster_fire_events:
		_broadcast_projectile_fired(monster_entity_id)

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

	# Register with leaderboard manager
	if broadcast_service.leaderboard_manager and state:
		broadcast_service.leaderboard_manager.register_player(state.entity_id)

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
		_:
			if config.debug_logging:
				print("[ServerMain] Unhandled message type %d from peer %d" % [message_type, peer_id])


## Handle authentication request (TASK-012)
func _handle_auth_request(peer_id: int, data: Dictionary) -> void:
	if config.debug_logging:
		print("[ServerMain] Auth request from peer %d" % peer_id)

	var character_id = data.get("character_id", "")
	var character_name = data.get("character_name", "Player_%d" % peer_id)

	# Authenticate player via PlayerManager
	# TODO: Validate character_id with API server
	player_manager.authenticate_player(peer_id, character_id, character_name)

	# Broadcast PLAYER_INFO to all clients for the newly authenticated player
	var nm = _get_network_manager()
	broadcast_service.broadcast_player_info(peer_id, player_manager, nm)

	# Send PLAYER_INFO for all existing players to the new client
	broadcast_service.send_all_player_info_to_client(peer_id, player_manager, nm)


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
