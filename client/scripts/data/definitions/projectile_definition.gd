## ProjectileDefinition - Data-driven definition for one projectile archetype.
##
## Parsed from the projectile catalogue (res://data/projectiles/<id>.json) by
## [DatabaseLoader]. Data-driven / prototype pattern: a new projectile is added
## by dropping in JSON, NOT by subclassing. One Projectile scene, configured by
## DATA (speed, lifetime, pierce, radius, appearance).
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base Projectile scene -> configured projectile.
##
## The client reads this to spawn predicted projectiles (visual responsiveness)
## and to render them. The shared Rust sim_core owns the authoritative flight +
## collision; these numbers must mirror the server's (server/contract.md
## numerics: positions quantized to 0.1 unit, truncate toward zero).
##
## Authority note: "the client requests, the server decides." Predicted
## projectiles are display/prediction only and are reconciled against snapshots.
##
## Governing docs: gdd/index.md, systems/abilities.md, server/contract.md.
##
## TODO:
## - Define fields: id, speed, lifetime, pierce (int), radius, damage hint,
##   appearance dict.
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep raw: Dictionary for round-trip fidelity.
class_name ProjectileDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""

# --- Flight (must mirror the Rust sim_core; server is authoritative) --------
var speed: float = 0.0
var lifetime: float = 0.0
var pierce: int = 0
var radius: float = 0.0

## Raw parsed dict, preserved for tooling round-trips.
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> ProjectileDefinition:
	# TODO: parse identity + flight fields; fall back per field.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
