## StateUpdatePacket - Server state broadcast (variable size)
## Sent from server to clients at 10Hz
## Contains all visible entities' states
## Format:
##   [u32 server_tick]                    4 bytes - server tick number
##   [u8 entity_count]                    1 byte  - number of entities
##   For each entity (9 bytes each):
##     [u16 entity_id]                    2 bytes
##     [u8 entity_type]                   1 byte
##     [s16 position_x][s16 position_y]   4 bytes
##     [u8 animation_state]               1 byte
##     [u8 flags]                         1 byte
class_name StateUpdatePacket
extends RefCounted

## Size of each entity entry in bytes
const ENTITY_SIZE := 9

## Server tick number when this update was generated
var server_tick: int = 0
## List of entity states
var entities: Array[EntityState] = []


## Inner class for entity state
class EntityState extends RefCounted:
	var entity_id: int = 0
	var entity_type: int = PacketTypes.EntityType.PLAYER
	var position: Vector2 = Vector2.ZERO
	var animation_state: int = PacketTypes.AnimationState.IDLE
	var flags: int = 0

	static func create(id: int, type: int, pos: Vector2, anim: int = 0, flg: int = 0) -> EntityState:
		var state = EntityState.new()
		state.entity_id = id
		state.entity_type = type
		state.position = pos
		state.animation_state = anim
		state.flags = flg
		return state

	func is_alive() -> bool:
		return (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0

	func is_moving() -> bool:
		return (flags & PacketTypes.ENTITY_FLAG_MOVING) != 0

	func is_attacking() -> bool:
		return (flags & PacketTypes.ENTITY_FLAG_ATTACKING) != 0

	func to_dict() -> Dictionary:
		return {
			"entity_id": entity_id,
			"entity_type": entity_type,
			"position": position,
			"animation_state": animation_state,
			"flags": flags,
			"flags_decoded": PacketTypes.decode_entity_flags(flags)
		}


func _init() -> void:
	entities = []


## Create state update with current tick
static func create(tick: int) -> StateUpdatePacket:
	var packet = StateUpdatePacket.new()
	packet.server_tick = tick
	return packet


## Add an entity to the update
func add_entity(id: int, type: int, pos: Vector2, anim: int = 0, flg: int = 0) -> void:
	entities.append(EntityState.create(id, type, pos, anim, flg))


## Add entity from dictionary
func add_entity_dict(data: Dictionary) -> void:
	var state = EntityState.new()
	state.entity_id = data.get("id", 0)
	state.entity_type = data.get("type", PacketTypes.EntityType.PLAYER)
	state.position = data.get("position", Vector2.ZERO)
	state.animation_state = data.get("animation", PacketTypes.AnimationState.IDLE)
	state.flags = data.get("flags", PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE)
	entities.append(state)


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	# Calculate size: header(3) + tick(4) + count(1) + entities(9 each)
	var size = 3 + 4 + 1 + (entities.size() * ENTITY_SIZE) + 4  # +4 safety
	var writer = PacketWriter.new(size)

	writer.write_header(PacketTypes.Type.STATE_UPDATE)
	write_payload(writer)
	writer.finalize_header()

	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u32(server_tick)
	writer.write_u8(mini(entities.size(), 255))  # Max 255 entities per packet

	for i in range(mini(entities.size(), 255)):
		var entity: EntityState = entities[i]
		writer.write_u16(entity.entity_id)
		writer.write_u8(entity.entity_type)
		writer.write_vector2_compressed(entity.position)
		writer.write_u8(entity.animation_state)
		writer.write_u8(entity.flags)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> StateUpdatePacket:
	var packet = StateUpdatePacket.new()
	packet.server_tick = reader.read_u32()

	var entity_count = reader.read_u8()
	for i in range(entity_count):
		var state = EntityState.new()
		state.entity_id = reader.read_u16()
		state.entity_type = reader.read_u8()
		state.position = reader.read_vector2_compressed()
		state.animation_state = reader.read_u8()
		state.flags = reader.read_u8()
		packet.entities.append(state)

	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> StateUpdatePacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Get entity by ID
func get_entity(entity_id: int) -> EntityState:
	for entity in entities:
		if entity.entity_id == entity_id:
			return entity
	return null


## Get all entities of a specific type
func get_entities_by_type(entity_type: int) -> Array[EntityState]:
	var result: Array[EntityState] = []
	for entity in entities:
		if entity.entity_type == entity_type:
			result.append(entity)
	return result


## Get all players
func get_players() -> Array[EntityState]:
	return get_entities_by_type(PacketTypes.EntityType.PLAYER)


## Get all monsters
func get_monsters() -> Array[EntityState]:
	return get_entities_by_type(PacketTypes.EntityType.MONSTER)


## Get all projectiles
func get_projectiles() -> Array[EntityState]:
	return get_entities_by_type(PacketTypes.EntityType.PROJECTILE)


## Calculate packet size in bytes
func get_size() -> int:
	return 3 + 4 + 1 + (entities.size() * ENTITY_SIZE)  # header + tick + count + entities


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	var entity_dicts: Array[Dictionary] = []
	for entity in entities:
		entity_dicts.append(entity.to_dict())

	return {
		"type": "STATE_UPDATE",
		"server_tick": server_tick,
		"entity_count": entities.size(),
		"entities": entity_dicts,
		"size_bytes": get_size()
	}
