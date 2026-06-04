## WebSocketTransport — the default Transport impl (roadmap #12).
##
## Holds every concrete WebSocketPeer / TCPServer / TLSOptions call that used to
## live inline in NetworkManager. The bodies here are RELOCATED VERBATIM from the
## old network_manager.gd call sites — no logic edits, only the structural split
## into seam methods. Behaviour is byte-for-byte identical to the pre-seam code.
##
## NetworkManager owns the protocol/encode/decode/batch/heartbeat/clock/reconnect
## logic and ALL stats accounting; this class only performs the raw socket verbs
## and tracks the per-peer WebSocketPeer dictionary, exposing peers as opaque ints.
class_name WebSocketTransport
extends Transport

## WebSocket client (client role). Was network_manager.gd `ws_client`.
var _ws_client: WebSocketPeer = null

## TCP listener (server role). Was network_manager.gd `ws_server`.
var _ws_server: TCPServer = null

## peer_id -> WebSocketPeer. Was network_manager.gd `connected_peers`.
var _connected_peers: Dictionary = {}

## peer_id -> bool: true once this transport has observed the peer reach OPEN.
## Lets server_poll() emit exactly one "connected" event per peer, mirroring the
## old `not peer_connection_announced.has(peer_id)` guard (the higher-level
## announce bookkeeping still lives in NetworkManager).
var _peer_open_seen: Dictionary = {}

## Events observed during the most recent server_poll(), drained by
## server_take_events(). Preserves per-peer FIFO packet order.
var _pending_events: Array = []


func _map_ws_state(state: int) -> int:
	# Map WebSocketPeer.STATE_* onto the transport-neutral LinkState so callers
	# never compare against the concrete socket enum.
	match state:
		WebSocketPeer.STATE_OPEN:
			return LinkState.OPEN
		WebSocketPeer.STATE_CONNECTING:
			return LinkState.CONNECTING
		WebSocketPeer.STATE_CLOSING:
			return LinkState.CLOSING
		_:
			return LinkState.CLOSED


# --- Server-role seam ------------------------------------------------------

func server_listen(port: int) -> int:
	_ws_server = TCPServer.new()
	return _ws_server.listen(port)


func server_poll() -> void:
	_pending_events = []
	if _ws_server == null:
		return

	# Accept new connections.
	if _ws_server.is_connection_available():
		var peer = _ws_server.take_connection()
		var ws_peer = WebSocketPeer.new()
		ws_peer.accept_stream(peer)
		var peer_id = randi()  # Generate unique peer ID
		_connected_peers[peer_id] = ws_peer
		print("[NetworkManager] Server: New client connecting (ID: %d)" % peer_id)

	# Poll all connected peers.
	for peer_id in _connected_peers.keys():
		var ws_peer: WebSocketPeer = _connected_peers[peer_id]
		ws_peer.poll()

		var state = ws_peer.get_ready_state()
		if state == WebSocketPeer.STATE_OPEN:
			if not _peer_open_seen.has(peer_id):
				_peer_open_seen[peer_id] = true
				_pending_events.append({"kind": "connected", "peer_id": peer_id})

			# Receive messages from this peer (FIFO).
			while ws_peer.get_available_packet_count() > 0:
				_pending_events.append({
					"kind": "packet",
					"peer_id": peer_id,
					"bytes": ws_peer.get_packet()
				})
		elif state == WebSocketPeer.STATE_CLOSED:
			_connected_peers.erase(peer_id)
			_peer_open_seen.erase(peer_id)
			_pending_events.append({"kind": "closed", "peer_id": peer_id})


func server_take_events() -> Array:
	var events := _pending_events
	_pending_events = []
	return events


func server_send(peer_id: int, bytes: PackedByteArray) -> bool:
	var ws_peer: WebSocketPeer = _connected_peers.get(peer_id)
	if ws_peer == null or ws_peer.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return false
	return ws_peer.send(bytes) == OK


func server_close_peer(peer_id: int, code: int, reason: String) -> void:
	var ws_peer: WebSocketPeer = _connected_peers.get(peer_id)
	if ws_peer == null:
		return
	ws_peer.close(code, reason)
	_connected_peers.erase(peer_id)
	_peer_open_seen.erase(peer_id)


func server_peer_open(peer_id: int) -> bool:
	var ws_peer: WebSocketPeer = _connected_peers.get(peer_id)
	return ws_peer != null and ws_peer.get_ready_state() == WebSocketPeer.STATE_OPEN


func server_peer_ids() -> Array:
	return _connected_peers.keys()


# --- Client-role seam ------------------------------------------------------

func client_connect(url: String) -> int:
	_ws_client = WebSocketPeer.new()
	return _ws_client.connect_to_url(url, TLSOptions.client())


func client_poll() -> void:
	if _ws_client == null:
		return
	_ws_client.poll()


func client_state() -> int:
	if _ws_client == null:
		return LinkState.CLOSED
	return _map_ws_state(_ws_client.get_ready_state())


func client_take_packets() -> Array:
	var buffers: Array = []
	if _ws_client == null:
		return buffers
	while _ws_client.get_available_packet_count() > 0:
		buffers.append(_ws_client.get_packet())
	return buffers


func client_send(bytes: PackedByteArray) -> int:
	if _ws_client == null:
		return ERR_UNCONFIGURED
	return _ws_client.send(bytes)


func client_close(code: int, reason: String) -> void:
	if _ws_client == null:
		return
	_ws_client.close(code, reason)


func client_close_info() -> Dictionary:
	if _ws_client == null:
		return {"code": 0, "reason": ""}
	return {
		"code": _ws_client.get_close_code(),
		"reason": _ws_client.get_close_reason()
	}


func client_reset() -> void:
	_ws_client = null
