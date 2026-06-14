## ENetTransport - client transport over Godot's native ENetConnection (ADR 0003, D2).
##
## Three raw channels per the migration-spec D2 plan:
##   ch0 unreliable sequenced  - Snapshot, ActionConfirm (server -> client)
##   ch1 reliable ordered      - auth, game events, acks, requests
##   ch2 unreliable sequenced  - PlayerInput (client -> server)
## Unreliable-sequenced is flags = 0 (no flag exists for it; FLAG_UNSEQUENCED would
## permit stale-after-newer dispatch and must never be used on ch0/ch2).
##
## The protocol version rides the connect data argument; the Rust server refuses
## mismatches before any packet is exchanged (D7).
class_name ENetTransport
extends Transport

var _connection: ENetConnection = null
var _peer: ENetPacketPeer = null
var _state: LinkState = LinkState.CLOSED
## Drained by client_take_channel_packets: Array of {channel: int, bytes: PackedByteArray}.
var _pending: Array = []
var _close_info: Dictionary = {"code": 0, "reason": ""}


## Accepts "host:port" with an optional scheme prefix (enet://, ws://, wss:// — the
## Go API region payload historically carries ws:// URLs).
static func parse_host_port(url: String) -> Dictionary:
	var rest := url.strip_edges()
	var scheme_idx := rest.find("://")
	if scheme_idx >= 0:
		rest = rest.substr(scheme_idx + 3)
	var slash_idx := rest.find("/")
	if slash_idx >= 0:
		rest = rest.substr(0, slash_idx)
	var host := rest
	var port := 8081
	var colon_idx := rest.rfind(":")
	if colon_idx >= 0:
		host = rest.substr(0, colon_idx)
		var port_text := rest.substr(colon_idx + 1)
		if port_text.is_valid_int():
			port = int(port_text)
	if host.is_empty():
		host = "localhost"
	return {"host": host, "port": port}


func client_connect(url: String) -> Error:
	client_reset()
	var parsed := parse_host_port(url)
	# Resolve bare hostnames to IPv4 ourselves: ENet takes whatever address family the
	# resolver returns first (on macOS "localhost" -> ::1), but omega-server binds
	# IPv4-only, so an IPv6 connect hangs until the connection timeout.
	var host: String = parsed.host
	if not host.is_valid_ip_address():
		var resolved := IP.resolve_hostname(host, IP.TYPE_IPV4)
		if resolved.is_valid_ip_address():
			host = resolved
	_connection = ENetConnection.new()
	var err := _connection.create_host(1)
	if err != OK:
		_connection = null
		return err
	_peer = _connection.connect_to_host(
		host, parsed.port, 3, ProtocolCodec.protocol_version()
	)
	if _peer == null:
		_connection.destroy()
		_connection = null
		return FAILED
	_state = LinkState.CONNECTING
	return OK


func client_poll() -> void:
	if _connection == null:
		return
	while true:
		var ev: Array = _connection.service(0)
		match ev[0]:
			ENetConnection.EVENT_NONE:
				break
			ENetConnection.EVENT_CONNECT:
				_state = LinkState.OPEN
			ENetConnection.EVENT_DISCONNECT:
				_state = LinkState.CLOSED
				_close_info = {"code": int(ev[2]), "reason": "Server closed the connection"}
			ENetConnection.EVENT_RECEIVE:
				var peer: ENetPacketPeer = ev[1]
				_pending.append({"channel": int(ev[3]), "bytes": peer.get_packet()})
			ENetConnection.EVENT_ERROR:
				push_error("[ENetTransport] host error - resetting")
				_state = LinkState.CLOSED
				_close_info = {"code": -1, "reason": "ENet host error"}
				break


func client_state() -> LinkState:
	return _state


## Drain all received packets in arrival order: Array of {channel, bytes}.
func client_take_channel_packets() -> Array:
	var out := _pending
	_pending = []
	return out


## Channel-aware send (the seam's un-channeled client_send is not used over ENet).
func client_send_channel(channel: int, bytes: PackedByteArray, reliable: bool) -> Error:
	if _peer == null or _state != LinkState.OPEN:
		return ERR_UNCONFIGURED
	var flags := ENetPacketPeer.FLAG_RELIABLE if reliable else 0
	return _peer.send(channel, bytes, flags)


## Round-trip time from ENet's native statistics (replaces app-level HEARTBEAT RTT).
func client_rtt_ms() -> float:
	if _peer == null:
		return 0.0
	return _peer.get_statistic(ENetPacketPeer.PEER_ROUND_TRIP_TIME)


func client_close(_code: int, _reason: String) -> void:
	if _peer != null and _state == LinkState.OPEN:
		_peer.peer_disconnect(0)
		_state = LinkState.CLOSING
		# NetworkManager stops polling once it leaves CONNECTED, so the disconnect
		# request would never leave the machine (the server would only learn via
		# ENet timeout — ghost player, stale session on rejoin). Service the host
		# here, bounded, until the disconnect is acknowledged.
		var deadline := Time.get_ticks_msec() + 200
		while Time.get_ticks_msec() < deadline:
			var ev: Array = _connection.service(10)
			if ev[0] == ENetConnection.EVENT_DISCONNECT or ev[0] == ENetConnection.EVENT_ERROR:
				_state = LinkState.CLOSED
				_close_info = {"code": 0, "reason": "Client disconnect"}
				return
	elif _peer != null:
		_peer.peer_disconnect_now(0)
		if _connection != null:
			_connection.flush()
		_state = LinkState.CLOSED


func client_close_info() -> Dictionary:
	return _close_info


func client_reset() -> void:
	if _connection != null:
		_connection.destroy()
	_connection = null
	_peer = null
	_state = LinkState.CLOSED
	_pending = []
	_close_info = {"code": 0, "reason": ""}
