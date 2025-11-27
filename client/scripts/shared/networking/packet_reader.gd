## PacketReader - Binary packet deserialization
## Provides efficient binary decoding for network packets
## Uses little-endian byte order (Godot default)
class_name PacketReader
extends RefCounted

## Buffer containing packet data
var _buffer: PackedByteArray
## Current read position in the buffer
var _position: int = 0
## Total buffer size
var _size: int = 0

## Position quantization scale (divide by 100 for 0.01 precision)
const POSITION_SCALE := 100.0
## Velocity quantization scale (divide by 10 for 0.1 precision)
const VELOCITY_SCALE := 10.0
## Angle quantization scale (divide by 100 for 0.01 degree precision)
const ANGLE_SCALE := 100.0


func _init(buffer: PackedByteArray) -> void:
	_buffer = buffer
	_position = 0
	_size = buffer.size()


## Check if there are enough bytes remaining
func _check_bounds(bytes_needed: int) -> bool:
	if _position + bytes_needed > _size:
		push_error("[PacketReader] Buffer underflow: need %d bytes, have %d" % [bytes_needed, _size - _position])
		return false
	return true


## Check if we've reached end of buffer
func is_eof() -> bool:
	return _position >= _size


## Get remaining bytes count
func remaining() -> int:
	return _size - _position


## Get current read position
func get_position() -> int:
	return _position


## Set read position (for seeking)
func set_position(pos: int) -> void:
	_position = clampi(pos, 0, _size)


## Read unsigned 8-bit integer (1 byte)
func read_u8() -> int:
	if not _check_bounds(1):
		return 0
	var value = _buffer.decode_u8(_position)
	_position += 1
	return value


## Read signed 8-bit integer (1 byte)
func read_s8() -> int:
	if not _check_bounds(1):
		return 0
	var value = _buffer.decode_s8(_position)
	_position += 1
	return value


## Read unsigned 16-bit integer (2 bytes, little-endian)
func read_u16() -> int:
	if not _check_bounds(2):
		return 0
	var value = _buffer.decode_u16(_position)
	_position += 2
	return value


## Read signed 16-bit integer (2 bytes, little-endian)
func read_s16() -> int:
	if not _check_bounds(2):
		return 0
	var value = _buffer.decode_s16(_position)
	_position += 2
	return value


## Read unsigned 32-bit integer (4 bytes, little-endian)
func read_u32() -> int:
	if not _check_bounds(4):
		return 0
	var value = _buffer.decode_u32(_position)
	_position += 4
	return value


## Read signed 32-bit integer (4 bytes, little-endian)
func read_s32() -> int:
	if not _check_bounds(4):
		return 0
	var value = _buffer.decode_s32(_position)
	_position += 4
	return value


## Read 32-bit float (4 bytes)
func read_float32() -> float:
	if not _check_bounds(4):
		return 0.0
	var value = _buffer.decode_float(_position)
	_position += 4
	return value


## Read 64-bit float (8 bytes)
func read_float64() -> float:
	if not _check_bounds(8):
		return 0.0
	var value = _buffer.decode_double(_position)
	_position += 8
	return value


## Read length-prefixed UTF-8 string
## Format: [u16 length][utf8 bytes]
func read_string() -> String:
	var length = read_u16()
	if length == 0:
		return ""

	if not _check_bounds(length):
		return ""

	var utf8_bytes = PackedByteArray()
	utf8_bytes.resize(length)
	for i in range(length):
		utf8_bytes[i] = _buffer[_position + i]
	_position += length

	return utf8_bytes.get_string_from_utf8()


## Read boolean from single byte
func read_bool() -> bool:
	return read_u8() != 0


## Read compressed Vector2 from 16-bit integers (4 bytes total)
## Dequantization: s16 / POSITION_SCALE -> float
func read_vector2_compressed() -> Vector2:
	var x_quantized = read_s16()
	var y_quantized = read_s16()
	return Vector2(
		float(x_quantized) / POSITION_SCALE,
		float(y_quantized) / POSITION_SCALE
	)


## Read compressed velocity from 16-bit integers (4 bytes total)
func read_velocity_compressed() -> Vector2:
	var x_quantized = read_s16()
	var y_quantized = read_s16()
	return Vector2(
		float(x_quantized) / VELOCITY_SCALE,
		float(y_quantized) / VELOCITY_SCALE
	)


## Read compressed angle from 16-bit integer (2 bytes)
func read_angle_compressed() -> float:
	var quantized = read_s16()
	return float(quantized) / ANGLE_SCALE


## Read raw bytes
func read_bytes(count: int) -> PackedByteArray:
	if not _check_bounds(count):
		return PackedByteArray()

	var bytes = PackedByteArray()
	bytes.resize(count)
	for i in range(count):
		bytes[i] = _buffer[_position + i]
	_position += count
	return bytes


## Skip bytes without reading
func skip(count: int) -> void:
	_position = mini(_position + count, _size)


## Read packet header and return type and payload length
## Returns: Dictionary with "type" and "payload_length" keys
func read_header() -> Dictionary:
	var packet_type = read_u8()
	var payload_length = read_u16()
	return {
		"type": packet_type,
		"payload_length": payload_length
	}


## Peek at packet type without advancing position
func peek_packet_type() -> int:
	if _size < 1:
		return -1
	return _buffer.decode_u8(0)


## Create reader from raw packet and skip header
## Returns the reader positioned after the header
static func from_packet(buffer: PackedByteArray) -> PacketReader:
	var reader = PacketReader.new(buffer)
	reader.skip(3)  # Skip header (type + payload_length)
	return reader


## Create reader and read header info
## Returns: Dictionary with "reader", "type", "payload_length"
static func parse_packet(buffer: PackedByteArray) -> Dictionary:
	var reader = PacketReader.new(buffer)
	var header = reader.read_header()
	return {
		"reader": reader,
		"type": header.type,
		"payload_length": header.payload_length
	}
