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
	DISCONNECT = 7,        ## Client -> Server: Clean disconnect
	REQUEST_FULL_STATE = 8, ## Client -> Server: Request full state sync (TASK-021)
	RESPAWN_REQUEST = 9,   ## Client -> Server: Request respawn after death
	SERVER_METRICS = 10,   ## Server -> Client: Server performance metrics (1/sec)
	BATCH = 11             ## Server -> Client: Multiple packets in one frame (TASK-066)
}

## Signals - Client mode
signal connected_to_server()
signal disconnected_from_server(reason: String)
signal connection_error(error: String)
signal server_message_received(message_type: MessageType, data: Dictionary)
signal heartbeat_timeout()

## Signals - Server mode (for ServerMain to connect to)
signal server_client_connected(peer_id: int)
signal server_client_disconnected(peer_id: int)
signal server_client_message(peer_id: int, message_type: int, data: Dictionary)

## Runtime mode detection
var is_server: bool = false

## WebSocket client
var ws_client: WebSocketPeer = null

## WebSocket server (for server mode)
var ws_server: TCPServer = null
var connected_peers: Dictionary = {}  # peer_id -> WebSocketPeer
var peer_connection_announced: Dictionary = {}  # peer_id -> true after WebSocket is open and ServerMain was notified

## Server-side heartbeat tracking (per peer)
var peer_last_heartbeat: Dictionary = {}  # peer_id -> float (timestamp)
var server_heartbeat_timeout: float = 5.0  # Same as client timeout

## Per-client bandwidth tracking (server mode)
var peer_bytes_sent: Dictionary = {}  # peer_id -> int (total bytes sent)

## Per-tick packet batching state (server mode, TASK-066). When a batch window
## is open, send_to_client appends encoded packets here instead of writing to
## the WebSocket immediately. flush_batches() then concatenates each peer's
## queue into BATCH packets capped by the on-wire count and payload fields.
var _batching_active: bool = false
var _pending_batches: Dictionary = {}  # peer_id -> Array[PackedByteArray]
## Hard cap on packets per BATCH frame (u8 count field on the wire).
const BATCH_MAX_PACKETS := 255
## BATCH payload is [u8 count][inner packets...], and the packet header stores
## payload length as u16. Leave one byte for the count field.
const BATCH_MAX_INNER_BYTES := PacketTypes.MAX_PACKET_SIZE - 1

## Connection state
var current_state: ConnectionState = ConnectionState.DISCONNECTED
var server_url: String = ""
var auth_token: String = ""
var server_port: int = 8080
## Idempotency for send_auth_handshake — true while a handshake is in flight or
## has been acknowledged for the current WebSocket session. Cleared on every
## fresh connection so reconnects can re-authenticate.
var _auth_handshake_sent: bool = false

## Reconnection parameters (exponential backoff)
var reconnect_attempts: int = 0
var max_reconnect_attempts: int = 5
var base_reconnect_delay: float = 1.0  ## Start with 1 second
var max_reconnect_delay: float = 32.0  ## Cap at 32 seconds
var reconnect_timer: float = 0.0
var connection_timeout_seconds: float = 5.0
var _connection_attempt_id: int = 0
var _had_successful_connection: bool = false

## Heartbeat system (1/sec as per spec)
var heartbeat_interval: float = 1.0
var heartbeat_timer: float = 0.0
var last_heartbeat_received: float = 0.0
var heartbeat_timeout_seconds: float = 5.0
const UINT32_WRAP: int = 4294967296
const MAX_REASONABLE_PING_MS: int = 10000

## Estimated offset between local Time.get_ticks_msec() and the server's
## wall clock, in milliseconds (§5.4). Computed as
## `server_ms - (local_ms - rtt/2)` and low-pass-filtered to ride out jitter.
## A value of `0` means no sample has been received yet.
var server_clock_offset_ms: float = 0.0
var server_clock_offset_samples: int = 0
const SERVER_CLOCK_FILTER_ALPHA := 0.2  ## EMA weight for new samples.

## Network statistics
var stats: Dictionary = {
	"packets_sent": 0,
	"packets_received": 0,
	"bytes_sent": 0,
	"bytes_received": 0,
	"ping_ms": 0.0,
	"last_ping_time": 0.0
}

## Per-channel egress breakdown (server mode, §8.1 of
## NETWORK_PERFORMANCE_UPGRADES.md). Keyed by MessageType. BATCH frames are
## tallied separately so envelope overhead is visible in dashboards.
var bytes_sent_by_type: Dictionary = {}

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = (OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless") and not _is_test_scene()

	print("[NetworkManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	if is_server:
		_initialize_server()
	else:
		_initialize_client()

	set_process(true)

## Initialize as server
func _initialize_server() -> void:
	# Load port from server config if available
	var config = ServerConfig.new()
	server_port = config.port

	print("[NetworkManager] Starting WebSocket server on port %d..." % server_port)
	ws_server = TCPServer.new()
	var error = ws_server.listen(server_port)
	if error != OK:
		push_error("[NetworkManager] Failed to start server: %d" % error)
		return
	current_state = ConnectionState.CONNECTED
	print("[NetworkManager] Server started successfully on port %d" % server_port)

## Initialize as client
func _initialize_client() -> void:
	print("[NetworkManager] Client initialized, ready to connect")


func _is_test_scene() -> bool:
	var current_scene: Node = get_tree().current_scene
	if current_scene == null:
		var root := get_tree().root
		if root.get_child_count() > 0:
			current_scene = root.get_child(root.get_child_count() - 1)

	return current_scene != null and current_scene.scene_file_path.begins_with("res://scenes/test/")

## Process loop - handles WebSocket polling and heartbeat
func _process(delta: float) -> void:
	if is_server:
		_process_server(delta)
	else:
		_process_client(delta)

## Process server mode
func _process_server(_delta: float) -> void:
	if ws_server == null:
		return

	# Accept new connections
	if ws_server.is_connection_available():
		var peer = ws_server.take_connection()
		var ws_peer = WebSocketPeer.new()
		ws_peer.accept_stream(peer)
		var peer_id = randi()  # Generate unique peer ID
		connected_peers[peer_id] = ws_peer
		print("[NetworkManager] Server: New client connecting (ID: %d)" % peer_id)

	# Poll all connected peers
	for peer_id in connected_peers.keys():
		var ws_peer: WebSocketPeer = connected_peers[peer_id]
		ws_peer.poll()

		var state = ws_peer.get_ready_state()
		if state == WebSocketPeer.STATE_OPEN:
			if not peer_connection_announced.has(peer_id):
				peer_connection_announced[peer_id] = true
				peer_last_heartbeat[peer_id] = Time.get_ticks_msec() / 1000.0
				print("[NetworkManager] Server: New client connected (ID: %d)" % peer_id)
				server_client_connected.emit(peer_id)

			# Receive messages from this peer
			while ws_peer.get_available_packet_count() > 0:
				_handle_server_incoming_packet(peer_id, ws_peer)
		elif state == WebSocketPeer.STATE_CLOSED:
			var was_announced := peer_connection_announced.has(peer_id)
			print("[NetworkManager] Server: Client %d disconnected" % peer_id)
			connected_peers.erase(peer_id)
			peer_connection_announced.erase(peer_id)
			peer_last_heartbeat.erase(peer_id)
			peer_bytes_sent.erase(peer_id)
			if was_announced:
				server_client_disconnected.emit(peer_id)

	# Check for heartbeat timeouts
	var current_time = Time.get_ticks_msec() / 1000.0
	for peer_id in peer_last_heartbeat.keys():
		var time_since_heartbeat = current_time - peer_last_heartbeat[peer_id]
		if time_since_heartbeat > server_heartbeat_timeout:
			print("[NetworkManager] Server: Peer %d timed out (no heartbeat for %.1fs)" % [peer_id, time_since_heartbeat])
			_disconnect_peer_timeout(peer_id)

## Process client mode
func _process_client(delta: float) -> void:
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
func connect_to_server(url: String, token: String = "", is_reconnect: bool = false) -> void:
	if current_state == ConnectionState.CONNECTED:
		print("[NetworkManager] Already connected to server")
		return

	if current_state == ConnectionState.CONNECTING:
		print("[NetworkManager] Connection already in progress")
		return

	if not is_reconnect:
		reconnect_attempts = 0
		_had_successful_connection = false

	server_url = url
	auth_token = token
	current_state = ConnectionState.CONNECTING
	_connection_attempt_id += 1
	var attempt_id := _connection_attempt_id

	print("[NetworkManager] Connecting to %s..." % url)

	# Create WebSocket client
	ws_client = WebSocketPeer.new()

	# Connect to server
	var error = ws_client.connect_to_url(url, TLSOptions.client())

	if error != OK:
		print("[NetworkManager] Failed to initiate connection: %d" % error)
		_fail_connection_attempt(_format_connection_error(url), is_reconnect)
	else:
		await _wait_for_connection(attempt_id, is_reconnect)

## Poll until the WebSocket opens, closes, or times out.
func _wait_for_connection(attempt_id: int, is_reconnect: bool) -> void:
	if ws_client == null:
		return

	var elapsed := 0.0
	while elapsed < connection_timeout_seconds:
		if attempt_id != _connection_attempt_id or ws_client == null:
			return

		ws_client.poll()
		var state = ws_client.get_ready_state()

		if state == WebSocketPeer.STATE_OPEN:
			_complete_connection()
			return
		elif state == WebSocketPeer.STATE_CLOSED:
			_fail_connection_attempt(_format_connection_error(server_url), is_reconnect)
			return

		await get_tree().create_timer(0.1).timeout
		elapsed += 0.1

	print("[NetworkManager] Connection timed out")
	_fail_connection_attempt(_format_connection_error(server_url), is_reconnect)


func _complete_connection() -> void:
	print("[NetworkManager] Connected to server successfully")
	current_state = ConnectionState.CONNECTED
	reconnect_attempts = 0
	_had_successful_connection = true
	last_heartbeat_received = Time.get_ticks_msec() / 1000.0

	# Auth handshake is intentionally NOT sent here — the arena scene drives it
	# from _setup_client once its server_message_received listener is bound.
	# Reset the idempotency flag so the arena (or reconnect handler) can issue
	# a fresh auth for this session.
	_auth_handshake_sent = false

	connected_to_server.emit()


func _fail_connection_attempt(error_message: String, is_reconnect: bool) -> void:
	print("[NetworkManager] Connection failed or still pending")
	current_state = ConnectionState.ERROR
	if ws_client != null:
		ws_client.close()
		ws_client = null

	if is_reconnect or _had_successful_connection:
		_schedule_reconnect()
	else:
		connection_error.emit(error_message)


func _format_connection_error(url: String) -> String:
	return "Cannot reach the game server at %s. Make sure the game server is running, then try again." % url

## Send authentication handshake. Idempotent within a connection session: a
## second call without a fresh _complete_connection (i.e. without disconnect/
## reconnect) is a no-op so the arena and reconnect hooks can both call it
## defensively.
func send_auth_handshake() -> void:
	if _auth_handshake_sent:
		return
	if auth_token.is_empty():
		print("[NetworkManager] send_auth_handshake skipped: no auth_token set")
		return
	if current_state != ConnectionState.CONNECTED:
		print("[NetworkManager] send_auth_handshake skipped: not connected (state=%d)" % current_state)
		return

	var character_id = ""
	var character_name = ""
	var region = "Asia"
	var player_color := Color(0.27, 0.53, 1.0)

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		character_id = game_mgr.player_data.get("character_id", "")
		character_name = game_mgr.player_data.get("character_name", "")
		region = game_mgr.player_data.get("selected_region", "Asia")
		player_color = game_mgr.player_data.get("player_color", player_color)

	var auth_data = {
		"token": auth_token,
		"character_id": character_id,
		"character_name": character_name,
		"region": region,
		"player_color": player_color
	}
	if send_message(MessageType.CONNECT_AUTH, auth_data):
		_auth_handshake_sent = true
		print("[NetworkManager] Authentication handshake sent")
	else:
		print("[NetworkManager] Authentication handshake send failed; retry remains allowed")

## Disconnect from server
func disconnect_from_server(reason: String = "User disconnect") -> void:
	if ws_client == null or current_state == ConnectionState.DISCONNECTED:
		return

	print("[NetworkManager] Disconnecting: %s" % reason)

	# Send disconnect message
	send_message(MessageType.DISCONNECT, {"reason": _get_disconnect_reason_code(reason)})

	# Close WebSocket
	ws_client.close(1000, reason)
	current_state = ConnectionState.DISCONNECTED

	disconnected_from_server.emit(reason)

## Handle incoming packet (client receiving from server)
func _handle_incoming_packet() -> void:
	if ws_client == null:
		return

	var packet = ws_client.get_packet()
	stats.packets_received += 1
	stats.bytes_received += packet.size()

	_dispatch_received_buffer(packet)


## Dispatch a single inbound buffer, transparently unwrapping BATCH envelopes
## (TASK-066). Inner packets are dispatched in order so listeners observe the
## same sequence the server queued during its tick.
func _dispatch_received_buffer(packet: PackedByteArray) -> void:
	if packet.size() < PacketTypes.HEADER_SIZE:
		print("[NetworkManager] Received undersized packet (%d bytes)" % packet.size())
		return

	var packet_type: int = packet.decode_u8(0)
	if packet_type == MessageType.BATCH:
		_dispatch_batch_buffer(packet)
		return

	var message = _decode_packet(packet)
	if message == null or message.is_empty():
		print("[NetworkManager] Failed to decode packet")
		return

	var message_type: MessageType = message.get("type", MessageType.HEARTBEAT)
	if message_type == MessageType.HEARTBEAT:
		last_heartbeat_received = Time.get_ticks_msec() / 1000.0
		_handle_heartbeat_response(message)
	else:
		server_message_received.emit(message_type, message.get("data", {}))


func _dispatch_batch_buffer(packet: PackedByteArray) -> void:
	# [u8 BATCH][u16 payload_len][u8 count][N inner_packets...]
	if packet.size() < PacketTypes.HEADER_SIZE + 1:
		return
	var count: int = packet.decode_u8(PacketTypes.HEADER_SIZE)
	var pos: int = PacketTypes.HEADER_SIZE + 1
	for i in count:
		if pos + PacketTypes.HEADER_SIZE > packet.size():
			print("[NetworkManager] BATCH truncated at packet %d/%d" % [i, count])
			return
		var inner_len: int = packet.decode_u16(pos + 1)
		var inner_size: int = PacketTypes.HEADER_SIZE + inner_len
		if pos + inner_size > packet.size():
			print("[NetworkManager] BATCH inner packet %d overflows envelope" % i)
			return
		_dispatch_received_buffer(packet.slice(pos, pos + inner_size))
		pos += inner_size

## Handle incoming packet from client (server receiving)
func _handle_server_incoming_packet(peer_id: int, ws_peer: WebSocketPeer) -> void:
	var packet = ws_peer.get_packet()
	stats.packets_received += 1
	stats.bytes_received += packet.size()

	# Decode packet
	var message = _decode_packet(packet)

	if message == null:
		print("[NetworkManager] Server: Failed to decode packet from peer %d" % peer_id)
		return

	var message_type: MessageType = message.get("type", MessageType.HEARTBEAT)
	var data: Dictionary = message.get("data", {})

	# Handle NetworkManager-level messages (heartbeat, disconnect)
	match message_type:
		MessageType.HEARTBEAT:
			# Update last heartbeat time and respond immediately
			peer_last_heartbeat[peer_id] = Time.get_ticks_msec() / 1000.0
			# §5.4: stamp the reply with our wall clock so the client can sync.
			send_to_client(peer_id, MessageType.HEARTBEAT, {
				"timestamp": data.get("timestamp", Time.get_ticks_msec()),
				"server_ms": Time.get_ticks_msec() & 0xFFFFFFFF
			})
			return
		MessageType.DISCONNECT:
			print("[NetworkManager] Server: Disconnect request from peer %d" % peer_id)
			ws_peer.close(1000, "Client disconnect")
			return

	# Emit signal for ServerMain to handle game-related messages
	server_client_message.emit(peer_id, message_type, data)

## Send message from server to specific client. While a tick batch window is
## open (see begin_batch / flush_batches), the encoded packet is queued and
## emitted as part of a single BATCH WebSocket frame at flush time (TASK-066).
func send_to_client(peer_id: int, message_type: MessageType, data: Dictionary = {}) -> void:
	if not connected_peers.has(peer_id):
		return

	var ws_peer: WebSocketPeer = connected_peers[peer_id]
	if ws_peer.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return

	var packet = _encode_packet(message_type, data)
	# Account against the channel before transport (§8.1). The batch envelope
	# adds a small wrapper at flush time which is tallied separately.
	_record_bytes_for_type(message_type, packet.size())

	if _batching_active:
		_enqueue_for_batch(peer_id, packet)
		return

	_send_raw_to_peer(peer_id, packet)


## Send message from server to all connected clients
func broadcast_to_clients(message_type: MessageType, data: Dictionary = {}) -> void:
	for peer_id in connected_peers.keys():
		send_to_client(peer_id, message_type, data)


## Begin a per-tick batching window (TASK-066). Subsequent send_to_client and
## broadcast_to_clients calls are buffered per-peer until flush_batches() is
## called. Safe to call when batching is already active (no-op).
func begin_batch() -> void:
	if _batching_active:
		return
	_batching_active = true
	_pending_batches.clear()


## Flush queued packets accumulated since begin_batch(). Each peer's queue is
## emitted as one or more WebSocket frames: one-packet chunks are sent directly
## with no envelope overhead, while multi-packet chunks are wrapped in BATCH
## frames sized to fit the u8 count and u16 payload length fields.
func flush_batches() -> void:
	if not _batching_active:
		return
	_batching_active = false

	for peer_id in _pending_batches.keys():
		var queue: Array = _pending_batches[peer_id]
		if queue.is_empty():
			continue

		var chunk: Array = []
		var chunk_inner_bytes := 0
		for packet_variant in queue:
			var packet := packet_variant as PackedByteArray
			var packet_bytes := packet.size()

			if not chunk.is_empty() and (
				chunk.size() >= BATCH_MAX_PACKETS
				or chunk_inner_bytes + packet_bytes > BATCH_MAX_INNER_BYTES
			):
				_send_batch_chunk_to_peer(peer_id, chunk)
				chunk = []
				chunk_inner_bytes = 0

			if packet_bytes > BATCH_MAX_INNER_BYTES:
				# This packet cannot fit inside any BATCH envelope because the
				# u8 count byte would push the payload length past u16. Send it
				# directly; its own header was finalized when encoded.
				_send_raw_to_peer(peer_id, packet)
				continue

			chunk.append(packet)
			chunk_inner_bytes += packet_bytes

		if not chunk.is_empty():
			_send_batch_chunk_to_peer(peer_id, chunk)

	_pending_batches.clear()


## Discard any pending batched packets without sending them. Used during
## shutdown so we never write to a half-torn-down peer.
func clear_batches() -> void:
	_batching_active = false
	_pending_batches.clear()


func _enqueue_for_batch(peer_id: int, packet: PackedByteArray) -> void:
	if not _pending_batches.has(peer_id):
		_pending_batches[peer_id] = []
	(_pending_batches[peer_id] as Array).append(packet)


func _send_batch_chunk_to_peer(peer_id: int, chunk: Array) -> void:
	if chunk.size() == 1:
		_send_raw_to_peer(peer_id, chunk[0])
		return
	_send_raw_to_peer(peer_id, _build_batch_packet(chunk))


## Wrap N inner packets in a BATCH envelope: [u8 BATCH][u16 payload_len][u8 N][packets...]
func _build_batch_packet(inner_packets: Array) -> PackedByteArray:
	var writer = PacketWriter.new()
	writer.write_header(MessageType.BATCH)
	writer.write_u8(inner_packets.size())
	var inner_bytes := 0
	for inner in inner_packets:
		writer.write_bytes(inner)
		inner_bytes += (inner as PackedByteArray).size()
	writer.finalize_header()
	var envelope := writer.get_buffer()
	# Inner packets are already tallied against their respective channels at
	# send_to_client(). Only the envelope overhead is attributed to BATCH.
	_record_bytes_for_type(MessageType.BATCH, envelope.size() - inner_bytes)
	return envelope


func _record_bytes_for_type(message_type: int, byte_count: int) -> void:
	if byte_count <= 0:
		return
	bytes_sent_by_type[message_type] = int(bytes_sent_by_type.get(message_type, 0)) + byte_count


func _send_raw_to_peer(peer_id: int, packet: PackedByteArray) -> bool:
	var ws_peer: WebSocketPeer = connected_peers.get(peer_id)
	if ws_peer == null or ws_peer.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return false

	var error = ws_peer.send(packet)
	if error == OK:
		stats.packets_sent += 1
		stats.bytes_sent += packet.size()
		if not peer_bytes_sent.has(peer_id):
			peer_bytes_sent[peer_id] = 0
		peer_bytes_sent[peer_id] += packet.size()
		return true

	print("[NetworkManager] Server: Failed to send packet to peer %d: %d" % [peer_id, error])
	return false


## Disconnect a client from server
func disconnect_client(peer_id: int, reason: String = "Server disconnect") -> void:
	if not connected_peers.has(peer_id):
		return

	var ws_peer: WebSocketPeer = connected_peers[peer_id]
	ws_peer.close(1000, reason)


## Disconnect a peer due to heartbeat timeout (internal)
func _disconnect_peer_timeout(peer_id: int) -> void:
	if not connected_peers.has(peer_id):
		peer_last_heartbeat.erase(peer_id)  # Clean up stale entry
		peer_connection_announced.erase(peer_id)
		return

	var ws_peer: WebSocketPeer = connected_peers[peer_id]
	var was_announced := peer_connection_announced.has(peer_id)
	ws_peer.close(1000, "Heartbeat timeout")
	connected_peers.erase(peer_id)
	peer_connection_announced.erase(peer_id)
	peer_last_heartbeat.erase(peer_id)
	peer_bytes_sent.erase(peer_id)
	if was_announced:
		server_client_disconnected.emit(peer_id)


## Get all connected peer IDs (server mode)
func get_connected_peer_ids() -> Array:
	return connected_peers.keys()

## Send message to server. Returns true once the packet has been accepted by
## the WebSocket layer so callers can keep retryable state in sync.
func send_message(message_type: MessageType, data: Dictionary = {}) -> bool:
	if ws_client == null or current_state != ConnectionState.CONNECTED:
		print("[NetworkManager] Cannot send message - not connected")
		return false
	if ws_client.get_ready_state() != WebSocketPeer.STATE_OPEN:
		print("[NetworkManager] Cannot send message - socket is not open")
		return false

	var packet = _encode_packet(message_type, data)
	var error = ws_client.send(packet)

	if error == OK:
		stats.packets_sent += 1
		stats.bytes_sent += packet.size()
		return true
	else:
		print("[NetworkManager] Failed to send packet: %d" % error)
		return false

## Send message to server (alias for send_message for code clarity)
func send_to_server(message_type: MessageType, data: Dictionary = {}) -> bool:
	return send_message(message_type, data)

## Send player input at the client prediction cadence.
func send_player_input(input_data: Dictionary) -> void:
	send_message(MessageType.PLAYER_INPUT, input_data)

## Send heartbeat (1/sec, 4B payload as per spec)
func send_heartbeat() -> void:
	# Binary heartbeat: only timestamp (4 bytes)
	send_message(MessageType.HEARTBEAT, {"timestamp": Time.get_ticks_msec()})
	stats.last_ping_time = Time.get_ticks_msec() / 1000.0

## Handle heartbeat response. Updates RTT and the server-clock offset (§5.4).
func _handle_heartbeat_response(message: Dictionary) -> void:
	var data = message.get("data", {})
	if not data.has("timestamp"):
		return

	var sent_timestamp: int = int(data.get("timestamp", 0))
	var ping_ms := _elapsed_msec_since_u32(sent_timestamp)
	if ping_ms <= MAX_REASONABLE_PING_MS:
		stats.ping_ms = ping_ms
	else:
		return  # Bogus sample; don't pollute the clock estimate either.

	var server_ms: int = int(data.get("server_ms", 0))
	if server_ms == 0:
		return  # Older server / not stamped this reply.

	# Estimate when on the local clock the server stamped the reply: roughly
	# half an RTT before we received it.
	var arrival_local_ms: int = Time.get_ticks_msec() & 0xFFFFFFFF
	var server_send_local_ms: int = arrival_local_ms - int(ping_ms / 2.0)
	var sample := float(server_ms - server_send_local_ms)

	if server_clock_offset_samples == 0:
		server_clock_offset_ms = sample
	else:
		server_clock_offset_ms = lerpf(server_clock_offset_ms, sample, SERVER_CLOCK_FILTER_ALPHA)
	server_clock_offset_samples += 1


## Server time in milliseconds estimated from the local clock plus the
## low-pass-filtered offset (§5.4). Returns 0 until at least one heartbeat
## reply has carried `server_ms`, so callers can detect "no sync yet."
func get_server_time_ms() -> int:
	if server_clock_offset_samples == 0:
		return 0
	return int(round(float(Time.get_ticks_msec() & 0xFFFFFFFF) + server_clock_offset_ms))


func _elapsed_msec_since_u32(timestamp_ms: int) -> int:
	var now_u32: int = Time.get_ticks_msec() & 0xFFFFFFFF
	var elapsed := now_u32 - (timestamp_ms & 0xFFFFFFFF)
	if elapsed < 0:
		elapsed += UINT32_WRAP
	return elapsed


func _get_disconnect_reason_code(reason: Variant) -> int:
	if reason is int:
		return reason

	var reason_text := str(reason).to_lower()
	if reason_text.contains("timeout"):
		return PacketTypes.DisconnectReason.TIMEOUT
	if reason_text.contains("kick"):
		return PacketTypes.DisconnectReason.KICKED
	if reason_text.contains("server shutdown"):
		return PacketTypes.DisconnectReason.SERVER_SHUTDOWN
	if reason_text.contains("invalid auth"):
		return PacketTypes.DisconnectReason.INVALID_AUTH
	if reason_text.contains("duplicate"):
		return PacketTypes.DisconnectReason.DUPLICATE_SESSION
	return PacketTypes.DisconnectReason.USER_QUIT


## Encode packet to binary format using PacketWriter
## Binary protocol as per ARCHITECTURE.md Section 4.3
func _encode_packet(message_type: MessageType, data: Dictionary) -> PackedByteArray:
	var writer = PacketWriter.new()
	writer.write_header(message_type)

	match message_type:
		MessageType.HEARTBEAT:
			# Wire format (8 bytes, both directions, §5.4 of
			# NETWORK_PERFORMANCE_UPGRADES.md):
			#   [u32 timestamp]  - echoed client send time for RTT
			#   [u32 server_ms]  - server wall clock; set by server, 0 on client
			writer.write_u32(data.get("timestamp", Time.get_ticks_msec()))
			writer.write_u32(data.get("server_ms", 0))

		MessageType.PLAYER_INPUT:
			var input_packet = PlayerInputPacket.from_input_dict(data)
			input_packet.write_payload(writer)

		MessageType.STATE_UPDATE:
			# Server constructs StateUpdatePacket with delta support (TASK-021)
			var state_flags: int = data.get("state_flags", 0)
			var is_delta := (state_flags & PacketTypes.STATE_FLAG_IS_DELTA) != 0

			var state_packet: StateUpdatePacket
			if is_delta:
				state_packet = StateUpdatePacket.create_delta(
					data.get("tick", 0),
					data.get("baseline_tick", 0)
				)
			else:
				state_packet = StateUpdatePacket.create(data.get("tick", 0))
				state_packet.state_flags = state_flags
				state_packet.baseline_tick = data.get("baseline_tick", 0)

			for entity_data in data.get("entities", []):
				state_packet.add_entity_dict(entity_data)

			state_packet.write_payload(writer)

		MessageType.GAME_EVENT:
			writer.write_u8(data.get("event_type", 0))
			writer.write_u16(data.get("source_id", 0))
			writer.write_u16(data.get("target_id", 0))
			# Event-specific data written based on type
			_write_game_event_data(writer, data)

		MessageType.ACTION_CONFIRM:
			writer.write_u8(data.get("sequence_number", data.get("sequence", 0)))
			writer.write_u8(data.get("action_type", 0))
			writer.write_vector2_compressed(data.get("corrected_position", data.get("position", Vector2.ZERO)))
			writer.write_u8(data.get("result_code", data.get("result", 0)))
			writer.write_u16(data.get("server_tick", data.get("tick", 0)))

		MessageType.CONNECT_AUTH:
			writer.write_string(data.get("token", ""))
			writer.write_string(data.get("character_id", ""))
			writer.write_string(data.get("character_name", ""))
			writer.write_u8(AuthPacket.region_from_string(data.get("region", "Asia")))
			_write_color_rgb(writer, data.get("player_color", Color(0.27, 0.53, 1.0)))

		MessageType.DISCONNECT:
			writer.write_u8(_get_disconnect_reason_code(data.get("reason", PacketTypes.DisconnectReason.USER_QUIT)))
			writer.write_u32(Time.get_ticks_msec())

		MessageType.REQUEST_FULL_STATE:
			# TASK-021: Client requesting full state sync
			# Minimal payload - just timestamp for tracking
			writer.write_u32(Time.get_ticks_msec())

		MessageType.RESPAWN_REQUEST:
			# Empty payload - server infers from peer_id
			writer.write_u32(Time.get_ticks_msec())

		MessageType.SERVER_METRICS:
			# Server performance metrics broadcast
			writer.write_u32(data.get("tick_count", 0))
			writer.write_u16(int(data.get("avg_tick_time_ms", 0.0) * 100))  # Fixed-point *100
			writer.write_u16(int(data.get("max_tick_time_ms", 0.0) * 100))  # Fixed-point *100
			writer.write_u16(data.get("player_count", 0))
			writer.write_u16(data.get("entity_count", 0))
			writer.write_u32(data.get("total_bytes_sent", 0))
			writer.write_u32(data.get("total_bytes_received", 0))
			writer.write_u32(int(data.get("avg_bandwidth_per_client", 0.0)))

	writer.finalize_header()
	return writer.get_buffer()


## Helper: Write game event specific data
func _write_game_event_data(writer: PacketWriter, data: Dictionary) -> void:
	var event_type = data.get("event_type", 0)
	var event_data: Dictionary = data.get("event_data", {})
	match event_type:
		PacketTypes.GameEventType.DAMAGE:
			writer.write_u16(event_data.get("amount", data.get("amount", 0)))
			writer.write_u8(event_data.get("damage_type", data.get("damage_type", 0)))
		PacketTypes.GameEventType.KILL, \
		PacketTypes.GameEventType.KILL_PVP:
			pass  # No extra data.
		PacketTypes.GameEventType.PROJECTILE_FIRED:
			writer.write_vector2_compressed(event_data.get("position", data.get("position", Vector2.ZERO)))
			writer.write_u16(event_data.get("server_tick", data.get("server_tick", 0)))
		PacketTypes.GameEventType.RESPAWN:
			writer.write_vector2_compressed(event_data.get("position", data.get("position", Vector2.ZERO)))
		PacketTypes.GameEventType.EFFECT_APPLY:
			writer.write_u8(event_data.get("effect_id", data.get("effect_id", 0)))
			writer.write_u16(event_data.get("duration_ms", data.get("duration_ms", 0)))
		PacketTypes.GameEventType.EFFECT_REMOVE:
			writer.write_u8(event_data.get("effect_id", data.get("effect_id", 0)))
		PacketTypes.GameEventType.PLAYER_INFO:
			writer.write_string(event_data.get("character_name", ""))
			writer.write_vector2_compressed(event_data.get("position", Vector2.ZERO))
			_write_color_rgb(writer, event_data.get("player_color", Color(0.27, 0.53, 1.0)))
		PacketTypes.GameEventType.LEADERBOARD_UPDATE:
			var entries: Array = event_data.get("entries", [])
			writer.write_u8(entries.size())
			for entry in entries:
				writer.write_u16(entry.get("entity_id", 0))
				writer.write_u16(entry.get("pvp_kills", 0))


func _write_color_rgb(writer: PacketWriter, color: Color) -> void:
	writer.write_u8(clampi(roundi(color.r * 255.0), 0, 255))
	writer.write_u8(clampi(roundi(color.g * 255.0), 0, 255))
	writer.write_u8(clampi(roundi(color.b * 255.0), 0, 255))


## Decode packet from binary format using PacketReader
## Binary protocol as per ARCHITECTURE.md Section 4.3
func _decode_packet(packet: PackedByteArray) -> Dictionary:
	if packet.size() < PacketTypes.HEADER_SIZE:
		push_error("[NetworkManager] Packet too small: %d bytes" % packet.size())
		return {}

	var reader = PacketReader.new(packet)
	var header = reader.read_header()
	var packet_type = header.type

	if not PacketTypes.is_valid_type(packet_type):
		push_error("[NetworkManager] Invalid packet type: %d" % packet_type)
		return {}

	var result = {
		"type": packet_type,
		"data": {}
	}

	match packet_type:
		PacketTypes.Type.HEARTBEAT:
			# §5.4: heartbeat now carries both echoed client timestamp and the
			# server's wall clock so the client can maintain a low-pass-filtered
			# clock offset for interpolation alignment.
			result.data = {
				"timestamp": reader.read_u32(),
				"server_ms": reader.read_u32()
			}

		PacketTypes.Type.PLAYER_INPUT:
			var input_packet = PlayerInputPacket.read(reader)
			result.data = input_packet.to_dict()

		PacketTypes.Type.STATE_UPDATE:
			# TASK-021: Read state update with delta support
			# Note: Delta reconstruction happens in InterpolationController
			var state_packet = StateUpdatePacket.read(reader)
			result.data = state_packet.to_dict()

		PacketTypes.Type.GAME_EVENT:
			var event_packet = GameEventPacket.read(reader)
			result.data = event_packet.to_dict()

		PacketTypes.Type.ACTION_CONFIRM:
			var confirm_packet = ActionConfirmPacket.read(reader)
			result.data = confirm_packet.to_dict()

		PacketTypes.Type.CONNECT_AUTH:
			var auth_packet = AuthPacket.read(reader)
			result.data = auth_packet.to_dict()

		PacketTypes.Type.DISCONNECT:
			var disconnect_packet = DisconnectPacket.read(reader)
			result.data = disconnect_packet.to_dict()

		PacketTypes.Type.REQUEST_FULL_STATE:
			# TASK-021: Client requesting full state sync
			result.data = {
				"timestamp": reader.read_u32()
			}

		PacketTypes.Type.RESPAWN_REQUEST:
			result.data = {
				"timestamp": reader.read_u32()
			}

		PacketTypes.Type.SERVER_METRICS:
			result.data = {
				"tick_count": reader.read_u32(),
				"avg_tick_time_ms": reader.read_u16() / 100.0,
				"max_tick_time_ms": reader.read_u16() / 100.0,
				"player_count": reader.read_u16(),
				"entity_count": reader.read_u16(),
				"total_bytes_sent": reader.read_u32(),
				"total_bytes_received": reader.read_u32(),
				"avg_bandwidth_per_client": reader.read_u32()
			}

	return result

## Handle connection closed
func _on_connection_closed(reason: String) -> void:
	current_state = ConnectionState.DISCONNECTED
	_auth_handshake_sent = false
	disconnected_from_server.emit(reason)
	if _had_successful_connection:
		_schedule_reconnect()

## Schedule reconnection with exponential backoff
## Auto-reconnects whenever the client had an active server connection
func _schedule_reconnect() -> void:
	# Only reconnect if we have a server URL (i.e., we were connected or connecting)
	if server_url.is_empty():
		print("[NetworkManager] Skipping auto-reconnect (no server URL)")
		current_state = ConnectionState.DISCONNECTED
		return

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
	connect_to_server(server_url, auth_token, true)

## Check if connected to server
func is_server_connected() -> bool:
	return current_state == ConnectionState.CONNECTED \
		and ws_client != null \
		and ws_client.get_ready_state() == WebSocketPeer.STATE_OPEN

## Get network statistics. Includes the per-channel byte breakdown when in
## server mode (§8.1) so dashboards / tests can detect when one packet type
## starts dominating egress.
func get_stats() -> Dictionary:
	var snapshot: Dictionary = stats.duplicate()
	if not bytes_sent_by_type.is_empty():
		snapshot["bytes_sent_by_type"] = bytes_sent_by_type.duplicate()
	return snapshot

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
