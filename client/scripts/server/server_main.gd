## ServerMain - Main server scene controller
## Coordinates server-side game logic and manages authoritative game state
## Entry point for dedicated server mode
extends Node

## Server configuration
var config: ServerConfig = null

## Server state
var server_running: bool = false
var server_time: float = 0.0

## Player management (peer_id -> PlayerState)
## PlayerState will be defined in TASK-012
var connected_players: Dictionary = {}

## Entity management (entity_id -> EntityState)
## Used for projectiles, monsters, etc. (TASK-014, TASK-015)
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
	connected_players.clear()
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


## Process queued client inputs
## Placeholder for TASK-012 implementation
func _process_client_inputs() -> void:
	# Will process movement inputs, attack commands, etc.
	pass


## Update game state (positions, timers, etc.)
## Placeholder for TASK-012, TASK-013 implementation
func _update_game_state() -> void:
	# Will handle:
	# - Player movement validation (TASK-013)
	# - Projectile movement (TASK-014)
	# - Entity timers and cooldowns
	pass


## Update monster AI behavior
## Placeholder for TASK-016 implementation
func _update_monster_ai() -> void:
	# Will handle monster pathfinding and targeting
	pass


## Process collision detection
## Placeholder for TASK-014 implementation
func _process_collisions() -> void:
	# Will handle projectile-entity collisions
	pass


## Broadcast state updates to all connected clients
## Placeholder for TASK-012 implementation
func _broadcast_state_updates() -> void:
	# Will send delta-compressed state updates
	# Using interest management (only entities in view)
	pass


## Handle client connection
func _on_client_connected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client connected: %d" % peer_id)

	if connected_players.size() >= config.max_players:
		print("[ServerMain] Server full, rejecting client: %d" % peer_id)
		# TODO: Send rejection message and disconnect
		return

	# Create placeholder player state (will be expanded in TASK-012)
	connected_players[peer_id] = {
		"peer_id": peer_id,
		"connected_at": server_time,
		"authenticated": false,
		"character_id": "",
		"position": Vector2.ZERO,
		"last_input_time": 0.0
	}

	print("[ServerMain] Player count: %d/%d" % [connected_players.size(), config.max_players])


## Handle client disconnection
func _on_client_disconnected(peer_id: int) -> void:
	if config.debug_logging:
		print("[ServerMain] Client disconnected: %d" % peer_id)

	if connected_players.has(peer_id):
		connected_players.erase(peer_id)

	print("[ServerMain] Player count: %d/%d" % [connected_players.size(), config.max_players])


## Handle incoming client message
func _on_client_message(peer_id: int, message_type: int, data: Dictionary) -> void:
	if not connected_players.has(peer_id):
		if config.debug_logging:
			print("[ServerMain] Message from unknown peer: %d" % peer_id)
		return

	# Handle message based on type (will be expanded in later tasks)
	# MessageType enum values from NetworkManager
	match message_type:
		1:  # PLAYER_INPUT
			_handle_player_input(peer_id, data)
		6:  # CONNECT_AUTH
			_handle_auth_request(peer_id, data)
		_:
			if config.debug_logging:
				print("[ServerMain] Unhandled message type %d from peer %d" % [message_type, peer_id])


## Handle player input message
## Placeholder for TASK-013 implementation
func _handle_player_input(peer_id: int, data: Dictionary) -> void:
	# Will validate and queue player input for processing
	pass


## Handle authentication request
## Placeholder for authentication implementation
func _handle_auth_request(peer_id: int, data: Dictionary) -> void:
	if config.debug_logging:
		print("[ServerMain] Auth request from peer %d" % peer_id)

	if connected_players.has(peer_id):
		connected_players[peer_id].authenticated = true
		connected_players[peer_id].character_id = data.get("character_id", "")
		# TODO: Validate character_id with API server


## Record tick processing time for metrics
func _record_tick_time(time_ms: float) -> void:
	_tick_times.append(time_ms)
	if _tick_times.size() > METRICS_SAMPLE_SIZE:
		_tick_times.pop_front()


## Update performance metrics
func _update_metrics() -> void:
	metrics.tick_count = tick_count
	metrics.player_count = connected_players.size()
	metrics.entity_count = game_entities.size()

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
	return connected_players.size()


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
		for peer_id in connected_players.keys():
			# TODO: Send disconnect message to each client
			pass

	connected_players.clear()
	game_entities.clear()

	print("[ServerMain] Server shutdown complete")


## Called when scene is exited
func _exit_tree() -> void:
	if server_running:
		shutdown("Scene exit")
