## ActionConfirmPacket - Server action confirmation (variable, ~10-20 bytes)
## Sent from server to client to confirm an action was processed
## Used for client-side prediction reconciliation
## Format:
##   [u8 sequence_number]                 1 byte  - matches client input sequence
##   [u8 action_type]                     1 byte  - type of action confirmed
##   [s16 corrected_x][s16 corrected_y]   4 bytes - server's authoritative position
##   [u8 result_code]                     1 byte  - success/failure code
##   [u16 server_tick]                    2 bytes - server tick when processed
class_name ActionConfirmPacket
extends RefCounted

## Action types
enum ActionType {
	MOVE = 0,
	SHOOT = 1,
	ABILITY = 2,
	INTERACT = 3
}

## Result codes
enum ResultCode {
	SUCCESS = 0,
	FAILED_INVALID_POSITION = 1,
	FAILED_COOLDOWN = 2,
	FAILED_NO_TARGET = 3,
	FAILED_BLOCKED = 4,
	FAILED_INVALID_STATE = 5
}

## Sequence number from client input being confirmed
var sequence_number: int = 0
## Type of action that was confirmed
var action_type: int = ActionType.MOVE
## Server's authoritative position after action
var corrected_position: Vector2 = Vector2.ZERO
## Result of the action
var result_code: int = ResultCode.SUCCESS
## Server tick when this action was processed
var server_tick: int = 0


func _init() -> void:
	pass


## Create move confirmation
static func create_move_confirm(seq: int, position: Vector2, tick: int, success: bool = true) -> ActionConfirmPacket:
	var packet = ActionConfirmPacket.new()
	packet.sequence_number = seq
	packet.action_type = ActionType.MOVE
	packet.corrected_position = position
	packet.result_code = ResultCode.SUCCESS if success else ResultCode.FAILED_INVALID_POSITION
	packet.server_tick = tick
	return packet


## Create shoot confirmation
static func create_shoot_confirm(seq: int, position: Vector2, tick: int, result: int = ResultCode.SUCCESS) -> ActionConfirmPacket:
	var packet = ActionConfirmPacket.new()
	packet.sequence_number = seq
	packet.action_type = ActionType.SHOOT
	packet.corrected_position = position
	packet.result_code = result
	packet.server_tick = tick
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	var writer = PacketWriter.new(16)  # 3 header + 9 payload + safety
	writer.write_header(PacketTypes.Type.ACTION_CONFIRM)
	write_payload(writer)
	writer.finalize_header()
	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_u8(sequence_number)
	writer.write_u8(action_type)
	writer.write_vector2_compressed(corrected_position)
	writer.write_u8(result_code)
	writer.write_u16(server_tick)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> ActionConfirmPacket:
	var packet = ActionConfirmPacket.new()
	packet.sequence_number = reader.read_u8()
	packet.action_type = reader.read_u8()
	packet.corrected_position = reader.read_vector2_compressed()
	packet.result_code = reader.read_u8()
	packet.server_tick = reader.read_u16()
	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> ActionConfirmPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Check if action was successful
func is_success() -> bool:
	return result_code == ResultCode.SUCCESS


## Get action type name
func get_action_type_name() -> String:
	match action_type:
		ActionType.MOVE: return "MOVE"
		ActionType.SHOOT: return "SHOOT"
		ActionType.ABILITY: return "ABILITY"
		ActionType.INTERACT: return "INTERACT"
		_: return "UNKNOWN(%d)" % action_type


## Get result code name
func get_result_name() -> String:
	match result_code:
		ResultCode.SUCCESS: return "SUCCESS"
		ResultCode.FAILED_INVALID_POSITION: return "INVALID_POSITION"
		ResultCode.FAILED_COOLDOWN: return "COOLDOWN"
		ResultCode.FAILED_NO_TARGET: return "NO_TARGET"
		ResultCode.FAILED_BLOCKED: return "BLOCKED"
		ResultCode.FAILED_INVALID_STATE: return "INVALID_STATE"
		_: return "UNKNOWN(%d)" % result_code


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "ACTION_CONFIRM",
		"sequence_number": sequence_number,
		"action_type": action_type,
		"action_name": get_action_type_name(),
		"corrected_position": corrected_position,
		"result_code": result_code,
		"result_name": get_result_name(),
		"server_tick": server_tick
	}
