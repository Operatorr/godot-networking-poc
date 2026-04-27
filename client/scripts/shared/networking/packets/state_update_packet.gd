## StateUpdatePacket - Server state broadcast (variable size)
## Sent from server to clients at 10Hz
## Contains all visible entities' states
##
## Full State Format:
##   [u32 server_tick]                    4 bytes - server tick number
##   [u8 state_flags]                     1 byte  - packet flags (TASK-021)
##   [u8 entity_count]                    1 byte  - number of entities
##   For each entity (9 bytes each):
##     [u16 entity_id]                    2 bytes
##     [u8 entity_type]                   1 byte
##     [s16 position_x][s16 position_y]   4 bytes, 0.1-unit precision
##     [u8 animation_state]               1 byte
##     [u8 flags]                         1 byte
##
## Delta Format (TASK-021):
##   [u32 server_tick]                    4 bytes
##   [u8 state_flags]                     1 byte  - STATE_FLAG_IS_DELTA set
##   [u32 baseline_tick]                  4 bytes - tick of last full state
##   [u8 entity_count]                    1 byte
##   For each entity (3-10 bytes):
##     [u16 entity_id]                    2 bytes
##     [u8 delta_mask]                    1 byte  - which fields changed
##     no additional fields               if DELTA_MASK_REMOVED
##     [s16 pos_x][s16 pos_y]             4 bytes, 0.1-unit precision (if DELTA_MASK_POSITION)
##     [u8 animation_state]               1 byte  (if DELTA_MASK_ANIMATION)
##     [u8 flags]                         1 byte  (if DELTA_MASK_FLAGS)
class_name StateUpdatePacket
extends RefCounted

## Size of each full-state entity entry in bytes
const ENTITY_SIZE := 9
## Minimum delta entity size (entity_id + delta_mask)
const DELTA_ENTITY_MIN_SIZE := 3

## Server tick number when this update was generated
var server_tick: int = 0
## Packet-level state flags (TASK-021)
var state_flags: int = 0
## Baseline tick for delta packets (TASK-021)
var baseline_tick: int = 0
## List of entity states
var entities: Array[EntityState] = []


## Inner class for entity state
class EntityState extends RefCounted:
	var entity_id: int = 0
	var entity_type: int = PacketTypes.EntityType.PLAYER
	var position: Vector2 = Vector2.ZERO
	var animation_state: int = PacketTypes.AnimationState.IDLE
	var flags: int = 0
	## Delta mask indicating which fields are present (TASK-021)
	## For full state, this is DELTA_MASK_FULL_STATE
	var delta_mask: int = PacketTypes.DELTA_MASK_FULL_STATE

	static func create(id: int, type: int, pos: Vector2, anim: int = 0, flg: int = 0) -> EntityState:
		var state = EntityState.new()
		state.entity_id = id
		state.entity_type = type
		state.position = pos
		state.animation_state = anim
		state.flags = flg
		state.delta_mask = PacketTypes.DELTA_MASK_FULL_STATE
		return state

	## Create entity state with specific delta mask (TASK-021)
	static func create_delta(id: int, type: int, mask: int, pos: Vector2, anim: int, flg: int) -> EntityState:
		var state = EntityState.new()
		state.entity_id = id
		state.entity_type = type
		state.position = pos
		state.animation_state = anim
		state.flags = flg
		state.delta_mask = mask
		return state

	## Check if this is a full state (not delta)
	func is_full_state() -> bool:
		return (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0

	func is_removed() -> bool:
		return (delta_mask & PacketTypes.DELTA_MASK_REMOVED) != 0

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
			"flags_decoded": PacketTypes.decode_entity_flags(flags),
			"delta_mask": delta_mask,
			"is_full_state": is_full_state()
		}


func _init() -> void:
	entities = []


## Create state update with current tick (full state mode)
static func create(tick: int) -> StateUpdatePacket:
	var packet = StateUpdatePacket.new()
	packet.server_tick = tick
	packet.state_flags = 0  # Full state (not delta)
	return packet


## Create delta state update (TASK-021)
static func create_delta(tick: int, baseline: int) -> StateUpdatePacket:
	var packet = StateUpdatePacket.new()
	packet.server_tick = tick
	packet.baseline_tick = baseline
	packet.state_flags = PacketTypes.STATE_FLAG_IS_DELTA
	return packet


## Check if this is a delta packet
func is_delta() -> bool:
	return (state_flags & PacketTypes.STATE_FLAG_IS_DELTA) != 0


## Add an entity to the update (full state)
func add_entity(id: int, type: int, pos: Vector2, anim: int = 0, flg: int = 0) -> void:
	entities.append(EntityState.create(id, type, pos, anim, flg))


## Add entity with delta mask (TASK-021)
func add_entity_delta(id: int, type: int, mask: int, pos: Vector2, anim: int, flg: int) -> void:
	entities.append(EntityState.create_delta(id, type, mask, pos, anim, flg))


## Add entity from dictionary
func add_entity_dict(data: Dictionary) -> void:
	var state = EntityState.new()
	state.entity_id = data.get("entity_id", data.get("id", 0))
	state.entity_type = data.get("entity_type", data.get("type", PacketTypes.EntityType.PLAYER))
	state.position = data.get("position", Vector2.ZERO)
	state.animation_state = data.get("animation_state", data.get("animation", PacketTypes.AnimationState.IDLE))
	state.delta_mask = data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
	if state.is_removed():
		state.flags = 0
	else:
		state.flags = data.get("flags", PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE)
	entities.append(state)


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	# Estimate size based on packet mode
	var estimated_size: int
	if is_delta():
		# Delta: header(3) + tick(4) + flags(1) + baseline(4) + count(1) + entities(variable)
		estimated_size = 3 + 4 + 1 + 4 + 1 + (entities.size() * ENTITY_SIZE) + 8
	else:
		# Full: header(3) + tick(4) + flags(1) + count(1) + entities(9 each)
		estimated_size = 3 + 4 + 1 + 1 + (entities.size() * ENTITY_SIZE) + 4

	var writer = PacketWriter.new(estimated_size)

	writer.write_header(PacketTypes.Type.STATE_UPDATE)
	write_payload(writer)
	writer.finalize_header()

	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u32(server_tick)
	writer.write_u8(state_flags)

	if is_delta():
		# Delta mode: include baseline tick
		writer.write_u32(baseline_tick)
		_write_delta_entities(writer)
	else:
		# Full state mode
		_write_full_entities(writer)


## Write entities in full state format
func _write_full_entities(writer: PacketWriter) -> void:
	writer.write_u8(mini(entities.size(), 255))

	for i in range(mini(entities.size(), 255)):
		var entity: EntityState = entities[i]
		writer.write_u16(entity.entity_id)
		writer.write_u8(entity.entity_type)
		writer.write_vector2_compressed(entity.position)
		writer.write_u8(entity.animation_state)
		writer.write_u8(entity.flags)


## Write entities in delta format (TASK-021)
func _write_delta_entities(writer: PacketWriter) -> void:
	writer.write_u8(mini(entities.size(), 255))

	for i in range(mini(entities.size(), 255)):
		var entity: EntityState = entities[i]
		writer.write_u16(entity.entity_id)
		writer.write_u8(entity.delta_mask)

		# Write full state for new entities or periodic sync
		if entity.is_full_state():
			writer.write_u8(entity.entity_type)
			writer.write_vector2_compressed(entity.position)
			writer.write_u8(entity.animation_state)
			writer.write_u8(entity.flags)
		else:
			# Write only changed fields
			if (entity.delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
				writer.write_vector2_compressed(entity.position)
			if (entity.delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
				writer.write_u8(entity.animation_state)
			if (entity.delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
				writer.write_u8(entity.flags)


## Read packet from reader (assumes header already read)
## For delta packets, caller must provide last_states for reconstruction
static func read(reader: PacketReader, last_states: Dictionary = {}) -> StateUpdatePacket:
	var packet = StateUpdatePacket.new()
	packet.server_tick = reader.read_u32()
	packet.state_flags = reader.read_u8()

	if packet.is_delta():
		# Delta mode: read baseline tick and delta entities
		packet.baseline_tick = reader.read_u32()
		_read_delta_entities(reader, packet, last_states)
	else:
		# Full state mode
		_read_full_entities(reader, packet)

	return packet


## Read full state entities
static func _read_full_entities(reader: PacketReader, packet: StateUpdatePacket) -> void:
	var entity_count = reader.read_u8()
	for i in range(entity_count):
		var state = EntityState.new()
		state.entity_id = reader.read_u16()
		state.entity_type = reader.read_u8()
		state.position = reader.read_vector2_compressed()
		state.animation_state = reader.read_u8()
		state.flags = reader.read_u8()
		state.delta_mask = PacketTypes.DELTA_MASK_FULL_STATE
		packet.entities.append(state)


## Read delta entities and reconstruct full state (TASK-021)
static func _read_delta_entities(reader: PacketReader, packet: StateUpdatePacket, last_states: Dictionary) -> void:
	var entity_count = reader.read_u8()
	for i in range(entity_count):
		var state = EntityState.new()
		state.entity_id = reader.read_u16()
		state.delta_mask = reader.read_u8()

		# Get last known state for this entity (for reconstruction)
		var last: Dictionary = last_states.get(state.entity_id, {})

		if state.is_full_state():
			# Full state: read all fields
			state.entity_type = reader.read_u8()
			state.position = reader.read_vector2_compressed()
			state.animation_state = reader.read_u8()
			state.flags = reader.read_u8()
		elif state.is_removed():
			# Removal marker: entity_id + delta_mask only.
			state.entity_type = last.get("entity_type", PacketTypes.EntityType.PLAYER)
			state.position = last.get("position", Vector2.ZERO)
			state.animation_state = last.get("animation_state", PacketTypes.AnimationState.IDLE)
			state.flags = 0
		else:
			# Delta: merge with last known state
			state.entity_type = last.get("entity_type", PacketTypes.EntityType.PLAYER)

			# Position: read if changed, otherwise use last
			if (state.delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
				state.position = reader.read_vector2_compressed()
			else:
				state.position = last.get("position", Vector2.ZERO)

			# Animation: read if changed, otherwise use last
			if (state.delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
				state.animation_state = reader.read_u8()
			else:
				state.animation_state = last.get("animation_state", PacketTypes.AnimationState.IDLE)

			# Flags: read if changed, otherwise use last
			if (state.delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
				state.flags = reader.read_u8()
			else:
				state.flags = last.get("flags", 0)

		packet.entities.append(state)


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray, last_states: Dictionary = {}) -> StateUpdatePacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader, last_states)


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
	if is_delta():
		# Delta: header(3) + tick(4) + flags(1) + baseline(4) + count(1) + variable entities
		var entity_bytes := 0
		for entity in entities:
			entity_bytes += _get_delta_entity_size(entity)
		return 3 + 4 + 1 + 4 + 1 + entity_bytes
	else:
		# Full state: header(3) + tick(4) + flags(1) + count(1) + entities(9 each)
		return 3 + 4 + 1 + 1 + (entities.size() * ENTITY_SIZE)


## Calculate size of a single delta-encoded entity (TASK-021)
func _get_delta_entity_size(entity: EntityState) -> int:
	if entity.is_full_state():
		# entity_id(2) + delta_mask(1) + type(1) + pos(4) + anim(1) + flags(1) = 10
		return 10

	if entity.is_removed():
		# entity_id(2) + delta_mask(1)
		return DELTA_ENTITY_MIN_SIZE

	# entity_id(2) + delta_mask(1) = 3 base
	var size := 3
	if (entity.delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
		size += 4
	if (entity.delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
		size += 1
	if (entity.delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
		size += 1
	return size


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	var entity_dicts: Array[Dictionary] = []
	for entity in entities:
		entity_dicts.append(entity.to_dict())

	return {
		"type": "STATE_UPDATE",
		"server_tick": server_tick,
		"state_flags": state_flags,
		"is_delta": is_delta(),
		"baseline_tick": baseline_tick,
		"entity_count": entities.size(),
		"entities": entity_dicts,
		"size_bytes": get_size()
	}
