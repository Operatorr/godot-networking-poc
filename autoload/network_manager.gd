## NetworkManager - WebSocket connection handling singleton
## Manages persistent WebSocket connections to game server
## Implements client-side networking as per ARCHITECTURE.md
extends Node

## Connection states
enum ConnectionState {
	DISCONNECTED,
	CONNECTING,
	CONNECTED,
	RECONNECTING,
	ERROR
}

## Network message types (as per ARCHITECTURE.md)
enum MessageType {
	PLAYER_INPUT = 1,      ## Client -> Server: Movement, actions
	STATE_UPDATE = 2,      ## Server -> Client: Entity positions, animations
	GAME_EVENT = 3,        ## Server -> Client: Damage, kills, status effects
	HEARTBEAT = 4,         ## Bidirectional: Keep-alive (1/sec, 4B)
	ACTION_CONFIRM = 5,    ## Server -> Client: Confirm attack
	CONNECT_AUTH = 6,      ## Client -> Server: Authentication handshake
	DISCONNECT = 7         ## Client -> Server: Clean disconnect
}

## Signals
signal connected_to_server()
signal disconnected_from_server(reason: String)
signal connection_error(error: String)
signal server_message_received(message_type: MessageType, data: Dictionary)
signal heartbeat_timeout()

## WebSocket client
var ws_client: WebSocketPeer = null

## Connection state
var current_state: ConnectionState = ConnectionState.DISCONNECTED
var server_url: String = ""
var auth_token: String = ""

## Reconnection parameters (exponential backoff)
var reconnect_attempts: int = 0
var max_reconnect_attempts: int = 5
var base_reconnect_delay: float = 1.0  ## Start with 1 second
var max_reconnect_delay: float = 32.0  ## Cap at 32 seconds
var reconnect_timer: float = 0.0

## Heartbeat system (1/sec as per spec)
var heartbeat_interval: float = 1.0
var heartbeat_timer: float = 0.0
var last_heartbeat_received: float = 0.0
var heartbeat_timeout_seconds: float = 5.0

## Network statistics
var stats: Dictionary = {
	"packets_sent": 0,
	"packets_received": 0,
	"bytes_sent": 0,
	"bytes_received": 0,
	"ping_ms": 0.0,
	"last_ping_time": 0.0
}

## Called when the node enters the scene tree
func _ready() -> void:
	print("[NetworkManager] Initializing...")
	set_process(true)

## Process loop - handles WebSocket polling and heartbeat
func _process(delta: float) -> void:
	match current_state:
		ConnectionState.CONNECTED:
			_process_connected(delta)
		ConnectionState.RECONNECTING:
			_process_reconnecting(delta)

## Process when connected
func _process_connected(delta: float) -> void:
	if ws_client == null:
		return

	# Poll WebSocket
	ws_client.poll()
	var state = ws_client.get_ready_state()

	# Handle state changes
	if state == WebSocketPeer.STATE_OPEN:
		# Receive messages
		while ws_client.get_available_packet_count() > 0:
			_handle_incoming_packet()

		# Send heartbeat
		heartbeat_timer += delta
		if heartbeat_timer >= heartbeat_interval:
			heartbeat_timer = 0.0
			send_heartbeat()

		# Check for heartbeat timeout
		var time_since_heartbeat = Time.get_ticks_msec() / 1000.0 - last_heartbeat_received
		if time_since_heartbeat > heartbeat_timeout_seconds:
			print("[NetworkManager] Heartbeat timeout - server not responding")
			heartbeat_timeout.emit()
			disconnect_from_server("Heartbeat timeout")

	elif state == WebSocketPeer.STATE_CLOSING:
		print("[NetworkManager] Connection closing...")

	elif state == WebSocketPeer.STATE_CLOSED:
		var code = ws_client.get_close_code()
		var reason = ws_client.get_close_reason()
		print("[NetworkManager] Connection closed - Code: %d, Reason: %s" % [code, reason])
		_on_connection_closed(reason)

## Process when reconnecting
func _process_reconnecting(delta: float) -> void:
	reconnect_timer -= delta
	if reconnect_timer <= 0.0:
		_attempt_reconnect()

## Connect to game server
func connect_to_server(url: String, token: String = "") -> void:
	if current_state == ConnectionState.CONNECTED:
		print("[NetworkManager] Already connected to server")
		return

	server_url = url
	auth_token = token
	current_state = ConnectionState.CONNECTING

	print("[NetworkManager] Connecting to %s..." % url)

	# Create WebSocket client
	ws_client = WebSocketPeer.new()

	# Connect to server
	var error = ws_client.connect_to_url(url, TLSOptions.client())

	if error != OK:
		print("[NetworkManager] Failed to initiate connection: %d" % error)
		current_state = ConnectionState.ERROR
		connection_error.emit("Failed to connect: Error %d" % error)
		_schedule_reconnect()
	else:
		# Wait for connection to establish
		await get_tree().create_timer(0.5).timeout
		_check_connection_status()

## Check if connection was established
func _check_connection_status() -> void:
	if ws_client == null:
		return

	ws_client.poll()
	var state = ws_client.get_ready_state()

	if state == WebSocketPeer.STATE_OPEN:
		print("[NetworkManager] Connected to server successfully")
		current_state = ConnectionState.CONNECTED
		reconnect_attempts = 0
		last_heartbeat_received = Time.get_ticks_msec() / 1000.0

		# Send authentication handshake
		if not auth_token.is_empty():
			send_auth_handshake()

		connected_to_server.emit()
	else:
		print("[NetworkManager] Connection failed or still pending")
		current_state = ConnectionState.ERROR
		connection_error.emit("Connection timeout")
		_schedule_reconnect()

## Send authentication handshake
func send_auth_handshake() -> void:
	var character_id = ""
	var region = "Asia"

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		character_id = game_mgr.player_data.get("character_id", "")
		region = game_mgr.player_data.get("selected_region", "Asia")

	var auth_data = {
		"token": auth_token,
		"character_id": character_id,
		"region": region
	}
	send_message(MessageType.CONNECT_AUTH, auth_data)
	print("[NetworkManager] Authentication handshake sent")

## Disconnect from server
func disconnect_from_server(reason: String = "User disconnect") -> void:
	if ws_client == null or current_state == ConnectionState.DISCONNECTED:
		return

	print("[NetworkManager] Disconnecting: %s" % reason)

	# Send disconnect message
	send_message(MessageType.DISCONNECT, {"reason": reason})

	# Close WebSocket
	ws_client.close(1000, reason)
	current_state = ConnectionState.DISCONNECTED

	disconnected_from_server.emit(reason)

## Handle incoming packet
func _handle_incoming_packet() -> void:
	if ws_client == null:
		return

	var packet = ws_client.get_packet()
	stats.packets_received += 1
	stats.bytes_received += packet.size()

	# Decode packet (binary format as per ARCHITECTURE.md)
	var message = _decode_packet(packet)

	if message == null:
		print("[NetworkManager] Failed to decode packet")
		return

	var message_type: MessageType = message.get("type", MessageType.HEARTBEAT)

	# Update heartbeat timestamp
	if message_type == MessageType.HEARTBEAT:
		last_heartbeat_received = Time.get_ticks_msec() / 1000.0
		_handle_heartbeat_response(message)
	else:
		# Emit signal for other systems to handle
		server_message_received.emit(message_type, message.get("data", {}))

## Send message to server
func send_message(message_type: MessageType, data: Dictionary = {}) -> void:
	if ws_client == null or current_state != ConnectionState.CONNECTED:
		print("[NetworkManager] Cannot send message - not connected")
		return

	var packet = _encode_packet(message_type, data)
	var error = ws_client.send(packet)

	if error == OK:
		stats.packets_sent += 1
		stats.bytes_sent += packet.size()
	else:
		print("[NetworkManager] Failed to send packet: %d" % error)

## Send player input (10/sec as per spec)
func send_player_input(input_data: Dictionary) -> void:
	send_message(MessageType.PLAYER_INPUT, input_data)

## Send heartbeat (1/sec, 4B as per spec)
func send_heartbeat() -> void:
	var heartbeat_data = {
		"timestamp": Time.get_ticks_msec(),
		"ping_request": true
	}
	send_message(MessageType.HEARTBEAT, heartbeat_data)
	stats.last_ping_time = Time.get_ticks_msec() / 1000.0

## Handle heartbeat response
func _handle_heartbeat_response(message: Dictionary) -> void:
	if message.get("data", {}).has("timestamp"):
		var server_timestamp = message.data.timestamp
		var now = Time.get_ticks_msec()
		stats.ping_ms = now - server_timestamp

## Encode packet to binary format (simplified version)
## TODO: Implement full binary protocol as per ARCHITECTURE.md Section 4.3
func _encode_packet(message_type: MessageType, data: Dictionary) -> PackedByteArray:
	# For now, use JSON (will optimize to binary later)
	var message = {
		"type": message_type,
		"data": data,
		"timestamp": Time.get_ticks_msec()
	}
	var json_string = JSON.stringify(message)
	return json_string.to_utf8_buffer()

## Decode packet from binary format (simplified version)
## TODO: Implement full binary protocol as per ARCHITECTURE.md Section 4.3
func _decode_packet(packet: PackedByteArray) -> Dictionary:
	# For now, use JSON (will optimize to binary later)
	var json_string = packet.get_string_from_utf8()
	var json = JSON.new()
	var error = json.parse(json_string)
	if error == OK:
		return json.data
	return {}

## Handle connection closed
func _on_connection_closed(reason: String) -> void:
	current_state = ConnectionState.DISCONNECTED
	disconnected_from_server.emit(reason)
	_schedule_reconnect()

## Schedule reconnection with exponential backoff
func _schedule_reconnect() -> void:
	if reconnect_attempts >= max_reconnect_attempts:
		print("[NetworkManager] Max reconnection attempts reached")
		current_state = ConnectionState.ERROR
		connection_error.emit("Failed to reconnect after %d attempts" % reconnect_attempts)
		return

	# Calculate exponential backoff delay
	var delay = min(base_reconnect_delay * pow(2, reconnect_attempts), max_reconnect_delay)
	reconnect_timer = delay
	reconnect_attempts += 1

	print("[NetworkManager] Scheduling reconnect attempt %d in %.1f seconds..." % [reconnect_attempts, delay])
	current_state = ConnectionState.RECONNECTING

## Attempt to reconnect
func _attempt_reconnect() -> void:
	print("[NetworkManager] Attempting to reconnect...")
	connect_to_server(server_url, auth_token)

## Check if connected to server
func is_server_connected() -> bool:
	return current_state == ConnectionState.CONNECTED and ws_client != null

## Get network statistics
func get_stats() -> Dictionary:
	return stats.duplicate()

## Reset statistics
func reset_stats() -> void:
	stats = {
		"packets_sent": 0,
		"packets_received": 0,
		"bytes_sent": 0,
		"bytes_received": 0,
		"ping_ms": 0.0,
		"last_ping_time": 0.0
	}
	print("[NetworkManager] Statistics reset")
