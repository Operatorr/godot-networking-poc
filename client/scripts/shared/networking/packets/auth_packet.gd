## AuthPacket - Authentication handshake packet (variable size)
## Sent from client to server when connecting
## Format:
##   [u16 token_length][utf8 token]           variable - JWT auth token
##   [u16 char_id_length][utf8 char_id]       variable - character ID
##   [u16 char_name_length][utf8 char_name]   variable - character display name
##   [u8 region_code]                         1 byte   - region enum
##   [u8 color_r][u8 color_g][u8 color_b]      3 bytes  - optional player color
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
## Character display name
var character_name: String = ""
## Selected region
var region: int = Region.ASIA
## Selected player color. Optional on the wire for compatibility with old clients.
var player_color: Color = Color(0.27, 0.53, 1.0)
## Client-advertised egress budget in bytes/sec. 0 means "let the server decide"
## (falls back to ServerConfig.default_client_bandwidth_bps). Optional + trailing
## on the wire so an old client that omits it still decodes (length-gated read).
var bandwidth_budget_bps: int = 0


func _init() -> void:
	pass


## Create auth packet
static func create(
	auth_token: String,
	char_id: String,
	char_name: String,
	reg: int = Region.ASIA,
	color: Color = Color(0.27, 0.53, 1.0),
	budget_bps: int = 0
) -> AuthPacket:
	var packet = AuthPacket.new()
	packet.token = auth_token
	packet.character_id = char_id
	packet.character_name = char_name
	packet.region = reg
	packet.player_color = color
	packet.bandwidth_budget_bps = budget_bps
	return packet


## Write packet to buffer (includes header)
func write() -> PackedByteArray:
	# Calculate approximate size
	var token_bytes = token.to_utf8_buffer().size()
	var char_bytes = character_id.to_utf8_buffer().size()
	var name_bytes = character_name.to_utf8_buffer().size()
	var size = 3 + 2 + token_bytes + 2 + char_bytes + 2 + name_bytes + 1 + 3 + 4 + 4  # header + strings + region + color + budget + safety

	var writer = PacketWriter.new(size)
	writer.write_header(PacketTypes.Type.CONNECT_AUTH)
	write_payload(writer)
	writer.finalize_header()

	return writer.get_buffer()


## Write just the payload (no header)
func write_payload(writer: PacketWriter) -> void:
	writer.write_string(token)
	writer.write_string(character_id)
	writer.write_string(character_name)
	writer.write_u8(region)
	_write_color_rgb(writer, player_color)
	# Trailing client-advertised egress budget (bytes/sec). u32 because a realistic
	# budget (~60k–200k B/s) exceeds u16's 65535. Append-only at the end so old
	# clients that omit it still decode via the length-gated read below.
	writer.write_u32(maxi(0, bandwidth_budget_bps))


## Read packet from reader (assumes header already read)
static func read(reader: PacketReader) -> AuthPacket:
	var packet = AuthPacket.new()
	packet.token = reader.read_string()
	packet.character_id = reader.read_string()
	packet.character_name = reader.read_string()
	packet.region = reader.read_u8()
	if reader.remaining() >= 3:
		packet.player_color = _read_color_rgb(reader)
	# Length-gated: old clients omit the trailing budget; server then defaults.
	if reader.remaining() >= 4:
		packet.bandwidth_budget_bps = reader.read_u32()
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
		"character_name": character_name,
		"region": region,
		"region_name": get_region_name(),
		"player_color": player_color,
		"bandwidth_budget_bps": bandwidth_budget_bps
	}


static func _write_color_rgb(writer: PacketWriter, color: Color) -> void:
	writer.write_u8(clampi(roundi(color.r * 255.0), 0, 255))
	writer.write_u8(clampi(roundi(color.g * 255.0), 0, 255))
	writer.write_u8(clampi(roundi(color.b * 255.0), 0, 255))


static func _read_color_rgb(reader: PacketReader) -> Color:
	return Color(
		float(reader.read_u8()) / 255.0,
		float(reader.read_u8()) / 255.0,
		float(reader.read_u8()) / 255.0,
		1.0
	)
