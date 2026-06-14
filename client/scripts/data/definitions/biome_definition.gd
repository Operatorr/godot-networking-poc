## BiomeDefinition - Data-driven definition for one biome.
##
## Parsed from the biome catalogue (res://data/biomes/<id>.json) by
## [DatabaseLoader]. Data-driven / prototype pattern: a new biome is added by
## dropping in JSON, NOT by subclassing.
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base arena/region scene -> configured biome.
##
## The client reads this to label/theme regions and to display tier/level gating.
## The spawn table + boss reference enemy ids (MonsterDefinition entries,
## resolved via the cache / MonsterDatabase; named here in comments only).
##
## Authority note: "the client requests, the server decides." Spawning is fully
## server-authoritative; the spawn data here is descriptive/UX only.
##
## Governing docs: gdd/BIOMES.md, gdd/index.md, gdd/game-modes.md.
##
## TODO:
## - Define fields: id, display_name, shard, tier (int), level range (min/max),
##   boss enemy id, spawn_table (Array/Dictionary of enemy ids + weights).
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep raw: Dictionary for round-trip fidelity.
class_name BiomeDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""
var display_name: String = ""
var shard: String = ""
var tier: int = 1

# --- Level gating -----------------------------------------------------------
var level_min: int = 1
var level_max: int = 1

## Boss enemy id (into the monster catalogue; see MonsterDefinition).
var boss_id: String = ""

## Weighted spawn entries (enemy ids -> weight); shape TBD with design.
var spawn_table: Dictionary = {}

## Raw parsed dict, preserved for tooling round-trips.
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> BiomeDefinition:
	# TODO: parse identity, tier/level range, boss, spawn table.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
