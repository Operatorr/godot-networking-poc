## Transport — abstract transport seam for NetworkManager (roadmap #12).
##
## This is the ONE line the netcode is split along: everything that names a
## concrete socket type (WebSocketPeer / TCPServer / TLSOptions today, ENet
## tomorrow) lives BELOW this seam, inside a Transport subclass. Everything
## protocol-level — _encode_packet/_decode_packet, the [u8 type][u16 length]
## header, BATCH coalescing, heartbeat/clock-sync, reconnect/backoff, and ALL
## stats accounting (bytes_sent_by_type / peer_bytes_sent) — stays ABOVE the
## seam, in NetworkManager, addressing peers only by opaque int peer_id.
##
## The seam is wire-neutral: it sits below PacketWriter/PacketReader, so swapping
## the substrate (the deferred ENet follow-up, ADR 0003) changes zero bytes on
## the wire — only the framing/delivery layer.
##
## A single Transport object knows its role (CLIENT vs SERVER); NetworkManager
## already branches on `is_server`, so it sets `role` at construction and then
## calls only the seam methods for the matching role.
##
## Subclasses MUST override every method below. The base implementations
## push_error so an un-overridden seam method fails loudly during bring-up rather
## than silently returning a wrong default.
class_name Transport
extends RefCounted

## Transport-neutral link state. Concrete transports map their native socket
## state (e.g. WebSocketPeer.STATE_*) onto this so NetworkManager never compares
## against a concrete socket enum.
enum LinkState {
	OPEN,
	CONNECTING,
	CLOSING,
	CLOSED
}

## Role of this transport instance. NetworkManager sets this once at construction.
enum Role {
	CLIENT,
	SERVER
}

var role: int = Role.CLIENT


func _not_overridden(method_name: String) -> void:
	push_error("[Transport] %s() not overridden by %s" % [method_name, get_script().resource_path])


# --- Server-role seam ------------------------------------------------------

## Bind/listen on `port`. Returns an Error code (OK on success).
func server_listen(_port: int) -> int:
	_not_overridden("server_listen")
	return ERR_UNCONFIGURED

## Accept pending connections and poll all tracked peers. No return value; the
## observed events are drained via server_take_events().
func server_poll() -> void:
	_not_overridden("server_poll")

## Return the normalized events observed during the most recent server_poll(),
## in observation order. Each entry is a Dictionary:
##   {"kind": "connected", "peer_id": int}
##   {"kind": "closed",    "peer_id": int}
##   {"kind": "packet",    "peer_id": int, "bytes": PackedByteArray}
## "packet" entries MUST appear in FIFO receive order per peer — downstream
## interpolation/reconciliation depend on snapshot ordering.
func server_take_events() -> Array:
	_not_overridden("server_take_events")
	return []

## Send a raw, already-encoded packet to one peer. Returns true on success.
## Stats accounting stays in NetworkManager; this only writes the bytes.
func server_send(_peer_id: int, _bytes: PackedByteArray) -> bool:
	_not_overridden("server_send")
	return false

## Close one peer's connection with a close code + reason and drop its state.
func server_close_peer(_peer_id: int, _code: int, _reason: String) -> void:
	_not_overridden("server_close_peer")

## True if the peer's link is OPEN (used as a send guard).
func server_peer_open(_peer_id: int) -> bool:
	_not_overridden("server_peer_open")
	return false

## All currently tracked peer ids (server mode).
func server_peer_ids() -> Array:
	_not_overridden("server_peer_ids")
	return []


# --- Client-role seam ------------------------------------------------------

## Begin connecting to `url`. Returns an Error code (OK if the attempt started).
func client_connect(_url: String) -> int:
	_not_overridden("client_connect")
	return ERR_UNCONFIGURED

## Pump the client socket. Must be called before reading client_state().
func client_poll() -> void:
	_not_overridden("client_poll")

## Current link state as a transport-neutral LinkState.
func client_state() -> int:
	_not_overridden("client_state")
	return LinkState.CLOSED

## Drain all currently-available inbound buffers in FIFO order. NetworkManager
## dispatches each buffer itself (BATCH unwrap stays above the seam).
func client_take_packets() -> Array:
	_not_overridden("client_take_packets")
	return []

## Send a raw, already-encoded packet to the server. Returns an Error code.
func client_send(_bytes: PackedByteArray) -> int:
	_not_overridden("client_send")
	return ERR_UNCONFIGURED

## Close the client connection with a close code + reason.
func client_close(_code: int, _reason: String) -> void:
	_not_overridden("client_close")

## {"code": int, "reason": String} for the most recent close (disconnect log).
func client_close_info() -> Dictionary:
	_not_overridden("client_close_info")
	return {"code": 0, "reason": ""}

## Tear down the underlying client socket so a fresh client_connect() starts clean.
func client_reset() -> void:
	_not_overridden("client_reset")
