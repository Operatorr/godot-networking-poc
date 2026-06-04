## MonsterDefinition - Data-driven definition for one monster archetype.
##
## Parsed from res://data/monsters/<id>.json by [MonsterDatabase]. This is the
## "data-driven / prototype" pattern: a new monster is added by dropping in a
## JSON file, NOT by subclassing. There is exactly one MonsterState class and
## one MonsterAI; monsters differ by DATA, not by inheritance.
##
## The server reads stats/perception/combat/movement to drive AI + combat.
## The client reads display_name + appearance to render the monster.
##
## Every field falls back to the matching GameConstants value, so a partial or
## missing JSON still produces a valid, behavior-preserving monster.
class_name MonsterDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = "toxic_slime"
var display_name: String = "Toxic Slime"
## Reusable AI taxonomy bucket (e.g. ranged_grunt, melee_grunt, tank, boss).
var archetype: String = "ranged_grunt"
## Relationship group used by future aggro/faction logic.
var faction: String = "hostile_fauna"
## Difficulty/level tier for future stat scaling.
var tier: int = 1
## Named behaviour profile selecting which FSM/strategy the monster runs.
var ai_profile: String = "ranged_kiter"

# --- Stats ------------------------------------------------------------------
var max_health: int = GameConstants.MONSTER_HEALTH
var move_speed: float = GameConstants.MONSTER_SPEED
var hitbox_radius: float = GameConstants.MONSTER_HITBOX_RADIUS

# --- Perception / aggro -----------------------------------------------------
var detection_range: float = GameConstants.MONSTER_DETECTION_RANGE
var lose_interest_range: float = GameConstants.MONSTER_LOSE_INTEREST_DISTANCE
var retarget_interval: float = GameConstants.MONSTER_RETARGET_INTERVAL
## Hard leash distance from home (0 = disabled; roadmap, not yet enforced —
## lose_interest_range currently acts as the soft leash).
var leash_range: float = 0.0

# --- Combat -----------------------------------------------------------------
var attack_range: float = GameConstants.MONSTER_ATTACK_RANGE
var flee_distance: float = GameConstants.MONSTER_FLEE_DISTANCE
var preferred_distance: float = GameConstants.MONSTER_PREFERRED_DISTANCE
var shoot_cooldown: float = GameConstants.MONSTER_SHOOT_COOLDOWN
var attack_duration: float = GameConstants.MONSTER_ATTACK_DURATION
var projectile_speed: float = GameConstants.MONSTER_PROJECTILE_SPEED
## Canonical basic-attack damage. NOTE: the live damage applied on hit still
## comes from GameConstants.MONSTER_PROJECTILE_DAMAGE because projectiles do not
## yet carry per-source damage (documented coupling / future seam).
var projectile_damage: int = GameConstants.MONSTER_PROJECTILE_DAMAGE

# --- Movement tuning --------------------------------------------------------
var steering_randomness: float = GameConstants.MONSTER_STEERING_RANDOMNESS
var avoidance_distance: float = GameConstants.MONSTER_AVOIDANCE_DISTANCE

# --- Appearance (client render only) ---------------------------------------
# Exact float forms of the shipped hex so the no-JSON fallback matches the data
# file byte-for-byte (the live path uses the JSON hex via Color.from_string).
var core_color: Color = Color(0.372549, 0.749020, 0.247059)   # #5fbf3f toxic green
var glow_color: Color = Color(0.666667, 1.0, 0.2)             # #aaff33 acid bioluminescence
var shell_color: Color = Color(0.086275, 0.141176, 0.047059)  # #16240c dark swamp shell

# --- Forward-looking data, preserved verbatim for designers/tools -----------
## Not yet consumed by the runtime; kept so the JSON is the source of record.
var abilities: Array = []
var loot: Dictionary = {}
var spawn: Dictionary = {}

## The raw parsed dictionary, preserved so designer-facing fields we don't
## consume yet survive tooling round-trips.
var raw: Dictionary = {}


## Build the built-in default definition (the Toxic Slime), independent of any
## JSON file. Used as a safety fallback so the AI never null-derefs.
static func default() -> MonsterDefinition:
	return MonsterDefinition.new()


## Build a definition from a parsed JSON dictionary. Unknown/missing keys keep
## their GameConstants-backed defaults.
static func from_dict(p_id: String, dict: Dictionary) -> MonsterDefinition:
	var def := MonsterDefinition.new()
	def.raw = dict.duplicate(true)

	def.id = _get_string(dict, "id", p_id if not p_id.is_empty() else def.id)
	def.display_name = _get_string(dict, "display_name", def.display_name)
	def.archetype = _get_string(dict, "archetype", def.archetype)
	def.faction = _get_string(dict, "faction", def.faction)
	def.tier = _get_int(dict, "tier", def.tier)
	def.ai_profile = _get_string(dict, "ai_profile", def.ai_profile)

	var stats: Dictionary = dict.get("stats", {})
	def.max_health = _get_int(stats, "max_health", def.max_health)
	def.move_speed = _get_float(stats, "move_speed", def.move_speed)
	def.hitbox_radius = _get_float(stats, "hitbox_radius", def.hitbox_radius)

	var perception: Dictionary = dict.get("perception", {})
	def.detection_range = _get_float(perception, "detection_range", def.detection_range)
	def.lose_interest_range = _get_float(perception, "lose_interest_range", def.lose_interest_range)
	def.retarget_interval = _get_float(perception, "retarget_interval", def.retarget_interval)
	def.leash_range = _get_float(perception, "leash_range", def.leash_range)

	var combat: Dictionary = dict.get("combat", {})
	def.attack_range = _get_float(combat, "attack_range", def.attack_range)
	def.flee_distance = _get_float(combat, "flee_distance", def.flee_distance)
	def.preferred_distance = _get_float(combat, "preferred_distance", def.preferred_distance)
	def.shoot_cooldown = _get_float(combat, "shoot_cooldown", def.shoot_cooldown)
	def.attack_duration = _get_float(combat, "attack_duration", def.attack_duration)
	def.projectile_speed = _get_float(combat, "projectile_speed", def.projectile_speed)
	def.projectile_damage = _get_int(combat, "projectile_damage", def.projectile_damage)

	var movement: Dictionary = dict.get("movement", {})
	def.steering_randomness = _get_float(movement, "steering_randomness", def.steering_randomness)
	def.avoidance_distance = _get_float(movement, "avoidance_distance", def.avoidance_distance)

	var appearance: Dictionary = dict.get("appearance", {})
	def.core_color = _parse_color(appearance.get("core_color"), def.core_color)
	def.glow_color = _parse_color(appearance.get("glow_color"), def.glow_color)
	def.shell_color = _parse_color(appearance.get("shell_color"), def.shell_color)

	def.abilities = dict.get("abilities", def.abilities)
	def.loot = dict.get("loot", def.loot)
	def.spawn = dict.get("spawn", def.spawn)

	return def


## Flatten back to a dictionary (debugging / tooling).
func to_dict() -> Dictionary:
	return {
		"id": id,
		"display_name": display_name,
		"archetype": archetype,
		"faction": faction,
		"tier": tier,
		"ai_profile": ai_profile,
		"stats": {
			"max_health": max_health,
			"move_speed": move_speed,
			"hitbox_radius": hitbox_radius,
		},
		"perception": {
			"detection_range": detection_range,
			"lose_interest_range": lose_interest_range,
			"retarget_interval": retarget_interval,
			"leash_range": leash_range,
		},
		"combat": {
			"attack_range": attack_range,
			"flee_distance": flee_distance,
			"preferred_distance": preferred_distance,
			"shoot_cooldown": shoot_cooldown,
			"attack_duration": attack_duration,
			"projectile_speed": projectile_speed,
			"projectile_damage": projectile_damage,
		},
		"movement": {
			"steering_randomness": steering_randomness,
			"avoidance_distance": avoidance_distance,
		},
	}


# --- Parsing helpers --------------------------------------------------------

static func _get_float(d: Dictionary, key: String, fallback: float) -> float:
	if d.has(key) and (d[key] is float or d[key] is int):
		return float(d[key])
	return fallback


static func _get_int(d: Dictionary, key: String, fallback: int) -> int:
	if d.has(key) and (d[key] is float or d[key] is int):
		return int(d[key])
	return fallback


static func _get_string(d: Dictionary, key: String, fallback: String) -> String:
	if d.has(key) and d[key] is String and not (d[key] as String).is_empty():
		return d[key]
	return fallback


static func _parse_color(value: Variant, fallback: Color) -> Color:
	if value is Color:
		return value
	if value is String and not (value as String).is_empty():
		return Color.from_string(value, fallback)
	return fallback
