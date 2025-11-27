## GameEventPacket - Server event notification (variable size)
## Sent from server to clients for game events (damage, kills, effects)
## Format varies by event type:
##   [u8 event_type]                      1 byte  - event type enum
##   [u16 source_id]                      2 bytes - source entity
##   [u16 target_id]                      2 bytes - target entity
##   [varies]                             - event-specific data
class_name GameEventPacket
extends RefCounted

## Event type (from PacketTypes.GameEventType)
var event_type: int = 0
## Source entity ID (who caused the event)
var source_id: int = 0
## Target entity ID (who was affected)
var target_id: int = 0
## Event-specific data
var event_data: Dictionary = {}


func _init() -> void:
	event_data = {}


## Create a damage event
static func create_damage(source: int, target: int, damage_amount: int, damage_type: int = 0) -> GameEventPacket:
	var packet = GameEventPacket.new()
	packet.event_type = PacketTypes.GameEventType.DAMAGE
	packet.source_id = source
	packet.target_id = target
	packet.event_data = {
		"amount": damage_amount,
		"damage_type": damage_type
	}
	return packet


## Create a kill event
static func create_kill(killer_id: int, victim_id: int) -> GameEventPacket:
	var packet = GameEventPacket.new()
	packet.event_type = PacketTypes.GameEventType.KILL
	packet.source_id = killer_id
	packet.target_id = victim_id
	return packet


## Create a respawn event
static func create_respawn(entity_id: int, spawn_position: Vector2) -> GameEventPacket:
	var packet = GameEventPacket.new()
	packet.event_type = PacketTypes.GameEventType.RESPAWN
	packet.source_id = 0
	packet.target_id = entity_id
	packet.event_data = {
		"position": spawn_position
	}
	return packet


## Create an effect applied event
static func create_effect_apply(source: int, target: int, effect_id: int, duration_ms: int) -> GameEventPacket:
	var packet = GameEventPacket.new()
	packet.event_type = PacketTypes.GameEventType.EFFECT_APPLY
	packet.source_id = source
	packet.target_id = target
	packet.event_data = {
		"effect_id": effect_id,
		"duration_ms": duration_ms
	}
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	var writer = PacketWriter.new(64)  # Most events fit in 64 bytes
	writer.write_header(PacketTypes.Type.GAME_EVENT)
	write_payload(writer)
	writer.finalize_header()
	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u8(event_type)
	writer.write_u16(source_id)
	writer.write_u16(target_id)

	# Write event-specific data based on type
	match event_type:
		PacketTypes.GameEventType.DAMAGE:
			writer.write_u16(event_data.get("amount", 0))
			writer.write_u8(event_data.get("damage_type", 0))

		PacketTypes.GameEventType.KILL:
			# No additional data needed
			pass

		PacketTypes.GameEventType.RESPAWN:
			var pos: Vector2 = event_data.get("position", Vector2.ZERO)
			writer.write_vector2_compressed(pos)

		PacketTypes.GameEventType.EFFECT_APPLY:
			writer.write_u8(event_data.get("effect_id", 0))
			writer.write_u16(event_data.get("duration_ms", 0))

		PacketTypes.GameEventType.EFFECT_REMOVE:
			writer.write_u8(event_data.get("effect_id", 0))

		_:
			# Generic: write event_data as simple key-value pairs
			# For extensibility, could use JSON for unknown types
			pass


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> GameEventPacket:
	var packet = GameEventPacket.new()
	packet.event_type = reader.read_u8()
	packet.source_id = reader.read_u16()
	packet.target_id = reader.read_u16()

	# Read event-specific data based on type
	match packet.event_type:
		PacketTypes.GameEventType.DAMAGE:
			packet.event_data = {
				"amount": reader.read_u16(),
				"damage_type": reader.read_u8()
			}

		PacketTypes.GameEventType.KILL:
			packet.event_data = {}

		PacketTypes.GameEventType.RESPAWN:
			packet.event_data = {
				"position": reader.read_vector2_compressed()
			}

		PacketTypes.GameEventType.EFFECT_APPLY:
			packet.event_data = {
				"effect_id": reader.read_u8(),
				"duration_ms": reader.read_u16()
			}

		PacketTypes.GameEventType.EFFECT_REMOVE:
			packet.event_data = {
				"effect_id": reader.read_u8()
			}

	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> GameEventPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Get event type name
func get_event_type_name() -> String:
	match event_type:
		PacketTypes.GameEventType.DAMAGE: return "DAMAGE"
		PacketTypes.GameEventType.KILL: return "KILL"
		PacketTypes.GameEventType.RESPAWN: return "RESPAWN"
		PacketTypes.GameEventType.EFFECT_APPLY: return "EFFECT_APPLY"
		PacketTypes.GameEventType.EFFECT_REMOVE: return "EFFECT_REMOVE"
		PacketTypes.GameEventType.PICKUP: return "PICKUP"
		PacketTypes.GameEventType.LEVEL_UP: return "LEVEL_UP"
		PacketTypes.GameEventType.CHAT_MESSAGE: return "CHAT_MESSAGE"
		_: return "UNKNOWN(%d)" % event_type


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "GAME_EVENT",
		"event_type": event_type,
		"event_name": get_event_type_name(),
		"source_id": source_id,
		"target_id": target_id,
		"event_data": event_data
	}
