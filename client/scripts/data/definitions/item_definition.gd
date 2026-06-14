## ItemDefinition - Data-driven definition for one item / equipment archetype.
##
## Parsed from the item catalogue (res://data/items/<id>.json) by
## [DatabaseLoader]. Data-driven / prototype pattern: a new item is added by
## dropping in JSON, NOT by subclassing.
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base item/pickup scene -> configured item.
##
## The client reads this to render inventory/loot UI and to gate equip
## eligibility in the request layer (tier/biome requirements). A granted spell
## references a SpellDefinition (resolved via the cache; named in comments only).
##
## Authority note: "the client requests, the server decides." Eligibility checks
## here are UX hints only; the Rust server is the authority on what can equip and
## what stats apply (server/contract.md numerics policy).
##
## Governing docs: gdd/loot.md, gdd/index.md, systems/abilities.md.
##
## TODO:
## - Define fields: id, display_name, type/slot, base stats dict,
##   tier_requirement (int), biome_requirement (String), granted_spell_id.
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep raw: Dictionary for round-trip fidelity.
class_name ItemDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""
var display_name: String = ""
var type: String = ""   # weapon / armor / trinket / consumable ...

# --- Requirements (client-side gating hints; server is authoritative) -------
var tier_requirement: int = 0
var biome_requirement: String = ""

## Spell this item grants when equipped (id into the spell catalogue; see
## SpellDefinition). Empty for items that grant no ability.
var granted_spell_id: String = ""

## Raw parsed dict, preserved for tooling round-trips.
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> ItemDefinition:
	# TODO: parse identity, type, base stats, requirements, granted spell.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
