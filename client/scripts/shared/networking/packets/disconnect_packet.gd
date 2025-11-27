## DisconnectPacket - Clean disconnect notification (5 bytes payload)
## Sent from client to server when disconnecting intentionally
## Format:
##   [u8 reason_code]                     1 byte  - disconnect reason enum
##   [u32 timestamp_ms]                   4 bytes - disconnect timestamp
class_name DisconnectPacket
extends RefCounted

## Disconnect reason (from PacketTypes.DisconnectReason)
var reason: int = PacketTypes.DisconnectReason.USER_QUIT
## Timestamp when disconnect was initiated
var timestamp_ms: int = 0


func _init() -> void:
	pass


## Create disconnect packet
static func create(disconnect_reason: int = PacketTypes.DisconnectReason.USER_QUIT) -> DisconnectPacket:
	var packet = DisconnectPacket.new()
	packet.reason = disconnect_reason
	packet.timestamp_ms = Time.get_ticks_msec()
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	var writer = PacketWriter.new(12)  # 3 header + 5 payload + safety
	writer.write_header(PacketTypes.Type.DISCONNECT)
	write_payload(writer)
	writer.finalize_header()
	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u8(reason)
	writer.write_u32(timestamp_ms)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> DisconnectPacket:
	var packet = DisconnectPacket.new()
	packet.reason = reader.read_u8()
	packet.timestamp_ms = reader.read_u32()
	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> DisconnectPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Get reason name
func get_reason_name() -> String:
	match reason:
		PacketTypes.DisconnectReason.USER_QUIT: return "User quit"
		PacketTypes.DisconnectReason.TIMEOUT: return "Connection timeout"
		PacketTypes.DisconnectReason.KICKED: return "Kicked by server"
		PacketTypes.DisconnectReason.SERVER_SHUTDOWN: return "Server shutdown"
		PacketTypes.DisconnectReason.INVALID_AUTH: return "Invalid authentication"
		PacketTypes.DisconnectReason.DUPLICATE_SESSION: return "Duplicate session"
		_: return "Unknown (%d)" % reason


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "DISCONNECT",
		"reason": reason,
		"reason_name": get_reason_name(),
		"timestamp_ms": timestamp_ms
	}
