## ServerMain - Main server scene controller
## Coordinates server-side game logic and manages authoritative game state
## Entry point for dedicated server mode
extends Node

## Preload delta state cache for TASK-021
const DeltaStateCacheClass = preload("res://scripts/server/delta_state_cache.gd")

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

## Leaderboard management
var leaderboard_manager: LeaderboardManager = null

## Entity management (entity_id -> EntityState)
## Used for additional entities beyond players/projectiles/monsters
var game_entities: Dictionary = {}

## Leaderboard broadcast timer (periodic fallback)
var leaderboard_timer: float = 0.0
const LEADERBOARD_BROADCAST_INTERVAL := 5.0

## Delta state caches per client (TASK-021)
## peer_id -> DeltaStateCache
var delta_caches: Dictionary = {}

## Tick loop state
var tick_timer: float = 0.0
var tick_count: int = 0

## Performance metrics
var metrics: Dictionary = {
	"tick_count": 0,
	"avg_tick_time_ms": 0.0,
	"max_tick_time_ms": 0.0,
	"player_count": 0,
	"entity_count": 0,
	"last_metrics_time": 0.0
}
var _tick_times: Array[float] = []
const METRICS_SAMPLE_SIZE := 30  # Track last 30 ticks for averaging


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
	var network_manager = _get_network_manager()
	if network_manager == null:
		push_error("[ServerMain] NetworkManager not found!")
		return

	# Connect to server-side signals
	if network_manager.has_signal("server_client_connected"):
		network_manager.server_client_connected.connect(_on_client_connected)
	if network_manager.has_signal("server_client_disconnected"):
		network_manager.server_client_disconnected.connect(_on_client_disconnected)
	if network_manager.has_signal("server_client_message"):
		network_manager.server_client_message.connect(_on_client_message)

	print("[ServerMain] Connected to NetworkManager signals")


## Initialize server state
func _initialize_server() -> void:
	server_running = true
	server_time = 0.0
	tick_count = 0

	# Initialize player manager (TASK-012)
	player_manager = PlayerManager.new()
	player_manager.debug_logging = config.debug_logging

	# Initialize projectile manager (TASK-014)
	projectile_manager = ProjectileManager.new()
	projectile_manager.debug_logging = config.debug_logging

	# Initialize monster manager and spawner (TASK-015)
	monster_manager = MonsterManager.new()
	monster_manager.debug_logging = config.debug_logging
	monster_spawner = MonsterSpawner.new(monster_manager, player_manager)
	monster_spawner.debug_logging = config.debug_logging

	# Initialize monster AI (TASK-016)
	monster_ai = MonsterAI.new(player_manager, projectile_manager)
	monster_ai.debug_logging = config.debug_logging

	# Initialize leaderboard manager
	leaderboard_manager = LeaderboardManager.new()
	leaderboard_manager.debug_logging = config.debug_logging

	game_entities.clear()
	_tick_times.clear()
	metrics.last_metrics_time = Time.get_ticks_msec() / 1000.0

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
	if server_time - metrics.last_metrics_time >= 1.0:
		_update_metrics()
		metrics.last_metrics_time = server_time


## Process a single server tick - core game loop
func _process_server_tick() -> void:
	var tick_start := Time.get_ticks_usec()
	tick_count += 1

	# 1. Process incoming client messages
	#    (Messages are handled via signals, but queued processing could go here)
	_process_client_inputs()

	# 2. Update game state
	_update_game_state()

	# 3. Run AI/monster logic (TASK-016)
	_update_monster_ai()

	# 4. Process physics/collisions (TASK-014)
	_process_collisions()

	# 5. Broadcast state updates to clients (TASK-012)
	_broadcast_state_updates()

	# Track tick performance
	var tick_time := (Time.get_ticks_usec() - tick_start) / 1000.0  # Convert to ms
	_record_tick_time(tick_time)


## Process queued client inputs and validate movement (TASK-012, TASK-013)
func _process_client_inputs() -> void:
	var tick_interval := 1.0 / config.tick_rate

	# Process shoot inputs before movement (TASK-014)
	_process_shoot_inputs()

	var corrections = player_manager.process_all_inputs(tick_interval)

	# Send correction packets to clients with invalid positions
	if corrections.size() > 0:
		_send_position_corrections(corrections)


## Process shoot inputs and spawn projectiles (TASK-014)
func _process_shoot_inputs() -> void:
	for state: PlayerState in player_manager.get_all_players():
		# Check each queued input for shoot flag
		for input in state.input_queue:
			var flags: int = input.get("input_flags", 0)
			if flags & PacketTypes.INPUT_FLAG_SHOOT:
				_try_spawn_projectile(state, input)


## Send position correction packets to clients (TASK-013)
func _send_position_corrections(corrections: Array[Dictionary]) -> void:
	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	for correction in corrections:
		var peer_id: int = correction.peer_id
		var sequence: int = correction.sequence
		var position: Vector2 = correction.position
		var cheat_detected: bool = correction.cheat_detected

		# Create correction packet using ActionConfirmPacket
		var confirm_packet = ActionConfirmPacket.create_move_confirm(
			sequence,
			position,
			tick_count,
			false  # success=false indicates correction needed
		)

		# Send correction to the specific client
		network_manager.send_to_client(
			peer_id,
			NetworkManager.MessageType.ACTION_CONFIRM,
			confirm_packet.to_dict()
		)

		# Log potential cheating attempts
		if cheat_detected:
			print("[ServerMain] CHEAT DETECTED: peer=%d teleport attempt (deviation=%.1f)" % [
				peer_id, correction.deviation
			])
		elif config.debug_logging:
			print("[ServerMain] Position correction: peer=%d seq=%d deviation=%.1f" % [
				peer_id, sequence, correction.deviation
			])


## Try to spawn a projectile from player shoot input (TASK-014)
func _try_spawn_projectile(player: PlayerState, input: Dictionary) -> void:
	# Check shoot cooldown
	if not player.can_shoot():
		return

	# Get aim direction from input
	var aim_angle: float = input.get("aim_angle", player.aim_angle)
	var aim_direction := Vector2.from_angle(aim_angle)

	# Spawn position slightly in front of player to avoid self-collision
	var spawn_offset := aim_direction * (GameConstants.PLAYER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0)
	var spawn_position := player.position + spawn_offset

	# Spawn the projectile
	var projectile := projectile_manager.spawn_projectile(
		player.entity_id,
		spawn_position,
		aim_direction
	)

	if projectile != null:
		# Start cooldown on successful spawn
		player.start_shoot_cooldown()


## Update game state (positions, timers, etc.)
func _update_game_state() -> void:
	var tick_interval := 1.0 / config.tick_rate

	# Update projectile positions (TASK-014)
	projectile_manager.update_all(tick_interval)

	# Update monster spawner (TASK-015)
	monster_spawner.update(tick_interval)

	# Update player invulnerability timers
	_update_invulnerability_timers(tick_interval)

	# Broadcast leaderboard periodically
	leaderboard_timer += tick_interval
	if leaderboard_timer >= LEADERBOARD_BROADCAST_INTERVAL:
		leaderboard_timer = 0.0
		_broadcast_leaderboard()


## Update monster AI behavior (TASK-016)
func _update_monster_ai() -> void:
	if monster_ai == null or monster_manager == null:
		return

	var tick_interval := 1.0 / config.tick_rate
	var alive_monsters := monster_manager.get_alive_monsters()

	# Update all monster AI - handles movement, targeting, and shooting
	var projectiles_spawned := monster_ai.update_all(alive_monsters, tick_interval)

	if config.debug_logging and projectiles_spawned > 0:
		print("[ServerMain] Monsters spawned %d projectiles this tick" % projectiles_spawned)


## Process collision detection (TASK-014, TASK-016)
func _process_collisions() -> void:
	var network_manager = _get_network_manager()

	# Check projectile-player collisions (players can be hit by monster projectiles)
	var player_hits = projectile_manager.check_collisions_with_players(player_manager)

	for hit in player_hits:
		var target := player_manager.get_player_by_entity_id(hit.target_id)
		if target != null:
			# Determine damage based on projectile owner
			var damage: int = GameConstants.PLAYER_PROJECTILE_DAMAGE
			# Check if owner is a monster (entity_id >= 100000)
			if hit.owner_id >= 100000:
				damage = GameConstants.MONSTER_PROJECTILE_DAMAGE

			# Record killer before damage (take_damage may set DEAD state)
			target.last_killer_id = hit.owner_id
			var killed := target.take_damage(damage)

			# Broadcast DAMAGE event to all clients
			if network_manager:
				var damage_packet = GameEventPacket.create_damage(
					hit.owner_id, hit.target_id, damage
				)
				network_manager.broadcast_to_clients(
					NetworkManager.MessageType.GAME_EVENT,
					damage_packet.to_dict()
				)

			if killed and network_manager:
				# PvP kill: attribute to killer player
				if hit.owner_id < 100000:
					var killer := player_manager.get_player_by_entity_id(hit.owner_id)
					if killer != null:
						killer.pvp_kills += 1
					var kill_packet = GameEventPacket.create_kill_pvp(
						hit.owner_id, hit.target_id
					)
					network_manager.broadcast_to_clients(
						NetworkManager.MessageType.GAME_EVENT,
						kill_packet.to_dict()
					)

					# Record kill in leaderboard and broadcast immediately
					if leaderboard_manager:
						leaderboard_manager.record_pvp_kill(hit.owner_id, hit.target_id)
						_broadcast_leaderboard()
				else:
					# PvE kill: monster killed player
					var kill_packet = GameEventPacket.create_kill(
						hit.owner_id, hit.target_id
					)
					network_manager.broadcast_to_clients(
						NetworkManager.MessageType.GAME_EVENT,
						kill_packet.to_dict()
					)

			if config.debug_logging:
				print("[ServerMain] Player %d took %d damage from entity %d (killed=%s)" % [
					hit.target_id, damage, hit.owner_id, killed
				])

	# Check projectile-monster collisions (monsters can be hit by player projectiles)
	var monster_hits = projectile_manager.check_collisions_with_monsters(monster_manager)

	for hit in monster_hits:
		var monster := monster_manager.get_monster(hit.target_id)
		if monster != null:
			var killed := monster.take_damage(GameConstants.PLAYER_PROJECTILE_DAMAGE)

			# Broadcast DAMAGE event to all clients
			if network_manager:
				var damage_packet = GameEventPacket.create_damage(
					hit.owner_id, hit.target_id, GameConstants.PLAYER_PROJECTILE_DAMAGE
				)
				network_manager.broadcast_to_clients(
					NetworkManager.MessageType.GAME_EVENT,
					damage_packet.to_dict()
				)

			# Attribute monster kill to player
			if killed:
				var killer := player_manager.get_player_by_entity_id(hit.owner_id)
				if killer != null:
					killer.monster_kills += 1

				if network_manager:
					var kill_packet = GameEventPacket.create_kill(
						hit.owner_id, hit.target_id
					)
					network_manager.broadcast_to_clients(
						NetworkManager.MessageType.GAME_EVENT,
						kill_packet.to_dict()
					)

			if config.debug_logging:
				print("[ServerMain] Monster %d took %d damage from player %d (killed=%s)" % [
					hit.target_id, GameConstants.PLAYER_PROJECTILE_DAMAGE, hit.owner_id, killed
				])


## Broadcast state updates to all connected clients (TASK-012, TASK-021)
## Now uses delta compression to reduce bandwidth
func _broadcast_state_updates() -> void:
	if player_manager.get_player_count() == 0:
		return

	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	# Collect all entity states (full state for delta calculation)
	var all_entities: Array[Dictionary] = []

	# Add player entities
	for state: PlayerState in player_manager.get_all_players():
		all_entities.append(state.to_entity_data())

	# Add projectile entities (TASK-014)
	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		all_entities.append(proj_data)

	# Add monster entities (TASK-015)
	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		all_entities.append(monster_data)

	# Send delta-compressed updates to each client (TASK-021)
	for state: PlayerState in player_manager.get_all_players():
		var peer_id: int = state.peer_id
		var cache = _get_or_create_delta_cache(peer_id)

		# Check if we need to send a full state (baseline) packet
		var needs_baseline: bool = cache.needs_full_state_for_interval(tick_count)

		# Create appropriate packet type
		var packet_data: Dictionary
		if needs_baseline:
			packet_data = _create_full_state_packet(all_entities, cache)
		else:
			packet_data = _create_delta_packet(all_entities, cache)

		# Send to this client
		network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)


## Get or create delta cache for a client (TASK-021)
func _get_or_create_delta_cache(peer_id: int):
	if not delta_caches.has(peer_id):
		delta_caches[peer_id] = DeltaStateCacheClass.create_for_client(peer_id)
		delta_caches[peer_id].debug_logging = config.debug_logging
	return delta_caches[peer_id]


## Create a full state (baseline) packet (TASK-021)
func _create_full_state_packet(entities: Array[Dictionary], cache) -> Dictionary:
	var entity_data: Array[Dictionary] = []

	for entity in entities:
		var entity_id: int = entity.get("id", -1)
		if entity_id < 0:
			continue

		# Full state: all fields present, delta_mask = FULL_STATE
		entity_data.append({
			"entity_id": entity_id,
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0),
			"delta_mask": PacketTypes.DELTA_MASK_FULL_STATE
		})

		# Update cache with sent state
		cache.update_cache(entity_id, {
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0)
		}, tick_count)

	# Reset baseline tick
	cache.reset_baseline(tick_count)

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,  # Full state (baseline)
		"baseline_tick": tick_count,
		"entities": entity_data
	}


## Create a delta-compressed packet (TASK-021)
func _create_delta_packet(entities: Array[Dictionary], cache) -> Dictionary:
	var entity_data: Array[Dictionary] = []
	var active_entity_ids: Array[int] = []

	for entity in entities:
		var entity_id: int = entity.get("id", -1)
		if entity_id < 0:
			continue

		active_entity_ids.append(entity_id)

		var current_state := {
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0)
		}

		# Calculate delta mask
		var delta_mask: int = cache.calculate_delta_mask(entity_id, current_state, tick_count)

		# Skip entities with no changes (delta_mask = 0)
		if delta_mask == 0:
			continue

		# Add entity to packet
		entity_data.append({
			"entity_id": entity_id,
			"entity_type": current_state.entity_type,
			"position": current_state.position,
			"animation_state": current_state.animation_state,
			"flags": current_state.flags,
			"delta_mask": delta_mask
		})

		# Update cache with sent state
		cache.update_cache(entity_id, current_state, tick_count)

	# Cleanup stale entities from cache
	cache.cleanup_stale_entities(active_entity_ids)

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"baseline_tick": cache.get_baseline_tick(),
		"entities": entity_data
	}


## Handle client connection (TASK-012)
func _on_client_connected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client connected: %d" % peer_id)

	if player_manager.get_player_count() >= config.max_players:
		print("[ServerMain] Server full, rejecting client: %d" % peer_id)
		var network_manager = _get_network_manager()
		if network_manager:
			network_manager.disconnect_client(peer_id, "Server full")
		return

	# Create player state via PlayerManager
	var state = player_manager.add_player(peer_id)
	if state == null:
		print("[ServerMain] Failed to create player state for: %d" % peer_id)
		return

	# Create delta cache for this client (TASK-021)
	delta_caches[peer_id] = DeltaStateCacheClass.create_for_client(peer_id)
	delta_caches[peer_id].debug_logging = config.debug_logging

	# Register with leaderboard manager
	if leaderboard_manager and state:
		leaderboard_manager.register_player(state.entity_id)

	print("[ServerMain] Player count: %d/%d" % [player_manager.get_player_count(), config.max_players])


## Handle client disconnection (TASK-012)
func _on_client_disconnected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client disconnected: %d" % peer_id)

	# Remove from leaderboard before player_manager (need entity_id)
	var state = player_manager.get_player(peer_id)
	if leaderboard_manager and state:
		leaderboard_manager.remove_player(state.entity_id)
		_broadcast_leaderboard()

	player_manager.remove_player(peer_id)

	# Remove delta cache for this client (TASK-021)
	delta_caches.erase(peer_id)

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
			_handle_player_input(peer_id, data)
		NetworkManager.MessageType.CONNECT_AUTH:
			_handle_auth_request(peer_id, data)
		NetworkManager.MessageType.REQUEST_FULL_STATE:
			_handle_full_state_request(peer_id)
		NetworkManager.MessageType.RESPAWN_REQUEST:
			_handle_respawn_request(peer_id)
		_:
			if config.debug_logging:
				print("[ServerMain] Unhandled message type %d from peer %d" % [message_type, peer_id])


## Handle player input message (TASK-012)
## Movement validation will be added in TASK-013
func _handle_player_input(peer_id: int, data: Dictionary) -> void:
	# Queue input for processing in next tick
	player_manager.queue_player_input(peer_id, data)


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
	_broadcast_player_info(peer_id)

	# Send PLAYER_INFO for all existing players to the new client
	_send_all_player_info_to_client(peer_id)


## Handle client request for full state sync (TASK-021)
func _handle_full_state_request(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Full state request from peer %d" % peer_id)

	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	# Collect all entity states
	var all_entities: Array[Dictionary] = []

	# Add player entities
	for state: PlayerState in player_manager.get_all_players():
		all_entities.append(state.to_entity_data())

	# Add projectile entities
	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		all_entities.append(proj_data)

	# Add monster entities
	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		all_entities.append(monster_data)

	# Get or create delta cache for this client
	var cache = _get_or_create_delta_cache(peer_id)

	# Create and send full state packet
	var packet_data = _create_full_state_packet(all_entities, cache)

	network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)

	if config.debug_logging:
		print("[ServerMain] Sent full state to peer %d (%d entities)" % [peer_id, all_entities.size()])


## Record tick processing time for metrics
func _record_tick_time(time_ms: float) -> void:
	_tick_times.append(time_ms)
	if _tick_times.size() > METRICS_SAMPLE_SIZE:
		_tick_times.pop_front()


## Update performance metrics
func _update_metrics() -> void:
	metrics.tick_count = tick_count
	metrics.player_count = player_manager.get_player_count()
	metrics.entity_count = game_entities.size() + projectile_manager.get_projectile_count() + monster_manager.get_monster_count()

	if _tick_times.size() > 0:
		var total := 0.0
		var max_time := 0.0
		for t in _tick_times:
			total += t
			if t > max_time:
				max_time = t
		metrics.avg_tick_time_ms = total / _tick_times.size()
		metrics.max_tick_time_ms = max_time

	if config.debug_logging:
		_print_metrics()


## Print current server metrics
func _print_metrics() -> void:
	print("[ServerMain] Tick: %d | Players: %d | Entities: %d | Avg: %.2fms | Max: %.2fms" % [
		tick_count,
		metrics.player_count,
		metrics.entity_count,
		metrics.avg_tick_time_ms,
		metrics.max_tick_time_ms
	])


## Get NetworkManager singleton
func _get_network_manager() -> Node:
	return get_tree().root.get_node_or_null("NetworkManager")


## Get current server metrics
func get_metrics() -> Dictionary:
	return metrics.duplicate()


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
	var network_manager = _get_network_manager()
	if network_manager != null:
		for state: PlayerState in player_manager.get_all_players():
			network_manager.send_to_client(
				state.peer_id,
				NetworkManager.MessageType.DISCONNECT,
				{"reason": PacketTypes.DisconnectReason.SERVER_SHUTDOWN}
			)

	player_manager.clear_all()
	projectile_manager.clear_all()
	monster_manager.clear_all()
	monster_ai = null
	if leaderboard_manager:
		leaderboard_manager.clear()
	game_entities.clear()
	delta_caches.clear()  # TASK-021

	print("[ServerMain] Server shutdown complete")


## Broadcast PLAYER_INFO event for a specific player to all clients
func _broadcast_player_info(peer_id: int) -> void:
	var state = player_manager.get_player(peer_id)
	if state == null:
		return

	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	var event_packet = GameEventPacket.create_player_info(
		state.entity_id,
		state.character_name
	)

	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		event_packet.to_dict()
	)


## Send PLAYER_INFO for all existing players to a newly connected client
func _send_all_player_info_to_client(peer_id: int) -> void:
	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	for state: PlayerState in player_manager.get_all_players():
		if state.peer_id == peer_id:
			continue  # Skip self

		var event_packet = GameEventPacket.create_player_info(
			state.entity_id,
			state.character_name
		)

		network_manager.send_to_client(
			peer_id,
			NetworkManager.MessageType.GAME_EVENT,
			event_packet.to_dict()
		)


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

	# Respawn via PlayerManager
	var success = player_manager.respawn_player(peer_id)
	if not success:
		return

	# Broadcast RESPAWN event to all clients
	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	var respawn_packet = GameEventPacket.create_respawn(state.entity_id, state.position)
	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		respawn_packet.to_dict()
	)

	if config.debug_logging:
		print("[ServerMain] Player %d respawned at %s" % [state.entity_id, state.position])


## Update invulnerability timers for all players
func _update_invulnerability_timers(delta: float) -> void:
	for state: PlayerState in player_manager.get_all_players():
		state.update_invulnerability(delta)


## Broadcast leaderboard update to all clients
func _broadcast_leaderboard() -> void:
	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	var entries: Array
	if leaderboard_manager:
		entries = leaderboard_manager.get_top_n(10)
	else:
		# Fallback: collect from player states directly
		var players := player_manager.get_all_players()
		entries = []
		for state: PlayerState in players:
			entries.append({"entity_id": state.entity_id, "pvp_kills": state.pvp_kills})
		entries.sort_custom(func(a, b): return a.pvp_kills > b.pvp_kills)
		if entries.size() > 10:
			entries.resize(10)

	var packet = GameEventPacket.create_leaderboard_update(entries)
	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		packet.to_dict()
	)


## Called when scene is exited
func _exit_tree() -> void:
	if server_running:
		shutdown("Scene exit")
