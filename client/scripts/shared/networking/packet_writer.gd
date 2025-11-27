## PacketWriter - Binary packet serialization
## Provides efficient binary encoding for network packets
## Uses little-endian byte order (Godot default)
class_name PacketWriter
extends RefCounted

## Internal buffer for packet data
var _buffer: PackedByteArray
## Current write position in the buffer
var _position: int = 0
## Initial buffer capacity
const INITIAL_CAPACITY := 256

## Position quantization scale (multiply by 100 for 0.01 precision)
const POSITION_SCALE := 100.0
## Velocity quantization scale (multiply by 10 for 0.1 precision)
const VELOCITY_SCALE := 10.0
## Angle quantization scale (multiply by 100 for 0.01 degree precision)
const ANGLE_SCALE := 100.0


func _init(initial_size: int = INITIAL_CAPACITY) -> void:
	_buffer = PackedByteArray()
	_buffer.resize(initial_size)
	_position = 0


## Ensure buffer has enough space for additional bytes
func _ensure_capacity(additional_bytes: int) -> void:
	var required = _position + additional_bytes
	if required > _buffer.size():
		var new_size = max(required, _buffer.size() * 2)
		_buffer.resize(new_size)


## Write unsigned 8-bit integer (1 byte)
func write_u8(value: int) -> PacketWriter:
	_ensure_capacity(1)
	_buffer.encode_u8(_position, value & 0xFF)
	_position += 1
	return self


## Write signed 8-bit integer (1 byte)
func write_s8(value: int) -> PacketWriter:
	_ensure_capacity(1)
	_buffer.encode_s8(_position, value)
	_position += 1
	return self


## Write unsigned 16-bit integer (2 bytes, little-endian)
func write_u16(value: int) -> PacketWriter:
	_ensure_capacity(2)
	_buffer.encode_u16(_position, value & 0xFFFF)
	_position += 2
	return self


## Write signed 16-bit integer (2 bytes, little-endian)
func write_s16(value: int) -> PacketWriter:
	_ensure_capacity(2)
	_buffer.encode_s16(_position, value)
	_position += 2
	return self


## Write unsigned 32-bit integer (4 bytes, little-endian)
func write_u32(value: int) -> PacketWriter:
	_ensure_capacity(4)
	_buffer.encode_u32(_position, value & 0xFFFFFFFF)
	_position += 4
	return self


## Write signed 32-bit integer (4 bytes, little-endian)
func write_s32(value: int) -> PacketWriter:
	_ensure_capacity(4)
	_buffer.encode_s32(_position, value)
	_position += 4
	return self


## Write 32-bit float (4 bytes)
func write_float32(value: float) -> PacketWriter:
	_ensure_capacity(4)
	_buffer.encode_float(_position, value)
	_position += 4
	return self


## Write 64-bit float (8 bytes)
func write_float64(value: float) -> PacketWriter:
	_ensure_capacity(8)
	_buffer.encode_double(_position, value)
	_position += 8
	return self


## Write length-prefixed UTF-8 string
## Format: [u16 length][utf8 bytes]
func write_string(value: String) -> PacketWriter:
	var utf8_bytes = value.to_utf8_buffer()
	var length = utf8_bytes.size()

	# Write length as u16 (max string length: 65535 bytes)
	write_u16(length)

	# Write UTF-8 bytes
	_ensure_capacity(length)
	for i in range(length):
		_buffer[_position + i] = utf8_bytes[i]
	_position += length

	return self


## Write boolean as single byte
func write_bool(value: bool) -> PacketWriter:
	return write_u8(1 if value else 0)


## Write Vector2 as compressed 16-bit integers (4 bytes total)
## Quantization: position * POSITION_SCALE -> s16
## Range: -327.68 to +327.67 units with 0.01 precision
func write_vector2_compressed(vec: Vector2) -> PacketWriter:
	var x_quantized: int = int(vec.x * POSITION_SCALE)
	var y_quantized: int = int(vec.y * POSITION_SCALE)

	# Clamp to s16 range
	x_quantized = clampi(x_quantized, -32768, 32767)
	y_quantized = clampi(y_quantized, -32768, 32767)

	write_s16(x_quantized)
	write_s16(y_quantized)
	return self


## Write velocity as compressed 16-bit integers (4 bytes total)
## Uses VELOCITY_SCALE for coarser precision (0.1 units)
func write_velocity_compressed(vec: Vector2) -> PacketWriter:
	var x_quantized: int = int(vec.x * VELOCITY_SCALE)
	var y_quantized: int = int(vec.y * VELOCITY_SCALE)

	x_quantized = clampi(x_quantized, -32768, 32767)
	y_quantized = clampi(y_quantized, -32768, 32767)

	write_s16(x_quantized)
	write_s16(y_quantized)
	return self


## Write angle as compressed 16-bit integer (2 bytes)
## Quantization: angle_radians * ANGLE_SCALE -> s16
func write_angle_compressed(angle_radians: float) -> PacketWriter:
	var quantized: int = int(angle_radians * ANGLE_SCALE)
	quantized = clampi(quantized, -32768, 32767)
	write_s16(quantized)
	return self


## Write raw bytes directly
func write_bytes(bytes: PackedByteArray) -> PacketWriter:
	var length = bytes.size()
	_ensure_capacity(length)
	for i in range(length):
		_buffer[_position + i] = bytes[i]
	_position += length
	return self


## Get the final packet buffer (trimmed to actual size)
func get_buffer() -> PackedByteArray:
	var result = PackedByteArray()
	result.resize(_position)
	for i in range(_position):
		result[i] = _buffer[i]
	return result


## Get current write position (packet size so far)
func get_size() -> int:
	return _position


## Reset writer for reuse
func reset() -> void:
	_position = 0


## Write packet header: [u8 type][u16 payload_length]
## Call this first, then write payload, then call finalize_header()
func write_header(packet_type: int) -> PacketWriter:
	write_u8(packet_type)
	write_u16(0)  # Placeholder for length, updated in finalize_header()
	return self


## Update the payload length in the header
## Call after writing all payload data
func finalize_header() -> void:
	var payload_length = _position - 3  # Subtract header size
	_buffer.encode_u16(1, payload_length)


## Utility: Create a complete packet with header
## Usage: var packet = PacketWriter.create_packet(type, func(w): w.write_u32(data))
static func create_packet(packet_type: int, write_func: Callable) -> PackedByteArray:
	var writer = PacketWriter.new()
	writer.write_header(packet_type)
	write_func.call(writer)
	writer.finalize_header()
	return writer.get_buffer()
