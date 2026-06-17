## PacketTypes - Network packet type definitions and constants
## Central location for all packet-related constants
class_name PacketTypes
extends RefCounted

## Legacy WebSocket framing header size: [u8 type][u16 payload_length].
## RETIRED — ENet datagrams carry no length field (frame = [u8 type][payload], bounded by
## datagram edges; see AGENTS.md invariants). The live wire codec is the Rust ProtocolCodec
## (rust/protocol); this constant survives only for a few size calcs in legacy HUD/debug code.
const HEADER_SIZE := 3

## Maximum packet size (64KB)
const MAX_PACKET_SIZE := 65535

## Numeric ceiling of the u16 entity_count wire field. NOTE: this is the field's
## value range, NOT the real per-packet limit — a Snapshot is bounded by the ENet
## unreliable payload budget (< 1200 B; see docs/server/contract.md), which works
## out far lower in practice.
const STATE_MAX_ENTITIES := 65535

## Action types echoed back in ACTION_CONFIRM (moved here from the retired
## ActionConfirmPacket codec; the live decode is the Rust ProtocolCodec).
enum ActionType {
	MOVE = 0,
	SHOOT = 1,
	ABILITY = 2,
	INTERACT = 3,
}

## Result codes in ACTION_CONFIRM. SUCCESS means "no correction"; anything else
## means the server is correcting the client's predicted state.
enum ResultCode {
	SUCCESS = 0,
	FAILED_INVALID_POSITION = 1,
	FAILED_COOLDOWN = 2,
	FAILED_NO_TARGET = 3,
	FAILED_BLOCKED = 4,
	FAILED_INVALID_STATE = 5,
}

## Packet types as per ARCHITECTURE.md.
## MUST stay in sync (same ids) with NetworkManager.MessageType, the live ENet-facing
## dispatch enum — the two are parallel and any divergence breaks is_valid_type/dispatch.
## HEARTBEAT (4) and BATCH (11) are RETIRED on the live ENet path (D2: ENet keepalive/RTT
## is native, the clock-sync payload rides every Snapshot) but remain here so the id space
## stays stable and matches the Rust protocol's historical type table.
enum Type {
	PLAYER_INPUT = 1,      ## Client -> Server: Movement, actions (~16 bytes)
	STATE_UPDATE = 2,      ## Server -> Client: Entity positions, animations (variable)
	GAME_EVENT = 3,        ## Server -> Client: Damage, kills, status effects (50-200 bytes)
	HEARTBEAT = 4,         ## RETIRED (D2) — kept for parity scripts only
	ACTION_CONFIRM = 5,    ## Server -> Client: Confirm attack (20 bytes)
	CONNECT_AUTH = 6,      ## Client -> Server: Authentication handshake (variable)
	DISCONNECT = 7,        ## Clean disconnect — handled natively by ENet on the live path
	REQUEST_FULL_STATE = 8, ## Client -> Server: Request full state sync (TASK-021)
	RESPAWN_REQUEST = 9,   ## Client -> Server: Request respawn after death
	SERVER_METRICS = 10,   ## Server -> Client: Server performance metrics (1/sec)
	BATCH = 11,            ## RETIRED (D2) — kept for parity scripts only
	BASELINE_ACK = 12,     ## Client -> Server: acknowledge a received full-state Baseline
	LOCAL_HIT_REPORT = 13, ## Client -> Server: "a monster projectile hit me" (client-detected, server-validated). [u16 projectile_id]
	AUTH_RESULT = 14       ## Server -> Client: explicit auth answer (D9); carries entity_id
}

## Entity types for state updates. Values 4-7 are the world-effect band entities
## (id range 40000-49999) the GDExtension decoder emits for ability spawns.
enum EntityType {
	PLAYER = 1,
	MONSTER = 2,
	PROJECTILE = 3,
	HEALTHORB = 4,   ## Dropped health pickup (green orb)
	MINE = 5,        ## Engineer proximity mine
	DOT_ZONE = 6,    ## Plague Seer damage-over-time zone
	BIBLE = 7        ## Zealot orbiting bible orb
}

## Player classes (u8 on the wire, protocol v3). Identity metadata chosen by the
## client in CONNECT_AUTH and broadcast in PLAYER_INFO; the server clamps values
## > 6 to ZEALOT (0) and does not validate against account data yet.
enum PlayerClass {
	ZEALOT = 0,
	VOID_HUNTER = 1,
	ENGINEER = 2,
	PLAGUE_SEER = 3,
	WARRIOR = 4,
	ROGUE = 5,
	MAGE = 6
}

## Display/account names for each PlayerClass, indexed by enum value. These are the
## strings stored on the character row in the Go API; the wire/sprite layer uses the
## u8 enum, so class_name_to_id()/class_id_to_name() convert between them.
const CLASS_DISPLAY_NAMES := [
	"Zealot", "Void Hunter", "Engineer", "Plague Seer", "Warrior", "Rogue", "Mage"
]

## Pre-alpha scope gate: only these classes are playable/selectable in the client.
## The other four (Zealot, Void Hunter, Engineer, Plague Seer) stay fully defined in
## the enum above, in data/classes/<id>.json, in the Rust server and in
## docs/gdd/classes/ — they are DEFERRED, not removed (see docs/gdd/classes/index.md).
## Keep the PlayerClass enum order (0..6) stable: it is the wire class byte the server
## clamps against, so the deferred ids must not be reused or renumbered.
const PLAYABLE_CLASSES: Array[int] = [PlayerClass.WARRIOR, PlayerClass.ROGUE, PlayerClass.MAGE]

## True if a class id is selectable in the current (pre-alpha) scope.
static func is_class_playable(class_id: int) -> bool:
	return PLAYABLE_CLASSES.has(class_id)


## PlayerClass enum value for a display/account name (case-insensitive). Unknown or
## legacy names fall back to ZEALOT (the wire default the server also clamps to).
static func class_name_to_id(class_label: String) -> int:
	var normalized := class_label.strip_edges().to_lower()
	for i in CLASS_DISPLAY_NAMES.size():
		if String(CLASS_DISPLAY_NAMES[i]).to_lower() == normalized:
			return i
	return PlayerClass.ZEALOT


## Display/account name for a PlayerClass enum value (clamped to the valid range).
static func class_id_to_name(class_id: int) -> String:
	if class_id < 0 or class_id >= CLASS_DISPLAY_NAMES.size():
		return String(CLASS_DISPLAY_NAMES[PlayerClass.ZEALOT])
	return String(CLASS_DISPLAY_NAMES[class_id])

## Per-class identity colors, indexed by PlayerClass. Inspired by World of Warcraft class colors:
## Warrior=tan, Rogue=yellow, Mage=light-blue (the three playable classes), with the deferred four
## mapped to thematically-fitting WoW palettes (Zealot=Paladin pink, Void Hunter=Demon Hunter
## magenta, Engineer=Evoker teal, Plague Seer=Death Knight red). Used to tint leaderboard rows etc.
const CLASS_COLORS := [
	Color(0.961, 0.549, 0.729),  # ZEALOT      — Paladin pink   #F58CBA
	Color(0.639, 0.188, 0.788),  # VOID_HUNTER — Demon Hunter    #A330C9
	Color(0.200, 0.576, 0.498),  # ENGINEER    — Evoker teal     #33937F
	Color(0.769, 0.118, 0.227),  # PLAGUE_SEER — Death Knight red #C41E3A
	Color(0.776, 0.612, 0.431),  # WARRIOR     — Warrior tan      #C69B6E
	Color(1.000, 0.961, 0.412),  # ROGUE       — Rogue yellow     #FFF569
	Color(0.412, 0.800, 0.941),  # MAGE        — Mage light-blue  #69CCF0
]

## Pixel-art class-icon texture paths, keyed by PlayerClass. Only the playable classes (Warrior,
## Rogue, Mage) ship icons today; deferred classes have no entry and fall back to no icon (see
## PLAYABLE_CLASSES). Add the other four here when those classes leave the deferred set.
const CLASS_ICON_PATHS := {
	PlayerClass.WARRIOR: "res://assets/ui/hud/class_icons/warrior.png",
	PlayerClass.ROGUE: "res://assets/ui/hud/class_icons/rogue.png",
	PlayerClass.MAGE: "res://assets/ui/hud/class_icons/mage.png",
}

## WoW-inspired identity color for a PlayerClass enum value (clamped to the valid range).
static func class_color(class_id: int) -> Color:
	if class_id < 0 or class_id >= CLASS_COLORS.size():
		return CLASS_COLORS[PlayerClass.ZEALOT]
	return CLASS_COLORS[class_id]

## res:// path of the class icon for a PlayerClass, or "" when that class has no icon yet.
static func class_icon_path(class_id: int) -> String:
	return CLASS_ICON_PATHS.get(class_id, "")

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

## Input flags bitfield (fits in u16 — bits 0-7 were the original u8 set; bit 8+
## was added for the movement state machine and required widening the wire field).
## Each bit represents an input action.
const INPUT_FLAG_MOVE_UP := 1 << 0      ## W key
const INPUT_FLAG_MOVE_DOWN := 1 << 1    ## S key
const INPUT_FLAG_MOVE_LEFT := 1 << 2    ## A key
const INPUT_FLAG_MOVE_RIGHT := 1 << 3   ## D key
const INPUT_FLAG_SHOOT := 1 << 4        ## Left mouse button
const INPUT_FLAG_ABILITY := 1 << 5      ## Right mouse button / ability key
const INPUT_FLAG_SPRINT := 1 << 6       ## Shift key
const INPUT_FLAG_INTERACT := 1 << 7     ## E key
const INPUT_FLAG_DASH := 1 << 8         ## Spacebar — edge-triggered dash request

## Entity flags bitfield (u16 on the wire since protocol v2 — bits 0-7 are the
## original u8 set; bit 8+ is the status-effect extension).
const ENTITY_FLAG_ALIVE := 1 << 0
const ENTITY_FLAG_MOVING := 1 << 1
const ENTITY_FLAG_ATTACKING := 1 << 2
const ENTITY_FLAG_INVULNERABLE := 1 << 3
const ENTITY_FLAG_STUNNED := 1 << 4
const ENTITY_FLAG_VISIBLE := 1 << 5
const ENTITY_FLAG_DASHING := 1 << 6       ## Movement SM is in the DASHING state
const ENTITY_FLAG_KNOCKED_BACK := 1 << 7  ## Movement SM is in the KNOCKED_BACK state
const ENTITY_FLAG_DAZED := 1 << 8         ## Daze timer active (sprint/dash locked out)
const ENTITY_FLAG_STEALTH := 1 << 9       ## Rogue stealth: local player dims, others hide fully

## Delta compression mask bits (TASK-021)
## Used in STATE_UPDATE packets to indicate which fields changed
const DELTA_MASK_POSITION := 1 << 0    ## Position (x, y) changed - 4 bytes if set
const DELTA_MASK_ANIMATION := 1 << 1   ## Animation state changed - 1 byte if set
const DELTA_MASK_FLAGS := 1 << 2       ## Entity flags changed - 1 byte if set
const DELTA_MASK_REMOVED := 1 << 6     ## Entity should be removed client-side
const DELTA_MASK_FULL_STATE := 1 << 7  ## Full state (new spawn or periodic sync)

## State update packet flags (TASK-021)
## First byte after server_tick indicates packet mode
const STATE_FLAG_IS_DELTA := 1 << 0    ## Packet contains delta-encoded entities
const STATE_FLAG_BASELINE := 1 << 1    ## This is a baseline (full state) packet

## Delta compression configuration
## TICK-DERIVED: cadence halves in wall-clock at 60 Hz (~3.3s @30 -> ~1.7s @60),
## so 60 Hz forces full baselines twice as often = more downstream bandwidth.
## See docs/netcode/perf-notes/tick-rate-30-vs-60.md.
const DELTA_FULL_STATE_INTERVAL := 100 ## Ticks between forced full state (~3.3s at 30Hz)

## Game event types
enum GameEventType {
	DAMAGE = 1,            ## Entity took damage
	KILL = 2,              ## Entity was killed
	RESPAWN = 3,           ## Entity respawned
	EFFECT_APPLY = 4,      ## Status effect applied
	EFFECT_REMOVE = 5,     ## Status effect removed
	PICKUP = 6,            ## Item picked up
	LEVEL_UP = 7,          ## Player leveled up
	CHAT_MESSAGE = 8,      ## Chat message
	PLAYER_INFO = 9,       ## Player identity broadcast (entity_id -> character_name)
	KILL_PVP = 10,         ## PvP kill event (killer/victim with names)
	LEADERBOARD_UPDATE = 11, ## Top 10 leaderboard update
	PROJECTILE_FIRED = 12, ## Entity fired a projectile
	EXP_GAIN = 13,         ## A player gained experience (COSMETIC "+N XP" floater only — server owns leveling)
	ABILITY_EFFECT = 14,   ## A class ability fired a transient VFX (effect_id/position/radius)
	PROGRESS = 15          ## Authoritative level/XP/move-speed update for a player
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
		Type.REQUEST_FULL_STATE: return "REQUEST_FULL_STATE"
		Type.RESPAWN_REQUEST: return "RESPAWN_REQUEST"
		Type.SERVER_METRICS: return "SERVER_METRICS"
		Type.BATCH: return "BATCH"
		Type.BASELINE_ACK: return "BASELINE_ACK"
		Type.LOCAL_HIT_REPORT: return "LOCAL_HIT_REPORT"
		Type.AUTH_RESULT: return "AUTH_RESULT"
		_: return "UNKNOWN(%d)" % packet_type


## Helper: Check if packet type is valid. Spans the whole enum range including
## AUTH_RESULT (the current max) — keep this upper bound in step with the enum.
static func is_valid_type(packet_type: int) -> bool:
	return packet_type >= Type.PLAYER_INPUT and packet_type <= Type.AUTH_RESULT


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
	if input.get("dash", false): flags |= INPUT_FLAG_DASH
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
		"interact": (flags & INPUT_FLAG_INTERACT) != 0,
		"dash": (flags & INPUT_FLAG_DASH) != 0
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
	if entity.get("dashing", false): flags |= ENTITY_FLAG_DASHING
	if entity.get("knocked_back", false): flags |= ENTITY_FLAG_KNOCKED_BACK
	return flags


## Helper: Decode entity flags
static func decode_entity_flags(flags: int) -> Dictionary:
	return {
		"alive": (flags & ENTITY_FLAG_ALIVE) != 0,
		"moving": (flags & ENTITY_FLAG_MOVING) != 0,
		"attacking": (flags & ENTITY_FLAG_ATTACKING) != 0,
		"invulnerable": (flags & ENTITY_FLAG_INVULNERABLE) != 0,
		"stunned": (flags & ENTITY_FLAG_STUNNED) != 0,
		"visible": (flags & ENTITY_FLAG_VISIBLE) != 0,
		"dashing": (flags & ENTITY_FLAG_DASHING) != 0,
		"knocked_back": (flags & ENTITY_FLAG_KNOCKED_BACK) != 0
	}
