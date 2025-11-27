## ServerMain - Main server scene controller
## Coordinates server-side game logic and manages authoritative game state
## Entry point for dedicated server mode
extends Node

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

## Entity management (entity_id -> EntityState)
## Used for additional entities beyond players/projectiles/monsters
var game_entities: Dictionary = {}

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

	# Entity timers and cooldowns handled in player input processing


## Update monster AI behavior
## Placeholder for TASK-016 implementation
func _update_monster_ai() -> void:
	# Will handle monster pathfinding and targeting
	pass


## Process collision detection (TASK-014)
func _process_collisions() -> void:
	# Check projectile-player collisions
	var hits = projectile_manager.check_collisions_with_players(player_manager)

	# Log hits for now (damage system will be added in future task)
	for hit in hits:
		if config.debug_logging:
			print("[ServerMain] Projectile hit: proj=%d -> player=%d at %s" % [
				hit.projectile_id, hit.target_id, hit.position
			])


## Broadcast state updates to all connected clients (TASK-012)
func _broadcast_state_updates() -> void:
	if player_manager.get_player_count() == 0:
		return

	var network_manager = _get_network_manager()
	if network_manager == null:
		return

	# Collect all player states for broadcast
	var state_data = player_manager.collect_state_updates(tick_count)

	# Add projectile entities (TASK-014)
	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		state_data.entities.append(proj_data)

	# Add monster entities (TASK-015)
	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		state_data.entities.append(monster_data)

	# Broadcast to all connected clients
	network_manager.broadcast_to_clients(NetworkManager.MessageType.STATE_UPDATE, state_data)


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

	print("[ServerMain] Player count: %d/%d" % [player_manager.get_player_count(), config.max_players])


## Handle client disconnection (TASK-012)
func _on_client_disconnected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client disconnected: %d" % peer_id)

	player_manager.remove_player(peer_id)

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
	game_entities.clear()

	print("[ServerMain] Server shutdown complete")


## Called when scene is exited
func _exit_tree() -> void:
	if server_running:
		shutdown("Scene exit")
