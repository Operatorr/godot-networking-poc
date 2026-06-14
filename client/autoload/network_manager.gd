## NetworkManager - client networking singleton over ENet/UDP (migration-spec D2).
##
## The wire codec lives in the Rust GDExtension (ProtocolCodec — D6/D7): this script owns
## connection lifecycle, channel routing, dispatch, clock sync, and reconnect, and hands raw
## bytes across the extension boundary. There is no GDScript codec.
##
## The GDScript server role is RETIRED (D1): the authoritative server is the Rust
## `omega-server` binary (rust/server). The server-mode API surface below is kept as inert
## stubs so legacy scripts fail soft with a pointer to the Rust binary.
extends Node

## Connection states
enum ConnectionState {
	DISCONNECTED,
	CONNECTING,
	CONNECTED,
	RECONNECTING,
	ERROR
}

## Network message types. Wire bytes are owned by the Rust protocol crate; these ids are the
## GDScript-facing dispatch values (ProtocolCodec.decode_server_packet returns them).
## HEARTBEAT and BATCH died with the ENet transport (D2): ENet provides keepalive/RTT natively
## and coalesces packets itself; the clock-sync payload now rides every Snapshot.
enum MessageType {
	PLAYER_INPUT = 1,      ## Client -> Server: Movement, actions (ch2, unreliable sequenced)
	STATE_UPDATE = 2,      ## Server -> Client: Snapshots (ch0, unreliable sequenced)
	GAME_EVENT = 3,        ## Server -> Client: Damage, kills, player info (ch1, reliable)
	HEARTBEAT = 4,         ## RETIRED (D2) - kept so stale references fail soft
	ACTION_CONFIRM = 5,    ## Server -> Client: per-input ack (ch0)
	CONNECT_AUTH = 6,      ## Client -> Server: auth handshake (ch1, reliable)
	DISCONNECT = 7,        ## Handled natively by ENet disconnect (reason in event data)
	REQUEST_FULL_STATE = 8, ## Client -> Server (ch1, reliable)
	RESPAWN_REQUEST = 9,   ## Client -> Server (ch1, reliable)
	SERVER_METRICS = 10,   ## Server -> Client (ch1, reliable, 1/sec)
	BATCH = 11,            ## RETIRED (D2)
	BASELINE_ACK = 12,     ## Client -> Server (ch1, reliable)
	LOCAL_HIT_REPORT = 13, ## Client -> Server (ch1, reliable - a lost hit report is lost damage)
	AUTH_RESULT = 14       ## Server -> Client: explicit auth answer (D9); carries entity_id
}

## Signals - Client mode
signal connected_to_server()
signal disconnected_from_server(reason: String)
signal connection_error(error: String)
signal server_message_received(message_type: MessageType, data: Dictionary)
@warning_ignore("unused_signal")  # RETIRED - never emitted (ENet owns liveness); kept for listeners
signal heartbeat_timeout()

## Transport and ENetTransport are global classes (class_name); referenced directly — no
## preload const, which would shadow the global identifiers.

## Runtime mode detection (server mode = misconfiguration since the Rust port)
var is_server: bool = false

var _transport: ENetTransport = null

## The Rust wire codec (D6/D7).
var _codec: ProtocolCodec = ProtocolCodec.new()

## Default egress budget the client advertises in CONNECT_AUTH (bytes/sec).
const DEFAULT_CLIENT_BUDGET := 120000

## The two server instances share a host but listen on different UDP ports: the Arena is the
## region's advertised port (8081 locally), the Sanctuary hub runs alongside it on 8082. The
## client derives the Sanctuary address from the selected region's host (see *_url_for_region).
const ARENA_DEFAULT_PORT := 8081
const SANCTUARY_PORT := 8082

## Connection state
var current_state: ConnectionState = ConnectionState.DISCONNECTED
var server_url: String = ""
var auth_token: String = ""
## Session ticket blob from the Go API (D9). Empty = dev-mode unsigned join (the server must
## run with --allow-unsigned-tickets). Populated by the M3 ticket-issuance flow.
var session_ticket: PackedByteArray = PackedByteArray()
var _auth_handshake_sent: bool = false

## Reconnection parameters (exponential backoff)
var reconnect_attempts: int = 0
var max_reconnect_attempts: int = 5
var base_reconnect_delay: float = 1.0
var max_reconnect_delay: float = 32.0
var reconnect_timer: float = 0.0
var connection_timeout_seconds: float = 5.0
var _connection_attempt_id: int = 0
var _had_successful_connection: bool = false
## Set when a disconnect is expected and must NOT trigger the auto-reconnect loop — e.g. a
## hardcore (permadeath) kick: the server deleted the character, so reconnecting would just
## re-auth and spawn the player again behind the death screen. Cleared on a fresh connect.
var _suppress_auto_reconnect: bool = false

const UINT32_WRAP: int = 4294967296
const MAX_REASONABLE_PING_MS: int = 10000

## Estimated offset between local Time.get_ticks_msec() and the server's monotonic clock, in
## ms. Fed by the server_ms stamp every Snapshot carries (the relocated HEARTBEAT payload, D2)
## plus ENet-native RTT. `samples == 0` means no sync yet.
var server_clock_offset_ms: float = 0.0
var server_clock_offset_samples: int = 0
const SERVER_CLOCK_FILTER_ALPHA := 0.2

## Network statistics
var stats: Dictionary = {
	"packets_sent": 0,
	"packets_received": 0,
	"bytes_sent": 0,
	"bytes_received": 0,
	"ping_ms": 0.0,
	"last_ping_time": 0.0
}


func _ready() -> void:
	is_server = (OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless") and not _is_test_scene()
	if is_server:
		push_error(
			"[NetworkManager] The GDScript server is retired (migration-spec D1). "
			+ "Run the Rust server instead: rust/ -> cargo run -p omega-server"
		)
		return

	print("[NetworkManager] Initializing in CLIENT mode (ENet transport)...")
	_transport = ENetTransport.new()
	_transport.role = Transport.Role.CLIENT
	set_process(true)


func _is_test_scene() -> bool:
	var current_scene: Node = get_tree().current_scene
	if current_scene == null:
		var root := get_tree().root
		if root.get_child_count() > 0:
			current_scene = root.get_child(root.get_child_count() - 1)

	if current_scene == null:
		return false

	var scene_path := current_scene.scene_file_path
	return scene_path.begins_with("res://scenes/test/") \
		or scene_path == "res://scenes/levels/offline/practice.tscn"


func _process(delta: float) -> void:
	if is_server or _transport == null:
		return
	match current_state:
		ConnectionState.CONNECTED:
			_process_connected(delta)
		ConnectionState.RECONNECTING:
			_process_reconnecting(delta)


func _process_connected(_delta: float) -> void:
	_transport.client_poll()
	var state = _transport.client_state()

	if state == Transport.LinkState.OPEN:
		for entry in _transport.client_take_channel_packets():
			_handle_incoming_packet(entry["bytes"])
		# RTT comes from ENet natively (replaces the HEARTBEAT echo path).
		stats.ping_ms = _transport.client_rtt_ms()
	elif state == Transport.LinkState.CLOSING:
		pass
	elif state == Transport.LinkState.CLOSED:
		var close_info := _transport.client_close_info()
		print("[NetworkManager] Connection closed - Code: %d, Reason: %s" % [close_info.get("code", 0), close_info.get("reason", "")])
		_on_connection_closed(close_info.get("reason", ""))


func _process_reconnecting(delta: float) -> void:
	reconnect_timer -= delta
	if reconnect_timer <= 0.0:
		_attempt_reconnect()


## Split a region/server URL into [host, port], tolerating a scheme prefix (ws://, udp://, …)
## and a missing port. Returns ARENA_DEFAULT_PORT when no port is present. IPv6 literals are
## not expected from the region API, so the simple rsplit on ":" is sufficient here.
static func _split_host_port(url: String) -> Array:
	var rest := url
	var scheme_idx := rest.find("://")
	if scheme_idx != -1:
		rest = rest.substr(scheme_idx + 3)
	# Drop any path/query the region URL might carry.
	var slash_idx := rest.find("/")
	if slash_idx != -1:
		rest = rest.substr(0, slash_idx)
	var host := rest
	var port := ARENA_DEFAULT_PORT
	var colon_idx := rest.rfind(":")
	if colon_idx != -1:
		host = rest.substr(0, colon_idx)
		var port_str := rest.substr(colon_idx + 1)
		if port_str.is_valid_int():
			port = port_str.to_int()
	return [host, port]


## The ARENA instance address for a region: its advertised host:port unchanged (8081 locally).
## Accepts a region URL (with or without scheme) and returns a bare "host:port" for ENet.
func arena_url_for_region(region_url: String) -> String:
	var parts := _split_host_port(region_url)
	return "%s:%d" % [parts[0], parts[1]]


## The SANCTUARY instance address for a region: the region's HOST on SANCTUARY_PORT (8082).
## The Sanctuary runs alongside the Arena on the same machine, one port up.
func sanctuary_url_for_region(region_url: String) -> String:
	var parts := _split_host_port(region_url)
	return "%s:%d" % [parts[0], SANCTUARY_PORT]


## Connect to the game server. Accepts "host:port" with any scheme prefix (the Go API region
## payload historically carries ws:// URLs; only host/port are used over ENet).
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
		_suppress_auto_reconnect = false

	server_url = url
	auth_token = token
	current_state = ConnectionState.CONNECTING
	_connection_attempt_id += 1
	var attempt_id := _connection_attempt_id

	print("[NetworkManager] Connecting to %s (ENet)..." % url)

	var error = _transport.client_connect(url)

	if error != OK:
		print("[NetworkManager] Failed to initiate connection: %d" % error)
		_fail_connection_attempt(_format_connection_error(url), is_reconnect)
	else:
		await _wait_for_connection(attempt_id, is_reconnect)


func _wait_for_connection(attempt_id: int, is_reconnect: bool) -> void:
	var elapsed := 0.0
	while elapsed < connection_timeout_seconds:
		if attempt_id != _connection_attempt_id:
			return

		_transport.client_poll()
		var state = _transport.client_state()

		if state == Transport.LinkState.OPEN:
			_complete_connection()
			return
		elif state == Transport.LinkState.CLOSED:
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
	server_clock_offset_samples = 0

	# Auth handshake is intentionally NOT sent here — the arena scene drives it
	# from _setup_client once its server_message_received listener is bound.
	_auth_handshake_sent = false

	connected_to_server.emit()


func _fail_connection_attempt(error_message: String, is_reconnect: bool) -> void:
	print("[NetworkManager] Connection failed or still pending")
	current_state = ConnectionState.ERROR
	_transport.client_reset()

	if is_reconnect or _had_successful_connection:
		_schedule_reconnect()
	else:
		connection_error.emit(error_message)


func _format_connection_error(url: String) -> String:
	return "Cannot reach the game server at %s. Make sure the game server is running, then try again." % url


## Send the authentication handshake (D9). The JWT itself never crosses ENet — in production
## the Go API exchanges it for a short-lived Ed25519 session ticket over HTTPS and that ticket
## is presented here; in dev mode the ticket is empty and the server (running with
## --allow-unsigned-tickets) trusts the join. Idempotent per connection session.
func send_auth_handshake() -> void:
	if _auth_handshake_sent:
		return
	if auth_token.is_empty():
		print("[NetworkManager] send_auth_handshake skipped: no auth_token set")
		return
	if current_state != ConnectionState.CONNECTED:
		print("[NetworkManager] send_auth_handshake skipped: not connected (state=%d)" % current_state)
		return

	var character_name = ""
	var player_color := Color(0.27, 0.53, 1.0)
	# Class is chosen at character creation and stored on the character; Zealot is the
	# fallback if GameManager has no class yet (e.g. a legacy character).
	var player_class: int = PacketTypes.PlayerClass.ZEALOT
	# The character id lets the server hydrate the right character (dev mode). The Go API
	# stores it as a string id; pass it as an int (0 when unknown/empty).
	var character_id: int = 0

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		character_name = game_mgr.player_data.get("character_name", "")
		player_color = game_mgr.player_data.get("player_color", player_color)
		player_class = int(game_mgr.player_data.get("player_class", player_class))
		character_id = _character_id_to_int(game_mgr.player_data.get("character_id", ""))

	var bytes := _codec.encode_connect_auth(
		character_name, player_color, player_class, character_id,
		_get_client_bandwidth_budget(), session_ticket
	)
	if bytes.is_empty():
		# The codec refuses malformed tickets rather than downgrading to an unsigned join.
		push_error("[NetworkManager] Session ticket is malformed; aborting handshake")
		connection_error.emit("Session ticket is invalid - please log in again")
		return
	if _send_bytes(ProtocolCodec.channel_reliable(), bytes, true):
		_auth_handshake_sent = true
		print("[NetworkManager] Authentication handshake sent")
	else:
		print("[NetworkManager] Authentication handshake send failed; retry remains allowed")


## Convert the Go API's character id (a string on the account, possibly empty) to the
## int the wire format expects. Returns 0 when unknown so the server treats it as "no id".
func _character_id_to_int(raw_id: Variant) -> int:
	var id_str := str(raw_id).strip_edges()
	if id_str.is_empty() or not id_str.is_valid_int():
		return 0
	return id_str.to_int()


func _get_client_bandwidth_budget() -> int:
	var budget := DEFAULT_CLIENT_BUDGET
	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		budget = int(game_mgr.player_data.get("bandwidth_budget_bps", DEFAULT_CLIENT_BUDGET))
	if budget <= 0:
		budget = DEFAULT_CLIENT_BUDGET
	return budget


## Disconnect from server. The reason rides ENet's native disconnect data (no packet).
func disconnect_from_server(reason: String = "User disconnect") -> void:
	# An intentional disconnect must always cancel a pending auto-reconnect — including from the
	# RECONNECTING state, where the transport is already closed and the early-return below would
	# otherwise leave the backoff timer running and dial back in.
	_suppress_auto_reconnect = true
	if current_state == ConnectionState.RECONNECTING:
		current_state = ConnectionState.DISCONNECTED
		_transport.client_reset()
		disconnected_from_server.emit(reason)
		return

	if _transport.client_state() == Transport.LinkState.CLOSED or current_state == ConnectionState.DISCONNECTED:
		return

	print("[NetworkManager] Disconnecting: %s" % reason)
	_transport.client_close(0, reason)
	current_state = ConnectionState.DISCONNECTED

	disconnected_from_server.emit(reason)


func _handle_incoming_packet(packet: PackedByteArray) -> void:
	stats.packets_received += 1
	stats.bytes_received += packet.size()

	var message: Dictionary = _codec.decode_server_packet(packet)
	if message.is_empty():
		print("[NetworkManager] Failed to decode packet (%d bytes)" % packet.size())
		return

	var message_type: int = message.get("type", 0)

	# Every Snapshot carries the server's monotonic ms clock (the relocated HEARTBEAT
	# clock-sync payload, D2). Update the offset filter before fan-out.
	if message_type == MessageType.STATE_UPDATE:
		_update_clock_from_server_ms(int(message.get("server_ms", 0)))

	if message_type == MessageType.AUTH_RESULT:
		_handle_auth_result(message)

	server_message_received.emit(message_type, message)


## D9: the explicit auth answer. Success carries our entity id — instant Authority sync
## (the PLAYER_INFO name-match heuristic stays as a fallback for older flows).
func _handle_auth_result(data: Dictionary) -> void:
	var result: int = data.get("result", -1)
	if result == 0:
		var entity_id: int = data.get("entity_id", -1)
		print("[NetworkManager] Auth accepted - entity id %d" % entity_id)
		var game_mgr = get_tree().root.get_node_or_null("GameManager")
		if game_mgr and entity_id > 0 and game_mgr.has_method("set_local_player_entity_id"):
			game_mgr.set_local_player_entity_id(entity_id)
	else:
		push_error("[NetworkManager] Auth rejected by server (code %d)" % result)
		connection_error.emit("Authentication rejected (code %d)" % result)


## Clock sync (relocated from HEARTBEAT, D2): same EMA filter, half-RTT estimate from
## ENet-native RTT. `server_ms == 0` would be the unstamped sentinel; the Rust server always
## stamps, but tolerate it for the first tick (server_ms wraps u32 and is never 0 for long).
func _update_clock_from_server_ms(server_ms: int) -> void:
	if server_ms == 0:
		return
	var ping_ms := _transport.client_rtt_ms()
	if ping_ms > MAX_REASONABLE_PING_MS:
		return
	var arrival_local_ms: int = Time.get_ticks_msec() & 0xFFFFFFFF
	var server_send_local_ms: int = arrival_local_ms - int(ping_ms / 2.0)
	var sample := float(server_ms - server_send_local_ms)

	# Both clocks are u32-masked and wrap ~49.7 days; a wrap on either side throws the raw
	# difference off by ±2^32 — fold it back so the EMA never ingests a poisoned sample.
	if sample > UINT32_WRAP / 2.0:
		sample -= UINT32_WRAP
	elif sample < -UINT32_WRAP / 2.0:
		sample += UINT32_WRAP

	if server_clock_offset_samples == 0:
		server_clock_offset_ms = sample
	elif absf(sample - server_clock_offset_ms) > UINT32_WRAP / 4.0:
		# The filtered offset itself sits near a wrap boundary; re-seed instead of
		# letting one boundary-straddling sample drag the EMA across 2^32.
		server_clock_offset_ms = sample
	else:
		server_clock_offset_ms = lerpf(server_clock_offset_ms, sample, SERVER_CLOCK_FILTER_ALPHA)
	server_clock_offset_samples += 1


## Server time in ms estimated from the local clock plus the filtered offset.
## Returns 0 until at least one stamped Snapshot arrived ("no sync yet" sentinel).
func get_server_time_ms() -> int:
	if server_clock_offset_samples == 0:
		return 0
	return int(round(float(Time.get_ticks_msec() & 0xFFFFFFFF) + server_clock_offset_ms))


## Send a message to the server. Routes to the D2 channel for the type and encodes through
## the Rust codec. Returns true once ENet accepted the packet.
func send_message(message_type: MessageType, data: Dictionary = {}) -> bool:
	if current_state != ConnectionState.CONNECTED:
		print("[NetworkManager] Cannot send message - not connected")
		return false
	if _transport.client_state() != Transport.LinkState.OPEN:
		print("[NetworkManager] Cannot send message - link is not open")
		return false

	var bytes: PackedByteArray
	var channel: int = ProtocolCodec.channel_reliable()
	var reliable := true

	match message_type:
		MessageType.PLAYER_INPUT:
			var input_flags: int = data.get("input_flags", PacketTypes.encode_input_flags(data.get("keys", {})))
			bytes = _codec.encode_input(
				data.get("position", Vector2.ZERO),
				data.get("velocity", Vector2.ZERO),
				input_flags,
				data.get("aim_angle", 0.0),
				data.get("cursor", Vector2.ZERO),
				data.get("sequence", 0),
				data.get("client_render_tick", 0),
				data.get("client_rtt_ms", 0)
			)
			channel = ProtocolCodec.channel_input()
			reliable = false
		MessageType.BASELINE_ACK:
			bytes = _codec.encode_baseline_ack(data.get("baseline_tick", 0))
		MessageType.REQUEST_FULL_STATE:
			bytes = _codec.encode_request_full_state()
		MessageType.RESPAWN_REQUEST:
			bytes = _codec.encode_respawn_request()
		MessageType.LOCAL_HIT_REPORT:
			bytes = _codec.encode_local_hit_report(data.get("projectile_id", 0))
		MessageType.CONNECT_AUTH:
			# Use send_auth_handshake(); kept for compatibility with direct callers.
			bytes = _codec.encode_connect_auth(
				data.get("character_name", ""),
				data.get("player_color", Color(0.27, 0.53, 1.0)),
				int(data.get("player_class", PacketTypes.PlayerClass.ZEALOT)),
				_character_id_to_int(data.get("character_id", "")),
				int(data.get("bandwidth_budget_bps", DEFAULT_CLIENT_BUDGET)),
				session_ticket
			)
		MessageType.DISCONNECT:
			# Native ENet disconnect carries the reason; no packet exists.
			disconnect_from_server(str(data.get("reason", "User disconnect")))
			return true
		_:
			push_error("[NetworkManager] send_message: type %d is not client-sendable" % message_type)
			return false

	return _send_bytes(channel, bytes, reliable)


func _send_bytes(channel: int, bytes: PackedByteArray, reliable: bool) -> bool:
	if bytes.is_empty():
		# The codec returns empty bytes when it refuses to encode; never send a 0-byte packet.
		return false
	var error = _transport.client_send_channel(channel, bytes, reliable)
	if error == OK:
		stats.packets_sent += 1
		stats.bytes_sent += bytes.size()
		return true
	print("[NetworkManager] Failed to send packet: %d" % error)
	return false


## Send message to server (alias for send_message for code clarity)
func send_to_server(message_type: MessageType, data: Dictionary = {}) -> bool:
	return send_message(message_type, data)


## Send player input at the client prediction cadence (ch2, unreliable sequenced).
func send_player_input(input_data: Dictionary) -> void:
	send_message(MessageType.PLAYER_INPUT, input_data)


func _on_connection_closed(reason: String) -> void:
	current_state = ConnectionState.DISCONNECTED
	_auth_handshake_sent = false
	disconnected_from_server.emit(reason)
	if _had_successful_connection and not _suppress_auto_reconnect:
		_schedule_reconnect()


## Suppress the auto-reconnect loop for an expected disconnect (e.g. hardcore permadeath kick).
## Must be called before the server closes the link; cleared on the next fresh connect.
func suppress_auto_reconnect() -> void:
	_suppress_auto_reconnect = true


func _schedule_reconnect() -> void:
	if server_url.is_empty():
		print("[NetworkManager] Skipping auto-reconnect (no server URL)")
		current_state = ConnectionState.DISCONNECTED
		return

	if reconnect_attempts >= max_reconnect_attempts:
		print("[NetworkManager] Max reconnection attempts reached")
		current_state = ConnectionState.ERROR
		connection_error.emit("Failed to reconnect after %d attempts" % reconnect_attempts)
		return

	var delay = min(base_reconnect_delay * pow(2, reconnect_attempts), max_reconnect_delay)
	reconnect_timer = delay
	reconnect_attempts += 1

	print("[NetworkManager] Scheduling reconnect attempt %d in %.1f seconds..." % [reconnect_attempts, delay])
	current_state = ConnectionState.RECONNECTING


func _attempt_reconnect() -> void:
	print("[NetworkManager] Attempting to reconnect...")
	connect_to_server(server_url, auth_token, true)


## Check if connected to server
func is_server_connected() -> bool:
	return current_state == ConnectionState.CONNECTED \
		and _transport != null \
		and _transport.client_state() == Transport.LinkState.OPEN


func get_stats() -> Dictionary:
	return stats.duplicate()


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


# ── Retired server-mode API (the Rust server owns this role now) ─────────────
# Inert stubs so legacy scripts (server_main.gd and friends) fail soft instead of crashing.

## server_main.gd reads this per metrics second; an empty dictionary keeps it inert.
var peer_bytes_sent: Dictionary = {}


func begin_batch() -> void:
	pass


func flush_batches() -> void:
	pass


func clear_batches() -> void:
	pass


func send_to_client(_peer_id: int, _message_type: int, _data: Dictionary = {}) -> void:
	push_error("[NetworkManager] send_to_client: the GDScript server is retired - use omega-server")


func broadcast_to_clients(_message_type: int, _data: Dictionary = {}) -> void:
	push_error("[NetworkManager] broadcast_to_clients: the GDScript server is retired - use omega-server")


func disconnect_client(_peer_id: int, _reason: String = "") -> void:
	pass


func get_connected_peer_ids() -> Array:
	return []
