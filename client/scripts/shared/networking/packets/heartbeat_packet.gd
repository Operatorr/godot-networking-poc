## HeartbeatPacket - Keep-alive packet (4 bytes payload)
## Used for connection health monitoring and latency measurement
## Format: [u32 timestamp_ms]
class_name HeartbeatPacket
extends RefCounted

## Timestamp in milliseconds when packet was sent
var timestamp_ms: int = 0


func _init(ts: int = 0) -> void:
	timestamp_ms = ts


## Create heartbeat with current timestamp
static func create_now() -> HeartbeatPacket:
	return HeartbeatPacket.new(Time.get_ticks_msec())


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	var writer = PacketWriter.new(8)  # 3 header + 4 payload + 1 safety
	writer.write_header(PacketTypes.Type.HEARTBEAT)
	writer.write_u32(timestamp_ms)
	writer.finalize_header()
	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u32(timestamp_ms)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> HeartbeatPacket:
	var packet = HeartbeatPacket.new()
	packet.timestamp_ms = reader.read_u32()
	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> HeartbeatPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Calculate round-trip latency from this packet's timestamp
func get_latency_ms() -> int:
	return Time.get_ticks_msec() - timestamp_ms


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "HEARTBEAT",
		"timestamp_ms": timestamp_ms
	}
