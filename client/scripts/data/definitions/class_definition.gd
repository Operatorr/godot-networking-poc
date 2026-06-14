## ClassDefinition - Data-driven definition for one playable player-class.
##
## Parsed from res://data/classes/<id>.json by [DatabaseLoader]. This is the
## "data-driven / prototype" pattern: a new class is added by dropping in a JSON
## file, NOT by subclassing. There is one Player scene; classes differ by DATA
## (stats, abilities, appearance), not by inheritance.
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base Player scene -> configured player.
##
## The client reads display_name + appearance to render the avatar and reads the
## primary / RMB ability ids to drive prediction + HUD. Ability ids reference
## SpellDefinition entries (resolved via the cache; named here in comments only).
##
## Authority note: "the client requests, the server decides." These stats are the
## client's display/prediction copy; the Rust server holds the authoritative
## numbers (see server/contract.md numerics policy).
##
## Governing docs: gdd/classes/ (per-class), gdd/index.md, systems/abilities.md.
##
## TODO:
## - Define fields: id, display_name, base stats (max_health, move_speed, etc.),
##   primary_ability_id (LMB), rmb_ability_id, appearance dict, race_id.
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep a raw: Dictionary so designer fields survive tooling round-trips.
class_name ClassDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""
var display_name: String = ""

# --- Ability references (ids into the spell catalogue; see SpellDefinition) --
var primary_ability_id: String = ""   # LMB
var rmb_ability_id: String = ""       # RMB

## Raw parsed dict, preserved so unconsumed designer fields survive round-trips.
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> ClassDefinition:
	# TODO: parse identity, stats, ability ids, appearance; fall back per field.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
