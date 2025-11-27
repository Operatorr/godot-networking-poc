## PlayerInputPacket - Client input packet (~12 bytes payload)
## Sent from client to server at 10Hz (100ms intervals)
## Format:
##   [s16 position_x][s16 position_y]     4 bytes - quantized position
##   [s16 velocity_x][s16 velocity_y]     4 bytes - quantized velocity
##   [u8 input_flags]                     1 byte  - WASD + actions
##   [s16 aim_angle]                      2 bytes - quantized aim direction
##   [u8 sequence_number]                 1 byte  - for server reconciliation
## Total: 12 bytes payload
class_name PlayerInputPacket
extends RefCounted

## Client's current position (for validation)
var position: Vector2 = Vector2.ZERO
## Client's current velocity
var velocity: Vector2 = Vector2.ZERO
## Input flags (WASD, shoot, ability, etc.)
var input_flags: int = 0
## Aim direction in radians
var aim_angle: float = 0.0
## Sequence number for server reconciliation (wraps at 255)
var sequence_number: int = 0


func _init() -> void:
	pass


## Create from current input state
static func create(pos: Vector2, vel: Vector2, flags: int, angle: float, seq: int) -> PlayerInputPacket:
	var packet = PlayerInputPacket.new()
	packet.position = pos
	packet.velocity = vel
	packet.input_flags = flags
	packet.aim_angle = angle
	packet.sequence_number = seq & 0xFF
	return packet


## Create from input dictionary (convenience method)
static func from_input_dict(input: Dictionary) -> PlayerInputPacket:
	var packet = PlayerInputPacket.new()
	packet.position = input.get("position", Vector2.ZERO)
	packet.velocity = input.get("velocity", Vector2.ZERO)
	packet.input_flags = PacketTypes.encode_input_flags(input.get("keys", {}))
	packet.aim_angle = input.get("aim_angle", 0.0)
	packet.sequence_number = input.get("sequence", 0) & 0xFF
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	var writer = PacketWriter.new(16)  # 3 header + 12 payload + 1 safety
	writer.write_header(PacketTypes.Type.PLAYER_INPUT)
	write_payload(writer)
	writer.finalize_header()
	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_vector2_compressed(position)
	writer.write_velocity_compressed(velocity)
	writer.write_u8(input_flags)
	writer.write_angle_compressed(aim_angle)
	writer.write_u8(sequence_number)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> PlayerInputPacket:
	var packet = PlayerInputPacket.new()
	packet.position = reader.read_vector2_compressed()
	packet.velocity = reader.read_velocity_compressed()
	packet.input_flags = reader.read_u8()
	packet.aim_angle = reader.read_angle_compressed()
	packet.sequence_number = reader.read_u8()
	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> PlayerInputPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Check if specific input is pressed
func is_input_pressed(flag: int) -> bool:
	return (input_flags & flag) != 0


## Get movement direction from input flags
func get_movement_direction() -> Vector2:
	var dir = Vector2.ZERO
	if is_input_pressed(PacketTypes.INPUT_FLAG_MOVE_UP):
		dir.y -= 1
	if is_input_pressed(PacketTypes.INPUT_FLAG_MOVE_DOWN):
		dir.y += 1
	if is_input_pressed(PacketTypes.INPUT_FLAG_MOVE_LEFT):
		dir.x -= 1
	if is_input_pressed(PacketTypes.INPUT_FLAG_MOVE_RIGHT):
		dir.x += 1
	return dir.normalized()


## Check if player is trying to shoot
func is_shooting() -> bool:
	return is_input_pressed(PacketTypes.INPUT_FLAG_SHOOT)


## Check if player is using ability
func is_using_ability() -> bool:
	return is_input_pressed(PacketTypes.INPUT_FLAG_ABILITY)


## Check if player is sprinting
func is_sprinting() -> bool:
	return is_input_pressed(PacketTypes.INPUT_FLAG_SPRINT)


## Get aim direction as Vector2
func get_aim_direction() -> Vector2:
	return Vector2.from_angle(aim_angle)


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "PLAYER_INPUT",
		"position": position,
		"velocity": velocity,
		"input_flags": input_flags,
		"inputs": PacketTypes.decode_input_flags(input_flags),
		"aim_angle": aim_angle,
		"aim_degrees": rad_to_deg(aim_angle),
		"sequence_number": sequence_number
	}
