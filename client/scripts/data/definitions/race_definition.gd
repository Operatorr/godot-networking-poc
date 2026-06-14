## RaceDefinition - Data-driven definition for one character race.
##
## Parsed from the race catalogue (res://data/races/<id>.json) by
## [DatabaseLoader]. Data-driven / prototype pattern: a new race is added by
## dropping in JSON, NOT by subclassing.
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base Player scene -> configured player.
##
## Deferred design surface: races are a planned axis (modifiers + appearance)
## layered on top of ClassDefinition. Fields here are intentionally thin until
## the design lands; kept so the JSON is the source of record meanwhile.
##
## Authority note: "the client requests, the server decides." Any stat modifiers
## here are the client's display/prediction copy; the Rust server is authority.
##
## Governing docs: gdd/classes/, gdd/index.md (deferred design surface).
##
## TODO:
## - Define fields once the design lands: id, display_name, stat modifiers dict,
##   appearance dict.
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep raw: Dictionary for round-trip fidelity.
class_name RaceDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""
var display_name: String = ""

## Raw parsed dict, preserved for tooling round-trips (the source of record
## while the race design surface is still deferred).
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> RaceDefinition:
	# TODO: parse identity + modifiers/appearance once designed.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
