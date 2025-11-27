## AuthPacket - Authentication handshake packet (variable size)
## Sent from client to server when connecting
## Format:
##   [u16 token_length][utf8 token]       variable - JWT auth token
##   [u16 char_id_length][utf8 char_id]   variable - character ID
##   [u8 region_code]                     1 byte   - region enum
class_name AuthPacket
extends RefCounted

## Region codes
enum Region {
	ASIA = 0,
	EUROPE = 1,
	US_WEST = 2,
	US_EAST = 3
}

## JWT authentication token
var token: String = ""
## Character ID to use for this session
var character_id: String = ""
## Selected region
var region: int = Region.ASIA


func _init() -> void:
	pass


## Create auth packet
static func create(auth_token: String, char_id: String, reg: int = Region.ASIA) -> AuthPacket:
	var packet = AuthPacket.new()
	packet.token = auth_token
	packet.character_id = char_id
	packet.region = reg
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	# Calculate approximate size
	var token_bytes = token.to_utf8_buffer().size()
	var char_bytes = character_id.to_utf8_buffer().size()
	var size = 3 + 2 + token_bytes + 2 + char_bytes + 1 + 4  # header + strings + region + safety

	var writer = PacketWriter.new(size)
	writer.write_header(PacketTypes.Type.CONNECT_AUTH)
	write_payload(writer)
	writer.finalize_header()

	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_string(token)
	writer.write_string(character_id)
	writer.write_u8(region)


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> AuthPacket:
	var packet = AuthPacket.new()
	packet.token = reader.read_string()
	packet.character_id = reader.read_string()
	packet.region = reader.read_u8()
	return packet


## Read packet from raw buffer (with header)
static func from_buffer(buffer: PackedByteArray) -> AuthPacket:
	var reader = PacketReader.from_packet(buffer)
	return read(reader)


## Get region name
func get_region_name() -> String:
	match region:
		Region.ASIA: return "Asia"
		Region.EUROPE: return "Europe"
		Region.US_WEST: return "US-West"
		Region.US_EAST: return "US-East"
		_: return "Unknown"


## Parse region from string
static func region_from_string(region_str: String) -> int:
	match region_str.to_lower():
		"asia": return Region.ASIA
		"europe": return Region.EUROPE
		"us-west", "uswest", "us_west": return Region.US_WEST
		"us-east", "useast", "us_east": return Region.US_EAST
		_: return Region.ASIA


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"type": "CONNECT_AUTH",
		"token": token.substr(0, 20) + "..." if token.length() > 20 else token,
		"character_id": character_id,
		"region": region,
		"region_name": get_region_name()
	}
