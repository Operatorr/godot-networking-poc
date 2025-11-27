## PacketTypes - Network packet type definitions and constants
## Central location for all packet-related constants
class_name PacketTypes
extends RefCounted

## Packet header size: [u8 type][u16 payload_length]
const HEADER_SIZE := 3

## Maximum packet size (64KB)
const MAX_PACKET_SIZE := 65535

## Packet types as per ARCHITECTURE.md
enum Type {
	PLAYER_INPUT = 1,      ## Client -> Server: Movement, actions (~12 bytes)
	STATE_UPDATE = 2,      ## Server -> Client: Entity positions, animations (variable)
	GAME_EVENT = 3,        ## Server -> Client: Damage, kills, status effects (50-200 bytes)
	HEARTBEAT = 4,         ## Bidirectional: Keep-alive (4 bytes)
	ACTION_CONFIRM = 5,    ## Server -> Client: Confirm attack (20 bytes)
	CONNECT_AUTH = 6,      ## Client -> Server: Authentication handshake (variable)
	DISCONNECT = 7         ## Client -> Server: Clean disconnect (4 bytes)
}

## Entity types for state updates
enum EntityType {
	PLAYER = 1,
	MONSTER = 2,
	PROJECTILE = 3
}

## Animation states (fits in u8)
enum AnimationState {
	IDLE = 0,
	WALK = 1,
	RUN = 2,
	ATTACK = 3,
	HIT = 4,
	DEATH = 5,
	SPAWN = 6
}

## Input flags bitfield (fits in u8)
## Each bit represents an input action
const INPUT_FLAG_MOVE_UP := 1 << 0      ## W key
const INPUT_FLAG_MOVE_DOWN := 1 << 1    ## S key
const INPUT_FLAG_MOVE_LEFT := 1 << 2    ## A key
const INPUT_FLAG_MOVE_RIGHT := 1 << 3   ## D key
const INPUT_FLAG_SHOOT := 1 << 4        ## Left mouse button
const INPUT_FLAG_ABILITY := 1 << 5      ## Right mouse button / ability key
const INPUT_FLAG_SPRINT := 1 << 6       ## Shift key
const INPUT_FLAG_INTERACT := 1 << 7     ## E key

## Entity flags bitfield (fits in u8)
const ENTITY_FLAG_ALIVE := 1 << 0
const ENTITY_FLAG_MOVING := 1 << 1
const ENTITY_FLAG_ATTACKING := 1 << 2
const ENTITY_FLAG_INVULNERABLE := 1 << 3
const ENTITY_FLAG_STUNNED := 1 << 4
const ENTITY_FLAG_VISIBLE := 1 << 5

## Game event types
enum GameEventType {
	DAMAGE = 1,            ## Entity took damage
	KILL = 2,              ## Entity was killed
	RESPAWN = 3,           ## Entity respawned
	EFFECT_APPLY = 4,      ## Status effect applied
	EFFECT_REMOVE = 5,     ## Status effect removed
	PICKUP = 6,            ## Item picked up
	LEVEL_UP = 7,          ## Player leveled up
	CHAT_MESSAGE = 8       ## Chat message
}

## Disconnect reason codes
enum DisconnectReason {
	USER_QUIT = 0,         ## User chose to disconnect
	TIMEOUT = 1,           ## Connection timed out
	KICKED = 2,            ## Kicked by server
	SERVER_SHUTDOWN = 3,   ## Server is shutting down
	INVALID_AUTH = 4,      ## Authentication failed
	DUPLICATE_SESSION = 5  ## Another session started
}


## Helper: Get packet type name for debugging
static func get_type_name(packet_type: int) -> String:
	match packet_type:
		Type.PLAYER_INPUT: return "PLAYER_INPUT"
		Type.STATE_UPDATE: return "STATE_UPDATE"
		Type.GAME_EVENT: return "GAME_EVENT"
		Type.HEARTBEAT: return "HEARTBEAT"
		Type.ACTION_CONFIRM: return "ACTION_CONFIRM"
		Type.CONNECT_AUTH: return "CONNECT_AUTH"
		Type.DISCONNECT: return "DISCONNECT"
		_: return "UNKNOWN(%d)" % packet_type


## Helper: Check if packet type is valid
static func is_valid_type(packet_type: int) -> bool:
	return packet_type >= Type.PLAYER_INPUT and packet_type <= Type.DISCONNECT


## Helper: Encode input flags from dictionary
static func encode_input_flags(input: Dictionary) -> int:
	var flags := 0
	if input.get("up", false): flags |= INPUT_FLAG_MOVE_UP
	if input.get("down", false): flags |= INPUT_FLAG_MOVE_DOWN
	if input.get("left", false): flags |= INPUT_FLAG_MOVE_LEFT
	if input.get("right", false): flags |= INPUT_FLAG_MOVE_RIGHT
	if input.get("shoot", false): flags |= INPUT_FLAG_SHOOT
	if input.get("ability", false): flags |= INPUT_FLAG_ABILITY
	if input.get("sprint", false): flags |= INPUT_FLAG_SPRINT
	if input.get("interact", false): flags |= INPUT_FLAG_INTERACT
	return flags


## Helper: Decode input flags to dictionary
static func decode_input_flags(flags: int) -> Dictionary:
	return {
		"up": (flags & INPUT_FLAG_MOVE_UP) != 0,
		"down": (flags & INPUT_FLAG_MOVE_DOWN) != 0,
		"left": (flags & INPUT_FLAG_MOVE_LEFT) != 0,
		"right": (flags & INPUT_FLAG_MOVE_RIGHT) != 0,
		"shoot": (flags & INPUT_FLAG_SHOOT) != 0,
		"ability": (flags & INPUT_FLAG_ABILITY) != 0,
		"sprint": (flags & INPUT_FLAG_SPRINT) != 0,
		"interact": (flags & INPUT_FLAG_INTERACT) != 0
	}


## Helper: Encode entity flags
static func encode_entity_flags(entity: Dictionary) -> int:
	var flags := 0
	if entity.get("alive", true): flags |= ENTITY_FLAG_ALIVE
	if entity.get("moving", false): flags |= ENTITY_FLAG_MOVING
	if entity.get("attacking", false): flags |= ENTITY_FLAG_ATTACKING
	if entity.get("invulnerable", false): flags |= ENTITY_FLAG_INVULNERABLE
	if entity.get("stunned", false): flags |= ENTITY_FLAG_STUNNED
	if entity.get("visible", true): flags |= ENTITY_FLAG_VISIBLE
	return flags


## Helper: Decode entity flags
static func decode_entity_flags(flags: int) -> Dictionary:
	return {
		"alive": (flags & ENTITY_FLAG_ALIVE) != 0,
		"moving": (flags & ENTITY_FLAG_MOVING) != 0,
		"attacking": (flags & ENTITY_FLAG_ATTACKING) != 0,
		"invulnerable": (flags & ENTITY_FLAG_INVULNERABLE) != 0,
		"stunned": (flags & ENTITY_FLAG_STUNNED) != 0,
		"visible": (flags & ENTITY_FLAG_VISIBLE) != 0
	}
